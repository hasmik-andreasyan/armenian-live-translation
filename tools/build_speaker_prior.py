"""Rebuild the speaker prior mean (models/speaker/prior_mean.npy) from ALL calibration audio.

The prior is the mean speaker embedding the live tracker subtracts before
comparing voices (D-026). The working threshold depends on it (D-032), so it
is rebuilt from as much varied audio as we have, phrase by phrase, exactly as
the live app segments it.

Usage:
    .venv\\Scripts\\python tools\\build_speaker_prior.py
"""

import hashlib
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.speakers import SpeakerEmbedder  # noqa: E402
from app.vad import SAMPLE_RATE, segment_audio  # noqa: E402

MODEL = ROOT / "models" / "speaker" / "wespeaker_en_voxceleb_resnet34_LM.onnx"
SOURCES = ["eval/speakers/loopback.wav", "results/session_20261026_164715_loopback.wav",
           "eval/capture/loopback.wav", "eval/audio/clip01.wav", "eval/audio/clip02.wav", "eval/audio/clip03.wav"]
OUT = ROOT / "models" / "speaker" / "prior_mean.npy"


def main() -> None:
    embedder = SpeakerEmbedder(MODEL)
    embs, report = [], []
    for rel in SOURCES:
        path = ROOT / rel
        if not path.exists():
            raise SystemExit(f"Missing {rel}: the prior must be rebuilt from the same files every time.")
        audio, sr = sf.read(path, dtype="float32")
        if sr != SAMPLE_RATE or audio.ndim != 1:
            raise SystemExit(f"{rel}: need 16 kHz mono")
        n = 0
        for s in segment_audio(audio, "loopback"):
            try:
                embs.append(embedder.embed(s.audio)[0])
                n += 1
            except ValueError:
                pass
        report.append(f"{rel}: {n} phrases")
        print(f"  {rel}: {n} phrases")
    prior = np.mean(np.stack(embs), axis=0).astype(np.float32)
    np.save(OUT, prior)
    digest = hashlib.sha256(prior.tobytes()).hexdigest()[:16]
    (OUT.parent / "PRIOR.txt").write_text(
        f"built {datetime.now():%Y-%m-%d %H:%M} from {len(embs)} phrases\n" + "\n".join(report) +
        f"\nsha256[:16] of the float32 vector = {digest}\n", encoding="utf-8")
    print(f"Prior from {len(embs)} phrases → {OUT} (sha256[:16] {digest}); details in PRIOR.txt")


if __name__ == "__main__":
    main()
