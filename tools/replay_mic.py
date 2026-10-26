"""Offline replay of recorded audio through the live app's segmenter + ASR.

Used to choose the ASR-confidence threshold from real data (D-030) without a
new live session. For every phrase it prints the speech duration, the ASR
text and confidence, as the live app computes them:
  - "as live": exactly what the app sees
  - "padded":  the same phrase with --pad seconds of silence added on both
               sides (a cheap test of whether short isolated words can be
               rescued, not just hidden)
The EXP-01 clips (known reference text) are scored too, as a reference for
what "clearly correct" confidence looks like.

Usage:
    .venv\\Scripts\\python tools\\replay_mic.py --wav results\\session_20261026_164715_mic.wav
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.asr import OmniCtcAsr  # noqa: E402
from app.metrics import cer  # noqa: E402
from app.text_norm import normalize_for_scoring  # noqa: E402
from app.vad import SAMPLE_RATE, segment_audio  # noqa: E402

ASR_DIR = ROOT / "models" / "aadel4__omniASR-CTC-300M-v2"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--wav", type=Path, required=True)
    p.add_argument("--pad", type=float, default=0.5, help="seconds of silence added on both sides (variant)")
    args = p.parse_args()

    audio, sr = sf.read(args.wav, dtype="float32")
    if sr != SAMPLE_RATE or audio.ndim != 1:
        raise SystemExit(f"{args.wav}: need 16 kHz mono")
    print("Loading ASR (int8, Armenian-only, as in the live app)...")
    asr = OmniCtcAsr(ASR_DIR, threads=4, precision="int8")
    pad = np.zeros(int(args.pad * SAMPLE_RATE), dtype=np.float32)

    rows = []
    print(f"\n{'#':>2s} {'time':>13s} {'speech':>6s} | {'conf':>4s} as live{'':22s} | {'conf':>4s} padded {args.pad:g} s")
    for i, s in enumerate(segment_audio(audio, "mic"), 1):
        live = asr.transcribe(s.audio)
        padded = asr.transcribe(np.concatenate([pad, s.audio, pad]))
        rows.append({"n": i, "t_start": round(s.t_start, 2), "t_end": round(s.t_end, 2), "speech_s": s.speech_s,
                     "live_text": live.text, "live_conf": live.confidence,
                     "padded_text": padded.text, "padded_conf": padded.confidence})
        print(f"{i:2d} {s.t_start:6.1f}-{s.t_end:6.1f} {s.speech_s:5.1f}s | {live.confidence:.2f} {live.text[:28]:28s} "
              f"| {padded.confidence:.2f} {padded.text[:40]}")

    print("\nReference: EXP-01 clips (known text)")
    clips = []
    with open(ROOT / "eval" / "manifest.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            x, _ = sf.read(ROOT / r["file"], dtype="float32")
            res = asr.transcribe(x)
            c = cer(normalize_for_scoring(r["reference"]), normalize_for_scoring(res.text))
            clips.append({"clip": r["clip_id"], "conf": res.confidence, "cer": round(c, 3), "text": res.text})
            print(f"  {r['clip_id']}: conf {res.confidence:.2f}  CER {c:.1%}  {res.text[:60]}")

    out = ROOT / "results" / f"replay_mic_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"wav": str(args.wav), "pad_s": args.pad, "phrases": rows, "clips": clips},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
