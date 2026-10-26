"""CAL-02: choose the speaker-tracking settings from labelled real audio.

1. Splits the target recording into phrases (same Segmenter as the live app)
   and computes one embedding per phrase. Embeddings are saved to
   eval/speakers/embeddings.npz (not committed) for later analysis.
2. Estimates the PRIOR mean embedding from OTHER recordings (default: the
   earlier capture and the EXP-01 clips). It never uses the target itself, so
   the evaluation is honest.
3. Runs the online SpeakerTracker over the phrases, in time order, for several
   settings: raw (no centring) and centred (prior weight × threshold).
4. If eval/speakers/labels.json exists (tools/label_phrases.py), scores each
   setting against your labels:
     speakers found · purity (each found speaker is one real person)
     · coverage (each real person is one found speaker) · F = harmonic mean
5. Writes models/speaker/prior_mean.npy for the live app: the mean over ALL
   calibration embeddings, target included (most data = most stable prior).

Usage:
    .venv\\Scripts\\python tools\\speaker_calibrate.py
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.speakers import SpeakerEmbedder, SpeakerTracker  # noqa: E402
from app.vad import SAMPLE_RATE, segment_audio  # noqa: E402

MODEL = ROOT / "models" / "speaker" / "wespeaker_en_voxceleb_resnet34_LM.onnx"
DEFAULT_PRIOR_WAVS = ["eval/capture/loopback.wav", "eval/audio/clip01.wav", "eval/audio/clip02.wav",
                      "eval/audio/clip03.wav"]
RAW_THRESHOLDS = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
CENTRED_THRESHOLDS = [-0.20, -0.10, 0.00, 0.10, 0.20, 0.30]
PRIOR_WEIGHTS = [10, 30]


def embed_file(embedder: SpeakerEmbedder, path: Path) -> tuple[list, np.ndarray, list[float]]:
    audio, sr = sf.read(path, dtype="float32")
    if sr != SAMPLE_RATE or audio.ndim != 1:
        raise SystemExit(f"{path}: need 16 kHz mono, got {sr} Hz, shape {audio.shape}")
    kept, embs, ms = [], [], []
    for s in segment_audio(audio, "loopback"):
        try:
            e, dt = embedder.embed(s.audio)
        except ValueError:
            continue
        kept.append(s)
        embs.append(e)
        ms.append(dt * 1000)
    return kept, np.stack(embs) if embs else np.zeros((0, embedder.dim)), ms


def score(pred: list[str], truth: list[str | None]) -> dict:
    pairs = [(p, t) for p, t in zip(pred, truth) if t is not None]
    n = len(pairs)
    by_pred, by_true = Counter(), Counter()
    for p, t in pairs:
        by_pred[(p, t)] += 1
    purity = sum(max(c for (p2, _), c in by_pred.items() if p2 == p) for p in {p for p, _ in pairs}) / n
    coverage = sum(max(c for (_, t2), c in by_pred.items() if t2 == t) for t in {t for _, t in pairs}) / n
    f = 2 * purity * coverage / (purity + coverage)
    return {"speakers_found": len(set(pred)), "purity": round(purity, 3), "coverage": round(coverage, 3), "F": round(f, 3)}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--wav", type=Path, default=ROOT / "eval" / "speakers" / "loopback.wav")
    p.add_argument("--labels", type=Path, default=ROOT / "eval" / "speakers" / "labels.json")
    p.add_argument("--prior-wavs", nargs="+", default=DEFAULT_PRIOR_WAVS)
    args = p.parse_args()

    embedder = SpeakerEmbedder(MODEL)
    phrases, E, ms = embed_file(embedder, args.wav)
    print(f"Target {args.wav.name}: {len(phrases)} phrases, embedding median {np.median(ms):.0f} ms, max {max(ms):.0f} ms")

    prior_parts = []
    for w in args.prior_wavs:
        path = ROOT / w
        if not path.exists():
            print(f"  (prior: {w} not found, skipped)")
            continue
        _, Ep, _ = embed_file(embedder, path)
        prior_parts.append(Ep)
        print(f"  prior: {w}: {len(Ep)} phrases")
    if not prior_parts:
        raise SystemExit("No prior recordings found.")
    prior = np.concatenate(prior_parts).mean(axis=0)
    np.savez(ROOT / "eval" / "speakers" / "embeddings.npz", target=E, prior=np.concatenate(prior_parts),
             t_start=[s.t_start for s in phrases], t_end=[s.t_end for s in phrases])

    truth = None
    if args.labels.exists():
        raw = json.loads(args.labels.read_text(encoding="utf-8"))["labels"]
        keys = [f"{s.t_start:.2f}-{s.t_end:.2f}" for s in phrases]
        missing = [k for k in keys if k not in raw]
        if missing:
            raise SystemExit(f"labels.json doesn't match these phrases ({len(missing)} missing): re-run label_phrases.py")
        truth = [raw[k] if raw[k].isdigit() else None for k in keys]
        print(f"Labels: {Counter(raw[k] for k in keys)}  ('m' = mixed and '?' are ignored in scoring)")
        print(f"  truth:      {''.join(t or '.' for t in truth)}")

    settings = [("raw", None, th) for th in RAW_THRESHOLDS]
    settings += [(f"centred w={w}", w, th) for w in PRIOR_WEIGHTS for th in CENTRED_THRESHOLDS]
    rows = []
    for name, w, th in settings:
        tracker = SpeakerTracker(threshold=th, prior_mean=None if w is None else prior, prior_weight=w or 0)
        pred = [tracker.assign(e, s.speech_s).label.split()[-1] for e, s in zip(E, phrases)]
        row = {"setting": name, "threshold": th, "labels": "".join(pred)}
        if truth:
            row.update(score(pred, truth))
        rows.append(row)
    if truth:
        rows.sort(key=lambda r: (-r["F"], abs(r["speakers_found"] - len(set(t for t in truth if t)))))
    print(f"\n{'setting':16s} {'thr':>5s}  {'found':>5s} {'purity':>6s} {'cover':>6s} {'F':>5s}  labels")
    for r in rows:
        extra = f"{r['speakers_found']:5d} {r['purity']:6.2f} {r['coverage']:6.2f} {r['F']:5.2f}" if truth else " " * 25
        print(f"{r['setting']:16s} {r['threshold']:5.2f}  {extra}  {r['labels']}")

    final_prior = np.concatenate(prior_parts + [E]).mean(axis=0)
    np.save(ROOT / "models" / "speaker" / "prior_mean.npy", final_prior)
    out = ROOT / "results" / f"cal02_speakers_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"timestamp": datetime.now().isoformat(timespec="seconds"), "wav": str(args.wav),
                               "prior_wavs": args.prior_wavs, "n_prior": int(sum(len(x) for x in prior_parts)),
                               "phrases": [[round(s.t_start, 2), round(s.t_end, 2), s.speech_s] for s in phrases],
                               "truth": truth, "embed_ms_median": round(float(np.median(ms))), "results": rows},
                              indent=2), encoding="utf-8")
    print(f"\nSaved: {out}\nPrior for the live app: models/speaker/prior_mean.npy ({len(final_prior)} dims)")


if __name__ == "__main__":
    main()
