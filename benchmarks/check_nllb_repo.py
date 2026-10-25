"""CHK-02: Is NLLB-200-distilled-600M usable here? (no weight download)

1. Imports ctranslate2 and sacrebleu, records versions, and lists the CPU
   compute types CTranslate2 supports on this machine (we need "int8").
2. Lists the official repo's files and sizes, and pins the commit.
3. Downloads ONLY the tokenizer/config files (a few MB, no weights).
4. Loads the tokenizer and checks:
   - the language codes hye_Armn and eng_Latn exist as real tokens;
   - every sentence in eval/mt_sentences.csv tokenizes without <unk>;
   - input lengths in tokens (feeds the latency estimate).

Usage (project folder):
    .venv\\Scripts\\python benchmarks\\check_nllb_repo.py

Exit code 0 = all checks passed, 1 = at least one failed.
"""

import csv
import json
import platform
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.text_norm import normalize_for_scoring  # noqa: E402

REPO = "facebook/nllb-200-distilled-600M"
SMALL_FILES = ["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
               "special_tokens_map.json", "sentencepiece.bpe.model", "README.md"]
WEIGHT_SUFFIXES = (".safetensors", ".bin")


class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append({"check": name, "ok": ok, "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    checks = Checks()
    report: dict = {"timestamp": datetime.now().isoformat(timespec="seconds"), "repo": REPO,
                    "platform": platform.platform(), "python": sys.version.split()[0]}

    print("\n[1/4] Dependencies")
    import ctranslate2
    import sacrebleu  # noqa: F401
    from huggingface_hub import HfApi, hf_hub_download
    from transformers import AutoTokenizer

    report["versions"] = {p: version(p) for p in ["ctranslate2", "sacrebleu", "transformers", "tokenizers", "torch"]}
    for p, v in report["versions"].items():
        print(f"  {p:14s} {v}")
    compute_types = sorted(ctranslate2.get_supported_compute_types("cpu"))
    report["ct2_cpu_compute_types"] = compute_types
    checks.add("CTranslate2 supports int8 on this CPU", "int8" in compute_types, ", ".join(compute_types))

    print(f"\n[2/4] Repository listing: {REPO}")
    info = HfApi().model_info(REPO, files_metadata=True)
    files = {s.rfilename: s.size for s in info.siblings}
    report["revision"] = info.sha
    report["repo_files"] = files
    for name, size in sorted(files.items()):
        print(f"  {name:32s} {(size or 0) / 1e6:9.1f} MB")
    weights = {n: s for n, s in files.items() if n.endswith(WEIGHT_SUFFIXES)}
    print(f"  pinned revision: {info.sha}")
    checks.add("weights present", bool(weights), ", ".join(f"{n} ({(s or 0) / 1e9:.2f} GB)" for n, s in weights.items()))
    checks.add("fast tokenizer file (tokenizer.json) present", "tokenizer.json" in files)

    print("\n[3/4] Downloading tokenizer/config files only (no weights)")
    model_dir = ROOT / "models" / REPO.replace("/", "__")
    for name in SMALL_FILES:
        if name in files:
            hf_hub_download(REPO, name, revision=info.sha, local_dir=model_dir)
            print(f"  got {name}")
    report["model_dir"] = str(model_dir)

    print("\n[4/4] Tokenizer checks")
    tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, src_lang="hye_Armn")
    report["tokenizer_class"] = type(tok).__name__
    print(f"  tokenizer: {type(tok).__name__}, vocab size {len(tok)}")
    for code in ("hye_Armn", "eng_Latn"):
        tid = tok.convert_tokens_to_ids(code)
        checks.add(f"language token {code} exists", tid is not None and tid != tok.unk_token_id, f"id {tid}")

    with open(ROOT / "eval" / "mt_sentences.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    lengths, unknown = {}, {}
    for r in rows:
        for variant, text in (("original", r["hy"]), ("asr_style", normalize_for_scoring(r["hy"]))):
            ids = tok(text).input_ids
            lengths[f"{r['id']}/{variant}"] = len(ids)
            if ids.count(tok.unk_token_id):
                unknown[f"{r['id']}/{variant}"] = ids.count(tok.unk_token_id)
    checks.add("all sentences tokenize without <unk>", not unknown, json.dumps(unknown) if unknown else "")
    report["input_token_lengths"] = lengths
    print("  input lengths (tokens incl. language code + </s>):")
    for r in rows:
        print(f"    {r['id']:7s} original {lengths[r['id'] + '/original']:3d}   asr_style {lengths[r['id'] + '/asr_style']:3d}")

    report["checks"] = checks.items
    report["all_checks_passed"] = all(c["ok"] for c in checks.items)
    out = ROOT / "results" / f"chk02_nllb_repo_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")
    print("ALL CHECKS PASSED" if report["all_checks_passed"] else "SOME CHECKS FAILED: see [FAIL] lines above")
    sys.exit(0 if report["all_checks_passed"] else 1)


if __name__ == "__main__":
    main()
