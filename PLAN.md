# PLAN.md: Live Armenian Transcription → English Translation

Status (2026-10-26, 17:15): **live app working (0 of 22 lines over 5 s in LIVE-03b); confidence filter added; speaker identification is the open problem (mixed phrases, D-031).** For the current state and next steps, see **HANDOVER.md**.

| Milestone | Status |
|---|---|
| M0 plan, docs | ✅ |
| M1 audio capture (Spike 1) | ✅ mic + loopback, 100 % complete, no overflow |
| M2 eval set | 🟡 3 clips + 11 MT sentences (one speaker); more voices + call audio still to do |
| M3 ASR | ✅ omniASR-CTC-300M-v2 int8 (D-014, D-023) |
| M4 MT | ✅ NLLB-600M CT2 int8, beam 1 (D-018) |
| M5 speaker ID | 🟡 integrated (centred tracker, D-026/027); fails on fast cross-talk because of mixed phrases (D-031); window-level evaluation ready to run |
| M6 walking skeleton | ✅ `python -m app.main`, LIVE-01/02 |
| M7 latency + robustness on a real call | ⬜ |
| M8 README, chats export, rehearsal | ⬜ |

*(The plan below is the original from day 1. Section 4's model candidates were superseded by the measurements in EXPERIMENTS.md.)*
Target machine: Windows laptop, Intel Core i5-8250U (4 cores / 8 threads, 15 W, no GPU), 8 GB RAM.

---

## 1. Goal

A Python terminal program that captures **microphone + system audio at the same time**, transcribes spoken **Armenian**, translates it to **English**, and prints one line block per phrase with **time, speaker, HY text, EN text**. It must do this within **≤ 5 s of the end of each phrase**, using **local models only**.

### 1.1 Mandatory requirements (from the brief)

| # | Requirement | Notes |
|---|---|---|
| R1 | Capture mic and system output **simultaneously** | Windows: WASAPI loopback. No virtual cable needed, and the user still hears the call. |
| R2 | User can **pick the input devices** | `--list-devices`, `--mic <id>`, `--loopback <id>` |
| R3 | Armenian speech → Armenian text | Low-resource language. This is the main quality risk. |
| R4 | Each segment translated to English | |
| R5 | Mic is always labelled **Me** | Comes from the source, so no model is needed. |
| R6 | System-audio speakers labelled **Speaker 1, 2, …**, with labels **stable for the session** | Needs online speaker clustering. |
| R7 | Live terminal output: `[hh:mm:ss] Speaker`, `HY: …`, `EN: …` | |
| C1 | **≤ 5 s** from end of phrase to EN line | Measured per segment and logged. |
| C2 | Transcription, translation and speaker ID all **local** | No cloud APIs at runtime. |
| C3 | Python, runs on **this laptop** | |
| C4 | Models chosen deliberately and justified in the README | Based on our own measurements. |

### 1.2 Deliverables
- Git repo containing the source code, a `README.md` (setup + audio setup, model choices + alternatives, architecture, limitations, improvements), and a `chats/` folder with **every** Claude session exported in full, one `.md` per session.
- No model weights, audio recordings or keys in git. `.gitignore` takes care of this from the first commit.
- Supporting docs (per the guidelines): `DECISIONS.md` (decision log), `TESTS.md` (requirement-driven test list), and a project-rules file.

### 1.3 Success criteria (what the interview checks)
1. It starts and runs during a live call with ≥ 2 Armenian speakers on the call side.
2. Armenian is recognised well enough that the English is **understandable**.
3. Each phrase stays **under 5 s** from end of phrase to EN line. We print the measured latency so it can be verified.
4. Speakers are **kept apart**, and labels don't swap mid-session.
5. Code has clean separation: audio / VAD / ASR / translation / speakers / output.
6. The README is honest about limits, and every model choice is backed by numbers from our eval set.
7. The chat history shows planning, measurement and steering.

Out of scope (per the brief, so we won't build it): GUI, installer, echo cancellation, naming speakers, cross-session memory, saving transcripts, non-Armenian input. Spare time goes into **reliability**.

---

## 2. Components (each independently testable)

| Module | Input | Output | Standalone test |
|---|---|---|---|
| `audio_capture` | device ids | stream of `(source, t_start, float32 16 kHz mono chunk)` | Record 10 s from both sources to WAV files. Both are clean, with no dropouts, and you still hear the call. |
| `vad_segmenter` | chunks for one source | `Segment(source, t_start, t_end, audio)` emitted at end of phrase | Feed a WAV with known pauses and check that segment boundaries are within ±0.3 s. Also enforce a max segment length. |
| `asr` | `Segment.audio` | Armenian text (+ timing) | Run on the eval set to get WER/CER, real-time factor and peak RAM. |
| `translate` | Armenian text | English text (+ timing) | Run on reference HY sentences to get readable EN and ms/sentence. |
| `speakers` | loopback segment audio | `"Speaker N"` | Feed labelled multi-speaker clips to measure label purity and the number of speakers created. |
| `pipeline` | segments from both sources | `Result(time, label, hy, en, latency)` | Replay pre-recorded WAVs as if live and check per-segment latency. |
| `output` | `Result` | formatted terminal lines | Unit test of the formatting. |
| `main` / CLI | flags | running app | Manual end-to-end test on a real call. |

Every module has one job, clear I/O, and fails loudly (no silent fallbacks).

---

## 3. Proposed minimal architecture

```
 Mic (WASAPI)  ──► capture thread ──► VAD segmenter (source=Me) ──┐
                                                                   ├─► segment queue ─► ONE worker:
 Loopback      ──► capture thread ──► VAD segmenter (source=Call)─┘     1. ASR (hy)
 (WASAPI)                                                               2. speaker ID (Call only)
                                                                        3. MT hy→en
                                                                        4. print + latency
```

Design choices and why:
- **WASAPI loopback** (e.g. `PyAudioWPatch` or `soundcard`). It captures exactly what plays on the output device, without a virtual cable. To verify in Spike 1: does it work with your default device and call app?
- **Resample to 16 kHz mono** at capture time, since all candidate models expect it.
- **Silero VAD per source**. A phrase ends after ~500–700 ms of silence. We also **force-cut at ~8–10 s** so a long monologue can't blow the latency budget.
- **One processing worker**, not one per source. The CPU has only 4 real cores. Running two model inferences in parallel would make both slower, and it would double RAM. Segments are processed in order of their end time.
- **Speaker ID only on the loopback side**, using a speaker-embedding model plus **online centroid clustering** (cosine similarity: assign to the nearest centroid above a threshold, otherwise create a new speaker). This is language-independent, so Armenian doesn't matter here. Segments shorter than a minimum duration don't create a new speaker.
- **Shared session clock** (monotonic, starting at program start) so timestamps from both sources line up.
- All model calls use **int8 CPU inference** (CTranslate2 / ONNX) where it's available.

### 3.1 Latency budget (end of phrase → EN line ≤ 5 s)

| Stage | Budget |
|---|---|
| VAD end-of-speech wait | 0.5–0.7 s |
| ASR (for a ≤ 8 s phrase) | ≤ 2.5 s |
| Speaker embedding | ≤ 0.3 s |
| Translation | ≤ 0.7 s |
| Queue wait + overhead | ≤ 0.8 s |
| **Total** | **≤ 5 s** |

The queue term is the hidden risk. If Me and a Speaker finish phrases at the same moment, the second one waits for the first one's whole pipeline. So in practice **ASR + MT has to be well under ~2 s per phrase**.

### 3.2 RAM budget (8 GB total)
Windows + call app (+ browser) will likely take 4–5 GB, which leaves **~3 GB for our models**. Rough sizes, to be measured: a large-v3-size ASR in int8 is ~1.5–2 GB, NLLB-600M int8 is ~0.6–1 GB, a speaker embedding model is < 0.1 GB, and VAD is tiny.

---

## 4. Model candidates (to be measured, not assumed)

### 4.1 ASR, the biggest risk

| Candidate | Size | What's known for Armenian | CPU concern |
|---|---|---|---|
| Whisper large-v3 (zero-shot) | 1.55 B | CER ≈ 14–16 % on FLEURS / Common Voice (reported on the BuzzASR card) | Probably too slow on this CPU |
| Whisper large-v3-turbo | ~0.8 B | Armenian quality **unverified** | Faster decoder, so a likely middle ground |
| **BuzzASR/armenian** (full fine-tune of large-v3, MIT) | 1.55 B | Self-reported CER 2.3 % combined (FLEURS WER 11.9 %). Big improvement, but Common Voice is partly in-domain. | Same size as large-v3. Needs a CTranslate2 conversion, and speed is unknown. |
| Whisper small/medium + community fine-tunes | 0.24–0.77 B | Reported WERs of 40–75 %, self-evaluated | Fast, but probably too inaccurate |
| Meta Omnilingual ASR (CTC 300M / 1B) | 0.3–1 B | Covers ~1600 languages. Armenian support and quality **to verify**. | Non-autoregressive (single pass), so potentially much faster |
| Meta MMS-1b-all (CTC, language adapters) | 1 B | Armenian adapter **to verify**. Older model. | Single pass |

Caveat: CTC models usually output no punctuation or casing, and that may hurt translation. We'll test it.

### 4.2 Translation

| Candidate | Notes |
|---|---|
| NLLB-200 distilled 600M (`hye_Armn → eng_Latn`) | Strong low-resource coverage, and CTranslate2 int8 versions exist. License is CC-BY-NC, fine for a challenge but noted in the README. |
| NLLB-200 distilled 1.3B | Better quality, about 2× slower. Only if the budget allows. |
| Opus-MT hy→en (Marian) | Very small and fast. Existence and quality **to verify**. |
| Whisper `task=translate` | Rejected for now. We need both HY and EN, so it would mean two decodes. |

### 4.3 Speaker embeddings
SpeechBrain ECAPA-TDNN (VoxCeleb), WeSpeaker ResNet34 (ONNX, e.g. via sherpa-onnx), or pyannote embedding (gated on Hugging Face). The full pyannote 3.x diarization pipeline is offline and heavy on CPU, so we don't need it. Our VAD segments plus clustering are enough.

---

## 5. Biggest technical risks

| # | Risk | Likelihood / impact | Mitigation | Tested in |
|---|---|---|---|---|
| K1 | **No ASR model is both accurate enough and fast enough on the i5-8250U** | High / critical | Measure early. Options: int8, beam size 1, turbo or CTC models, shorter max segments, fine-tuned large-v3 if it's fast enough. | Spike 3 |
| K2 | **Latency > 5 s when both sources speak at once**, or after long phrases | Medium / high | Single worker with ordered queue, max segment length, per-stage timing log, keep ASR+MT ≪ 2.5 s | Spike 6 |
| K3 | **CPU thermal throttling / power mode** (15 W laptop CPU) makes the interview run slower than the tests | Medium / high | Benchmark under sustained load (10+ min), plugged in, "Best performance" mode. Set the thread count explicitly. | Spikes 3 and 6 |
| K4 | **Speaker confusion**: call-codec audio, short utterances, similar voices, threshold sensitivity, labels splitting or merging | Medium / high | Minimum duration for new speakers, threshold tuned on our own clips, centroid update, test with ≥ 3 real voices through a real call | Spike 5 |
| K5 | **Call-audio quality** (Opus codec, noise) is worse than clean benchmark audio | High / medium | Eval set includes clips recorded **through a real call** via loopback | Spikes 2 and 3 |
| K6 | **RAM pressure** with a call app open → swapping → latency spikes | Medium / high | Measure peak RAM with the call app running. Prefer int8 and smaller models. | Spike 3 |
| K7 | **Translation of imperfect ASR text** is unreadable | Medium / medium | Evaluate MT on ASR output, not only on reference text | Spike 4 |
| K8 | **Overlapping speech** or two speakers in one segment | Medium / low–medium | Documented limitation. Short max segment helps. | Spike 5 |
| K9 | **Speakers instead of headphones**: the mic picks up the call → duplicate "Me" lines | Medium / medium | Echo is out of scope, so use headphones in the interview and document it | Spike 1 |
| K10 | Windows audio quirks: loopback device sample rate (48 kHz stereo), device ids changing, exclusive mode | Medium / medium | Device listing tool, resampling, test with the actual call app | Spike 1 |
| K11 | Model claims (AI or model cards) are wrong or don't apply | Medium / medium | Verify every model on our own eval set before deciding | Spikes 3–5 |

---

## 6. Feasibility-first order (milestones)

Each spike has a **pass criterion** and a **decision gate**. We commit after every working step. Hours add up to roughly 20.

| # | Milestone | ~h | Pass criterion / output |
|---|---|---|---|
| M0 | Repo, `.gitignore`, plan, DECISIONS.md, TESTS.md, project rules | 1 | Reviewed plan, first commit |
| M1 | **Spike 1: audio capture**: list devices, record mic + loopback simultaneously to WAV | 2 | Both WAVs intelligible, no dropouts over 60 s, you still hear the call, sample-rate handling correct |
| M2 | **Eval set**, grown in stages: (a) a few clips recorded by you, of different lengths, including some with English terms; (b) later ≥ 3 voices and clips recorded through a real call. Typed reference text for every clip. Audio stays out of git. | 1.5 | `eval/manifest.csv` with path, speaker, reference text |
| M3 | **Spike 3: ASR benchmark**: 3–4 candidates, CER/WER, real-time factor, peak RAM, sustained-load run | 4 | **Gate:** pick a model with ASR time ≤ ~2 s for a 5 s clip and the best CER. If none qualifies, revisit segment length, model size or approach before going further. |
| M4 | **Spike 4: translation benchmark** on references *and* on ASR output | 1.5 | ≤ 0.7 s per sentence; you judge whether the EN is understandable |
| M5 | **Spike 5: speaker ID** offline on labelled clips: embeddings + online clustering | 2.5 | Same person → same label in ≥ 90 % of segments ≥ 1.5 s, no label explosion, threshold chosen from data |
| M6 | **Walking skeleton**: live mic → VAD → ASR → MT → terminal, then add loopback, then speakers | 3 | Live output for both sources, latency printed per line |
| M7 | **Latency and robustness tuning** under realistic load (call app open, 15-minute run, simultaneous speech) | 2.5 | ≥ 95 % of segments ≤ 5 s, no crashes, no memory growth |
| M8 | README, limitations, chat export, **interview rehearsal** with real people on a call | 2 | Someone else can follow the README. A full rehearsal passes. |

Rule from the guidelines: if something fails three times, go back to the last working commit and narrow it down.

---

## 7. Testing and measurement

- **Accuracy:** CER (primary, more stable for Armenian morphology) and WER on the eval set, with normalisation (punctuation and case removed) defined in code.
- **Latency:** per-segment timestamps for `t_phrase_end`, `t_asr_done`, `t_mt_done` and `t_printed`, logged to the console in debug mode, with p50/p95 reported.
- **Speed:** real-time factor = processing time / audio duration, measured cold and after 10 minutes of warm, sustained load.
- **RAM:** peak RSS per model and for the whole app with the call app open.
- **Speakers:** label purity and number of speakers created vs. true number, on labelled clips and on the live rehearsal.
- **Requirement checklist** in `TESTS.md`, derived from R1–R7 and C1–C4, not from the code.

---

## 8. Answered questions (2026-10-25)

1. **Call app**: not fixed. The solution must work with **any app's Windows system audio** (Zoom, Meet, …). So we capture the output device via WASAPI loopback and depend on no particular app.
2. **Headphones**: yes, in the demo. Echo/feedback stays out of scope.
3. **Language**: Eastern Armenian, with **occasional English words and technical terms**. This goes in the eval set (see M2).
4. **Segmentation**: aim for a balance. Splitting long phrases is allowed, but the **max-segment length is chosen from measurements** of its impact on accuracy, not fixed up front.
5. **Eval data**: start with **your own recordings**. Other voices and real call audio come after the basic transcription pipeline works.
6. **Environment**: Windows, Python 3.12.3, ~65 GB free disk. Git and the Python install still need to be checked on Windows (see DECISIONS.md, D-004).
7. **Power**: plugged in + "Best performance" mode for all benchmarks and the demo.
8. **Packaging**: `venv` + `requirements.txt`.

---

## 9. Sources consulted while planning
- Challenge brief and the vibe-coding guidelines (project docs)
- BuzzASR Armenian model card: https://huggingface.co/BuzzASR/armenian
- BuzzASR paper (Whisper large-v3 fine-tunes, 100+ languages): https://arxiv.org/pdf/2609.09554
- Community small Whisper fine-tunes: https://friendli.ai/models/Edmon02/whisper-small-hy, https://huggingface.co/Chillarmo/checkpoint_9971
- Omnilingual ASR overview: https://soniqo.audio/guides/omnilingual
- PyAudioWPatch (WASAPI loopback): https://pypi.org/project/PyAudioWPatch/0.2.12.1
- Microsoft WASAPI loopback recording: https://learn.microsoft.com/ar-sa/Windows/win32/coreaudio/loopback-recording
- NLLB-600M CTranslate2 int8: https://huggingface.co/pulkitchowdry/nllb-600m-ct2-int8
