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
- **Status:** **Accepted 2026-10-26** (provisional, as above). Re-check with more voices and realistic conversation audio.

## D-016 · Translation candidates (desk research, 2026-10-26)

| Candidate | Armenian → English | License | Size | CPU latency outlook | Verdict |
|---|---|---|---|---|---|
| **NLLB-200 distilled 600M** (Meta) | **Confirmed:** `hye_Armn` is in the model card's language list | **CC-BY-NC-4.0**. The card says "research model, not released for production deployment". Fine for this challenge, stated in the README. | ~600 M params. Official weights ~2.5 GB (fp32) | See the estimate below: plausible with int8 | **Test first** |
| NLLB-200 distilled 1.3B | Same | Same | ~2× compute | Probably over budget on this CPU | Only if 600M quality is insufficient |
| M2M-100 418M | Armenian supported *(from memory, not re-verified)* | MIT | 418 M | Similar to NLLB-600M | Reserve candidate (permissive license) |
| Opus-MT hy→en (Helsinki-NLP) | **Couldn't confirm the model exists** (absent from the lists I could check) | — | — | — | Dropped unless found |
| TranslateGemma 4B / Armenian Gemma (LLMs) | TranslateGemma's language list unconfirmed | various | 4 B+ | Far too slow for ~1 s on this CPU | Out of scope |

**Latency estimate for NLLB-600M (why int8 matters here):** generating text one token at a time is limited by **memory bandwidth**, and EXP-00 measured only ~10 GB/s. Each output token reads the 12 decoder layers (~200 M weights) **plus the output layer over NLLB's 256 k-token vocabulary (~262 M weights)**.
- fp32: ~1.8 GB read per token → ~0.18 s/token → a 20-token sentence takes **~3.5 s (too slow)**.
- int8: ~0.46 GB per token → ~0.05 s/token → **~1 s per 20-token sentence**.

So int8 is required, and an efficient runtime matters. A later optimisation is to restrict the output vocabulary to English tokens; CTranslate2 calls this a vocabulary map. These are estimates. EXP-02 measures the real numbers.

**Runtime choice:** **CTranslate2** (MIT, built for fast int8 CPU inference of exactly this kind of model) instead of plain `transformers.generate`.
- It costs one new dependency, `ctranslate2`, whose Windows/Python 3.12 support is checked with a dry run (CHK-02).
- The conversion is done **locally from Meta's official weights**, not from a community upload, so there's a single trusted source.

**EXP-02 design** (see D-017 below).

**Updated MT latency budget:** with int8 ASR at ~1.5 s for a 6 s phrase, the 5 s total leaves **≤ ~1.5 s for translation**. Under 1 s is the target.
- **Status:** Accepted for testing.

## D-017 · EXP-02 design: translation *(proposed)*
- **Question:** How good, how fast and how memory-hungry is NLLB-600M (CTranslate2) for Armenian → English? And how much do **missing punctuation** and **ASR errors** hurt it?
- **Inputs (`eval/mt_sentences.csv`):** 11 sentences, each with a reference English translation: the 3 recorded EXP-01 clips plus 8 short call-style sentences (text only). **To be checked by you as a native speaker.**
- **Three input conditions, so each effect is isolated:**
  - **A, original:** the Armenian sentence with punctuation and capitals.
  - **B, ASR-style:** the same sentence lowercased, without punctuation. This is what our ASR outputs, **minus its errors**. A → B measures the cost of missing punctuation.
  - **C, real ASR output:** the int8 hypotheses from EXP-01, for the 3 recorded clips. B → C measures the cost of recognition errors.
- **Configurations:** compute type int8 vs float32, **each in its own process** (clean RAM numbers). Within each: beam size 1 (greedy, fastest) vs 4 (usually better). 1 warm-up + 3 timed runs per sentence.
- **Metrics:**
  - **Quality:** chrF (sacrebleu) against the reference, plus **your rating** of each English output: 0 = wrong/misleading, 1 = understandable, 2 = good. The brief asks whether the English is *understandable*, and with only 11 sentences a human judgment is more meaningful than any automatic score.
  - **Latency:** per sentence (median), plus seconds per generated token.
  - **Memory:** RSS after load and peak.
- **Provisional decision rule** (judgment calls, written before the results):
  - int8 understandable (rating ≥ 1) on ≥ 9/11 in condition B, and **≤ ~1 s** median latency → adopt NLLB-600M int8.
  - Latency ok but quality poor → try NLLB 1.3B or M2M-100.
  - Quality ok but too slow → try greedy decoding and an English-only output vocabulary.
