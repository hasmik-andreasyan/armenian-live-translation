"""CHK-01: Can omniASR-CTC-300M-v2 run on this laptop? (no weight download)

What it does, in order:
  1. Imports every ASR dependency and records the installed versions.
  2. Lists the model repo's files and sizes on Hugging Face, and pins the commit.
  3. Downloads ONLY the small files (config, vocabulary, tokenizer settings,
     model card): a few KB. The 1.3 GB weights are NOT downloaded.
  4. Checks the config and vocabulary: standard Wav2Vec2ForCTC? Blank token at
     id 0? How many vocabulary pieces contain Armenian letters? What does the
     model card say about the parity check?
  5. Builds the exact architecture from config.json with RANDOM weights and
     times a forward pass on 3 / 6 / 10 s of noise, in float32 and int8.
     Speed and RAM of a dense network don't depend on the weight values, so
     this measures real latency without the download. The output text is
     meaningless at this stage, by design.

Usage (project folder, after installing requirements-asr.txt):
    .venv\\Scripts\\python benchmarks\\check_ctc_compat.py

Exit code 0 = all checks passed, 1 = at least one check failed (see output).
"""

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

DEFAULT_REPO = "aadel4/omniASR-CTC-300M-v2"
SMALL_FILES = ["config.json", "vocab.json", "tokenizer_config.json",
               "special_tokens_map.json", "preprocessor_config.json", "README.md"]
REQUIRED_FILES = {"config.json", "vocab.json"}
ARMENIAN_BLOCK = range(0x0530, 0x0590)  # Unicode block "Armenian"
SAMPLE_RATE = 16000
ASR_BUDGET_S = 2.0  # from the latency budget in PLAN.md


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--threads", type=int, default=4, help="torch threads (D-010: 4)")
    p.add_argument("--lengths", type=float, nargs="+", default=[3, 6, 10], help="clip lengths in seconds")
    p.add_argument("--runs", type=int, default=3, help="timed runs per length (median is reported)")
    p.add_argument("--models-dir", type=Path, default=Path("models"))
    p.add_argument("--out", type=Path, default=Path("results"))
    p.add_argument("--skip-int8", action="store_true")
    return p.parse_args()


