"""CPU calibration benchmark (EXP-00).

Measures this laptop's *sustained* matrix-multiply throughput and memory
bandwidth, then predicts ASR time per phrase for each candidate model using
benchmarks/model_costs.py.

No models are downloaded. The only dependency is numpy.

Usage (from the project folder, inside the venv):
    .venv\\Scripts\\python benchmarks\\cpu_benchmark.py
    .venv\\Scripts\\python benchmarks\\cpu_benchmark.py --duration 60 --threads 4

Results are printed and saved as JSON in results/.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--duration", type=float, default=60.0, help="seconds of sustained load (default 60)")
    p.add_argument("--threads", type=int, default=None, help="BLAS threads (default: library default, usually all logical cores)")
    p.add_argument("--out", type=Path, default=Path("results"), help="folder for the JSON result")
    return p.parse_args()


args = parse_args()
# Thread count must be set BEFORE numpy is imported, otherwise it is ignored.
if args.threads:
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = str(args.threads)

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_costs import predict_seconds  # noqa: E402


# ---------------------------------------------------------------- system info
def windows_power_info() -> dict:
    """AC/battery state and active power scheme (Windows only)."""
    import ctypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    status = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        raise OSError("GetSystemPowerStatus failed")
    ac = {0: "battery", 1: "plugged in"}.get(status.ACLineStatus, "unknown")
    scheme = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True).stdout.strip()
    return {"power_source": ac, "power_scheme": scheme}


def total_ram_gb() -> float:
    if sys.platform == "win32":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullTotalPhys / 1e9, 1)
    with open("/proc/meminfo") as f:
        return round(int(f.readline().split()[1]) / 1e6, 1)


def system_info() -> dict:
    info = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cores": os.cpu_count(),
        "ram_gb": total_ram_gb(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "blas_threads_requested": args.threads or "default",
    }
    if sys.platform == "win32":
        info.update(windows_power_info())
    return info


# ---------------------------------------------------------------- benchmarks
def sustained_matmul(m: int, k: int, n: int, duration: float) -> list[float]:
    """Repeat an (m x k) @ (k x n) float32 matmul for `duration` seconds.

    Returns one GFLOP/s sample per second, so throttling shows up as a drop.
    """
    rng = np.random.default_rng(0)
    a = rng.standard_normal((m, k), dtype=np.float32)
    b = rng.standard_normal((k, n), dtype=np.float32)
    flops_per_call = 2.0 * m * k * n

    # Warm-up: lets the CPU boost and BLAS start its threads.
    t_end = time.perf_counter() + 3
    while time.perf_counter() < t_end:
        a @ b

    samples, calls = [], 0
    start = window_start = time.perf_counter()
    while True:
        a @ b
        calls += 1
        now = time.perf_counter()
        if now - window_start >= 1.0:
            samples.append(calls * flops_per_call / (now - window_start) / 1e9)
            print(f"\r  t={now - start:5.0f}s  {samples[-1]:7.1f} GFLOP/s", end="", flush=True)
            calls, window_start = 0, now
        if now - start >= duration:
            break
    print()
    return samples


def memory_bandwidth_gbs(size_mb: int = 256, repeats: int = 10) -> float:
    """Copy a large array repeatedly. Counts bytes read + bytes written."""
    src = np.ones(size_mb * 1024 * 1024 // 8, dtype=np.float64)
    dst = np.empty_like(src)
    np.copyto(dst, src)  # warm-up, page faults
    t0 = time.perf_counter()
    for _ in range(repeats):
        np.copyto(dst, src)
    elapsed = time.perf_counter() - t0
    return 2 * src.nbytes * repeats / elapsed / 1e9


def median(xs: list[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2]


# ---------------------------------------------------------------- main
def main() -> None:
    info = system_info()
    print("System:", json.dumps(info, indent=2))
    if info.get("power_source") == "battery":
        print("\nWARNING: running on battery. Results will not match the demo setup.\n")

    print(f"\n[1/3] Sustained float32 matmul, CTC-300M feed-forward shape (300x1024 @ 1024x4096), {args.duration:.0f} s")
    ctc_samples = sustained_matmul(300, 1024, 4096, args.duration)

    print("[2/3] Whisper-large encoder shape (1500x1280 @ 1280x5120), 10 s")
    whisper_samples = sustained_matmul(1500, 1280, 5120, 10)

    print("[3/3] Memory bandwidth (256 MB copy)")
    bandwidth = memory_bandwidth_gbs()

    first = median(ctc_samples[:10])
    last = median(ctc_samples[-20:])
    summary = {
        "ctc_shape_gflops_first10s_median": round(first, 1),
        "ctc_shape_gflops_last20s_median": round(last, 1),
        "ctc_shape_gflops_min": round(min(ctc_samples), 1),
        "sustained_ratio_last_vs_first": round(last / first, 2),
        "whisper_shape_gflops_median": round(median(whisper_samples), 1),
        "memory_bandwidth_gbs": round(bandwidth, 1),
    }

    # Predictions use the SUSTAINED (last 20 s) number: a live call is a sustained load.
    # float32 throughput = what PyTorch uses by default. int8 may be faster; we measure that later.
    macs_per_s = last * 1e9 / 2
    predictions = {f"{s:g}s_phrase": predict_seconds(macs_per_s, bandwidth * 1e9, s) for s in (3, 6, 10)}

    print("\nSummary:", json.dumps(summary, indent=2))
    print("\nPredicted ASR time per phrase (float32, from sustained throughput; rough, +/-2x):")
    print(f"  {'model':32s} {'3 s':>7s} {'6 s':>7s} {'10 s':>7s}")
    for i, row in enumerate(predictions["6s_phrase"]):
        t3, t6, t10 = (predictions[k][i]["seconds"] for k in ("3s_phrase", "6s_phrase", "10s_phrase"))
        print(f"  {row['model']:32s} {t3:6.1f}s {t6:6.1f}s {t10:6.1f}s")

    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"cpu_benchmark_{datetime.now():%Y%m%d_%H%M%S}.json"
    out_file.write_text(json.dumps({
        "system": info, "summary": summary, "per_second_gflops": [round(x, 1) for x in ctc_samples],
        "predictions": predictions,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved: {out_file}")


if __name__ == "__main__":
    main()
