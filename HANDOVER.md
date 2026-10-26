# HANDOVER.md: where we are and what comes next

Last updated: **Mon 2026-10-26, 17:15** (day 2, afternoon). **Deadline: Sun 2026-11-01.**
Read this first in a new session, then DECISIONS.md (why) and EXPERIMENTS.md (numbers).

---

## 1. State in one paragraph

The live app works end to end: `python -m app.main [--log | --record]`.
- **Pipeline:** mic + system audio (WASAPI loopback) → energy VAD phrases (max 7 s, cut at the quietest point) → Armenian ASR (omniASR-CTC-300M-v2 int8, Armenian-only decoding) → **confidence filter** (< 0.80 → shown as "unclear", not translated) → English MT (NLLB-600M CTranslate2 int8, beam 1, repetition guard) → `[time] Me / Speaker N`, `HY:`, `EN:` with the measured latency.
- **Last recorded run (LIVE-03b):** **0 of 22 lines over 5 s**, max 4.8 s, no lost audio.
- **Microphone:** full sentences and 2-word phrases are recognised well (confidence 0.89–0.98). Isolated single words (< 1 s) are not; this is a model limitation, now flagged as unclear instead of mistranslated.
- **Open problem: speaker identification.** Every call phrase becomes Speaker 1. The diagnosis is that **many 7 s phrases contain both speakers** (8/14 and 11/25 in the labelled recordings), so the first speaker's centroid is a blend that matches everyone. A window-level fix is designed and the **evaluation script is written, but not run yet**.

## 2. Next session: exact steps

```powershell
cd $HOME\Desktop\Mathrix-Claude-Project
git add .
git commit -m "D-030 confidence filter; LIVE-03b analysis; speaker window-level evaluation tool; handover"
.venv\Scripts\python -m unittest discover tests     # expect: Ran 20 tests ... OK
.venv\Scripts\python tools\speaker_eval.py          # 2-4 min: phrase vs window-level speaker ID on both labelled recordings
```

Then:
1. **Read the speaker_eval table** (`results/spk_eval_*.json`). It compares the current method (one embedding per phrase) with 1.5 / 2 / 3 s windows (the phrase label = majority of window labels), 2 prior weights × 5 thresholds, on both labelled recordings. The prior always comes from the *other* recordings. The last row is the current live setting.
2. **If a window setting clearly beats the current one on BOTH recordings:** implement it in `CallSpeakerLabeler` (`app/speakers.py`). Embed the windows of each loopback segment, assign them to the tracker, majority vote. Watch the latency: +0.2–0.4 s per call line. Then run **one short live check** with `--record`.
3. **If not:** decide together. Options:
   - document speaker ID as a limitation for fast cross-talk;
   - shorter max phrase on the call side only (cleaner embeddings, but less ASR/MT context);
   - another embedding model from sherpa-onnx (e.g. `3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx`).

   Note: a **real call with turn-taking** (pauses between speakers) has far fewer mixed phrases than a podcast video. The real-call test is the decisive one.
4. **Real call test (LIVE-04)** with ≥ 2 Armenian speakers on the call side, using `--record`. Label the call phrases afterwards (`tools/label_phrases.py --wav results\session_..._loopback.wav --out eval\speakers\labels_call.json`).

## 3. Key findings (details in EXPERIMENTS.md)

| Topic | Finding |
|---|---|
| CPU | 4 threads stable (~145 GFLOP/s sustained); memory bandwidth only ~10 GB/s |
| ASR | omniASR-CTC-300M-v2 int8: CER 6.3 % on 3 clips, ~1.5 s per 6 s phrase, ~1.0 GB. Armenian-only decoding removed foreign-script drift (LIVE-01 → LIVE-02) |
| ASR confidence | correct ≥ 0.89, garbage ≤ 0.72 → filter at 0.80 (D-030). Padding short words doesn't help |
| MT | NLLB-600M CT2 int8 beam 1: 10/11 understandable (human-rated), 0.44 s median, ~0.8 GB. A repetition loop once took 14.4 s → fixed with a length cap + no-repeat-4-grams (D-029) |
| Latency | LIVE-01 max 4.4 s, LIVE-02 1 line at 7.0 s (overlapping speech), LIVE-03 17.5 s (MT loop, fixed), **LIVE-03b max 4.8 s, 0 over 5 s** |
| Speaker ID | Raw cosine can't separate speakers on one channel (all 0.46–0.94) → centring with a prior (D-026). CAL-02 perfect on 14 labelled phrases at w = 30 / th = 0.10, **but a new video fails because of mixed phrases** (D-031) |

## 4. Decisions so far (details in DECISIONS.md)

