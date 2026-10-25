"""EXP-01: real Armenian accuracy, latency and RAM of omniASR-CTC-300M-v2.

Run once per precision, each in its own process, so RAM numbers don't mix:
    .venv\\Scripts\\python benchmarks\\exp01_asr_eval.py --precision fp32
    .venv\\Scripts\\python benchmarks\\exp01_asr_eval.py --precision int8

Per clip:  hypothesis text, latency (median of --runs warm runs), RTF,
           CER/WER raw and normalised (see app/text_norm.py).
Overall:   corpus CER/WER, load time, RAM after load, peak RAM.
Reproducibility: records model revision, package versions and the SHA-256 of
the manifest and of every WAV (the audio itself is never committed).
"""

import argparse
import csv
import hashlib
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import psutil  # noqa: E402
import soundfile as sf  # noqa: E402

from app.asr import SAMPLE_RATE, OmniCtcAsr  # noqa: E402
from app.metrics import cer, corpus_cer, corpus_wer, wer  # noqa: E402
from app.text_norm import normalize_for_scoring  # noqa: E402

DEFAULT_MODEL = Path("models/aadel4__omniASR-CTC-300M-v2")


def mem_mb() -> dict:
    mi = psutil.Process().memory_info()
    return {"rss_mb": round(mi.rss / 1e6), "peak_mb": round(getattr(mi, "peak_wset", mi.rss) / 1e6)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--precision", choices=["fp32", "int8"], required=True)
    p.add_argument("--manifest", type=Path, default=Path("eval/manifest.csv"))
    p.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--out", type=Path, default=Path("results"))
    args = p.parse_args()

    revision_file = args.model_dir / "REVISION.txt"
    if not revision_file.exists():
        raise SystemExit(f"{revision_file} missing: run tools/download_model.py first.")

    with open(args.manifest, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    missing = [r["file"] for r in rows if not Path(r["file"]).exists()]
    if missing:
        raise SystemExit(f"Missing recordings: {missing}. Record them with tools/record_clip.py.")

    clips = []
    for r in rows:
        audio, sr = sf.read(r["file"], dtype="float32")
        if sr != SAMPLE_RATE or audio.ndim != 1:
            raise SystemExit(f"{r['file']}: need 16 kHz mono, got {sr} Hz, shape {audio.shape}")
        clips.append((r, audio))

    mem_start = mem_mb()
    t0 = time.perf_counter()
    asr = OmniCtcAsr(args.model_dir, threads=args.threads, precision=args.precision)
    load_s = time.perf_counter() - t0
    mem_loaded = mem_mb()
    print(f"Loaded {args.precision} in {load_s:.1f} s, RSS {mem_loaded['rss_mb']} MB")

    asr.transcribe(clips[0][1])  # warm-up, not timed

    results = []
    for r, audio in clips:
        runs = [asr.transcribe(audio) for _ in range(args.runs)]
        texts = {x.text for x in runs}
        hyp = runs[-1].text
        clip_s = len(audio) / SAMPLE_RATE
        latency = statistics.median(x.seconds for x in runs)
        ref_n, hyp_n = normalize_for_scoring(r["reference"]), normalize_for_scoring(hyp)
        results.append({
            "clip_id": r["clip_id"], "clip_s": round(clip_s, 2), "reference": r["reference"], "hypothesis": hyp,
            "deterministic": len(texts) == 1, "unknown_tokens": runs[-1].unknown_tokens,
            "latency_s": round(latency, 3), "all_latencies_s": [round(x.seconds, 3) for x in runs],
            "rtf": round(latency / clip_s, 3),
            "cer_raw": round(cer(r["reference"], hyp), 4), "cer_norm": round(cer(ref_n, hyp_n), 4),
            "wer_norm": round(wer(ref_n, hyp_n), 4),
            "reference_norm": ref_n, "hypothesis_norm": hyp_n,
        })
        print(f"\n[{r['clip_id']}] {clip_s:.1f} s  latency {latency:.2f} s  RTF {latency / clip_s:.2f}  "
              f"CER {results[-1]['cer_norm']:.1%}  WER {results[-1]['wer_norm']:.1%}")
        print(f"  REF: {r['reference']}\n  HYP: {hyp}")

    refs = [x["reference_norm"] for x in results]
    hyps = [x["hypothesis_norm"] for x in results]
    summary = {
        "corpus_cer_norm": round(corpus_cer(refs, hyps), 4),
        "corpus_wer_norm": round(corpus_wer(refs, hyps), 4),
        "corpus_cer_raw": round(corpus_cer([x["reference"] for x in results], [x["hypothesis"] for x in results]), 4),
        "max_latency_s": max(x["latency_s"] for x in results),
        "median_rtf": statistics.median(x["rtf"] for x in results),
        "load_s": round(load_s, 1),
        "memory": {"start": mem_start, "after_load": mem_loaded, "end": mem_mb()},
    }
    print("\nSummary:", json.dumps(summary, indent=2))

    report = {
        "experiment": "EXP-01", "timestamp": datetime.now().isoformat(timespec="seconds"),
        "precision": args.precision, "threads": args.threads, "runs": args.runs,
        "model_revision": revision_file.read_text(encoding="utf-8").split(),
        "platform": platform.platform(), "python": sys.version.split()[0],
        "versions": {pkg: version(pkg) for pkg in ["torch", "transformers", "numpy", "soundfile"]},
        "manifest_sha256": sha256(args.manifest),
        "audio_sha256": {r["clip_id"]: sha256(Path(r["file"])) for r, _ in clips},
        "summary": summary, "clips": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"exp01_{args.precision}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out_file}")


if __name__ == "__main__":
    main()
