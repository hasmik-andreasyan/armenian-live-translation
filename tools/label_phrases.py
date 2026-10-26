"""Ground truth for speaker calibration: listen to each phrase and say who it is.

Splits the recording exactly like the live app, plays each phrase through your
headset, and asks for a speaker number. The labels go to
eval/speakers/labels.json (the phrase times are stored too, so the
calibration can check it uses the same phrases).

Keys:  1..9 = speaker number (your own numbering, e.g. 1 = interviewer)
       m    = mixed (two people in one phrase)     ?  = can't tell
       r    = replay                               q  = save and quit

Usage:
    .venv\\Scripts\\python tools\\label_phrases.py [--wav eval/speakers/loopback.wav]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sounddevice as sd  # noqa: E402
import soundfile as sf  # noqa: E402

from app.vad import SAMPLE_RATE, segment_audio  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--wav", type=Path, default=ROOT / "eval" / "speakers" / "loopback.wav")
    p.add_argument("--out", type=Path, default=ROOT / "eval" / "speakers" / "labels.json")
    args = p.parse_args()

    audio, sr = sf.read(args.wav, dtype="float32")
    if sr != SAMPLE_RATE or audio.ndim != 1:
        raise SystemExit(f"{args.wav}: need 16 kHz mono")
    segments = segment_audio(audio, "loopback")
    labels = json.loads(args.out.read_text(encoding="utf-8"))["labels"] if args.out.exists() else {}
    print(f"{len(segments)} phrases, {len(labels)} already labelled. Headset on.\n")

    for i, s in enumerate(segments, 1):
        key = f"{s.t_start:.2f}-{s.t_end:.2f}"
        if key in labels:
            continue
        while True:
            print(f"#{i:2d}  {s.t_start:6.1f}-{s.t_end:6.1f} s  (playing...)")
            sd.play(s.audio, SAMPLE_RATE)
            sd.wait()
            answer = input("    speaker 1-9 / m = mixed / ? = can't tell / r = replay / q = quit: ").strip().lower()
            if answer in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "m", "?", "q"}:
                break
        if answer == "q":
            break
        labels[key] = answer
        args.out.write_text(json.dumps({"wav": str(args.wav), "labels": labels}, indent=2), encoding="utf-8")
    print(f"\nSaved {len(labels)}/{len(segments)} labels to {args.out}")


if __name__ == "__main__":
    main()