- **Status:** Done (2026-10-26). Results in EXPERIMENTS.md and D-018.

## D-018 · Adopt NLLB-200-distilled-600M, CTranslate2 **int8, beam size 1** *(provisional, proposed for your confirmation)*
- **Evidence (EXP-02 + blind human ratings):**
  - int8/beam 1: 10/11 understandable on ASR-style input, median latency 0.44 s, max 1.17 s, steady-state RAM ≈ 0.8 GB.
  - float32 is 3.2× slower (over budget) and 3.4× more RAM, and equal on clean input.
  - Beam 4's gain (+0.1 mean rating) is within rater noise, and it costs up to 4.9 s.
- **End-to-end budget check (6 s phrase):** VAD ~0.6 s + ASR ~1.5 s + MT ~0.5–1.2 s ≈ **2.6–3.3 s before speaker ID**. That leaves ~1.5 s for speaker ID and queueing under the 5 s limit. **Total model RAM ≈ 1.8 GB** (ASR 1.0 + MT 0.8).
- **Known weaknesses (README):**
  1. **Yes/no questions become statements.** The ASR doesn't output `՞`, the only written question marker in many Armenian questions.
  2. Phrases that rely on a comma can lose part of their meaning (t02).
  3. **ASR errors propagate and can change the meaning** (clip02 "classmates", clip03). **Improving ASR accuracy is the main quality lever**, not the MT settings.
  4. License: CC-BY-NC-4.0, research model.
- **Ideas for later, if time allows (not now):**
  - Restrict the output vocabulary to English (faster).
  - Beam 2 as a middle ground.
  - Light punctuation / question restoration.
- **Status:** **Accepted 2026-10-26** (provisional).

## D-019 · Priority shift: working application first
- **Context:** deadline 1 November. ASR and MT are chosen and measured.
- **Decision:** No more model experiments for now. Order:
  1. Audio capture check (Spike 1).
  2. Live pipeline: capture → VAD segmentation → ASR → MT → terminal.
  3. Speaker identification.
  4. Real-conversation tests.
  5. README + demo rehearsal.
  Each step still gets a quick, measured check, but no broad comparisons.
- **Status:** Accepted.

## D-020 · Audio capture stack
- **Library: PyAudioWPatch** (MIT). It's a PortAudio fork whose Windows wheels add **WASAPI loopback devices**: one per output device, capturing exactly what plays there. No virtual cable is needed, and playback isn't affected (D-001). The plain PortAudio in `sounddevice` has no loopback support. The **same library captures the microphone**, so both sources share one code path.
- **Each device runs at its native rate and channel count** (loopback is typically 48 kHz stereo). Audio is converted to **mono and resampled to 16 kHz with `soxr`** (python-soxr, LGPL-2.1, a high-quality streaming resampler). This doesn't depend on Windows choosing a rate for us.
- **Timestamps:** one monotonic session clock for both sources (PLAN.md §3).
- **Known WASAPI behaviour to verify in Spike 1:** loopback delivers **no data while nothing is playing**, so there are gaps in the stream. Later code must use timestamps, not sample counts, to place audio in time.
- **Status:** Accepted. Spike 1 passed (EXPERIMENTS.md).

## D-021 · Energy-based VAD first (pluggable)
- **Decision:** Speech/silence per 30 ms frame by loudness: speech if it's ≥ 15 dB above an adaptive noise floor and above −55 dBFS.
  - A phrase starts after 3 speech frames (+0.3 s preroll).
  - It ends after **0.6 s of silence**, or is force-cut at **7 s** (D-014).
  - It's dropped if it has < 0.4 s of speech.
- **Why:**
  - The measured conditions are very clean: 35–56 dB speech-to-background on the headset mic, near digital silence between phrases on the loopback, and call apps apply their own noise suppression.
  - No new dependency.
  - Fully unit-tested (`tests/test_vad.py`).
- **Trade-offs:** noise like keyboard clicks or breathing can start a segment. The ASR then returns little or nothing, and the pipeline skips results under 2 characters. A forced cut can split a sentence mid-word.
- **Upgrade path:** the frame classifier is a plain `(frame) -> bool`, so Silero VAD can replace it without touching the rest. Smarter cutting: cut at the quietest frame in the last ~1 s. Do it only if live tests show the VAD is the weakest link.
- **Status:** Accepted.

