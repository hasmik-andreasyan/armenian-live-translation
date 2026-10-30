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

## CHK-02 · NLLB-200-distilled-600M repo + tokenizer (`benchmarks/check_nllb_repo.py`)

| Date | Revision | ctranslate2 / sacrebleu | CT2 CPU compute types | Weights | Checks | Raw file |
|---|---|---|---|---|---|---|
| 2026-10-26 | `f8d333a0` | 4.8.4 / 2.6.0 | float32, int16, **int8**, int8_float32 | `pytorch_model.bin` 2.46 GB (no safetensors) | **6/6 pass** | `results/chk02_nllb_repo_20261026_022236.json` |

- Language tokens: `hye_Armn` = 256072, `eng_Latn` = 256047. All 11 sentences tokenize without `<unk>`, both original and ASR-style (lowercase, no punctuation).
- **Input lengths are 6–32 tokens.** ASR-style versions are 1–3 tokens shorter. The longest is clip03 (32).
- The weights are a PyTorch pickle (`.bin`), not safetensors. They come from Meta's official repo, are hash-verified, and are loaded by torch's default safe mode (`weights_only`). To mention in the README.
- Sentences: `eval/mt_sentences.csv`, reviewed by the native speaker. t03 was corrected to «Դու ինձ լսո՞ւմ ես։».

**Download + conversion (`tools/prepare_nllb.py`, 2026-10-26):** all files size-verified, and `pytorch_model.bin`, `tokenizer.json` and `sentencepiece.bpe.model` SHA-256-verified. Converter ran with `low_cpu_mem_usage=True`.

| CT2 folder | Conversion time | Folder size | Process peak RAM |
|---|---|---|---|
| `models/nllb-600m-ct2-int8` | 28 s | **651 MB** | 3661 MB |
| `models/nllb-600m-ct2-float32` | 43 s | 2493 MB | 3661 MB (same process) |

## EXP-02 · Translation, NLLB-200-distilled-600M via CTranslate2 (`benchmarks/exp02_mt_eval.py`)

Conditions: **A** original Armenian · **B** ASR-style (lowercase, no punctuation, no recognition errors) · **C** real int8 ASR output from EXP-01 (3 clips). 4 threads, 1 warm-up + 3 runs, median latency. chrF against one reference (sacrebleu 2.6.0).

| Precision | Beam | Condition | n | corpus chrF | Median latency | Max latency | s / token | Raw file |
|---|---|---|---|---|---|---|---|---|
| int8 | 1 | A original | 11 | 75.2 | **0.46 s** | 0.85 s | 0.060 | `results/exp02_int8_20261026_023934.json` |
| int8 | 1 | B asr_style | 11 | 73.8 | **0.44 s** | 1.17 s | 0.061 | |
| int8 | 1 | C asr_output | 3 | 60.4 | 1.02 s | 1.16 s | 0.060 | |
| int8 | 4 | A original | 11 | **83.3** | 0.84 s | 1.67 s | 0.088 | |
| int8 | 4 | B asr_style | 11 | 69.7 | 0.78 s | 2.31 s | 0.100 | |
| int8 | 4 | C asr_output | 3 | 62.0 | 1.28 s | **4.92 s** | 0.076 | |

| float32 | 1 | A original | 11 | 81.9 | 1.57 s | 3.13 s | 0.192 | `results/exp02_float32_20261026_024844.json` |
| float32 | 1 | B asr_style | 11 | 71.3 | 1.60 s | 3.87 s | 0.194 | |
| float32 | 1 | C asr_output | 3 | 66.7 | 2.54 s | 4.29 s | 0.169 | |
| float32 | 4 | A original | 11 | 81.2 | 2.05 s | 4.63 s | 0.261 | |
| float32 | 4 | B asr_style | 11 | 69.7 | 1.89 s | 4.86 s | 0.257 | |
| float32 | 4 | C asr_output | 3 | 61.4 | 3.51 s | 5.93 s | 0.220 | |

**Memory:** int8 RSS 1189 MB after load (peak 1302), **776 MB at the end** (steady state). float32: 588 MB right after load (the model is mapped in lazily), **2607 MB at the end**, peak 2872 MB. All outputs are deterministic in both precisions.

