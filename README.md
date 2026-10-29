# Live Armenian → English call transcription (local, CPU-only)

A Python program that listens to a live call, transcribes spoken **Armenian**, and prints an **English** translation in the terminal, labelled by speaker, while the conversation is still running. Everything runs **locally on a laptop CPU**: no cloud APIs.

- **Your microphone** → `Me`
- **System audio** (the other side of the call, any app: Zoom, Meet, Telegram, …) → `Speaker 1`, `Speaker 2`, …

```
[00:01:59] Me   (2.8 s)
  HY: այսօր եղանակը շատ լավ է
  EN: Today the weather is very good.
[00:00:39] Speaker 2   (4.9 s)
  HY: բայց ռոբորտ կոչվածի դասական սահմանումը ենձիեն ...
  EN: But the classic definition of a robot is that ...
[00:00:34] Me   (1.6 s)
  HY: ր   (unclear)
  EN: [unclear speech, not translated]
```

*(Format example assembled from lines of recorded test sessions; the speaker number is illustrative.)* The number in brackets is the **measured latency**: from the end of the spoken phrase to the moment the English line is printed.

Target machine (the one used for all measurements): **Windows 10 64-bit, Intel Core i5-8250U (4 cores), 8 GB RAM, no GPU**, Jabra EVOLVE 20 headset.

---

## 1. Setup

### 1.1 Prerequisites
- **Windows 10/11, 64-bit.** System-audio capture uses WASAPI loopback, which is Windows-only.
- **Python 3.12, 64-bit** (python.org installer). Use the `py` launcher: on many systems the bare `python` command opens the Microsoft Store.
- **Git**, ~**6 GB free disk** (models ~4.5 GB + Python packages), internet for the one-time model download.
- **A headset.** Echo cancellation is out of scope. With loudspeakers, the mic would pick up the call and label it `Me`.

### 1.2 Install

```powershell
git clone <this repository> Mathrix-Claude-Project
cd Mathrix-Claude-Project
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m unittest discover tests        # 21 unit tests, should end with: OK
```

All commands call `.venv\Scripts\python` directly, so there's no need to activate the venv (and no PowerShell script-policy issues).

### 1.3 Download the models (one time, ~4 GB download)

```powershell
.venv\Scripts\python tools\download_model.py           # ASR: omniASR-CTC-300M-v2, 1.3 GB, SHA-256 verified
.venv\Scripts\python tools\prepare_nllb.py             # MT: NLLB-200-distilled-600M (2.5 GB) → CTranslate2 int8
.venv\Scripts\python tools\download_speaker_model.py   # speaker embeddings: WeSpeaker ResNet34-LM, 26 MB
```

- Every model is downloaded at a **pinned revision** and verified against the published SHA-256 where one exists (`models/*/REVISION.txt`, `SOURCE.txt`).
- `prepare_nllb.py` converts the official weights locally. **Close the browser first:** conversion needs ~3.7 GB RAM at peak. It builds only the int8 model the app uses; `--with-float32` also builds the float32 reference used in EXP-02 (D-037).
- `download_model.py` and `prepare_nllb.py` show the files and ask before downloading (`--yes` skips the question).
- The speaker **prior** (`assets/speaker_prior_mean.npy`) is part of the repository (§3.4).

Models live in `models/`, which is never committed.

### 1.4 Audio setup (Windows)

1. Plug in the headset. In **Windows Sound settings**, make it the **default output** and the **default input**.
2. In the **call app** (Zoom/Meet/…), select the **same headset** for speaker and microphone.
3. Check what the program will use:

   ```powershell
   .venv\Scripts\python -m app.main --list-devices
   ```

   It lists every input and every `LOOPBACK` device and shows the defaults. By default the program uses:
   - **mic** = the Windows default input;
   - **system audio** = the loopback of the Windows **default output**, i.e. exactly what you hear in the headset.

   No virtual audio cable is needed, and playback isn't affected.
4. To choose explicitly: `--mic <index> --loopback <index>`, using the indices from `--list-devices`.

### 1.5 Run

```powershell
.venv\Scripts\python -m app.main
```

- Loading the models takes **about 1 minute**. Then it prints `Listening:` for both sources. Talk; lines appear as phrases end.
- **Ctrl+C** stops: phrases in progress are finished, then a summary prints. A second Ctrl+C skips the remaining phrases.
- **Summary:** lines, latency median / p95 / max / count over 5 s, capture statistics (lost audio?), phrases per speaker.

