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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live Armenian → English transcription")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--mic", type=int, help="microphone device index (default: Windows default input)")
    p.add_argument("--loopback", type=int, help="loopback device index (default: loopback of the default output)")
    p.add_argument("--no-mic", action="store_true", help="capture system audio only")
    p.add_argument("--no-loopback", action="store_true", help="capture the microphone only")
    p.add_argument("--log", action="store_true", help="write per-segment timings to results/session_*.jsonl")
    p.add_argument("--hide-latency", action="store_true")
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

    print("Loading models (ASR int8, MT int8)... this takes about a minute.")
    from app.asr import OmniCtcAsr
    from app.translate import NllbTranslator
    t = time.perf_counter()
    asr = OmniCtcAsr(ASR_DIR, threads=THREADS, precision="int8")
    mt = NllbTranslator(MT_DIR, MT_TOKENIZER_DIR, compute_type="int8", threads=THREADS)
    import numpy as np
    asr.transcribe(np.zeros(16000, dtype=np.float32))       # warm-up
    mt.translate("բարեւ", beam_size=BEAM_SIZE)
    print(f"Models ready in {time.perf_counter() - t:.0f} s.")

    chunk_q: queue.Queue = queue.Queue()
    seg_q: queue.Queue = queue.Queue()
    stop = threading.Event()
    segments_done = threading.Event()
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
    labels = {"mic": "Me", "loopback": "Call"}
    log_file = ROOT / "results" / f"session_{datetime.now():%Y%m%d_%H%M%S}.jsonl" if args.log else None
    results: list = []

    threads = run_threads([
        (segment_loop, (chunk_q, seg_q, segmenters, clock, stop, segments_done)),
        (process_loop, (seg_q, asr, mt, lambda seg: labels[seg.source], clock, segments_done, sys.stdout,
                        log_file, BEAM_SIZE, not args.hide_latency, results)),
    ])
    for s in sources:
        s.start()
        print(f"Listening: {labels[s.name]:4s} <- [{s.index}] {s.device_name}")
    print("Speak Armenian. Ctrl+C to stop.\n")

    try:
        wait_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for s in sources:
            s.stop()
        stop.set()
        for th in threads:          # segmenter first (flushes), then the worker finishes the queue
            th.join(timeout=60)
        pa.terminate()

    if results:
        lat = sorted(r.latency_s for r in results)
        p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))]
        print(f"\n{len(lat)} segments | latency median {statistics.median(lat):.1f} s, p95 {p95:.1f} s, "
              f"max {lat[-1]:.1f} s | over 5 s: {sum(x > 5 for x in lat)}")
    if log_file:
        print(f"Log: {log_file}")


if __name__ == "__main__":
    main()