**float32 vs int8:**
- **float32 is ~3.2× slower per token** (0.19 vs 0.06 s/token, as estimated in D-016: 0.18). Beam 1 has a 1.6 s median and up to 3.9 s, so it's **over the translation budget**. float32 is **out** for live use.
- **Quality:** 31/50 outputs are identical, and most differences are stylistic. float32 is better in two meaningful cases: t02-B "I'm fine. Thank you." (int8: "Thank you very much.") and clip02-C "friends" (int8: "classmates"). It's worse in one: t06-B "I'm tired **of it** today". chrF is mixed (beam 1: A 81.9 vs 75.2, B 71.3 vs 73.8, C 66.7 vs 60.4). The human ratings decide.
- **Memory:** int8 uses ~3.4× less at steady state (0.8 vs 2.6 GB).

**int8 findings:**
1. **Latency: beam 1 fits the budget.** Median ~0.45 s, max 1.17 s for the longest sentence (23 output tokens). That's ~0.06 s/token, close to the D-016 estimate of 0.05. **Beam 4 doesn't fit:** clip03 took 2.3 s (B) and 4.9 s (C, 30 tokens, consistent over 3 runs). Its cost grows faster than linearly with length.
2. **Missing punctuation (A → B) mostly costs little, with two important failures:**
   - **t03, a question that became a statement:** `դու ինձ լսում ես` → "You hear me." instead of "Can you hear me?". In Armenian a yes/no question is often marked **only** by `՞`, which the ASR never outputs. **This affects every spoken yes/no question. A README limitation, and a candidate for later improvement.**
   - **t02, half the meaning lost:** `լավ եմ շնորհակալություն` → "Thank you very much." ("I'm fine" disappeared without the comma).
   - Minor: t06 "so" → "and"; t05 (beam 4) adds "p.m.".
3. **ASR errors (B → C) can change the meaning:**
   - **clip02:** one dropped letter (`նկերների`) turned "friends" into **"classmates"**. Fluent, but wrong.
   - **clip03:** three small spelling errors made the translation lose most of its meaning.
   - "Python" is recovered correctly, even from `փայսոն`.
4. **Beam 4 vs beam 1:** beam 4 is better on clean text (A: 83 vs 75 chrF), not better on realistic input (B, C), and 2–4× slower. chrF with one reference over 11 sentences is noisy, so human ratings (Step 6) decide.

### EXP-02 human ratings (`benchmarks/exp02_rate.py`, `results/exp02_ratings.json`)

Blind rating by the native speaker: 46 distinct translations, shuffled, configuration hidden. Outputs differing only in casing or final punctuation were merged. Scale: 0 = wrong/misleading, 1 = understandable, 2 = good, judged against what the speaker meant.

| Configuration | A original: mean · ≥1 · =2 | B asr_style: mean · ≥1 · =2 | C asr_output: mean · ≥1 · =2 | Median latency (B) |
|---|---|---|---|---|
| **int8 / beam 1** | 1.91 · 11/11 · 10/11 | **1.45 · 10/11** · 6/11 | 1.00 · 2/3 · 1/3 | **0.44 s** |
| int8 / beam 4 | 1.91 · 11/11 · 10/11 | 1.55 · 10/11 · 7/11 | 1.00 · 3/3 · 0/3 | 0.78 s (max 4.9 s on C) |
| float32 / beam 1 | 1.91 · 11/11 · 10/11 | 1.55 · 11/11 · 6/11 | 1.67 · 3/3 · 2/3 | 1.60 s |
| float32 / beam 4 | 1.91 · 11/11 · 10/11 | 1.55 · 10/11 · 7/11 | 1.67 · 3/3 · 2/3 | 1.89 s |

**Findings:**
1. **On clean Armenian (A), all configurations are equal** (1.91). Precision and beam size don't matter there.
2. **Missing punctuation (B) costs ~0.4 points.** The only rating 0 is **t02-B "Thank you very much."** ("I'm fine" lost without the comma; 3 of 4 configs). **t03-B "You hear me."** was rated 1 (understandable, but the question is lost). It stays a documented limitation, because it affects every spoken yes/no question.
3. **ASR errors (C) cost the most.** int8/beam 1 got the other 0 (clip03-C). float32 was more robust on C (1.67 vs 1.00), but n = 3 and it's too slow.
4. **Beam 4 vs beam 1 on B: 1.55 vs 1.45, within rater noise.** Near-identical outputs sometimes differed by 1 point (e.g. "meet with my classmates" = 2, "meet some of my classmates" = 1). Beam 4 costs 2–4× the latency and up to 4.9 s.
5. **Decision rule (D-017):** int8/beam 1 has 10/11 understandable on B (≥ 9) at a 0.44 s median latency (≤ ~1 s), so it **passes**.

