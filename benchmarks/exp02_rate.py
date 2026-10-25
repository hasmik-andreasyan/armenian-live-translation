"""EXP-02 Step 6: blind human rating of the English translations.

Collects every distinct translation from the int8 and float32 runs. Outputs that
differ only in capitals or final punctuation are merged, since the meaning is
the same. They are shown in a fixed shuffled order WITHOUT saying which
configuration produced them, so the rating can't be biased.

Rate each translation against what the speaker MEANT (the original sentence and
reference), even when the input was the ASR version:
    0 = wrong or misleading (meaning lost or changed)
    1 = understandable (meaning gets across, wording is off)
    2 = good (correct and natural)

Progress is saved after every answer: you can stop with q and resume later.
At the end it prints ratings per configuration (precision x beam x condition).

Usage:
    .venv\\Scripts\\python benchmarks\\exp02_rate.py
"""

import json
import random
import string
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RATINGS_FILE = RESULTS / "exp02_ratings.json"
CONDITION_LABEL = {"A_original": "original Armenian", "B_asr_style": "lowercase, no punctuation",
                   "C_asr_output": "real ASR output (with recognition errors)"}


def canonical(text: str) -> str:
    return text.strip().rstrip(string.punctuation + " ").lower()


def latest(pattern: str) -> Path:
    files = sorted(RESULTS.glob(pattern))
    if not files:
        raise SystemExit(f"No results/{pattern} found.")
    return files[-1]


def load_items() -> tuple[list[dict], list[str]]:
    sources = [latest("exp02_int8_*.json"), latest("exp02_float32_*.json")]
    items: dict[str, dict] = {}
    for path in sources:
        report = json.loads(path.read_text(encoding="utf-8"))
        for r in report["results"]:
            key = f"{r['id']}|{r['condition']}|{canonical(r['output_en'])}"
            item = items.setdefault(key, {"key": key, "id": r["id"], "condition": r["condition"],
                                          "input_hy": r["input_hy"], "reference_en": r["reference_en"],
                                          "output_en": r["output_en"], "configs": []})
            item["configs"].append(f"{report['precision']}/beam{r['beam']}")
    ordered = sorted(items.values(), key=lambda x: x["key"])
    random.Random(42).shuffle(ordered)
    return ordered, [p.name for p in sources]


def summarise(items: list[dict], ratings: dict) -> dict:
    groups = defaultdict(list)
    for it in items:
        if it["key"] in ratings:
            for cfg in it["configs"]:
                groups[(cfg, it["condition"])].append(ratings[it["key"]]["rating"])
    summary = {}
    print(f"\n{'configuration':16s} {'condition':14s} {'n':>3s} {'mean':>5s} {'>=1 (understandable)':>21s} {'=2 (good)':>10s}")
    for (cfg, cond), vals in sorted(groups.items()):
        row = {"n": len(vals), "mean": round(sum(vals) / len(vals), 2),
               "understandable": sum(v >= 1 for v in vals), "good": sum(v == 2 for v in vals)}
        summary[f"{cfg}/{cond}"] = row
        print(f"{cfg:16s} {cond:14s} {row['n']:3d} {row['mean']:5.2f} {row['understandable']:>14d}/{row['n']:<6d} {row['good']:>4d}/{row['n']}")
    return summary


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    items, sources = load_items()
    state = json.loads(RATINGS_FILE.read_text(encoding="utf-8")) if RATINGS_FILE.exists() else {}
    ratings = state.get("ratings", {})
    todo = [it for it in items if it["key"] not in ratings]
    print(__doc__.split("Usage:")[0])
    print(f"{len(items)} distinct translations, {len(ratings)} already rated, {len(todo)} to go.\n")

    for n, it in enumerate(todo, len(ratings) + 1):
        print("-" * 70)
        print(f"[{n}/{len(items)}] {it['id']}, input = {CONDITION_LABEL[it['condition']]}")
        print(f"  Armenian input : {it['input_hy']}")
        print(f"  Reference      : {it['reference_en']}")
        print(f"  TRANSLATION    : {it['output_en']}")
        answer = ""
        while answer not in ("0", "1", "2", "q"):
            answer = input("  Rating 0 / 1 / 2 (q = save and quit): ").strip().lower()
        if answer == "q":
            break
        comment = input("  Comment (optional, Enter to skip): ").strip()
        ratings[it["key"]] = {"rating": int(answer), "comment": comment}
        RATINGS_FILE.write_text(json.dumps({"sources": sources, "ratings": ratings}, indent=2, ensure_ascii=False),
                                encoding="utf-8")

    summary = summarise(items, ratings)
    RATINGS_FILE.write_text(json.dumps({"sources": sources, "ratings": ratings, "items": items, "summary": summary},
                                       indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {RATINGS_FILE}  ({len(ratings)}/{len(items)} rated)")


if __name__ == "__main__":
    main()
