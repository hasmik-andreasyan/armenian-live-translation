# DECISIONS.md: Decision log

Each entry: **context → decision → reasons → status**. "Proposed" entries are waiting for review. Facts marked *(self-reported)* come from a model card or paper and haven't been measured by us yet.

---

## D-001 · Capture system audio with WASAPI loopback (no virtual cable)
- **Context:** The call app isn't fixed (Zoom, Meet, …). The user must still hear the call.
- **Decision:** Capture the Windows **output device** through WASAPI loopback, plus the mic as a normal input. Both devices can be picked from the CLI.
- **Reasons:** Works with any app that plays through that device. It's built into Windows, so nothing to install system-wide, and playback isn't affected.
- **Status:** Accepted in principle. Verified in Spike 1 (audio).

## D-002 · Headphones during the demo
- **Decision:** Assume headphones. No echo cancellation (out of scope per the brief).
- **Status:** Accepted.

## D-003 · `venv` + `requirements.txt`, pinned versions
- **Status:** Accepted.

## D-004 · Environment check before any install
- **Context:** The tool I use on your laptop runs in a **Linux VM** with your project folder mounted (it reports Python 3.10 / Linux). It cannot see your Windows Python or Git, so its output says nothing about your actual setup.
- **Decision:** You run the checks in **Windows PowerShell** and paste the output:
  ```powershell
  python --version
  py -0p
  where.exe python
  python -c "import platform, struct; print(platform.platform(), struct.calcsize('P')*8, 'bit')"
  git --version
  ```
  We need **64-bit** Python 3.12, since prebuilt wheels for CTranslate2/ONNX Runtime are 64-bit only, and a working `git`.
- **Result (2026-10-25):** Windows 10 64-bit, Python 3.12.3 64-bit at `C:\Users\Hasmik\AppData\Local\Programs\Python\Python312\python.exe`, Git 2.49.0. `py -3.12` works. **`python` points to the Microsoft Store alias.**
- **Consequence:** Never rely on bare `python`. Create the venv with `py -3.12 -m venv .venv`, then always use `.venv\Scripts\python` (or an activated venv). The README will say the same.
- **Status:** Done. The environment is fine.

## D-005 · ASR candidate verification (desk research, 2026-10-25)

| Candidate | Armenian support | License | Runs natively on Windows? | Size / compute | Verdict |
|---|---|---|---|---|---|
| **Whisper large-v3** via faster-whisper | Yes (`hy` is a built-in language). Zero-shot CER ≈ 14–16 % *(self-reported, BuzzASR card)* | MIT (model and faster-whisper) | Yes: `pip install faster-whisper` (CTranslate2, no PyTorch, no FFmpeg) | 1.55 B params. Int8 on CPU. ~3 GB download. | **Test first** (baseline + speed gate) |
| **Whisper large-v3-turbo** via faster-whisper | Same tokenizer and languages. Armenian quality **unknown** | MIT | Yes | ~0.8 B. Same 32-layer encoder, only 4 decoder layers | Test alongside large-v3 |
| **BuzzASR/armenian** (Whisper large-v3, fully fine-tuned) | Monolingual Armenian. CER 2.3 % combined, FLEURS WER 11.9 % *(self-reported; Common Voice partly in-domain)* | MIT | Only in Transformers format (3.09 GB F16). No CTranslate2 build, no `tokenizer.json`. **Extended vocabulary: 53,474 tokens vs 51,866 in large-v3**, so conversion to faster-whisper must be tested. | Same compute as large-v3 | Test **only if large-v3 is fast enough** |
| **MMS-1b-all** (Meta, CTC + language adapters) | Yes, `hye` adapter. Community ONNX spot-check: CER 0.03 on one FLEURS sentence (not a benchmark) | **CC-BY-NC-4.0** (non-commercial) | Yes, via `transformers` + PyTorch CPU, or a community ONNX export (int8 base ≈ 1 GB) | 1 B. **Cost scales with clip length** (no 30 s window) | Fallback / speed alternative |
| **Omnilingual ASR CTC 300M / 1B** (Meta) | **Confirmed:** `hye_Armn` (Eastern) and `hyw_Armn` (Western) are in the repo's language list, with **294 h of Armenian training data**. The 7B LLM model reaches CER 1.9 % on Armenian *(self-reported; `per_language_results_table_7B_llm_asr.csv`)*. **CTC-300M/1B Armenian CER is not published.** | Apache-2.0 | Official stack: **no** (fairseq2 has "no native support for Windows"). **Yes** via community `transformers` conversions (`aadel4/omniASR-CTC-300M-v2`, `-1B-v2`). The conversion script checks parity with the original (logits + transcripts). | 300M: 1.3 GiB fp32. 1B: 3.7 GiB. Single pass. Max 40 s input. | **Re-evaluated:** first candidate (see D-007) |
| Small community Whisper fine-tunes (tiny/small) | Self-reported 40–75 % WER on their own validation sets | Various | Yes | Small | Dropped: too inaccurate |

**Key technical fact behind the test order:** Whisper always pads the input to a **30-second window**, so the encoder costs about the same for a 3 s phrase as for a 30 s one. Turbo shortens only the decoder, and BuzzASR has exactly the large-v3 encoder. **If the large-v3 encoder is too slow on this CPU, the whole Whisper-large family is out for live use**, including the most accurate candidate. That's the cheapest question to answer first. CTC models (MMS) don't have this fixed cost.

- **Status:** Research done. Measurements pending (EXP-01).

## D-007 · Compute estimate per phrase on the i5-8250U *(back-of-envelope, to be measured)*