## Spike 1 · Simultaneous mic + system-audio capture (`tools/capture_test.py`)

2026-10-26, 30 s. Mic = [1] Jabra headset (MME, 44.1 kHz, 2 ch). Loopback = [16] Jabra earphone [Loopback] (WASAPI, 48 kHz, 2 ch). Both resampled to 16 kHz mono (soxr). Raw file: `results/capture_test_20261026_031317.json`.

| Source | Captured | Completeness | Max gap | Overflow | Peak | RMS | Sound in |
|---|---|---|---|---|---|---|---|
| mic | 30.0 s | 100 % | 0.06 s | no | 0.21 | −37.8 dBFS | 21 % |
| loopback | 30.1 s | 100 % | 0.06 s | no | 0.72 | −25.0 dBFS | 61 % |

- **Playback unaffected.** Both WAVs are clear (user listened), with no crackle and correct speed/pitch, so the resampling is right.
- **No call audio in the mic:** the mic stays at −64 dBFS while only the video plays. The headset works as intended (D-002).
- **This Jabra loopback sends silence (≈ −93 dBFS) during pauses** instead of stopping, so there's no gap. Gap handling stays in the segmenter for other devices/apps.

**Phrase segmenter (`app/vad.py`) on recorded audio:**
- clip01 → 1 segment [0.9–3.3 s].
- clip02 → 1 segment [0.4–5.6 s].
- clip03 → **force-cut at 7 s** + rest [7.1–9.0 s].
- Mic counting → short pieces at the pauses.
- Video audio → 6 sentence-like segments.

## LIVE-01 · First live session (`python -m app.main --log`)

2026-10-26, ~3 min: user speaking (Me) + an Armenian interview video in the headset (Call). Raw log: `results/session_20261026_032445.jsonl`.

| Source | Lines | Latency median | p95 | max | over 5 s | ASR median | MT median | max queue wait | forced cuts |
|---|---|---|---|---|---|---|---|---|---|
| Me (mic) | 14 | 2.36 s | 4.43 s | 4.43 s | 0 | 0.89 s | 0.61 s | 1.80 s | 1 |
| Call (loopback) | 31 | 3.03 s | 4.01 s | 4.17 s | 0 | 1.87 s | 0.94 s | 2.09 s | **18** |
| **All** | **45** | **3.00 s** | **4.01 s** | **4.43 s** | **0** | | | | 19 |

**Findings:**
1. **Latency requirement met:** 0 of 45 lines over 5 s, max 4.4 s. The queue wait (up to 2.1 s) is the largest variable, when both sides finish phrases close together.
2. **The ASR drifted into other scripts on unclear audio:** `բաrեվ իnչ պեseս`, `شاط وراخم`, `普勒`, `ساخرخوسليچه`, `makl … exտենsioն`. The translator then **invented sentences** from these, e.g. "The following is a list of the most common causes of death in the United States." This didn't happen on the clean EXP-01 clips. → **Fix: D-023, Armenian-only decoding.**
3. **18 of 31 Call segments were force-cut at exactly 7.0 s,** often mid-word (`…տարածաշրջանի աս` | `աշխարհի մասին`). The interview had few 0.6 s pauses. → **Fix: D-023, cut at the quietest point.**
4. **Clear speech worked well:**
   - "ինչ կատարվեց վերջին շրջանում" → "What has happened in recent times?"
   - "հենց նոր հասկացա" → "I just realized"
   - "We can't say that something is done well or something is done because" (Call)
5. **A few noise segments** (e.g. `o and o`). Armenian-only decoding plus the < 2 character filter should remove most of them.

## LIVE-02 · After D-023 (Armenian-only decoding + quiet-point cuts)

**Regression check first:** EXP-01 int8 re-run with Armenian-only decoding (`results/exp01_int8_20261026_033429.json`). **Identical transcripts on all 3 clips**, CER 6.3 % (unchanged), latency unchanged. The restriction doesn't hurt clean speech.

