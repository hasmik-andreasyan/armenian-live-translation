# EXPERIMENTS.md: Measurement log

Every measurement that informs a decision goes here, with the raw JSON in `results/`.
Conditions for all runs unless noted: **plugged in, Best performance mode, laptop warm**.

## EXP-00 · CPU calibration (`benchmarks/cpu_benchmark.py`)

| Date | Threads | GFLOP/s first 10 s | GFLOP/s last 20 s (sustained) | Sustained ratio | Whisper-shape GFLOP/s | Mem. bandwidth GB/s | Power source | Notes |
|---|---|---|---|---|---|---|---|---|
| | default | | | | | | | |
| | 4 | | | | | | | |

Predicted float32 ASR time per phrase (copy from the script output):

| Model | 3 s | 6 s | 10 s |
|---|---|---|---|
| Whisper large-v3 / BuzzASR | | | |
| Whisper large-v3-turbo | | | |
| omniASR-CTC-1B / MMS-1b-all | | | |
| omniASR-CTC-300M | | | |

## ASR runs (EXP-01 onwards)

**Latency** = ASR time for one clip (median of 3 warm runs). **RTF** = latency / clip length. **Peak RAM** = process peak working set. CER/WER are normalised (lowercase, punctuation removed).

| Exp | Date | Model | Precision | Threads | Clip | Clip s | Load s | Latency s | RTF | Peak RAM MB | CER | WER | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | | | |
