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
- **Status:** Accepted 2026-10-26. Order: Step 0 (CPU calibration) first, then the compatibility check (D-009), then EXP-01.

## D-009 · How we verify the converted model works on Windows + Python 3.12 *before* downloading weights
- **Limitation found:** In this session, my workspace **and** the shell on your laptop are blocked from PyPI and Hugging Face by network policy. I couldn't check the package files or the model repo from my side. **The check must run in your Windows PowerShell.**
- **Already verified, from the converter's source code** (`ahmedadelattia/omnilingual_to_hf`: I read the tokenizer, config and parity-check parts):
  - Output is a **standard** `transformers` `Wav2Vec2ForCTC` + `Wav2Vec2CTCTokenizer`. No custom code and no `trust_remote_code`.
  - The converter used `transformers>=5.3.0`.
  - CTC blank = `<s>` (id 0). Words are separated by the SentencePiece marker `▁`. Audio: 16 kHz with per-utterance mean/variance normalisation (`do_normalize=True`).
  - The parity check compares logits with the original fairseq2 model (`atol=1e-4`), plus greedy token ids and transcripts. **But** its transcript decoding is done manually: join the pieces, then replace `▁` with a space. It does *not* go through the HF tokenizer's `decode`. **Decision:** our ASR module uses the same manual greedy decode, so we decode exactly the way the parity check did.
  - **Unknown:** whether the parity check was actually run for the uploaded `aadel4/*` checkpoints. The model card states this, and we'll read it in Step 2.
- **Step 2 plan (cheap, no 1.3 GB download):**
  1. `pip install --dry-run` of the ASR packages, to confirm cp312/win_amd64 wheels exist before installing anything.
  2. Install them. Download only `config.json` + tokenizer files (a few KB), and list the repo's files and sizes.
  3. **Build the model architecture from `config.json` with random weights** and time a forward pass on 3 / 6 / 10 s of noise. This proves `transformers` + `torch` can run this exact architecture on your laptop, and gives real (non-estimated) speed and RAM numbers, all without the weights.
  4. Only if that passes: download the 1.3 GB weights and run EXP-01 on your recordings.
- **Dry run (2026-10-26, Windows, Python 3.12.3):** all packages resolved without errors: torch 2.14.1, transformers 5.20.2, huggingface_hub 2.3.0, tokenizers 0.23.3, safetensors 0.8.0, soundfile 0.14.0, jiwer 4.0.0, psutil 7.2.2 (numpy 2.5.4 was already installed). **No `nvidia-*` packages, which confirms the CPU-only torch build.** transformers 5.20 ≥ 5.3, as the converter requires.
- **Open risk:** torch 2.14 and huggingface_hub 2.x are newer than anything I can check documentation for here. Two things could have changed: `torch.ao.quantization.quantize_dynamic` (int8) and the hub download functions. CHK-01 reports either failure explicitly.
- **Status:** Accepted. EXP-00 is done, and this check is implemented as CHK-01 (`benchmarks/check_ctc_compat.py`).

## D-010 · Inference uses 4 threads
- **Evidence:** EXP-00 (EXPERIMENTS.md). 4 threads gave a higher sustained throughput (145 vs 128 GFLOP/s) and far more **stable** performance (min 115 vs 33 GFLOP/s) than the default 8.
- **Decision:** Every model call sets `torch.set_num_threads(4)` explicitly. We'll re-check this once two models (ASR + translation) share the CPU.
- **Status:** Accepted.

## D-011 · Whisper family deprioritised for live ASR
- **Evidence:** EXP-00 predictions with measured throughput. Even Whisper small needs ~3–4.5 s per phrase in float32, and large-v3/turbo need 17–28 s.
- **Decision:** Proceed with omniASR-CTC-300M-v2. CTC-1B stays a candidate only if int8 brings it near the budget. Whisper comes back only if CTC accuracy is unusable (and then with a shrunk encoder window).
- **Status:** Accepted. Confirmed by CHK-01: real int8 latency is 1.70 s for a 6 s phrase.