| Option | Effect |
|---|---|
| `--mic N`, `--loopback N` | choose devices (see `--list-devices`) |
| `--no-mic`, `--no-loopback` | capture only one side |
| `--log` | per-phrase timings, confidence and speaker scores → `results/session_*.jsonl` |
| `--record` | also save both audio streams as WAV (diagnostics; implies `--log`; never committed) |
| `--speaker-threshold X` | speaker matching threshold (default 0.30; higher = more speakers) |
| `--min-confidence X` | below this ASR confidence a line is shown as *unclear* and not translated (default 0.80; 0 = off) |
| `--hide-latency` | don't print the latency next to each label |

**For best results:** laptop **plugged in**, Windows power mode **Best performance**, browser tabs closed (CPU and RAM are tight on this machine). **Don't run it right after installing or copying the models:** Windows scans the new files for a few minutes, and a run during that time was ~40 % slower (CLONE-01). Do one short warm-up run before a demo.

---

## 2. How it works

```
 Mic (PyAudioWPatch) ──► capture callback ──► float32 mono 16 kHz (soxr) ─┐
                                                                            ├─► chunk queue
 System audio (WASAPI loopback) ──► capture callback ──► 16 kHz mono ──────┘
                                                                            │
                         segmenter thread: one energy-VAD Segmenter per source
                         (phrase ends after 0.6 s silence; max 7 s, cut at the quietest point)
                                                                            │
                                                                     segment queue
                                                                            │
                     ONE worker thread (the 4 cores are shared, models never run in parallel):
                       1. ASR   omniASR-CTC-300M-v2 int8, Armenian-only decoding, + confidence
                       2. label  mic → "Me";  loopback → speaker embedding → online tracker → "Speaker N"
                       3. MT    NLLB-600M (CTranslate2 int8, beam 1), skipped if ASR confidence < 0.80
                       4. print + optional log
```

- **One clock.** Both sources are timestamped on one monotonic session clock, so latency is measured per line, from the end of speech to print.
- **Only one model runs at a time.** On a 4-core laptop, running two models in parallel makes both slower and doubles RAM. The cost is that when both sides finish phrases at the same moment, one waits (see the limitations).
- **Fails loudly.** If a worker thread crashes, the program stops with a `FATAL` banner and the traceback, instead of silently "listening" (D-028).

**Measured latency budget** (6 s phrase, int8, 4 threads):

| Step | Time |
|---|---|
| VAD end-of-phrase wait | ~0.6 s |
| ASR | ~1.5–1.9 s |
| speaker embedding (call side) | ~0.14–0.34 s |
| MT | ~0.5–1.2 s |
| **typical total** | **~3–4 s** (limit: 5 s) |

**Memory:** ASR ~1.0 GB + MT ~0.8 GB + speaker model ~0.1 GB, i.e. **≈ 2 GB for all models.**

Code (`app/`):
- `audio.py`: capture
- `vad.py`: phrase segmentation
- `asr.py`: speech recognition
- `translate.py`: translation
- `speakers.py`: embeddings + tracker
- `pipeline.py`: threads, filter, logging
- `main.py`: command line
- `recorder.py`: `--record`
- `text_norm.py`, `metrics.py`: evaluation

---

## 3. Model choices, alternatives and why

Every choice below was **measured on this laptop**. The numbers come from `EXPERIMENTS.md` (raw JSON in `results/`), and the reasoning from `DECISIONS.md` (D-numbers).

### 3.1 CPU first: what this laptop can afford (EXP-00)
- **Sustained matrix-multiply throughput:** ~145 GFLOP/s with **4 threads**. 8 threads were faster at peak but dropped to 33 GFLOP/s at times, so **4 threads everywhere** (D-010).
- **Memory bandwidth:** only ~8–11 GB/s, which hurts autoregressive decoders (Whisper, NLLB).

### 3.2 Speech recognition: **omniASR-CTC-300M-v2** (Meta Omnilingual ASR), int8

| Candidate | Armenian | Measured / estimated cost on this CPU | Decision |
|---|---|---|---|
| Whisper large-v3 / turbo / **BuzzASR** (Armenian large-v3 fine-tune, best published CER) | yes | Whisper always encodes a 30 s window → est. **17–28 s per phrase** | ✗ too slow (D-011) |
| Whisper small/medium | weak (community fine-tunes report 40–75 % WER) | 3–14 s | ✗ |
| MMS-1b-all / omniASR-CTC-1B | yes | est. 2–7.5 s | reserve |
| **omniASR-CTC-300M-v2** | yes (Eastern Armenian in training data, 294 h) | **1.5 s for a 6 s phrase (int8)** | ✓ |