class Checks:
    """Collects pass/fail results so the script reports everything, then fails loudly."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append({"check": name, "ok": ok, "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))

    @property
    def all_ok(self) -> bool:
        return all(i["ok"] for i in self.items)


def memory_mb() -> dict:
    import psutil
    mi = psutil.Process().memory_info()
    out = {"rss_mb": round(mi.rss / 1e6)}
    if hasattr(mi, "peak_wset"):  # Windows only
        out["peak_mb"] = round(mi.peak_wset / 1e6)
    return out


def time_forward(model, torch, seconds: float, runs: int) -> dict:
    x = torch.randn(1, int(SAMPLE_RATE * seconds))
    times = []
    with torch.inference_mode():
        for _ in range(runs):
            t0 = time.perf_counter()
            logits = model(x).logits
            times.append(time.perf_counter() - t0)
    med = statistics.median(times)
    return {"clip_s": seconds, "median_s": round(med, 3), "all_s": [round(t, 3) for t in times],
            "rtf": round(med / seconds, 3), "logits_shape": list(logits.shape)}


def main() -> None:
    args = parse_args()
    checks = Checks()
    report: dict = {"timestamp": datetime.now().isoformat(timespec="seconds"), "repo": args.repo,
                    "platform": platform.platform(), "python": sys.version.split()[0]}

    # 1 ---------------------------------------------------------- dependencies
    print("\n[1/5] Dependencies")
    import numpy  # noqa: F401
    import torch
    import transformers  # noqa: F401
    import soundfile
    import jiwer  # noqa: F401
    import psutil  # noqa: F401
    from huggingface_hub import HfApi, hf_hub_download

    pkgs = ["torch", "transformers", "huggingface_hub", "soundfile", "psutil", "jiwer", "numpy"]
    report["versions"] = {p: version(p) for p in pkgs}
    report["versions"]["libsndfile"] = soundfile.__libsndfile_version__
    for p, v in report["versions"].items():
        print(f"  {p:16s} {v}")
    torch.set_num_threads(args.threads)
    report["torch_threads"] = torch.get_num_threads()
    report["quantized_engines"] = list(torch.backends.quantized.supported_engines)
    checks.add("torch uses requested threads", torch.get_num_threads() == args.threads, str(torch.get_num_threads()))
    checks.add("torch is CPU build", not torch.cuda.is_available(), f"cuda available: {torch.cuda.is_available()}")

    # 2 ---------------------------------------------------------- repo listing
    print(f"\n[2/5] Repository listing: {args.repo}")
    info = HfApi().model_info(args.repo, files_metadata=True)
    files = {s.rfilename: s.size for s in info.siblings}
    report["revision"] = info.sha
    report["repo_files"] = files
    for name, size in sorted(files.items()):
        print(f"  {name:40s} {size / 1e6 if size else 0:10.1f} MB")
    weights = {n: s for n, s in files.items() if n.endswith((".safetensors", ".bin"))}
    report["weights_total_mb"] = round(sum(s or 0 for s in weights.values()) / 1e6)
    print(f"  pinned revision: {info.sha}")
    checks.add("weights in safetensors format", any(n.endswith(".safetensors") for n in weights), ", ".join(weights))
    missing = REQUIRED_FILES - files.keys()
    checks.add("required small files present", not missing, f"missing: {sorted(missing)}" if missing else "")
    if missing:
        raise SystemExit("Cannot continue without config.json and vocab.json.")

    # 3 ---------------------------------------------------------- small files only
    print("\n[3/5] Downloading small files only (no weights)")
    model_dir = args.models_dir / args.repo.replace("/", "__")
    for name in SMALL_FILES:
        if name in files:
            hf_hub_download(args.repo, name, revision=info.sha, local_dir=model_dir)
            print(f"  got {name}")
    report["model_dir"] = str(model_dir)

    # 4 ---------------------------------------------------------- config / vocab
    print("\n[4/5] Config and vocabulary")
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    vocab = json.loads((model_dir / "vocab.json").read_text(encoding="utf-8"))
    keys = ["architectures", "hidden_size", "num_hidden_layers", "intermediate_size",
            "num_attention_heads", "vocab_size", "pad_token_id", "do_stable_layer_norm", "feat_extract_norm"]
    report["config"] = {k: config.get(k) for k in keys}
    for k in keys:
        print(f"  {k:24s} {config.get(k)}")
    checks.add("architecture is standard Wav2Vec2ForCTC", config.get("architectures") == ["Wav2Vec2ForCTC"])
    checks.add("vocab size matches config", len(vocab) == config.get("vocab_size"), f"{len(vocab)} vs {config.get('vocab_size')}")
    checks.add("CTC blank <s> is id 0 and pad_token_id", vocab.get("<s>") == 0 and config.get("pad_token_id") == 0)
    armenian = [t for t in vocab if any(ord(c) in ARMENIAN_BLOCK for c in t)]
    report["armenian_vocab_pieces"] = len(armenian)
    report["armenian_vocab_examples"] = armenian[:30]
    checks.add("vocabulary contains Armenian pieces", len(armenian) > 0, f"{len(armenian)} pieces, e.g. {armenian[:10]}")
    if (model_dir / "README.md").exists():
        card = (model_dir / "README.md").read_text(encoding="utf-8")
        parity = [line.strip() for line in card.splitlines() if "parity" in line.lower()]
        report["model_card_parity_lines"] = parity
        print("  model card lines mentioning parity:")
        for line in parity or ["(none found)"]:
            print(f"    {line}")

    # 5 ---------------------------------------------------------- random-weight timing
    print(f"\n[5/5] Random-weight forward pass, {args.threads} threads")
    from transformers import Wav2Vec2Config, Wav2Vec2ForCTC

    mem_before = memory_mb()
    t0 = time.perf_counter()
    model = Wav2Vec2ForCTC(Wav2Vec2Config.from_pretrained(model_dir)).eval()
    report["build_s"] = round(time.perf_counter() - t0, 1)
    n_params = sum(p.numel() for p in model.parameters())
    report["n_params_m"] = round(n_params / 1e6, 1)
    print(f"  built in {report['build_s']} s, {report['n_params_m']}M parameters")
    checks.add("parameter count ~325M", 300e6 < n_params < 350e6, f"{n_params / 1e6:.1f}M")

    with torch.inference_mode():  # warm-up
        model(torch.randn(1, SAMPLE_RATE * 3))
    report["fp32"] = [time_forward(model, torch, s, args.runs) for s in args.lengths]
    report["memory_fp32"] = {"before_model": mem_before, "after": memory_mb()}
    for r in report["fp32"]:
        frames_expected = round(r["clip_s"] * 50)
        ok_shape = abs(r["logits_shape"][1] - frames_expected) <= 2 and r["logits_shape"][2] == config["vocab_size"]
        checks.add(f"fp32 {r['clip_s']:g}s output shape", ok_shape, str(r["logits_shape"]))
        print(f"  fp32 {r['clip_s']:4.0f} s clip: {r['median_s']:.2f} s (RTF {r['rtf']:.2f}) "
              f"{'within' if r['median_s'] <= ASR_BUDGET_S else 'OVER'} the {ASR_BUDGET_S:g} s ASR budget")

    if not args.skip_int8:
        try:
            qmodel = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
        except Exception as e:  # reported, not hidden: int8 support is one of the things we test
            report["int8_error"] = repr(e)
            checks.add("int8 dynamic quantization available", False, repr(e))
        else:
            with torch.inference_mode():
                qmodel(torch.randn(1, SAMPLE_RATE * 3))
            report["int8"] = [time_forward(qmodel, torch, s, args.runs) for s in args.lengths]
            report["memory_after_int8"] = memory_mb()
            checks.add("int8 dynamic quantization available", True)
            for r in report["int8"]:
                print(f"  int8 {r['clip_s']:4.0f} s clip: {r['median_s']:.2f} s (RTF {r['rtf']:.2f})")

    print("\nMemory:", report["memory_fp32"], report.get("memory_after_int8", ""))
    report["checks"] = checks.items
    report["all_checks_passed"] = checks.all_ok
    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"chk01_ctc_compat_{datetime.now():%Y%m%d_%H%M%S}.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out_file}")
    print("ALL CHECKS PASSED" if checks.all_ok else "SOME CHECKS FAILED: see [FAIL] lines above")
    sys.exit(0 if checks.all_ok else 1)


if __name__ == "__main__":
    main()
