# EXPERIMENTS.md: Measurement log

Every measurement that informs a decision goes here, with the raw JSON in `results/`.
Conditions for all runs unless noted: **plugged in, Best performance mode, laptop warm**.

## EXP-00 · CPU calibration (`benchmarks/cpu_benchmark.py`)

Environment: Windows 10 (19045), Python 3.12.3, numpy 2.5.4, i5-8250U (8 logical cores), 8.4 GB RAM, plugged in. The power scheme reports "Balanced". On Windows 10 the "Best performance" slider sits inside that scheme, so `powercfg` can't show it.

| Date | Threads | GFLOP/s first 10 s | GFLOP/s last 20 s (sustained) | Min GFLOP/s | Sustained ratio | Whisper-shape GFLOP/s | Mem. bandwidth GB/s | Raw file |
|---|---|---|---|---|---|---|---|---|
| 2026-10-26 | default (8) | 115.6 | 128.4 | **32.6** | 1.11 | 174.9 | 8.3 | `results/cpu_benchmark_20261026_000640.json` |
| 2026-10-26 | **4** | **169.8** | **144.8** | 114.6 | 0.85 | 135.8 | 10.6 | `results/cpu_benchmark_20261026_000822.json` |

Predicted float32 ASR time per phrase, using the **4-thread sustained** throughput (≈ 72 GMAC/s):

| Model | 3 s | 6 s | 10 s | Fits a ~2 s ASR budget? |
|---|---|---|---|---|
| Whisper large-v3 / BuzzASR | 21.0 s | 24.1 s | 28.2 s | No |
| Whisper large-v3-turbo | 16.6 s | 17.2 s | 18.0 s | No |
| Whisper medium | 10.5 s | 12.1 s | 14.2 s | No |
| Whisper small | 3.2 s | 3.8 s | 4.5 s | No |
| omniASR-CTC-1B / MMS-1b-all | 2.2 s | 4.4 s | 7.5 s | Only short phrases |
| **omniASR-CTC-300M** | **0.8 s** | **1.6 s** | **2.7 s** | **Yes, up to ~7 s phrases** |

### Findings
1. **Use 4 threads (one per physical core), not the default 8.** With 8 threads, throughput swung between 33 and 155 GFLOP/s, with several drops below 50. With 4 threads it stayed between 115 and 172. For a live system, **stable latency matters more than peak speed.** The likely cause is two threads competing for one physical core (hyper-threading), plus background tasks.
2. **Moderate throttling under sustained load.** With 4 threads, speed dropped from ~170 to ~145 GFLOP/s (ratio 0.85). Predictions use the sustained number, since a call is a sustained load.
3. **Memory bandwidth is low: 8–11 GB/s.** I assumed ~15 GB/s. This suggests a single-channel RAM configuration (to be confirmed). It hurts autoregressive decoders like Whisper's, and large models in general. One more reason against Whisper-large.
4. **My earlier estimate (D-007) was optimistic by roughly 2–4×.** It assumed 150–300 GMAC/s (int8). The measured float32 rate is ~72 GMAC/s. The conclusion holds and is now stronger: **only CTC-300M fits comfortably.** CTC-1B fits only for short phrases, unless int8 helps a lot.
5. **Caveat:** these are pure matrix-multiply numbers, a best case. A real model also spends time in convolutions, attention, normalisation and Python overhead. The compatibility check (CHK-01) measures the real 300M architecture.

## CHK-01 · omniASR-CTC-300M-v2 compatibility + random-weight timing (`benchmarks/check_ctc_compat.py`)

| Date | Revision | torch / transformers | Checks | fp32 3 / 6 / 10 s | int8 3 / 6 / 10 s | RSS fp32 model / + int8 copy | Armenian vocab pieces | Raw file |
|---|---|---|---|---|---|---|---|---|
| 2026-10-26 | `f2b3c39a` | 2.14.1 / 5.20.2 | **13/13 pass** | 1.08 / 2.12 / 3.83 s | **0.99 / 1.70 / 2.86 s** | 1706 MB / 2070 MB (peak 2331) | 80 | `results/chk01_ctc_compat_20261026_002539.json` |

Random weights, 4 threads, median of 3 runs. Quantisation engine: `onednn`. Build time 5.3 s, 326.0 M parameters, weights 1304 MB (`model.safetensors`).

### Findings
1. **Compatible.** The standard `Wav2Vec2ForCTC` runs on Windows / Python 3.12 / torch 2.14 CPU. Output shapes are correct: 50 frames per second, 10,288 classes.
2. **Real latency, 6 s phrase: fp32 2.12 s, int8 1.70 s.** The matmul prediction (1.6 s fp32) was ~1.3× optimistic, as expected. The real model has overhead beyond matrix multiplications.
3. **int8 is only 8–25 % faster** (more on longer clips). That helps, but it isn't a 2× gain. Its **accuracy cost is unknown**, so EXP-01 measures fp32 and int8 on the same clips.
4. **Latency budget:** with int8, a phrase of ≤ ~7 s fits the ~2 s ASR budget. 10 s doesn't (2.9 s). This feeds the max-segment-length decision. RTF ≈ 0.28–0.33.
5. **RAM:** the fp32 model adds ~1.4 GB. In this test the int8 copy sat *next to* the fp32 one, so int8-alone RAM isn't known yet. EXP-01 measures each precision in a separate process.
6. **Vocabulary is character-level for Armenian:** 80 pieces, covering all upper/lowercase letters, `և`, and Armenian punctuation (`։ ՝ ՞ ՛ ՜ ֊`). Latin letters, digits and `. , ? ! - :` are also present. **Words are separated by a plain space** (the tokenizer config says `word_delimiter_token: " "`), not by `▁` as the converter source suggested. The model *may* output casing and punctuation, and EXP-01 will show whether it does.
7. **Model card says "Parity verification ✅ Verified"**: fairseq2 and HF outputs match within `atol=1e-4`. The sample clip was **English**, so Armenian accuracy is still unmeasured.

