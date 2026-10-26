"""Download the speaker-embedding model used by app/speakers.py.

Model: WeSpeaker ResNet34-LM trained on VoxCeleb, ONNX export with sherpa-onnx
metadata, from sherpa-onnx's official model release on GitHub.
License: CC-BY-4.0 (follows the VoxCeleb dataset, per WeSpeaker's docs).

GitHub releases don't publish a checksum, so this script records the SHA-256
and size of what it downloaded (in SOURCE.txt). Later runs and other machines
can then verify they use the identical file.

Usage:
    .venv\\Scripts\\python tools\\download_speaker_model.py
"""

import hashlib
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "wespeaker_en_voxceleb_resnet34_LM.onnx"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{NAME}"
DEST = ROOT / "models" / "speaker" / NAME


def main() -> None:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists():
        print(f"Already present: {DEST}")
    else:
        print(f"Downloading {URL}")
        tmp = DEST.with_suffix(".part")

        def progress(blocks: int, block_size: int, total: int) -> None:
            if total > 0:
                print(f"\r  {min(blocks * block_size, total) / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)

        urllib.request.urlretrieve(URL, tmp, reporthook=progress)
        print()
        tmp.replace(DEST)
    data = DEST.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) < 1_000_000:
        raise SystemExit(f"File is only {len(data)} bytes: not a model (bad URL or network error?). Delete it and retry.")
    source = DEST.parent / "SOURCE.txt"
    record = f"{NAME}\n{URL}\nsize={len(data)}\nsha256={digest}\nlicense=CC-BY-4.0 (VoxCeleb)\n"
    if source.exists() and f"sha256={digest}" not in source.read_text(encoding="utf-8"):
        raise SystemExit(f"SHA-256 differs from the one recorded in {source}. The file changed: check before using it.")
    if not source.exists():
        source.write_text(record + f"downloaded={date.today()}\n", encoding="utf-8")
    print(f"OK: {DEST} ({len(data) / 1e6:.1f} MB)\nsha256 {digest}\nRecorded in {source}")


if __name__ == "__main__":
    sys.exit(main())