- **Accuracy (EXP-01, 3 read sentences):** CER **6.3 %** int8 (5.4 % fp32). int8 is 1.9× faster, with ~1.0 GB vs 1.7 GB RAM (D-014).
- **Windows note:** Meta's official stack (fairseq2) doesn't run natively on Windows. We use a community conversion to `transformers` `Wav2Vec2ForCTC` (`aadel4/omniASR-CTC-300M-v2`) whose model card reports numerical parity with the original. The revision is pinned and the hash verified.
- **Armenian-only decoding (D-023):** the model covers ~1600 languages and has no language setting. Live, it drifted into Latin/Arabic/Chinese characters on unclear audio, and MT then invented sentences. Decoding is now restricted to Armenian letters, space and digits (88 of 10,288 tokens). Clean-speech accuracy is unchanged.
- **Confidence filter (D-030):** on recorded live audio, every correct phrase scored ASR confidence **≥ 0.89** and every wrong one **≤ 0.72**. Below **0.80** the line is shown as *unclear* and not translated, so MT can't turn garbage into fluent but false English.

### 3.3 Translation: **NLLB-200-distilled-600M**, CTranslate2 **int8, beam 1**

| Candidate | Result | Decision |
|---|---|---|
| **NLLB-600M int8, beam 1** | **10/11** sentences understandable (blind human rating), **0.44 s** median, max 1.17 s, ~0.8 GB | ✓ |
| NLLB-600M int8, beam 4 | rating 1.55 vs 1.45 (within rater noise), up to **4.9 s** | ✗ too slow |
| NLLB-600M float32 | 3.2× slower per token, 3.4× more RAM | ✗ |
| NLLB-1.3B, M2M-100, TranslateGemma-4B | larger / not better-documented for Armenian / far too slow | not needed |
| Opus-MT hy→en | couldn't confirm the model exists | — |

- **Converted locally** from Meta's official weights with CTranslate2.
- **EXP-02 (D-018) tested three inputs:**
  - original text;
  - the same without punctuation (what our ASR outputs);
  - real ASR output.

  Missing punctuation costs little, **except questions**. ASR errors cost the most.
- **Repetition guard (D-029):** output length is tied to input length, and no repeated 4-grams. One live phrase had looped for 14 s before this.

### 3.4 Speaker identification: **WeSpeaker ResNet34-LM** via sherpa-onnx + an online tracker
- **Embedding:** sherpa-onnx 2.0 (no torchaudio, no version clash). ~0.14–0.34 s per phrase.
- **Tracker** (`app/speakers.py`): online clustering, one centroid per speaker.
- **What the calibration found** (on three Armenian recordings that we **labelled phrase by phrase**):
  1. **Raw cosine similarity can't separate people on one call channel.** Different speakers scored 0.46–0.94; the shared codec/room signature dominates. → **Centre** the embeddings by subtracting a prior mean, updated during the session (D-026). The prior is `assets/speaker_prior_mean.npy`: one average over 49 phrases, committed so a fresh install works (D-035).
  2. **A fixed threshold doesn't transfer between recordings.** 0.10 merged everyone on one video; 0.40 split another into 7 "speakers". → **A new speaker is created only when a second similar unmatched phrase confirms it** (D-033), so one-off outliers don't become speakers.
  3. **Window-level embeddings** (1.5–3 s windows inside a phrase) were tested and **rejected**: not better, slower (D-032).
- **Setting:** confirmation on, prior weight 10, threshold 0.30 (D-034).
- **Score: balanced accuracy 0.79–1.00 (mean 0.90)** across the 3 recordings, with 2–3 speakers found for 2 real people. Balanced accuracy means each real speaker is mapped to their best label, then accuracy is averaged over speakers. The earlier F metric was dropped because it rewarded merging everyone.

### 3.5 Voice activity detection: energy-based (no dependency)
- Speech if a 30 ms frame is ≥ 15 dB above an adaptive noise floor and above −55 dBFS.
- **Measured headroom:** 35–56 dB between speech and background on the headset mic; near-digital silence between phrases on the loopback.
- It found every utterance with correct boundaries in the recorded tests.
- The classifier is pluggable (a trained VAD such as Silero would drop in).

---

## 4. Results (on this laptop)

| Test | What | Result |
|---|---|---|
| EXP-01 | ASR, 3 read Armenian sentences | CER 6.3 % (int8), 1.5 s per 6 s phrase |
| EXP-02 | MT, 11 sentences × 3 input variants, blind human rating | 10/11 understandable on ASR-style input, 0.44 s median |
| LIVE-01 | first live session (45 lines) | **0 lines over 5 s**, max 4.4 s |
| LIVE-03 | live, before the MT guard | max 17.5 s (MT loop, fixed) |
| LIVE-03b | scripted, recorded (22 lines) | **0 over 5 s**, max 4.8 s; no lost audio; mic sentences correct (confidence 0.87–0.98) |
| LIVE-04a | new 2-person video, 23 lines | max 5.2 s (1 line); speaker over-split → fixed by D-033/034 |
| SPK-EVAL2 | speaker settings on 3 labelled recordings | balanced accuracy mean 0.90, worst 0.79 |
| CLONE-01 | fresh clone following this README, 1-person video + mic (19 lines) | install + 21 tests OK; latency **median 4.0 s**, max 5.5 s, **3 over 5 s** (long call-side phrases); 1 speaker → 1 label; no lost audio |
| **LIVE-04** | **real call, ≥ 2 Armenian speakers** | **see EXPERIMENTS.md** |