## ASR runs (EXP-01 onwards)

**Latency** = ASR time for one clip (median of 3 warm runs). **RTF** = latency / clip length. **Peak RAM** = process peak working set. CER/WER are normalised (lowercase, punctuation removed).

### EXP-01 · omniASR-CTC-300M-v2 (rev `f2b3c39a`), speaker_a, Jabra headset (MME device 1), 3 clips

Recordings (16 kHz mono 16-bit, `eval/audio/`, not committed). Checked level per 100 ms and "speech minus background" ratio:

| Clip | Total | Speech | Peak | Speech vs. background |
|---|---|---|---|---|
| clip01 | 3.8 s | ~2.0 s | 0.12 | ~35 dB (recorded quieter) |
| clip02 | 6.0 s | 5.4 s | 0.91 | ~56 dB |
| clip03 | 9.5 s | 8.7 s | 0.92 | ~54 dB |

| Exp | Date | Precision | Threads | Clip | Clip s | Load s | Latency s | RTF | RSS after load / peak MB | CER norm | WER norm | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EXP-01 | 2026-10-26 | fp32 | 4 | clip01 | 3.85 | 17.2 | 1.92 | 0.50 | 1669 / 1884 | 0.0 % | 0.0 % | perfect after normalisation |
| EXP-01 | 2026-10-26 | fp32 | 4 | clip02 | 6.01 | | 2.77 | 0.46 | | 0.0 % | 0.0 % | perfect after normalisation |
| EXP-01 | 2026-10-26 | fp32 | 4 | clip03 | 9.46 | | 3.63 | 0.38 | | 9.7 % | 46.7 % | see errors below |
| **EXP-01** | | **fp32** | | **corpus** | | | max 3.63 | median 0.46 | | **5.4 %** | 21.9 % | raw CER 10.1 %. Raw file: `results/exp01_fp32_20261026_014121.json` |
| EXP-01 | 2026-10-26 | int8 | 4 | clip01 | 3.85 | 40.5 | **0.98** | 0.26 | 1792 after load (peak 2272) → **1028 at end** | 0.0 % | 0.0 % | identical to fp32 |
| EXP-01 | 2026-10-26 | int8 | 4 | clip02 | 6.01 | | **1.50** | 0.25 | | 2.9 % | 25.0 % | `գնամհամալսարան` (missing space), `նկերների` (dropped ը) |
| EXP-01 | 2026-10-26 | int8 | 4 | clip03 | 9.46 | | **2.60** | 0.28 | | 9.7 % | 40.0 % | fixed `որը թարգմանում`, new `ավելված` (dropped հ) |
| **EXP-01** | | **int8** | | **corpus** | | | max 2.60 | median 0.26 | | **6.3 %** | 28.1 % | raw CER 11.0 %. Raw file: `results/exp01_int8_20261026_014417.json` |

Both runs used identical audio and manifest (SHA-256 checked).

**fp32 observations:**
- **Errors in clip03:**
  - `Python` → `փայսոն` (transliterated into Armenian letters, `ս` instead of `թ`). That's 6 of the 11 character errors.
  - `որպեսզի` → `որպիսի`.
  - `որը թարգմանում` → `որըթարգմանում` (missing space).
  - `հայերեն` → `հայրեն`.
  - `անգլերեն` → `անգլեր են` (extra space).
  - Without the English term, clip03 CER ≈ 4.7 %.
- **The output is lowercase with no punctuation.** Raw CER is higher only because of capitals and `։`. This matters for translation, which will get unpunctuated lowercase input.
- **Deterministic** (all 3 runs identical), no `<unk>` tokens.
- **Latency is over the ~2 s budget for a 6 s phrase (2.77 s).** Short clips were slower than CHK-01 predicted: clip01 1.92 s vs ~1.4 s scaled, clip02 2.77 s vs ~2.1 s. clip03 matched (3.63 s vs 3.83 s for 10 s). The cause is unknown. To investigate after the int8 run, without guessing.

**fp32 vs int8 comparison:**
1. **Accuracy:** int8 is **+1.0 CER point** worse (6.3 % vs 5.4 %), within the pre-agreed +2 limit. 3 characters changed in total: 2 new errors in clip02, and 1 fixed + 1 new in clip03. Both new errors drop a short word-initial sound or the space before it. That's too few characters to call it a pattern. Watch it as the eval set grows.
2. **Latency:** int8 is **~1.9× faster** with real weights (RTF 0.26 vs 0.46). **6 s phrase: 1.50 s, within the ~2 s ASR budget.** 9.5 s phrase: 2.60 s, over budget. So segments need a cap around **7–8 s** (to be tuned).
3. **Unexpected:** in CHK-01 (random weights) int8 was only 8–25 % faster than fp32. With real weights it's ~1.9× faster. int8 latency matches CHK-01, but **fp32 with real weights is slower than with random weights.** One untested hypothesis is denormal (extremely small) floating-point numbers slowing fp32 arithmetic. It could be tested with `torch.set_flush_denormal(True)`. **Low priority: we use int8.**
4. **RAM:** int8 steady state ≈ **1.0 GB** (RSS at end), vs ≈ 1.7 GB fp32. Peak 2.3 GB **only during startup**, while the fp32 model and its int8 copy coexist. Load time is 40 s vs 17 s. If startup RAM or time becomes a problem, we can save the quantised model once and load it directly. Not needed now.
5. **Limits of this experiment:** 3 clips, 1 speaker, 1 mic, read speech, quiet room. It's a smoke test, not a benchmark. Each CER point here is about 3 characters.