## D-022 · Live pipeline structure
- **Threads:** capture callbacks → chunk queue → segmenter thread (one Segmenter per source) → segment queue → **one worker** (ASR → label → MT → print), plus the main thread for Ctrl+C. Models never run in parallel (4 cores; D-010).
- **Latency** is measured per line, from end of speech (`Segment.t_end`) to print, on the shared session clock. It's shown next to each label and summarised at the end (median, p95, max, count over 5 s). `--log` writes per-segment timings (VAD wait, queue wait, ASR, MT) to `results/session_*.jsonl`.
- **Labels:** mic → "Me", loopback → "Call" until speaker identification is added.
- **Simulated worst case:** both sources speaking continuously, with fake models at the measured speeds. Queue wait up to 2.1 s, total ≤ 4.5 s.
- **Status:** Accepted. LIVE-01 done: 45 lines, max latency 4.4 s, 0 over 5 s.

## D-023 · Two fixes after LIVE-01
1. **Armenian-only CTC decoding** (`app/asr.py`, `armenian_only=True` by default). Before the argmax, every token except blank, space, Armenian letters (incl. `և`, `։`, `֊`) and digits is set to −∞. That leaves **88 of 10,288 tokens**.
   - **Why:** the model has no language setting. Live, it drifted into Latin/Arabic/CJK on unclear audio, and NLLB then hallucinated whole sentences from that.
   - **Cost:** none in speed.
   - **Trade-off:** English terms always come out in Armenian letters, which was already the case (`Python` → `փայսոն`, and NLLB recovers it).
   - **Check:** re-run EXP-01 int8 to make sure the CER doesn't get worse.
2. **Forced cut at the quietest frame of the last 1.5 s** (`app/vad.py`) instead of exactly at 7.0 s. clip03 is now cut at 6.2 s (between words) instead of 7.0 s. The rest of the audio starts the next part, so nothing is lost (unit-tested).
- **Status:** **Verified.** EXP-01 int8 transcripts are identical (no regression). LIVE-02: 0 lines with non-Armenian characters, and cuts fall between words.

## D-024 · Clean shutdown
- **Ctrl+C:** stop capture, emit the phrase in progress, finish the queued phrases, print the latency summary.
- **A second Ctrl+C** skips the remaining phrases (only the ASR/MT call already running finishes) and still prints the summary. No traceback, which matters in the demo. Every line is appended to the `--log` file as soon as it's printed, so nothing is lost either way.
- **Status:** Implemented. Simulated with fake devices/models.

## D-025 · Speaker identification approach
- **Embeddings:**
  - **Library:** **sherpa-onnx 2.0.0** (Apache-2.0). It computes its own features, so there's no torchaudio and no version clash with torch 2.14.
  - **API verified** against the repository source at version 2.0.0: `SpeakerEmbeddingExtractorConfig` → `SpeakerEmbeddingExtractor` → `create_stream / accept_waveform / input_finished / is_ready / compute`, the same pattern as its "dynamic speaker identification" example.
  - **Model:** `wespeaker_en_voxceleb_resnet34_LM.onnx` from sherpa-onnx's official model release. CC-BY-4.0 (WeSpeaker models follow the VoxCeleb dataset licence). GitHub doesn't publish a checksum, so `tools/download_speaker_model.py` records SHA-256 + size on first download and verifies them afterwards.
  - **Caveat:** VoxCeleb is mostly English celebrity speech. Voice traits are largely language-independent, but this must be checked on Armenian (CAL-01).
- **Clustering (`app/speakers.py`, unit-tested):** online centroids. Each speaker is the running mean of their normalised embeddings, and a new phrase joins the most similar speaker if cosine similarity ≥ threshold. Otherwise:
  - it becomes a new speaker if it has ≥ 1 s of speech;
  - else it goes to the closest speaker, marked uncertain.

  Max 8 speakers. Labels are fixed for the session.
- **Only the loopback side is clustered.** The mic is always "Me" (brief).
- **Threshold:** chosen from data in CAL-01 (a real multi-speaker recording, timeline checked by the user). It isn't guessed.
- **Status:** Accepted, pending CAL-01. CAL-01 showed that raw cosine can't separate speakers on one channel → D-026.