2026-10-26, ~1.5 min, same setup as LIVE-01. Raw log: `results/session_20261026_033622.jsonl`. It ended with an accidental double Ctrl+C, so the summary line is missing but the log is complete; fixed in D-024.

| Source | Lines | Latency median | p95 | max | over 5 s | ASR median | MT median | max queue wait | forced cuts |
|---|---|---|---|---|---|---|---|---|---|
| Me (mic) | 7 | 2.39 s | 6.96 s | **6.96 s** | **1** | 1.06 s | 0.47 s | **3.83 s** | 0 |
| Call (loopback) | 15 | 3.85 s | 4.92 s | 4.92 s | 0 | 1.81 s | 1.12 s | 1.39 s | 13 |
| **All** | **22** | **3.75 s** | 4.92 s | 6.96 s | **1** | | | | 13 |

**Findings:**
1. **Non-Armenian characters: 0 lines** (LIVE-01: ≥ 5). No more hallucinated sentences like the "causes of death" one.
2. **Me lines are clearly better:**
   - "The weather is good today."
   - "I was glad to meet you."
   - "We don't know what the picture looks like."
   - "Thank you for the *wedding* interview": ASR heard `հարսազրույցի` for `հարցազրույցի`.
3. **Forced cuts now fall between words** (at 5.7–6.8 s), e.g. `…պարզեցված իրավիճակի կամ` | `պատկերի հիման վրա`.
4. **One line over 5 s (6.96 s):** the user spoke at t = 1.6 s, *while* the video was talking. The Me segment waited 3.83 s behind a 6.7 s Call segment (ASR 1.8 + MT 1.1). **This is risk K2 (overlapping speech) in its worst form.** A 6 s segment takes ~2.9 s of processing, so two people talking continuously at the same time saturate the single worker. In normal turn-taking, overlap is brief. **Documented limitation.** If time allows: speed up MT (English-only output vocabulary), which shortens every queue wait.
5. Call-side quality on fast, informal interview speech is mixed: often understandable, sometimes garbled. ASR errors are the main cause (as found in EXP-02).

## CAL-01 · Speaker embeddings on a real 2-speaker interview (`tools/speaker_calibrate.py`, first version)

2026-10-26. 150 s loopback capture of an Armenian interview video (`results/capture_test_20261026_040111.json`) → 25 phrases. WeSpeaker ResNet34-LM via sherpa-onnx, **138 ms median per phrase**. Raw file: `results/cal01_speakers_20261026_040122.json`.

**Result: every phrase was assigned to Speaker 1 at every threshold (0.30–0.70)**, although the user hears a definite speaker change at ~124–131 s (phrase 22: similarity 0.62 to the previous phrase).

**Investigation (on the saved similarity matrix):**
1. **The grouping code worked as designed.** Each phrase's similarity to the running Speaker 1 centroid was ≥ 0.74, above the highest threshold tried. Phrase 22: 0.62 to the previous phrase but **0.82 to the centroid**. An average of many phrases is a "cleaner" print, and it's similar to everything from the same channel.
2. **Raw embeddings are dominated by one shared direction.** All 300 pairs fall in cosine 0.46–0.94 (median 0.77). The top eigenvalue of the similarity matrix is 19.1 of 25: the shared codec/room/recording chain makes different people look alike.
3. **Subtracting the mean embedding (centring) reveals the speakers.** Centred cosines spread over −0.65…+0.54, and a 2-group structure appears (eigenvalues 7.4, 2.6).
   - Phrase 22 vs phrases 18–21: **−0.32 to −0.40**. Phrase 22 vs 23: +0.59.
   - The offline 2-way split puts phrases 18–21 in one group and 22–25 in the other, i.e. **the switch is at 124.7 s, as heard.**
4. **Online centring with only the session's running mean over-splits badly** (up to 17 "speakers"): the mean is unstable while there are only a few phrases. **With a stable prior mean** (blend weight 30), the online labels come close to the offline split. That simulation used this recording's own mean, so it's optimistic.
5. **There's no ground truth beyond "a change at ~124–131 s"**, and 7 s phrases can contain two speakers. → **CAL-02: user labels every phrase; prior estimated only from other recordings; settings scored against the labels.**

## CAL-02 · Speaker-tracker settings scored against human labels (`tools/speaker_calibrate.py`)

