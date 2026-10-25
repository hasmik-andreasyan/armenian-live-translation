"""Spike 1: capture the microphone and the system output at the same time.

Records both for --seconds, writes 16 kHz mono WAVs to eval/capture/ (not
committed), and reports per source:
  - device, native rate/channels
  - completeness: native frames received vs. expected for the elapsed time
  - longest gap between callbacks (WASAPI loopback pauses during silence)
  - overflow flags (audio lost because the program was too slow)
  - level: peak, RMS, and share of 100 ms windows with sound

Usage:
    .venv\\Scripts\\python tools\\capture_test.py --list
    .venv\\Scripts\\python tools\\capture_test.py [--mic N] [--loopback N] [--seconds 30]
"""

import argparse
import json
import queue
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.audio import (PA_INPUT_OVERFLOW, TARGET_RATE, AudioSource, default_loopback,  # noqa: E402
                       default_mic, describe_devices, open_pyaudio)


def levels(x: np.ndarray) -> dict:
    if len(x) == 0:
        return {"seconds": 0.0, "peak": 0.0, "rms_dbfs": None, "active_share": 0.0}
    win = TARGET_RATE // 10
    n = len(x) // win
    rms = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1)) if n else np.array([0.0])
    db = 20 * np.log10(rms + 1e-12)
    return {"seconds": round(len(x) / TARGET_RATE, 2), "peak": round(float(np.abs(x).max()), 3),
            "rms_dbfs": round(float(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-12)), 1),
            "active_share": round(float((db > -50).mean()), 2)}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true", help="list devices and exit")
    p.add_argument("--mic", type=int, help="microphone device index (default: Windows default input)")
    p.add_argument("--loopback", type=int, help="loopback device index (default: loopback of default output)")
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--out-dir", type=Path, default=ROOT / "eval" / "capture")
    args = p.parse_args()

    pa = open_pyaudio()
    try:
        if args.list:
            for d in describe_devices(pa):
                if d["inputs"] > 0:
                    tag = "LOOPBACK" if d["loopback"] else "input   "
                    print(f"{d['index']:3d}  {tag}  {d['host_api']:22s} {d['rate']:6d} Hz {d['inputs']} ch  {d['name']}")
            print(f"\nDefault mic:      {default_mic(pa)['index']}  {default_mic(pa)['name']}")
            print(f"Default loopback: {default_loopback(pa)['index']}  {default_loopback(pa)['name']}")
            return

        mic_dev = pa.get_device_info_by_index(args.mic) if args.mic is not None else default_mic(pa)
        lb_dev = pa.get_device_info_by_index(args.loopback) if args.loopback is not None else default_loopback(pa)
        if not lb_dev.get("isLoopbackDevice", False):
            raise SystemExit(f"Device {lb_dev['index']} ({lb_dev['name']}) is not a loopback device. See --list.")

        q: queue.Queue = queue.Queue()
        t0 = time.monotonic()
        sources = {"mic": AudioSource(pa, mic_dev, "mic", q, t0), "loopback": AudioSource(pa, lb_dev, "loopback", q, t0)}
        for s in sources.values():
            print(f"{s.name:8s} -> [{s.index}] {s.device_name}  ({s.rate} Hz, {s.channels} ch)")
        print(f"\nRecording {args.seconds:.0f} s. Play audio through your headset AND speak into the mic now...")

        audio = {"mic": [], "loopback": []}
        first_t = {}
        for s in sources.values():
            s.start()
        t_start = time.monotonic()
        while time.monotonic() - t_start < args.seconds:
            try:
                chunk = q.get(timeout=0.2)
            except queue.Empty:
                continue
            first_t.setdefault(chunk.source, chunk.t_start)
            audio[chunk.source].append(chunk.samples)
        elapsed = time.monotonic() - t_start
        for s in sources.values():
            s.stop()
        while not q.empty():  # drain what arrived during stop
            chunk = q.get_nowait()
            audio[chunk.source].append(chunk.samples)
    finally:
        pa.terminate()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {"timestamp": datetime.now().isoformat(timespec="seconds"), "seconds_requested": args.seconds,
              "elapsed_s": round(elapsed, 2), "sources": {}}
    for name, s in sources.items():
        x = np.concatenate(audio[name]) if audio[name] else np.zeros(0, dtype=np.float32)
        path = args.out_dir / f"{name}.wav"
        sf.write(path, x, TARGET_RATE, subtype="PCM_16")
        expected = s.rate * elapsed
        report["sources"][name] = {
            "device": s.device_name, "index": s.index, "native_rate": s.rate, "channels": s.channels,
            "callbacks": s.callbacks, "completeness": round(s.native_frames / expected, 3),
            "max_gap_s": round(s.max_gap_s, 3), "overflow": bool(s.status_flags & PA_INPUT_OVERFLOW),
            "first_chunk_t": round(first_t.get(name, -1), 3), "file": str(path.relative_to(ROOT)), **levels(x),
        }

    print("\nResults:")
    for name, r in report["sources"].items():
        print(f"  {name:8s} {r['seconds']:5.1f} s captured | completeness {r['completeness']:.0%} | "
              f"max gap {r['max_gap_s']:.2f} s | overflow {r['overflow']} | peak {r['peak']:.2f} | "
              f"RMS {r['rms_dbfs']} dBFS | sound in {r['active_share']:.0%} of the time")
        if r["active_share"] < 0.05:
            print(f"  WARNING: {name} is (almost) silent. Wrong device, muted, or nothing playing/spoken?")
        if r["overflow"]:
            print(f"  WARNING: {name} lost audio (input overflow).")
    out = ROOT / "results" / f"capture_test_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWAVs in {args.out_dir}. Listen to both.\nSaved: {out}")


if __name__ == "__main__":
    main()
