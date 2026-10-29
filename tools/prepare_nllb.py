"""Download Meta's official NLLB-200-distilled-600M and convert it to CTranslate2.

1. Shows the files and sizes at the PINNED revision and asks before downloading.
2. Downloads them to models/facebook__nllb-200-distilled-600M/ and verifies the
   weights' SHA-256 against the hash Hugging Face publishes.
3. Converts to CTranslate2:
       models/nllb-600m-ct2-int8/     (~0.6 GB, what the app uses)
       models/nllb-600m-ct2-float32/  (~2.5 GB, only with --with-float32: the
                                       accuracy reference for EXP-02, D-037)
   Each gets a SOURCE.txt recording repo, revision, quantization and ct2 version.

Conversion loads the full model into RAM (expect a peak of several GB):
close browsers and other heavy apps first.

Usage:
    .venv\\Scripts\\python tools\\prepare_nllb.py                  # the app: int8 only
    .venv\\Scripts\\python tools\\prepare_nllb.py --with-float32   # + EXP-02 reference
"""

import argparse
import inspect
import sys
import time
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from download_model import lfs_sha256, sha256_of  # noqa: E402  (shared, already tested helpers)

REPO = "facebook/nllb-200-distilled-600M"
REVISION = "f8d333a098d19b4fd9a8b18f94170487ad3f821d"  # inspected in CHK-02, 2026-10-26
TOKENIZER_FILES = ["tokenizer.json", "sentencepiece.bpe.model", "tokenizer_config.json", "special_tokens_map.json"]


def peak_mb() -> int:
    import psutil
    mi = psutil.Process().memory_info()
    return round(getattr(mi, "peak_wset", mi.rss) / 1e6)


def folder_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--models-dir", type=Path, default=Path("models"))
    p.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    p.add_argument("--with-float32", action="store_true",
                   help="also build the float32 model (EXP-02 reference only; the app uses int8)")
    args = p.parse_args()

    from huggingface_hub import HfApi, hf_hub_download

    # 1 ------------------------------------------------------------- plan
    info = HfApi().model_info(REPO, revision=REVISION, files_metadata=True)
    files = [s for s in info.siblings if s.rfilename not in (".gitattributes",)]
    src = args.models_dir / REPO.replace("/", "__")
    print(f"Repo {REPO} @ {REVISION}\nDestination: {src.resolve()}")
    for s in files:
        print(f"  {s.rfilename:28s} {(s.size or 0) / 1e6:9.1f} MB")
    print(f"  {'TOTAL':28s} {sum(s.size or 0 for s in files) / 1e6:9.1f} MB")
    quantizations = ("int8", "float32") if args.with_float32 else ("int8",)
    print("Then: convert to CTranslate2 " + " and ".join(quantizations)
          + (" (~0.6 GB + ~2.5 GB)." if args.with_float32 else " (~0.6 GB)."))
    if not args.yes and input("Download and convert? [y/N] ").strip().lower() != "y":
        raise SystemExit("Cancelled.")

    # 2 ------------------------------------------------------------- download + verify
    for s in files:
        hf_hub_download(REPO, s.rfilename, revision=REVISION, local_dir=src)
    print("\nVerifying:")
    failed = False
    for s in files:
        path = src / s.rfilename
        size_ok = path.stat().st_size == s.size
        expected = lfs_sha256(s)
        if expected is None:
            print(f"  {s.rfilename:28s} size {'OK' if size_ok else 'MISMATCH'} (small file, no published hash)")
            failed |= not size_ok
            continue
        ok = size_ok and sha256_of(path) == expected
        print(f"  {s.rfilename:28s} size {'OK' if size_ok else 'MISMATCH'}, sha256 {'OK' if ok else 'MISMATCH'}")
        failed |= not ok
    if failed:
        raise SystemExit("VERIFICATION FAILED: delete the folder and run again.")
    (src / "REVISION.txt").write_text(f"{REPO}\n{REVISION}\n", encoding="utf-8")

    # 3 ------------------------------------------------------------- convert
    import ctranslate2

    ct2_version = version("ctranslate2")
    kwargs = {"copy_files": TOKENIZER_FILES}
    if "low_cpu_mem_usage" in inspect.signature(ctranslate2.converters.TransformersConverter).parameters:
        kwargs["low_cpu_mem_usage"] = True
        print("\nConverter: low_cpu_mem_usage=True")
    else:
        print("\nConverter: this ctranslate2 version has no low_cpu_mem_usage option, so peak RAM will be higher")

    for quantization in quantizations:
        out = args.models_dir / f"nllb-600m-ct2-{quantization}"
        print(f"\nConverting to {out} (quantization={quantization}) ...")
        t0 = time.perf_counter()
        converter = ctranslate2.converters.TransformersConverter(str(src), **kwargs)
        converter.convert(str(out), quantization=quantization, force=True)
        (out / "SOURCE.txt").write_text(
            f"{REPO}\n{REVISION}\nquantization={quantization}\nctranslate2={ct2_version}\n", encoding="utf-8")
        print(f"  done in {time.perf_counter() - t0:.0f} s, folder {folder_mb(out):.0f} MB, process peak RAM so far {peak_mb()} MB")

    print("\nAll done.")


if __name__ == "__main__":
    main()