Method: count multiply-accumulates (MACs) from each architecture for one **6 s phrase**, and assume ~70 Whisper output tokens. Armenian is token-inefficient in Whisper's byte-level vocabulary. Then divide by an assumed **effective** throughput of 150–300 GMAC/s (4 cores, int8, AVX2, 15 W under sustained load). Greedy decoding is limited by memory bandwidth, so it's estimated separately at ~15 GB/s. Treat these as ±2×. They are for **ranking**, not promises.

| Model | Work per 6 s phrase | Est. ASR time | Est. RAM (int8 / fp32) | Download |
|---|---|---|---|---|
| Whisper large-v3 / BuzzASR | ~1,350 GMAC (encoder alone ~1,140, **fixed** because of the 30 s window) | **~8–13 s** | ~2 GB / — | 3.1 GB |
| Whisper large-v3-turbo | ~1,170 GMAC (same encoder) | **~4.5–8.5 s** | ~1.2 GB / — | 1.6 GB |
| Whisper medium | ~670 GMAC | ~4–6.5 s | ~1 GB / — | 1.5 GB |
| Whisper small | ~200 GMAC | ~1.3–2 s | ~0.5 GB / — | 0.5 GB (but Armenian accuracy is poor) |
| MMS-1b-all / omniASR-CTC-1B | ~320 GMAC (**scales with phrase length**) | ~1–2 s int8, ~3 s fp32 | ~1.2 GB / ~4 GB | 3.7–3.9 GB |
| **omniASR-CTC-300M-v2** | ~115 GMAC (scales with length) | **~0.4–0.8 s** int8, ~1.2 s fp32 | ~0.4 GB / ~1.3 GB | **1.3 GB** |

One external data point for scale: on 6 Apple M1 Max CPU cores (faster than this laptop), faster-whisper int8 ran large-v3 at about real time and turbo about 3.2× faster on a 5-minute file *(classmethod.jp)*.

**Reading of the table:**
- With an unmodified 30-second window, the **whole Whisper-large family**, including the most accurate model (BuzzASR), is predicted to need **more than the 5 s total budget for ASR alone**. Turbo is borderline even in the optimistic case.
- The CTC models fit the budget. The 300M model leaves room for translation, speaker ID and two speakers finishing at once.

**Trade-offs of CTC models to keep in mind:**
- They probably output no punctuation and no casing, which may hurt translation.
- English words probably come out as Armenian-script spellings, or wrong.
- The Armenian accuracy of the small CTC models isn't published.

A possible later rescue for Whisper is whisper.cpp's `audio_ctx` option, which shrinks the encoder window to the phrase length. Its quality impact is **unverified**, and we only look at it if the CTC accuracy isn't good enough.

## D-006 · EXP-01 (first version): Whisper CPU speed and accuracy probe *(superseded by D-008)*
- **Question:** On this laptop, how long does Whisper large-v3 / large-v3-turbo (int8, faster-whisper) take per short Armenian phrase, and how accurate is it?
- **Why first:** Cheapest install (one pip package, MIT, no PyTorch). It decides whether BuzzASR is worth converting, or whether we move to CTC models.
- **Inputs:** 3 clips you record yourself (~3 s, ~6 s, ~10 s), Eastern Armenian, one containing an English term, each with typed reference text. Different lengths test whether time grows with length, which feeds the segmentation decision.
- **Fixed settings:** `device=cpu`, `compute_type=int8`, `cpu_threads=4`, `language="hy"`, `vad_filter=False`, beam size 1 and 5, plugged in, Best performance, call app open.
- **Measured:** model load time, transcription time per clip (median of 3 warm runs), real-time factor, peak RAM, CER and WER (normalised).
- **Decision rule** (thresholds from the latency budget in PLAN.md):
  - large-v3 ≤ ~2 s on the 6 s clip → next: convert and test **BuzzASR**.
  - only turbo ≤ ~2 s → judge turbo's accuracy. Is it usable?
  - neither ≤ ~2 s → Whisper-large is out for live use. Next: **MMS-1b-all**.
- **Status:** Superseded. The estimate in D-007 suggests a 1.6–4.6 GB download just to confirm a likely negative result.

## D-008 · Revised first experiment *(proposed, waiting for agreement)*

**Step 0: CPU calibration (no model download, only `numpy`, ~15 MB).** Run a 60-second sustained matrix-multiply load to measure this laptop's real throughput when plugged in, in Best performance mode and warm. This replaces the assumed 150–300 GMAC/s in D-007 with a measured number. If the measurement shows turbo could fit in ≤ ~2.5 s, Whisper-turbo comes back into the experiment.

**EXP-01: omniASR-CTC-300M-v2 on your own recordings.**
- **Why this model first:**
  - It's the only candidate predicted to fit the budget comfortably.
  - It's the smallest download (1.3 GB).
  - It has an Apache-2.0 licence and confirmed Armenian training data.
  - It runs natively on Windows through `transformers`.
- **Install:** `torch` (CPU-only wheel), `transformers`, `soundfile`, `jiwer` (error rates), `psutil` (RAM). PyTorch is the largest install (~200 MB wheel, ~1 GB on disk).
- **Inputs:** 3 clips (~3 s, ~6 s, ~10 s), 16 kHz mono WAV, Eastern Armenian, one containing an English technical term, each with exact reference text.
- **Measured:** model load time; ASR time per clip (median of 3 warm runs) to check that time grows with length; peak RAM; CER and WER (normalised: no punctuation, lowercase); a look at the raw output for punctuation and how English words come out.
- **Decision rule:**
  - CER good enough and English readable after translation → keep 300M and move on to translation (M4).
  - Fast but inaccurate → EXP-02: omniASR-CTC-1B-v2 (3.7 GB, ~1–2 s estimated) or MMS-1b-all as a cross-check.
  - Both CTC models inaccurate → revisit Whisper with a shrunk encoder window (D-007).
- **Status:** Proposed.
