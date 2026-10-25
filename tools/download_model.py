"""Download omniASR-CTC-300M-v2 at a PINNED revision and verify it.

- Revision is fixed (the commit CHK-01 inspected), so everyone gets the same files.
- Shows the file list and total size, and asks before downloading (or pass --yes).
- After download, checks every large file's SHA-256 against the hash Hugging Face
  publishes for it, and writes REVISION.txt next to the model.

Usage:
    .venv\\Scripts\\python tools\\download_model.py
"""

import argparse
import hashlib
from pathlib import Path

REPO = "aadel4/omniASR-CTC-300M-v2"
REVISION = "f2b3c39a62c061c27623c3f2d803294fbb954324"  # inspected in CHK-01, 2026-10-26


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def lfs_sha256(sibling) -> str | None:
    lfs = getattr(sibling, "lfs", None)
    if lfs is None:
        return None
    return getattr(lfs, "sha256", None) or (lfs.get("sha256") if isinstance(lfs, dict) else None)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--models-dir", type=Path, default=Path("models"))
    p.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = p.parse_args()

    from huggingface_hub import HfApi, hf_hub_download

    info = HfApi().model_info(REPO, revision=REVISION, files_metadata=True)
    files = [s for s in info.siblings if s.rfilename != ".gitattributes"]
    total = sum(s.size or 0 for s in files)
    dest = args.models_dir / REPO.replace("/", "__")
    print(f"Repo {REPO} @ {REVISION}\nDestination: {dest.resolve()}")
    for s in files:
        print(f"  {s.rfilename:30s} {(s.size or 0) / 1e6:9.1f} MB")
    print(f"  {'TOTAL':30s} {total / 1e6:9.1f} MB")
    if not args.yes and input("Download? [y/N] ").strip().lower() != "y":
        raise SystemExit("Cancelled.")

    for s in files:
        hf_hub_download(REPO, s.rfilename, revision=REVISION, local_dir=dest)

    print("\nVerifying:")
    failed = False
    for s in files:
        path = dest / s.rfilename
        size_ok = path.stat().st_size == s.size
        expected = lfs_sha256(s)
        if expected is None:
            print(f"  {s.rfilename:30s} size {'OK' if size_ok else 'MISMATCH'} (small file, no published hash)")
            failed |= not size_ok
            continue
        actual = sha256_of(path)
        ok = size_ok and actual == expected
        print(f"  {s.rfilename:30s} size {'OK' if size_ok else 'MISMATCH'}, sha256 {'OK' if ok else 'MISMATCH'}")
        failed |= not ok
    if failed:
        raise SystemExit("VERIFICATION FAILED: delete the folder and download again.")
    (dest / "REVISION.txt").write_text(f"{REPO}\n{REVISION}\n", encoding="utf-8")
    print(f"\nAll files verified. Wrote {dest / 'REVISION.txt'}")


if __name__ == "__main__":
    main()