## D-012 · CHK-01 passed: decoding and scoring rules
- **Correction to D-009:** the uploaded tokenizer uses a **plain space** as the word separator, and its Armenian vocabulary is single characters. Our decoder (`app/asr.py`) does what the parity check did: argmax per frame → merge repeats → drop blank (`<s>`, id 0), `<pad>` and `</s>` → join. `<unk>` is counted, not shown.
- **Scoring normalisation** (`app/text_norm.py`, unit-tested in `tests/`): NFC, lowercase, `և` = `եւ`, standalone `եվ` = `եւ`. In-word marks `՞ ՜ ՛` are deleted (so "ինչպե՞ս" → "ինչպես"), and other punctuation becomes a space. **CER is the primary metric.** Armenian words are long and heavily inflected, so one wrong letter makes a whole word wrong, which inflates WER. Both are reported, plus raw (unnormalised) CER.
- **Own CER/WER code** (`app/metrics.py`) instead of jiwer: about 30 lines, dependency-free and unit-tested, and it doesn't depend on jiwer 4.0's API, which I can't check here.
- **Status:** Accepted.

## D-013 · EXP-01 design *(proposed)*
- **Model:** omniASR-CTC-300M-v2 at pinned revision `f2b3c39a62c061c27623c3f2d803294fbb954324`. Downloaded by `tools/download_model.py`, which verifies size and SHA-256 against Hugging Face's published hashes.
- **Data:** 3 clips by one speaker (`eval/manifest.csv`): ~3 s, ~6 s, and ~10 s with the English term "Python". 16 kHz mono 16-bit WAV recorded with `tools/record_clip.py`, which reads the sentence from the manifest. **Use the headset mic you'll use in the demo.** Audio stays local (gitignored). Only its SHA-256 is recorded.
- **Runs:** fp32 and int8, **each in a separate process** (clean RAM numbers), 4 threads, 1 warm-up + 3 timed runs per clip.
- **Provisional decision rule:** these thresholds are judgment calls, written down *before* seeing results:
  - corpus CER (normalised) ≤ 15 % and int8 within +2 points of fp32 → **adopt 300M int8**, move on to translation (M4)
  - CER 15–30 % → inspect the error types (systematic letter confusions? word boundaries? the English term?), then try CTC-1B on the same clips
  - CER > 30 % → 300M not usable. Compare CTC-1B / MMS-1b-all, and Whisper with a shrunk window as the last resort.
- **Known limitation:** 3 clips from one speaker is a *smoke test* of accuracy, not a benchmark. If it passes, the eval set grows (more sentences, more voices, call audio) before final decisions.
- **Status:** Done (2026-10-26). Results in EXPERIMENTS.md and D-014.

## D-014 · Adopt omniASR-CTC-300M-v2 **int8** as the ASR model *(provisional, proposed for your confirmation)*
- **Evidence (EXP-01):** corpus CER 6.3 % int8 vs 5.4 % fp32 (+1.0 point, limit +2). Latency for a 6 s phrase: 1.50 s int8 vs 2.77 s fp32. Steady-state RAM ≈ 1.0 GB int8 vs ≈ 1.7 GB fp32.
- **Decision:** int8 in the application. Cap segment length at **~7–8 s**; the exact value comes from the segmentation experiment (PLAN.md, answered question 4).
- **Why provisional:** 3 clips from 1 speaker. We re-check on the larger eval set (more sentences, other voices, call audio) before the final README choice.
- **Known weaknesses to document:**
  - English terms come out in Armenian letters (`Python` → `փայսոն`).
  - Output has no punctuation and no capitals.
  - Occasional missing or extra spaces between words.
- **Status:** Proposed. Waiting for your confirmation.

## D-015 · Microphone for evaluation and demo
- **Decision:** Jabra headset, MME device 1, the Windows default input. Windows' MME layer delivers 16 kHz mono directly.
- **Not used:** AirPods for recording. When their mic is in use, Bluetooth switches to a low-quality call mode, which is likely to hurt ASR. We can measure this later if needed. The built-in Realtek mic (device 2) is a backup.
- **Note:** recording levels varied by ~19 dB between clips (Jabra automatic gain or mic position). ASR normalises each clip, so this doesn't affect results. It's realistic for live use.
- **Status:** Accepted.