## D-026 · Centre speaker embeddings with a prior mean
- **Evidence (CAL-01):** through one call channel, raw embeddings of different people have cosine 0.46–0.94. One shared direction dominates (top eigenvalue 19.1 of 25), so no raw threshold separates the speakers. After subtracting the mean, a clear 2-speaker structure appears, and the change at 124.7 s is visible.
- **Decision:** `SpeakerTracker` compares phrases in a **centred** space. The mean starts from a **prior** (`models/speaker/prior_mean.npy`, estimated offline from calibration recordings) and is updated with every phrase of the session: `m = (w·prior + Σ session) / (w + n)`. The prior keeps early decisions stable; the session part adapts to the actual call channel. Centroids = mean of the centred, normalised member embeddings. Raw mode (`prior_mean=None`) is kept for comparison.
- **Threshold and prior weight:** chosen in **CAL-02** against the user's per-phrase labels, with the prior from *other* recordings only (honest evaluation). Not guessed.
- **Known limits:** the prior comes from our own recordings (one video channel plus the headset mic), not from a large background set. The demo call (Zoom/Meet codec) differs, and the running update must adapt. Two people in one 7 s phrase give a mixed embedding.
- **Status:** Implemented (unit test reproduces "raw merges, centred separates"). **Confirmed by CAL-02** (D-027).

