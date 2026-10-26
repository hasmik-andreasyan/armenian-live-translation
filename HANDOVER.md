# HANDOVER.md: where we are and what comes next

Last updated: **Mon 2026-10-26, 04:10** (end of day 1). **Deadline: Sun 2026-11-01.**
Read this first in a new session, then DECISIONS.md (why) and EXPERIMENTS.md (numbers).

---

## 1. State in one paragraph

A working live application exists: `python -m app.main`.
- **Pipeline:** captures the mic + system audio at the same time (WASAPI loopback), splits speech into phrases, transcribes Armenian (omniASR-CTC-300M-v2, int8), translates to English (NLLB-600M, CTranslate2 int8, beam 1), and prints `[time] Me/Call`, `HY:`, `EN:` with the measured latency.
- **Live tests:** LIVE-01 had 45 lines, **0 over 5 s**, max 4.4 s. LIVE-02 had 22 lines; 1 over 5 s, caused by deliberate overlapping speech.
- **Missing piece:** **speaker identification** (Speaker 1/2/… on the call side). The module exists (`app/speakers.py`), but the first calibration put every phrase in one speaker. The cause is found (§3), and a fix (centring with a prior) is implemented and unit-tested. It **still needs CAL-02 on real labels**, then integration into the app.

## 2. Start of the next session: exact steps

```powershell
cd $HOME\Desktop\Mathrix-Claude-Project
git add .
git commit -m "Speaker ID: sherpa-onnx embeddings, centred tracker, CAL-01 findings, labelling + calibration tools"
.venv\Scripts\python -m unittest discover tests        # expect: Ran 20 tests ... OK
.venv\Scripts\python tools\label_phrases.py            # ~3 min: label the 25 phrases (1/2/m/?)
.venv\Scripts\python tools\speaker_calibrate.py        # CAL-02: scores settings against the labels
```

Then:
1. Pick the threshold and prior weight from CAL-02, the best F with the right number of speakers. Record it in DECISIONS.md (D-027) and EXPERIMENTS.md.
2. **If no setting works:** analyse `eval/speakers/embeddings.npz` directly. It holds the real embeddings, which is better than the Gram-matrix reconstruction used in CAL-01. Ideas, in order:
   - a better prior (more/other recordings);
   - shorter max segment for the tracker only (pure single-speaker audio);
   - compare to the nearest member instead of the centroid;
   - a different embedding model from the sherpa-onnx release, e.g. `3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx` or `nemo_en_titanet_small`.
3. Integrate into `app/main.py` + `app/pipeline.py`:
   - loopback segment → `SpeakerEmbedder.embed` (~140 ms) → `SpeakerTracker.assign` → label "Speaker N";
   - the mic stays "Me";
   - load `models/speaker/prior_mean.npy`;
   - log the similarity and uncertain flag per line.
4. **LIVE-03:** the same interview video. Do the labels follow the real turns? Is latency still < 5 s?

## 3. The speaker-ID finding (CAL-01): why everything was "Speaker 1"

- **The code worked as designed.** Each phrase's similarity to the running Speaker 1 centroid was ≥ 0.74, above the highest threshold tried (0.70).
- **Root cause:** through one channel, raw embeddings of *different* people are very similar (cosine 0.46–0.94, median 0.77). One shared direction (codec/room/chain) dominates: the top eigenvalue is 19.1 of 25. The centroid, an average, is even more "generic", so phrase 22 (the real change at 124.7 s) scores 0.62 to the previous phrase but 0.82 to the centroid.
- **Centring** (subtracting the mean embedding) reveals the speakers. Phrase 22 vs 18–21 = −0.32…−0.40, and the offline 2-way split switches at 124.7 s, as heard.
- **Online centring needs a stable prior mean**, because the session-only running mean over-splits (up to 17 speakers). This is implemented: `SpeakerTracker(prior_mean=…, prior_weight=…)`, D-026.
- **Unknown:** the full ground truth (hence labelling), and whether 7 s phrases mix two speakers.

## 4. Decisions so far (details in DECISIONS.md)

| ID | Decision |
|---|---|
| D-001/020 | WASAPI loopback via **PyAudioWPatch**, no virtual cable; native rate → 16 kHz mono via **soxr**; one session clock |
| D-002/015 | Headset in the demo (Jabra, mic = MME device 1, loopback = device 16) |
| D-010 | **4 threads** for all models (stable latency; 8 threads had drops to 33 GFLOP/s) |
| D-011 | Whisper family deprioritised: predicted 17–28 s per phrase on this CPU (fixed 30 s window) |
| D-014 | **ASR: omniASR-CTC-300M-v2, int8.** CER 6.3 % on 3 clips; 1.5 s for a 6 s phrase; ~1.0 GB RAM |
| D-018 | **MT: NLLB-200-distilled-600M, CTranslate2 int8, beam 1.** 10/11 understandable on ASR-style input; 0.44 s median; ~0.8 GB |
| D-019 | Priority: working app first, no more broad model comparisons |
| D-021 | Energy VAD (pluggable): end of phrase = 0.6 s of silence, max 7 s, min 0.4 s of speech |
| D-022/024 | One worker thread (ASR → label → MT); latency per line; `--log`; clean double Ctrl+C |
| D-023 | **Armenian-only CTC decoding** (removed Latin/Arabic/CJK drift + MT hallucinations); **cut at the quietest point** of the last 1.5 s |
| D-025/026 | Speaker ID: sherpa-onnx 2.0.0 + WeSpeaker ResNet34-LM (CC-BY-4.0); **centred** online tracker with prior mean. Threshold from CAL-02 |