2026-10-26. Same 150 s interview recording as CAL-01 (25 phrases). **Labels by the user** (`tools/label_phrases.py` → `eval/speakers/labels.json`): 10 × speaker 1, 4 × speaker 2 (phrases 18–21, 100.2–124.7 s), **11 × mixed** (both people in one phrase; excluded from scoring). The change heard at ~124–131 s is **speaker 2 → speaker 1**, with phrase 22 mixed.
**Prior mean only from other recordings** (first capture + 3 clips = 10 phrases), so the evaluation is honest. Embedding: **337 ms median per phrase** (CAL-01: 138 ms). Raw file: `results/cal02_speakers_20261026_161610.json`.

| Setting | Speakers found | Purity | Coverage | F | Labels (phrases 1–25) |
|---|---|---|---|---|---|
| **centred, prior w = 30, threshold 0.10** | **2** | **1.00** | **1.00** | **1.00** | `1111111111111111122221111` |
| centred, w = 30, 0.20 | 3 | 1.00 | 0.93 | 0.96 | `1111111112111311122221111` |
| centred, w = 10, 0.10 | 4 | 1.00 | 0.93 | 0.96 | `1111111213211411122221111` |
| centred, w = 10, 0.00 | 2 | 0.93 | 0.93 | 0.93 | `1111111212211211122221111` |
| centred, w = 30, 0.00 | 1 | 0.71 | 1.00 | 0.83 | all merged |
| raw, 0.60–0.70 | 1 | 0.71 | 1.00 | 0.83 | all merged (the CAL-01 problem) |
| raw, 0.85 (best raw) | 8 | 1.00 | 0.79 | 0.88 | over-split |
| raw, 0.90 | 8 | 1.00 | 0.43 | 0.60 | over-split |

**Findings:**
1. **Centring fixes the CAL-01 failure.** No raw threshold finds 2 speakers. Centred, w = 30, th 0.10 is perfect on all 14 labelled phrases: speaker 2's block at 100–124.7 s is found, and the session returns to speaker 1 afterwards.
2. **The working range is narrow:** th 0.00 merges, 0.10 is perfect, 0.20 adds a spurious third speaker. The evidence is thin (14 scorable phrases, only 4 of speaker 2, prior from 10 phrases). → **The threshold is a CLI option**, re-checked in the real call.
3. **44 % of phrases are mixed.** In a quick back-and-forth, a 7 s phrase often spans a turn, and its embedding is a blend of two voices. This limits accuracy more than the threshold does. (Possible improvement: shorter windows for speaker embedding only.)
4. **Embedding cost is 0.14–0.34 s per call-side phrase,** added to that line's latency.
5. The app's prior (`models/speaker/prior_mean.npy`) = mean over all 35 calibration phrases (target included).

## LIVE-03 · First live session with speaker ID (2026-10-26 16:36)

A **different** 2-person video from the CAL-02 interview, the user speaking over it, then speaking alone. Raw log: `results/session_20261026_163637.jsonl`. (The earlier attempt at 16:24 processed zero phrases and left no log; the cause is unknown → D-028.)

**Summary:** 28 lines (6 Me, 22 call side) · latency median 4.5 s, p95 15.7 s, **max 17.5 s, 7 over 5 s** · `Speaker 1: 22`.