| ID | Decision |
|---|---|
| D-001/020 | WASAPI loopback via PyAudioWPatch; soxr resampling to 16 kHz mono; one session clock |
| D-002/015 | Headset (Jabra): mic = MME device 1, loopback = device 16 |
| D-010 | 4 threads for all models |
| D-011 | Whisper family deprioritised (too slow on this CPU) |
| D-014 | ASR: omniASR-CTC-300M-v2 int8 |
| D-018 | MT: NLLB-600M CTranslate2 int8, beam 1 |
| D-019 | Working app first, no broad model comparisons |
| D-021 | Energy VAD: 0.6 s end of phrase, max 7 s, min 0.4 s of speech |
| D-022/024/028 | One worker thread; latency per line; `--log`; clean double Ctrl+C; **a crashed thread stops the app loudly** |
| D-023 | Armenian-only CTC decoding; cut at the quietest point |
| D-025/026/027 | Speaker ID: sherpa-onnx + WeSpeaker ResNet34-LM; centred tracker with prior (w = 30, th = 0.10, `--speaker-threshold`) |
| D-029 | MT repetition guard; diagnostics (`--record`, every phrase logged, capture overflow stats) |
| D-030 | Confidence < 0.80 → "unclear", not translated (`--min-confidence`) |
| D-031 | Speaker ID: mixed phrases are the problem; window-level embeddings to be evaluated (**open**) |

## 5. Known limitations (for the README)

1. Isolated single words (< ~1 s) aren't recognised; they're shown as unclear (D-030).
2. Yes/no questions become statements: the ASR doesn't output `՞`.
3. ASR errors can change the meaning ("friends" → "classmates"); ASR is the main quality lever.
4. English terms come out in Armenian letters (`Python` → `փայսոն`); NLLB usually recovers them.
5. Overlapping speech on both sides queues up (single worker, 4 cores).
6. **Speaker ID degrades with fast cross-talk** (mixed phrases), status depending on D-031.
7. Licenses: NLLB CC-BY-NC-4.0 (research model); speaker model CC-BY-4.0.
8. No echo handling (out of scope); a headset is required.

## 6. Plan to the deadline

| Day | Must do | Done when |
|---|---|---|
| **Tue 27** | speaker_eval → decide/implement the speaker fix → short live check. **Real call test (LIVE-04)** if people are available | Speaker labels are acceptable on real turn-taking, or the limitation is documented with evidence |
| **Wed 28** | Real call test (if not done). Fix only the weakest link. Start the README | LIVE-04 logged: % lines < 5 s, labels vs truth, English understandable |
| **Thu 29** | **README.md** (setup incl. audio devices; models + alternatives + why; architecture; limitations; improvements). One pinned `requirements.txt` (`pip freeze`). **TESTS.md** (requirements R1–R7, C1–C4 → evidence) | Someone else can install and run it from the README |
| **Fri 30** | Full rehearsal (plugged in, Best performance, headset). **Export ALL Claude sessions to `chats/`** (one .md per session, full and unedited) | Rehearsal passes; chats exported |
| **Sat 31** | Buffer; push the repo; check that no weights/audio/keys are committed | Repo link ready |
| Sun 1 | Submit | |

Cut first if behind: extra speaker variants, the nice-to-haves (English-only MT vocabulary, Silero VAD). **Never cut:** the real call test, the README, the chat export.

## 7. Practical notes / gotchas

- **Always use `.venv\Scripts\python`** (bare `python` is the Microsoft Store alias).
- **Claude can't reach PyPI or Hugging Face** from its side. Installs and downloads run in your PowerShell. Claude's shell on your laptop is a **Linux VM** (it can read/analyse files and has numpy, but no Windows Python, torch or sherpa).
- **File sync:** Claude verifies every file it sends with MD5. Updates have arrived stale a few times when an edit and the send happened together; Claude re-sends until the checksums match. Don't edit a file while Claude is updating it.
- **Useful tools:**
  - `--record` (session audio + log);
  - `tools/replay_mic.py` (offline ASR on recorded audio);
  - `tools/label_phrases.py` (speaker ground truth);
  - `tools/speaker_calibrate.py`, `tools/speaker_eval.py` (speaker settings vs labels).
- **Audio, models and embeddings are gitignored** (`*.wav`, `models/`, `*.npz`, `*.npy`). Keep `eval/speakers/loopback.wav` and `results/session_20261026_164715_*.wav`: they're the labelled speaker data.

## 8. File map

- `app/`
  - `audio.py`: capture
  - `vad.py`: segmenter, `segment_audio`
  - `asr.py`: Armenian-only CTC + confidence
  - `translate.py`: NLLB + repetition guard
  - `speakers.py`: embedder, centred tracker, `CallSpeakerLabeler`
  - `pipeline.py`: threads, confidence filter, logging
  - `recorder.py`: `--record`
  - `main.py`: CLI
  - `text_norm.py`, `metrics.py`
- `benchmarks/`: CPU benchmark, compatibility checks, EXP-01, EXP-02, ratings
- `tools/`: model downloads, `record_clip`, `capture_test`, `label_phrases`, `speaker_calibrate`, `speaker_eval`, `replay_mic`
- `tests/`: 20 unit tests
- `eval/`: manifests + speaker labels (committed); audio (not committed)
- `results/`: raw JSON/JSONL of every measurement
- `PLAN.md` · `DECISIONS.md` (D-001…D-031) · `EXPERIMENTS.md` · `HANDOVER.md`
