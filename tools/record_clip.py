"""Record one evaluation clip as 16 kHz mono 16-bit WAV.

The sentence to read comes from eval/manifest.csv (column "reference"), so the
recording and its reference text can't drift apart.

Usage:
    .venv\\Scripts\\python tools\\record_clip.py --list-devices
    .venv\\Scripts\\python tools\\record_clip.py --id clip01 [--device 1]

Press Enter to start, Enter again to stop. Leave ~0.5 s of silence at both ends.
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

SAMPLE_RATE = 16000


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--id", help="clip_id from the manifest, e.g. clip01")
    p.add_argument("--manifest", type=Path, default=Path("eval/manifest.csv"))
    p.add_argument("--device", help="input device index or name (see --list-devices)")
    p.add_argument("--list-devices", action="store_true")
    args = p.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        print(f"\nDefault input device: {sd.default.device[0]}")
        return
    if not args.id:
        raise SystemExit("--id is required (or use --list-devices)")

    with open(args.manifest, encoding="utf-8-sig", newline="") as f:
        rows = {r["clip_id"]: r for r in csv.DictReader(f)}
    if args.id not in rows:
        raise SystemExit(f"{args.id} not in {args.manifest}. Known ids: {sorted(rows)}")
    row = rows[args.id]
    out = Path(row["file"])
    out.parent.mkdir(parents=True, exist_ok=True)
    device = int(args.device) if args.device and args.device.isdigit() else args.device

    print(f"\nSentence to read ({row.get('notes', '')}):\n\n    {row['reference']}\n")
    print("(If the Armenian shows as boxes, read it from eval/manifest.csv in Notepad.)")
    input("Press Enter to START recording...")

    chunks = []

    def callback(indata, frames, time_info, status):
        if status:
            print(f"\nAUDIO WARNING: {status}", file=sys.stderr)
        chunks.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device, callback=callback):
        input("Recording... press Enter to STOP.")

    audio = np.concatenate(chunks)[:, 0]
    duration = len(audio) / SAMPLE_RATE
    peak = float(np.abs(audio).max())
    rms_db = 20 * np.log10(float(np.sqrt(np.mean(audio ** 2))) + 1e-12)
    sf.write(out, audio, SAMPLE_RATE, subtype="PCM_16")
    print(f"Saved {out}: {duration:.1f} s, peak {peak:.2f}, RMS {rms_db:.0f} dBFS")
    if peak >= 0.99:
        print("WARNING: clipping (too loud). Move the mic away or lower the input level, then re-record.")
    if rms_db < -45:
        print("WARNING: very quiet. Check the input device and level, then re-record.")


if __name__ == "__main__":
    main()