## D-027 · Speaker-tracker settings and integration
- **Settings (CAL-02):** centred, **prior weight 30, threshold 0.10**, min 1 s of speech for a new speaker, max 8 speakers. This was perfect on the 14 labelled phrases (2 speakers, purity = coverage = 1.0), with the prior estimated only from other recordings.
- **Caution:** the good range is narrow (0.00 merges, 0.20 adds a speaker) and the evidence is small. So the threshold is a **CLI option, `--speaker-threshold`**, to re-check during the real-call test (the call app's codec differs from the YouTube video).
- **Integration:** `CallSpeakerLabeler` in `app/speakers.py`.
  - The mic is always "Me".
  - A loopback segment → embedding (sherpa-onnx, 4 threads) → `SpeakerTracker.assign` → "Speaker N".
  - Too short to embed → "Speaker ?".
  - It runs in the single worker after ASR, so noise segments that give empty ASR text are never embedded.
  - The per-line similarity / new / uncertain / embed time goes to the `--log` file. At the end, the session prints the phrase count per speaker.
- **Latency cost:** +0.14–0.34 s per call-side line. It makes the overlap case (K2) a bit worse.
- **Status:** Implemented, simulated end-to-end. **LIVE-03 next.**

## D-028 · A crashed worker thread stops the app loudly
- **Context:** the first LIVE-03 attempt (2026-10-26 16:24) processed **zero** phrases: no log file, an empty queue at Ctrl+C, no speaker counts. Yet the app kept "listening". A thread exception prints a traceback once and then scrolls away. That's a silent failure, the opposite of the "fail loudly" rule.
- **Decision:** every worker thread runs inside a guard. On an exception, it prints the traceback in a `FATAL` banner, and the main thread stops the app: it finishes or skips the remaining work, prints the summary, adds "(no lines were written)" when the log is empty, and exits with **code 1**. No retries, no fallbacks.
- **Status:** Implemented and simulated (forced embedder exception → banner, clean stop in ~12 s, exit code 1). The root cause of the 16:24 failure is still unknown; the rerun will show the traceback.

## D-029 · After LIVE-03: one bug fix + diagnostics, no model/threshold changes
1. **MT repetition guard** (`app/translate.py`): `max_decoding_length = 2 × input tokens + 10` and `no_repeat_ngram_size = 4`.
   - **Why:** one phrase looped for 14.4 s and pushed 5 lines over 5 s.
   - **Trade-off:** a translation that legitimately repeats a 4-token sequence gets reworded; it's rare in one sentence.
2. **Diagnostics, so problems are investigated with data, not guessed:**
   - `--record` saves each source's 16 kHz audio, time-aligned with the log (`results/session_*_<source>.wav`, gitignored).
   - The log has **every** phrase: `status` = shown / skipped (with a reason), the ASR **confidence** (mean probability of the emitted characters), the VAD noise floor, the segment peak, and the MT token count.
   - The summary + log include **capture statistics per source** (callbacks, longest gap, overflow = lost audio).
- **Not changed yet** (they need the recorded audio and ground truth first): speaker prior/threshold, VAD parameters, ASR.
- **Status:** Implemented, simulated end-to-end. Recorded rerun done (LIVE-03b, `results/session_20261026_164715*`).

## D-030 · Unclear speech is shown, not translated (ASR confidence < 0.80)
- **Evidence:**
  - LIVE-03b mic audio, replayed offline with `tools/replay_mic.py` and checked against what the user actually said: every correct phrase had confidence **≥ 0.89** (sentences, «Ողջույն, բարև», «Ինչպե՞ս ես»), and every wrong one **≤ 0.72** (isolated «Բարև», «Ողջույն», «Շատ բարի»: 0.6–1.0 s of speech). The EXP-01 clips score 0.946–0.962.
  - Padding short phrases with 0.5 s of silence rescued **none** of them and made «Ողջույն, բարև» worse → rejected.
- **Decision:** confidence < **0.80** → the line is shown with `(unclear)` after the Armenian, and `EN: [unclear speech, not translated]`. MT is skipped, so it can't invent fluent English like "The following is a list of" from garbled input, and the time is saved. CLI: `--min-confidence` (0 = off). Logged as `status: "unclear"`.
- **Limits:** confidence catches garbage, not small errors (clip03: CER 9.7 % at confidence 0.95). **Isolated words under ~1 s are a real ASR limitation** (README).
- **Status:** Implemented, simulated (MT not called for unclear lines).

## D-031 · Speaker ID: mixed phrases are the real problem *(investigation, no change yet)*
- **Evidence:** LIVE-03b call side, labelled by the user (`eval/speakers/labels_session2.json`): **8 of 14 phrases are mixed** (both people), 1 interviewer, 5 guest (93.8–126 s). CAL-02: 11 of 25 mixed.
  - Live, all 14 were Speaker 1. The guest phrases had similarity **0.56–0.72** to the Speaker 1 centroid.
  - That centroid was created and grown from **mixed** phrases, so it represents "interviewer + guest" and matches both.
  - Raising the threshold would mostly split the mixed phrases into spurious speakers.
- **Hypothesis to test:** embed **shorter windows** (1.5 / 2 / 3 s) within each phrase, track at window level, and label the phrase by the majority of its windows. Windows are much more likely to be single-speaker, so the centroids stay pure. Cost: ~0.2–0.4 s more per call-side line.
- **Test:** `tools/speaker_eval.py`. Phrase-level vs window-level on **both** labelled recordings, with the prior always from the *other* recordings. Decide from F, not impressions.
- **Status:** **Tested, hypothesis rejected** (SPK-EVAL, see D-032): window-level embeddings are at best equal to phrase-level, and they'd cost more latency.

## D-032 · Speaker ID: phrase-level, threshold 0.40, prior rebuilt from all calibration audio
- **Evidence (SPK-EVAL, `results/spk_eval_20261026_231325.json`):** 2 labelled recordings; the prior for each recording comes from the *other* recordings + capture + clips.
  - **The current live setting (phrase, w = 30, th 0.10) merges everyone on BOTH recordings** (1 speaker found; F 0.83 / 0.91). With a prior from more varied audio, 0.10 is far too low. The good threshold depends on the prior, which is why CAL-02's single-recording result (0.10 perfect) didn't transfer.
  - **Best: phrase-level, w = 30, th 0.40, mean F 0.98.** Interview: 3 speakers found, F 0.96, one spurious extra on one phrase. Session 2: **2 found, F 1.00** (interviewer → guest → interviewer).
  - Phrase w = 10 th 0.30 also scores 0.98, but finds 4 and 3 speakers.
  - Window-level best: 2 s / 3 s windows at 0.96, 1.5 s at 0.92.
- **Decision:**
  - Keep **one embedding per phrase**.
  - **Threshold 0.40**, prior weight 30. Among the tested settings, this one has the best mean F and the speaker counts closest to the truth. Over-splitting on an occasional phrase is a smaller error than merging everyone.
  - **Rebuild the prior** from all calibration audio (`tools/build_speaker_prior.py`: both labelled recordings + first capture + clips; documented in `models/speaker/PRIOR.txt`).
- **Limits:** the evidence is two recordings and 20 scorable phrases; the setting was chosen on them, so it **must be confirmed on new audio** (a new video or the real call). Mixed phrases (19 of 39) still get a single label. `--speaker-threshold` remains for tuning.
- **Status:** Implemented (default threshold 0.40), prior rebuilt (49 phrases). **The independent check (LIVE-04a) failed the other way: 7 speakers for 2 people.** → D-033.

## D-033 · Confirm a new speaker with a second similar phrase *(proposed, being evaluated)*
- **Evidence:** a fixed threshold doesn't transfer (0.10 merges on session 2, 0.40 over-splits session 3). In LIVE-04a, 3 of the 7 "speakers" were singletons: one-off phrases (often mixed or unusual) that matched no centroid.
- **Rule (`SpeakerTracker(confirm_new=True)`):** an unmatched phrase gets the closest existing label (marked uncertain) and becomes a **candidate**. A new speaker is created only when a later unmatched phrase (within 5 phrases) matches a candidate (≥ threshold). One-off outliers never become speakers. A real new person is confirmed on their second phrase; the cost is that their first phrase shows the old label.
- **Test:** `tools/speaker_eval.py` on **all three** labelled recordings, with priors from the other recordings. Thresholds 0.1–0.6 × prior weight 10/30 × confirmation off/on. Choose by mean **and worst** F. If no setting is acceptable on all three, speaker ID is documented as unreliable on fast cross-talk, and the real-call test (turn-taking) decides.
- **Status:** Implemented + unit-tested (21 tests). **Evaluated → D-034.**

## D-034 · Speaker ID setting: confirmation ON, prior weight 10, threshold 0.30; measured by balanced accuracy
- **Metric change:** purity/coverage F **rewards merging** when one person dominates. In session 3 (16 of 18 labelled phrases from the guest), "everyone = Speaker 1" scores F 0.93. The brief asks whether speakers are **kept apart**, so settings are now ranked by **balanced accuracy**: the best one-to-one mapping of real speakers to labels, averaged over real speakers. Merge-all = 0.5, perfect = 1.0. It's implemented in `tools/speaker_calibrate.py`, and `tools/speaker_eval.py` ranks by the worst recording.
- **Evidence (SPK-EVAL2, 3 labelled recordings, priors from the other recordings):**
  - **confirmation on, w 10, th 0.30:** balanced accuracy **mean 0.90, worst 0.79**; speakers found 3 / 2 / 3 (true 2 / 2 / 2).
  - confirmation on, w 30, th 0.50: mean 0.90, worst 0.75; found 3 / 2 / 2.
  - Previous live setting (no confirmation, w 30, th 0.40): mean 0.86, worst 0.68; found **5 / 2 / 8**.
  - No-confirmation settings over-split (5–8 speakers) or merge (1 speaker).
- **Decision:** `confirm_new=True`, `prior_weight=10`, `threshold=0.30` (`app/main.py`; `--speaker-threshold` stays).
- **Honest limits:**
  - **Decent, not perfect:** 0.79–1.00 balanced accuracy; ≤ 1 spurious extra speaker per recording.
  - Mixed phrases (fast cross-talk) still get one label.
  - A new person's **first** phrase shows the previous label (confirmation delay).
  - **All 3 labelled recordings were used to choose this, so the real call is the only independent test left.**
- **Status:** Implemented. Real-call test next.

## D-035 · Commit the speaker prior so a fresh clone works
- **Problem:** the app needs the prior mean embedding. It lived in `models/` (gitignored) and can only be rebuilt from our calibration recordings, which are never committed. A fresh clone couldn't run speaker identification.
- **Decision:** the prior moves to **`assets/speaker_prior_mean.npy`** and is **committed**, through an explicit `.gitignore` exception. Provenance is in `assets/speaker_prior_mean.txt`. It's **one average of 256 numbers over 49 phrases** from several recordings (two videos, one capture, the EXP-01 clips): a channel/population mean, not a voice print of any individual. Per-phrase embeddings (`*.npz`) stay uncommitted.
- **Only `tools/build_speaker_prior.py` writes it.** `tools/speaker_calibrate.py` no longer overwrites it.
- **Status:** Implemented 2026-10-29 (copied unchanged: same MD5 as the prior used in D-034).

## D-036 · Pinned requirements
- `requirements.txt` pins the **exact versions every measurement used** (Windows 10 64-bit, Python 3.12.3). The earlier `requirements-*.txt` files (per experiment) stay as history.
- **Status:** Implemented.

## D-015 · Microphone for evaluation and demo
- **Decision:** Jabra headset, MME device 1, the Windows default input. Windows' MME layer delivers 16 kHz mono directly.
- **Not used:** AirPods for recording. When their mic is in use, Bluetooth switches to a low-quality call mode, which is likely to hurt ASR. We can measure this later if needed. The built-in Realtek mic (device 2) is a backup.
- **Note:** recording levels varied by ~19 dB between clips (Jabra automatic gain or mic position). ASR normalises each clip, so this doesn't affect results. It's realistic for live use.
- **Status:** Accepted.