---

## 5. Known limitations (honest list)

1. **Isolated single words (< ~1 s, e.g. «Բարև» alone) are usually not recognised.** They're shown as *unclear* instead of being mistranslated. Sentences and two-word phrases work.
2. **Yes/no questions become statements.** The ASR never outputs `՞`, which is often the only written question marker in Armenian («Դու ինձ լսո՞ւմ ես» → "You hear me.").
3. **ASR errors can change the meaning** while the English stays fluent (one dropped letter turned "friends" into "classmates"). Fast, informal speech is clearly worse than read speech.
4. **English words come out in Armenian letters** (`Python` → `փայսոն`). NLLB usually recovers them.
5. **Speaker identification degrades with fast cross-talk.** Phrases containing two voices get one label. A new person's *first* phrase shows the previous label (the confirmation delay). Occasionally one extra speaker appears.
6. **The 5 s limit is met on median, not on every line.** Median latency is 4.0–4.3 s, but about 1 in 6 long, uninterrupted phrases from the call side arrives at **5.0–5.5 s** (CLONE-01: 3 of 19 lines). The time is spread over waiting for the speaker to pause, ASR and MT, so no single setting fixes it (§6, items 4–5 would). Your own lines are typically ~2 s.
7. **Overlapping speech on both sides** makes phrases queue behind each other: one worker, 4 cores. In LIVE-02 one line reached 7 s while the user spoke over a video.
8. **Long monologues are cut at ~7 s,** at the quietest point; a cut can still fall mid-sentence.
9. **Windows only** (WASAPI loopback); **headset required** (no echo cancellation).
10. **The ASR model is a community conversion** (`aadel4/omniASR-CTC-300M-v2` on Hugging Face), not a Meta release. It is pinned and hash-verified, but if that repository disappears, a fresh install needs another conversion of Meta's checkpoint.
11. **Licenses:** NLLB-200 is CC-BY-NC-4.0 ("research model", non-commercial). The speaker model is CC-BY-4.0. omniASR is Apache-2.0.

## 6. What I would improve with more time

1. **ASR accuracy on fast speech and short words** (the biggest quality lever). Fine-tune the CTC model on Armenian conversational speech, or test the 1B CTC model with int8 and a vocabulary-restricted head.
2. **Question / punctuation restoration** before MT (prosody or a small text model).
3. **Speaker ID on mixed phrases:** detect speaker changes inside a phrase and split the line; a trained VAD/segmentation model (e.g. pyannote-style) instead of energy + max-length cuts.
4. **Faster MT:** restrict NLLB's output vocabulary to English (the 256 k-token output layer is half the per-token cost), so overlapping phrases queue less.
5. **Two workers with core pinning** (e.g. 2 + 2 cores), so the mic and the call side don't wait for each other.
6. **A larger evaluation set:** more voices, real call audio with several codecs, and automatic latency/accuracy regression tests.

## 7. Repository map and documentation

| Path | Content |
|---|---|
| `app/` | the application (see §2) |
| `tools/` | model downloads, recording, capture test, phrase labelling, speaker calibration/evaluation, mic replay |
| `benchmarks/` | CPU benchmark, compatibility checks, EXP-01 (ASR), EXP-02 (MT) + blind rating |
| `tests/` | 21 unit tests (text normalisation, metrics, CTC decoding, VAD, speaker tracker) |
| `eval/` | sentence manifests and speaker labels (the audio itself is never committed) |
| `results/` | raw JSON/JSONL of every measurement |
| `assets/` | speaker prior mean (+ provenance) |
| `PLAN.md` | the original plan and milestone status |
| `DECISIONS.md` | every decision with evidence (D-001 … D-037) |
| `EXPERIMENTS.md` | every measurement, with findings |
| `HANDOVER.md` | working notes between sessions (historical; this README is current) |
| `chats/` | the complete, unedited AI chat transcripts (one Markdown file per session) |

**Not committed (per the brief):** model weights (`models/`), audio recordings (`*.wav`), per-phrase voice embeddings, secrets.

**Reproducing the measurements:** the app, the unit tests and the CPU benchmark run from a fresh clone. The ASR/MT experiments, speaker calibration/evaluation and mic replay need **our audio recordings, which are not committed** (they contain people's voices). Their inputs are described in `eval/` and their raw outputs are in `results/`, so the numbers can be checked, and the scripts can be rerun on your own recordings with the same manifest format.