**Findings from the log (before any change):**
1. **Speaker ID: all 22 call phrases → Speaker 1.** Centred similarity to the Speaker 1 centroid was 0.36–0.79, every time ≥ 0.10. Hypothesis: **the prior (from the CAL-02 interview + headset clips) doesn't fit this video's channel**, so centring doesn't remove this channel's shared component (w = 30 still weighs the prior at ~58 % after 22 phrases). Also, 21 of 22 call phrases were cut at the 7 s limit (5.7–7.0 s), so turns are likely mixed inside phrases. **No ground truth for this video yet.**
2. **Mic during the video: only one Me line** (67.9–69.7 s, garbled `դո միպն րաշմ ս`). The log **can't show why**: phrases with < 2 ASR characters were dropped without logging, and there were no levels and no overflow statistics.
3. **Mic alone afterwards («Ողջույն, բարև»): garbage** (`իլսս`, `վղ`, `ղ յ`, `բրւ`, `պր`, phrases of 1.1–3.0 s). In LIVE-02 the same mic gave good results ("The weather is good today."), so the audio reaching the model (level / gain / lost samples) is the main suspect, not the model. MT invents text from the garbage ("The following is a list of" ×3).
4. **MT repetition loop:** at 87–93 s, MT took **14.4 s** ("I'll tell you what, I'll tell you what, …" up to the 256-token default limit). The queue backed up, causing **5 of the 7 lines over 5 s** (8.9–17.5 s). Without it, latency was 2.9–5.5 s.
5. **Three models in one process:** speaker embedding 0.13–0.29 s. ASR ~2.2 s per 6–7 s phrase vs 1.8 s in LIVE-02 (the libraries' thread pools may compete briefly). Not the main problem; to be watched.

**Changes after LIVE-03 (D-029):** MT loop guard + diagnostics (`--record`, every phrase logged with reason/confidence/levels, capture overflow statistics). No model or threshold changes.

## LIVE-03b · Scripted, recorded session (`--record`, 2026-10-26 16:47)

Script: 0–10 s silence · 10–44 s the user alone (sentences and single words) · ~55–145 s video (the user silent as planned) · the user speaking over the video at ~120–137 s. Raw: `results/session_20261026_164715.jsonl` + `_mic.wav` + `_loopback.wav`.

**Summary:** 22 lines + 2 skipped · latency median 3.6 s, **max 4.8 s, 0 over 5 s** (the MT loop guard worked) · capture: **no overflow on either source**, longest gaps 0.06 / 0.08 s · speakers: `Speaker 1: 14`.

**Microphone (recorded audio + offline replay, `results/replay_mic_20261026_170223.json`):**
- **Capture is clean:** background −67 dBFS, speech peaks −9…−12 dBFS (~55 dB SNR). Silence at 44–118 s = the user was silent (as planned), not a capture problem.
- **The VAD found every utterance, with correct boundaries** (checked at 100 ms resolution).
- **ASR vs what the user said:**

| t | said | ASR (live replay) | confidence | ok |
|---|---|---|---|---|
| 12.6 | «Բարև» | (empty) | 0.00 | ✗ |
| 19.4 | «Այսօր եղանակը շատ լավ է» | correct | 0.97 | ✓ |
| 25.5 | «Ողջույն» | `վղ` | 0.59 | ✗ |
| 30.7 | «Ինչպե՞ս ես» | `ինչպես ես` | 0.98 | ✓ |
| 34.7 | «Բարև» | `ր` | 0.72 | ✗ |
| 40.3 | «Բարև, հուսամ լավ օր կունենանք» | correct (one missing space) | 0.95 | ✓ |
| 119.6 | «Այսօր եղանակը շատ լավ է» (over the video) | correct | 0.98 | ✓ |
| 125.6 | «Ողջույն, բարև» (over the video) | `ողջույն բարեւ` | 0.89 | ✓ |
| 136.2 | «Շատ բարի» (over the video) | `շտ բր` | 0.57 | ✗ |

- **Sentences and 2-word phrases are recognised; isolated words of 0.6–1.0 s are not.** Confidence separates the two cleanly (≥ 0.89 vs ≤ 0.72). Padding with 0.5 s of silence rescued none and hurt one → **D-030**.
- **Recognising the mic while call audio plays works** (119.6 / 125.6 s).

**Call side (labels: `eval/speakers/labels_session2.json`):** `m m 1 m m m 2 2 2 2 2 m m m`. **8 of 14 phrases are mixed.** Every call phrase was cut at 7 s (continuous speech). Live: all Speaker 1; the guest block 93.8–126 s had similarity 0.56–0.72 to a centroid built from mixed phrases → **D-031**.

## SPK-EVAL · Phrase-level vs window-level speaker embeddings (`tools/speaker_eval.py`, 2026-10-26 23:13)

Two labelled recordings: interview (25 phrases, 14 scorable) and session 2 (14 phrases, 6 scorable). The prior for each recording = the *other* recording + the first capture + the EXP-01 clips (never itself). Methods: one embedding per phrase, or 1.5 / 2 / 3 s windows with a majority vote. Prior weight 10/30 × threshold 0.0–0.4. Raw file: `results/spk_eval_20261026_231325.json`.

Truth: interview `1.1..11....111...2222.111` · session 2 `..1...22222...` (`.` = mixed / unknown).

| Method | w | thr | mean F | Interview: found, F, labels | Session 2: found, F, labels |
|---|---|---|---|---|---|
| **phrase (current live)** | 30 | 0.10 | 0.87 | 1, 0.83, `1111111111111111111111111` | 1, 0.91, `11111111111111` |
| **phrase** | **30** | **0.40** | **0.98** | 3, 0.96, `1111111112111311122221111` | **2, 1.00**, `11122222222211` |
| phrase | 10 | 0.30 | 0.98 | 4, 0.96 | 3, 1.00 |
| phrase | 30 | 0.30 | 0.95 | 2, 1.00 | 1, 0.91 |
| 2 s windows | 10 | 0.00 | 0.96 | 3, 0.92 | 2, 1.00 |
| 3 s windows | 10 | 0.10 | 0.96 | 3, 0.92 | 2, 1.00 |
| 1.5 s windows | 10 | 0.40 | 0.92 | 6, 0.83 | 5, 1.00 |

**Findings:**
1. **Window-level embeddings don't beat phrase-level** (best 0.96 vs 0.98), and they'd add 0.2–0.4 s per call line. The D-031 hypothesis is rejected.
2. **The live failure is the threshold, given the prior.** With a prior from more varied audio, th 0.10 merges everyone on both recordings. th 0.40 separates them: session 2 perfect, interview with one spurious extra speaker.
3. **The best threshold moves with the prior** (CAL-02's 0.10 → 0.40 here). So the deployed prior is rebuilt from all calibration audio, and the setting must be confirmed on **new** audio.
4. Mixed phrases (19 of 39) remain a structural limit: they get one label, whatever the method.

## LIVE-04a · Independent check of D-032 (threshold 0.40) on a NEW 2-person video (2026-10-26 23:21)

`--record`, ~2.3 min, user silent. Prior rebuilt from 49 phrases (`models/speaker/PRIOR.txt`). Raw: `results/session_20261026_232140.jsonl` + WAVs. Labels: `eval/speakers/labels_session3.json` (24 phrases: 16 × guest `2`, 2 × interviewer `1`, 6 × mixed).

- **Latency OK:** 23 lines + 1 skipped, max 5.2 s (one line), no overflow. Call-side ASR confidence 0.81–0.97.
- **Speaker ID over-split: 7 speakers for 2 people.** The guest's 16 phrases went to S5 ×8, S1 ×2, S4 ×2, S3, S6, S7. The interviewer's 2 → S1. **Purity ≈ 0.83, coverage ≈ 0.56, F ≈ 0.67.** The guest's phrases score only **0.41–0.64** to "his" S5 centroid, so several fell under 0.40 and each opened a new speaker. **S3, S6, S7 are singletons.**
- **Conclusion: one fixed threshold doesn't transfer between recordings.** 0.10 merged everyone on session 2; 0.40 over-splits session 3. → D-033 (confirmation rule) + a 3-recording evaluation.

## SPK-EVAL2 · Confirmation rule × threshold × prior weight on 3 labelled recordings (2026-10-26 23:42)

Raw file: `results/spk_eval_20261026_234241.json`. Phrase-level embeddings; priors from the other recordings (+ capture + clips). Truth: interview `1.1..11....111...2222.111` · session 2 `..1...22222...` · session 3 `..2..22222.2222211.2.22.`.

**Balanced accuracy** (best 1:1 mapping, mean over real speakers; merge-all = 0.5). The F score was rejected as the metric because it rewards merging (session 3: merge-all scores F 0.93).

| Confirm | w | thr | mean | worst | interview | session 2 | session 3 | speakers found (true 2/2/2) |
|---|---|---|---|---|---|---|---|---|
| **on** | **10** | **0.3** | **0.90** | **0.79** | 0.90 | 1.00 | 0.79 | 3 / 2 / 3 |
| on | 30 | 0.5 | 0.90 | 0.75 | 0.95 | 1.00 | 0.75 | 3 / 2 / 2 |
| on | 10 | 0.6 | 0.90 | 0.72 | 0.72 | 1.00 | 0.96 | 3 / 2 / 2 |
| off | 10 | 0.2 | 0.87 | 0.71 | 0.90 | 1.00 | 0.71 | 5 / 3 / 6 |
| off (previous live) | 30 | 0.4 | 0.86 | 0.68 | 0.90 | 1.00 | 0.68 | 5 / 2 / 8 |
| off (D-027) | 30 | 0.1 | | 0.50 | 1.00 | 0.50 | 0.50 | 2 / 1 / 2 |

**Findings:**
1. **The confirmation rule removes most over-splitting** (2–3 speakers instead of 5–8) and gives the best worst-case accuracy of all settings.
2. **No setting is perfect on all three.** The remaining errors sit mostly in mixed phrases and right after speaker changes (confirmation delay).
3. All three recordings were used for the choice, so this is not an independent estimate. The real call is.

## CLONE-01 · Fresh-clone install + live run (2026-10-29 18:42)
- **Setup:** `git clone` of the local repo (commit `b5fd9f7`) into a new folder, then the README exactly: venv, `pip install -r requirements.txt`, 21 unit tests (OK). The models were **copied** from the working folder instead of re-downloaded, without the float32 MT model (as `prepare_nllb.py` now builds it, D-037). `git status` afterwards: clean except the new session logs.
- **Run:** `python -m app.main --log`, 1 min of a 1-person Armenian video + a few of the user's sentences. Plugged in, Best performance. Raw file: `results/session_20261029_184216.jsonl`.
- **Result:** 19 lines; **latency median 4.0 s, p95 5.5 s, max 5.5 s; 3 / 19 over 5 s**; no lost audio on either side.
  - Mic (5 lines): all shown as `Me`, latency median 2.0 s, max 2.5 s.
  - Call side (14 lines): one person, **one label (Speaker 1) for all 13 phrases** counted by the tracker; latency median 4.3 s.
  - Same speed as the original folder (ASR on phrases ≥ 6 s: median 2.35 s; MT median 1.1 s). The clone behaves exactly like the working folder.
- **The 3 lines over 5 s** (over by 0.19, 0.52 and 0.36 s) were all call-side phrases, 3.8–5.9 s long:
  - waiting for the phrase end 0.6–1.4 s (the video speaker trailing off before a pause);
  - ASR 1.7–3.0 s; MT 1.0–1.6 s;
  - one waited 1.2 s behind a mic phrase (both sides spoke).
  - **Lowering the 7 s maximum phrase length would not have helped** (all three were under 6 s). No single setting targets this; the fixes are the bigger items in README §6 (faster MT output layer, two workers).
- **Environment matters:** a run started right after copying 4 GB of models and installing the venv was ~40 % slower in both models (9 / 17 over 5 s). A later run of the same clone in the same conditions gave the result above. So: don't demo right after an install; do one warm-up run.
- **Decision:** code frozen; result documented as a known limitation (README §5).

## LIVE-04 · Real Zoom call, the final end-to-end test (2026-10-30, evening)
- **Setup:** Zoom call between the user (Jabra headset, laptop) and **one** other Armenian speaker, **who was on her phone**. Laptop plugged in, Best performance, warm-up run first. Committed code `2849542` (no changes since CLONE-01). Natural conversation with turn-taking.
- **Evidence:** the summary the app prints at the end, plus the user's observations. **The run was without `--log`**, so there's no per-line file. The breakdown below is limited to what the summary contains.
- **Result (app summary):**
  - **43 lines; latency median 3.6 s, p95 4.9 s, max 5.5 s; 2 / 43 over 5 s.** The best result of any live session with call audio.
  - **No lost audio** on either side (longest gap 0.08 s, no overflow, ~5 min of both streams).
  - Call side: **Speaker 1: 14 phrases, Speaker 2: 2 phrases**, for **one real person**, so 1 extra speaker on 2 of 16 phrases (≈ 88 % of her phrases under one label). The remaining ~27 lines were the user's mic, all labelled `Me` by design.
- **User's observations:**
  - **Long sentences worked well,** on both sides.
  - **Short single words** (`բարև`, `ողջույն`, `հա`) were **sometimes recognised, sometimes not.** That's the known limit from LIVE-03b and D-030: isolated words under ~1 s have low confidence and are shown as *unclear* or dropped.
  - Recognition was **better on the Jabra headset (the user) than on the other side's phone audio** (lower quality, compressed by the call).
- **Not tested here:** 2 people on the call side (only 1 was available). That case is covered only by the recorded videos (SPK-EVAL2, CLONE-01).
- **Decision:** no further changes. The results are documented (README §4–5, TESTS.md); the code stays frozen for submission.

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
