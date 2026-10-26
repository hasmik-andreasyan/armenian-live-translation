"""Live Armenian → English transcription of a call. Entry point.

    .venv\\Scripts\\python -m app.main --list-devices
    .venv\\Scripts\\python -m app.main [--mic N] [--loopback N] [--log]

Microphone → "Me". System audio (WASAPI loopback) → "Call" (speaker
identification comes next). Ctrl+C stops and prints a latency summary.
"""

import argparse
import queue
import statistics
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from app.audio import AudioSource, default_loopback, default_mic, describe_devices, open_pyaudio
from app.pipeline import process_loop, run_threads, segment_loop, wait_forever
from app.vad import Segmenter

ROOT = Path(__file__).resolve().parents[1]
ASR_DIR = ROOT / "models" / "aadel4__omniASR-CTC-300M-v2"
MT_DIR = ROOT / "models" / "nllb-600m-ct2-int8"
MT_TOKENIZER_DIR = ROOT / "models" / "facebook__nllb-200-distilled-600M"
THREADS = 4          # D-010
BEAM_SIZE = 1        # D-018
MAX_SEGMENT_S = 7.0  # D-014
SPEAKER_MODEL = ROOT / "models" / "speaker" / "wespeaker_en_voxceleb_resnet34_LM.onnx"
SPEAKER_PRIOR = ROOT / "models" / "speaker" / "prior_mean.npy"
SPEAKER_THRESHOLD = 0.10     # D-027 (CAL-02)
SPEAKER_PRIOR_WEIGHT = 30    # D-027 (CAL-02)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live Armenian → English transcription")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--mic", type=int, help="microphone device index (default: Windows default input)")
    p.add_argument("--loopback", type=int, help="loopback device index (default: loopback of the default output)")
    p.add_argument("--no-mic", action="store_true", help="capture system audio only")
    p.add_argument("--no-loopback", action="store_true", help="capture the microphone only")
    p.add_argument("--log", action="store_true", help="write per-segment timings to results/session_*.jsonl")
    p.add_argument("--hide-latency", action="store_true")
    p.add_argument("--speaker-threshold", type=float, default=SPEAKER_THRESHOLD,
                   help="centred cosine needed to match a known speaker (higher = more speakers)")
    return p.parse_args()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    pa = open_pyaudio()
    if args.list_devices:
        for d in describe_devices(pa):
            if d["inputs"] > 0:
                tag = "LOOPBACK" if d["loopback"] else "input   "
                print(f"{d['index']:3d}  {tag}  {d['host_api']:22s} {d['rate']:6d} Hz  {d['name']}")
        print(f"\nDefault mic: {default_mic(pa)['index']}   Default loopback: {default_loopback(pa)['index']}")
        pa.terminate()
        return

    print("Loading models (ASR int8, MT int8, speaker embeddings)... this takes about a minute.")
    import numpy as np
    from app.asr import OmniCtcAsr
    from app.speakers import CallSpeakerLabeler, SpeakerEmbedder, SpeakerTracker
    from app.translate import NllbTranslator
    t = time.perf_counter()
    asr = OmniCtcAsr(ASR_DIR, threads=THREADS, precision="int8")
    mt = NllbTranslator(MT_DIR, MT_TOKENIZER_DIR, compute_type="int8", threads=THREADS)
    if not SPEAKER_PRIOR.exists():
        raise SystemExit(f"{SPEAKER_PRIOR} missing: run tools/speaker_calibrate.py first.")
    embedder = SpeakerEmbedder(SPEAKER_MODEL, threads=THREADS)
    tracker = SpeakerTracker(threshold=args.speaker_threshold, prior_mean=np.load(SPEAKER_PRIOR),
                             prior_weight=SPEAKER_PRIOR_WEIGHT)
    label_for = CallSpeakerLabeler(embedder, tracker)
    asr.transcribe(np.zeros(16000, dtype=np.float32))       # warm-up
    mt.translate("բարեւ", beam_size=BEAM_SIZE)
    embedder.embed(np.random.default_rng(0).standard_normal(32000).astype(np.float32) * 0.01)
    print(f"Models ready in {time.perf_counter() - t:.0f} s.")

    chunk_q: queue.Queue = queue.Queue()
    seg_q: queue.Queue = queue.Queue()
    stop = threading.Event()
    segments_done = threading.Event()
    abort = threading.Event()
    t0 = time.monotonic()
    clock = lambda: time.monotonic() - t0  # noqa: E731

    sources = []
    if not args.no_mic:
        dev = pa.get_device_info_by_index(args.mic) if args.mic is not None else default_mic(pa)
        sources.append(AudioSource(pa, dev, "mic", chunk_q, t0))
    if not args.no_loopback:
        dev = pa.get_device_info_by_index(args.loopback) if args.loopback is not None else default_loopback(pa)
        if not dev.get("isLoopbackDevice", False):
            raise SystemExit(f"Device {dev['index']} is not a loopback device. See --list-devices.")
        sources.append(AudioSource(pa, dev, "loopback", chunk_q, t0))
    if not sources:
        raise SystemExit("Nothing to capture (both --no-mic and --no-loopback).")

    segmenters = {s.name: Segmenter(s.name, max_segment_s=MAX_SEGMENT_S) for s in sources}
    labels = {"mic": "Me", "loopback": "Speaker N"}   # for the "Listening:" lines
    log_file = ROOT / "results" / f"session_{datetime.now():%Y%m%d_%H%M%S}.jsonl" if args.log else None
    results: list = []

    threads = run_threads([
        (segment_loop, (chunk_q, seg_q, segmenters, clock, stop, segments_done)),
        (process_loop, (seg_q, asr, mt, label_for, clock, segments_done, sys.stdout,
                        log_file, BEAM_SIZE, not args.hide_latency, results, abort)),
    ])
    for s in sources:
        s.start()
        print(f"Listening: {labels[s.name]:4s} <- [{s.index}] {s.device_name}")
    print("Speak Armenian. Ctrl+C to stop.\n")

    try:
        wait_forever()
    except KeyboardInterrupt:
        print(f"\nStopping: finishing {seg_q.qsize()} queued phrase(s) and any phrase in progress. "
              "Press Ctrl+C again to skip them.")
    finally:
        for s in sources:
            s.stop()
        stop.set()
        try:
            for th in threads:      # segmenter first (flushes), then the worker finishes the queue
                th.join(timeout=60)
        except KeyboardInterrupt:
            abort.set()
            print("Skipping the remaining phrases.")
            for th in threads:
                th.join(timeout=10)  # the current ASR/MT call finishes, then the worker exits
        pa.terminate()

    if results:
        lat = sorted(r.latency_s for r in results)
        p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))]
        print(f"\n{len(lat)} segments | latency median {statistics.median(lat):.1f} s, p95 {p95:.1f} s, "
              f"max {lat[-1]:.1f} s | over 5 s: {sum(x > 5 for x in lat)}")
    if tracker.counts:
        print("Call-side speakers: " + ", ".join(f"Speaker {i + 1}: {n} phrase(s)" for i, n in enumerate(tracker.counts)))
    if log_file:
        print(f"Log: {log_file}")


if __name__ == "__main__":
    main()