## 5. Known limitations (for the README)

1. Yes/no questions become statements: the ASR doesn't output `՞` (EXP-02, t03).
2. ASR errors change the meaning ("friends" → "classmates"). ASR is the main quality lever.
3. English terms come out in Armenian letters (`Python` → `փայսոն`). NLLB usually recovers them.
4. Overlapping speech on both sides queues up: one line at 7.0 s in LIVE-02. A single worker on 4 cores.
5. Fast, informal speech (interviews) is clearly worse than read speech.
6. Licenses: NLLB is CC-BY-NC-4.0 (research model); the speaker model is CC-BY-4.0.
7. Echo isn't handled (out of scope); a headset is required.

## 6. Remaining tasks and plan to the deadline (~20 h budget, a large part used on day 1)

| Day | Must do | Done when |
|---|---|---|
| **Tue 27** | Commit. CAL-02 (label + calibrate) → choose settings. **Integrate speaker ID.** LIVE-03 on the interview video. | Call-side lines show stable Speaker 1/2 matching the real turns; latency still < 5 s |
| **Wed 28** | **Real call test** (Zoom/Meet/Telegram, ≥ 2 Armenian speakers on the call side + you). Fix the weakest link only (speaker split/merge, VAD, overlap). | LIVE-04 logged: % lines < 5 s, labels correct, English understandable |
| **Thu 29** | **README.md** (setup incl. audio devices; models chosen + alternatives + why; architecture; limitations; improvements). One consolidated `requirements.txt` (pinned from `pip freeze`). **TESTS.md**: requirement checklist R1–R7, C1–C4 with evidence. | Someone else could install and run it from the README |
| **Fri 30** | **Full rehearsal** on the interview laptop (plugged in, Best performance, headset). **Export every Claude session** to `chats/` (one .md per session, full and unedited). | Rehearsal passes; chats exported |
| **Sat 31** | Buffer: fixes from the rehearsal; push the repo; final check that no weights/audio/keys are committed. | Repo link ready |
| Sun 1 | Submit. | |

**Nice-to-have only if ahead of schedule:**
- English-only MT output vocabulary (faster MT → shorter queue waits).
- Silero VAD instead of the energy VAD.
- A light question-mark/punctuation restoration.

**Cut first if behind:** the nice-to-haves, then extra calibration variants. **Never cut:** the real call test, the README, the chat export.

## 7. Practical notes / gotchas

- **Always use `.venv\Scripts\python`.** Bare `python` is the Microsoft Store alias.
- **Claude can't reach PyPI or Hugging Face** from its workspace or from your laptop's shell (network policy). Dry runs and downloads run in your PowerShell. Claude's shell on your laptop is a **Linux VM** with the project folder mounted: it can read/analyse files, but it doesn't see Windows Python.
- **File sync:** Claude verifies every file it sends with an MD5 comparison. Twice an update arrived stale when an edit and the send were in the same step. **Don't edit a file while Claude is updating it.**
- Audio and models are gitignored (`*.wav`, `models/`, `*.npz`, `*.npy`). `eval/speakers/loopback.wav` is the CAL-02 recording: keep it.
- The model folders under `models/` are pinned (REVISION.txt / SOURCE.txt with hashes). Re-download with `tools/download_model.py`, `tools/prepare_nllb.py` and `tools/download_speaker_model.py`.

## 8. File map

- `app/`
  - `audio.py`: capture
  - `vad.py`: segmenter, `segment_audio`
  - `asr.py`: Armenian-only CTC
  - `translate.py`: NLLB
  - `speakers.py`: embedder + centred tracker
  - `pipeline.py`: threads, latency, log
  - `main.py`: CLI entry point
  - `text_norm.py`, `metrics.py`: scoring
- `benchmarks/`: CPU benchmark, compatibility checks, EXP-01, EXP-02, ratings
- `tools/`: model downloads, `record_clip`, `capture_test`, `label_phrases`, `speaker_calibrate`
- `tests/`: 20 unit tests (text/metrics, VAD, speakers)
- `eval/`: manifests (committed); audio (not committed)
- `results/`: raw JSON/JSONL of every measurement
- `PLAN.md` · `DECISIONS.md` · `EXPERIMENTS.md` · `HANDOVER.md` (this file)
