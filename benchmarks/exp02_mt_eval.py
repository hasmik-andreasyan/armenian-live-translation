"""EXP-02: Armenian → English translation quality, latency and RAM (NLLB-600M, CTranslate2).

Run once per precision, each in its own process, so RAM numbers don't mix:
    .venv\\Scripts\\python benchmarks\\exp02_mt_eval.py --precision int8
    .venv\\Scripts\\python benchmarks\\exp02_mt_eval.py --precision float32
        (float32 needs: tools\\prepare_nllb.py --with-float32)

Input conditions (D-017):
    A original   : Armenian with punctuation and capitals (eval/mt_sentences.csv)
    B asr_style  : same text lowercased, punctuation removed (no recognition errors)
    C asr_output : real int8 ASR hypotheses from EXP-01 (recorded clips only)
Each condition is translated with beam size 1 and 4.

Metrics: chrF (sacrebleu) per sentence and per condition, latency (median of
--runs), output tokens, seconds per token, RSS after load and peak.
Human ratings are collected afterwards (Step 6).
"""

import argparse
import csv
import json
import platform
import statistics
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psutil  # noqa: E402
import sacrebleu  # noqa: E402

from app.text_norm import normalize_for_scoring  # noqa: E402
from app.translate import NllbTranslator  # noqa: E402

TOKENIZER_DIR = ROOT / "models" / "facebook__nllb-200-distilled-600M"


def mem_mb() -> dict:
    mi = psutil.Process().memory_info()
    return {"rss_mb": round(mi.rss / 1e6), "peak_mb": round(getattr(mi, "peak_wset", mi.rss) / 1e6)}


def latest(pattern: str) -> Path:
    files = sorted((ROOT / "results").glob(pattern))
    if not files:
        raise SystemExit(f"No results/{pattern} found.")
    return files[-1]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--precision", choices=["int8", "float32"], required=True)
    p.add_argument("--beams", type=int, nargs="+", default=[1, 4])
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--sentences", type=Path, default=ROOT / "eval" / "mt_sentences.csv")
    p.add_argument("--asr-results", type=Path, default=None, help="EXP-01 int8 JSON (default: latest)")
    args = p.parse_args()

    model_dir = ROOT / "models" / f"nllb-600m-ct2-{args.precision}"
    if not (model_dir / "SOURCE.txt").exists():
        raise SystemExit(f"{model_dir} missing: run tools/prepare_nllb.py first.")
    asr_file = args.asr_results or latest("exp01_int8_*.json")
    asr = {c["clip_id"]: c["hypothesis"] for c in json.loads(asr_file.read_text(encoding="utf-8"))["clips"]}

    with open(args.sentences, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    items = []  # (id, condition, armenian input, english reference)
    for r in rows:
        items.append((r["id"], "A_original", r["hy"], r["en_ref"]))
        items.append((r["id"], "B_asr_style", normalize_for_scoring(r["hy"]), r["en_ref"]))
        if r["id"] in asr:
            items.append((r["id"], "C_asr_output", asr[r["id"]], r["en_ref"]))

    mem_start = mem_mb()
    mt = NllbTranslator(model_dir, TOKENIZER_DIR, compute_type=args.precision, threads=args.threads)
    mem_loaded = mem_mb()
    print(f"Loaded {args.precision} from {model_dir.name}: RSS {mem_loaded['rss_mb']} MB")
    mt.translate(items[0][2], beam_size=max(args.beams))  # warm-up, not timed

    results = []
    for beam in args.beams:
        print(f"\n=== beam size {beam} ===")
        for sid, cond, hy, ref in items:
            runs = [mt.translate(hy, beam_size=beam) for _ in range(args.runs)]
            en = runs[-1].text
            latency = statistics.median(x.seconds for x in runs)
            chrf = sacrebleu.sentence_chrf(en, [ref]).score
            results.append({
                "id": sid, "condition": cond, "beam": beam, "input_hy": hy, "reference_en": ref, "output_en": en,
                "deterministic": len({x.text for x in runs}) == 1, "output_tokens": runs[-1].output_tokens,
                "latency_s": round(latency, 3), "all_latencies_s": [round(x.seconds, 3) for x in runs],
                "s_per_token": round(latency / max(runs[-1].output_tokens, 1), 4), "chrf": round(chrf, 1),
            })
            print(f"[{sid:6s} {cond:12s}] {latency:5.2f} s  {runs[-1].output_tokens:2d} tok  chrF {chrf:5.1f}  EN: {en}")

    summary = {}
    for beam in args.beams:
        for cond in ("A_original", "B_asr_style", "C_asr_output"):
            sel = [x for x in results if x["beam"] == beam and x["condition"] == cond]
            if not sel:
                continue
            summary[f"beam{beam}/{cond}"] = {
                "n": len(sel),
                "corpus_chrf": round(sacrebleu.corpus_chrf([x["output_en"] for x in sel], [[x["reference_en"] for x in sel]]).score, 1),
                "median_latency_s": round(statistics.median(x["latency_s"] for x in sel), 3),
                "max_latency_s": max(x["latency_s"] for x in sel),
                "median_s_per_token": round(statistics.median(x["s_per_token"] for x in sel), 4),
            }
    summary["memory"] = {"start": mem_start, "after_load": mem_loaded, "end": mem_mb()}
    print("\nSummary:", json.dumps(summary, indent=2))

    report = {
        "experiment": "EXP-02", "timestamp": datetime.now().isoformat(timespec="seconds"),
        "precision": args.precision, "threads": args.threads, "runs": args.runs, "beams": args.beams,
        "model_source": (model_dir / "SOURCE.txt").read_text(encoding="utf-8").split(),
        "asr_results_file": asr_file.name, "platform": platform.platform(), "python": sys.version.split()[0],
        "versions": {pkg: version(pkg) for pkg in ["ctranslate2", "transformers", "sacrebleu"]},
        "summary": summary, "results": results,
    }
    out = ROOT / "results" / f"exp02_{args.precision}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
