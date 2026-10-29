# TESTS.md: requirements → evidence

Each requirement from the challenge brief is checked against **measured evidence** (EXPERIMENTS.md, raw files in `results/`), not against the code.
Status: ✅ met · 🟡 met with documented limits · ⬜ pending.

## Functional requirements

| # | Requirement (brief) | How it's tested | Evidence | Status |
|---|---|---|---|---|
| R1 | Capture the microphone **and** system output **at the same time** | `tools/capture_test.py`: 30 s of both, completeness/gaps/overflow; listened to both WAVs | Spike 1: both 100 % complete, max gap 0.06 s, no overflow; the mic shows no call audio (−64 dBFS while the video plays); playback normal. All live sessions: no overflow (LIVE-03b, LIVE-04a) | ✅ |
| R2 | The user can **pick the input devices** | `--list-devices`, `--mic N`, `--loopback N` (a non-loopback device is rejected) | Manual check; defaults = Windows default input + loopback of the default output | ✅ |
| R3 | Spoken Armenian → Armenian text | EXP-01 (CER vs reference), live replay vs what was actually said | EXP-01: CER 6.3 % (int8). LIVE-03b: all sentences correct, confidence 0.87–0.98. **Isolated words < 1 s fail** (shown as unclear, D-030) | 🟡 |
| R4 | Each segment translated to English | EXP-02: 11 sentences × 3 input variants, blind human rating | 10/11 understandable on ASR-style input; failures: lost question marking, ASR errors propagate | 🟡 |
| R5 | Mic is labelled **Me** | Code path (`CallSpeakerLabeler`: mic → "Me") + every live log | All `mic` lines in all session logs are `Me` | ✅ |
| R6 | System-audio speakers → **Speaker 1, 2, …**, stable for the session | Phrase-level human labels on 3 recordings; balanced accuracy | SPK-EVAL2: mean 0.90, worst 0.79, 2–3 speakers found for 2. Mixed phrases get one label; a new person's first phrase keeps the previous label | 🟡 |
| R7 | Live output: time, speaker, Armenian, English | Every live session | Format `[hh:mm:ss] Label (latency)`, `HY:`, `EN:` | ✅ |

## Constraints

| # | Constraint | How it's tested | Evidence | Status |
|---|---|---|---|---|
| C1 | **≤ 5 s** from the end of a phrase to the English line | Latency measured per line on the session clock; summary prints median / p95 / max / count over 5 s | LIVE-01: 0/45 over 5 s (max 4.4). LIVE-03b: 0/22 (max 4.8). LIVE-04a: 1/23 (5.2 s). LIVE-02: 1 line at 7.0 s when **both sides spoke at once** (documented limitation) | 🟡 |
| C2 | Transcription, translation, speaker ID **run locally** | All models load from local folders (`local_files_only=True`, CTranslate2/sherpa local paths) | No network needed after the one-time download | ✅ |
| C3 | Python, runs on **this laptop** | All measurements on the i5-8250U / 8 GB / Windows 10 | RAM for all models ≈ 2 GB; 4 threads | ✅ |
| C4 | Models chosen deliberately, explained | README §3, DECISIONS.md | Every choice backed by a measurement on this laptop | ✅ |

## Robustness checks (our own)

| Check | Evidence | Status |
|---|---|---|
| No crash on garbage / noise input | Segments with < 2 characters are skipped (logged); confidence filter; Armenian-only decoding | ✅ |
| MT can't stall the pipeline | Repetition guard (D-029); after it: LIVE-03b max 4.8 s | ✅ |
| A crashed thread is visible | `FATAL` banner + clean stop + exit code 1 (D-028; simulated) | ✅ |
| Ctrl+C / double Ctrl+C clean | D-024, simulated + used live | ✅ |
| Unit tests | `python -m unittest discover tests`: 21 tests (normalisation, CER/WER, CTC decode, Armenian token mask, VAD incl. quiet-point cut and gaps, speaker tracker incl. centring and confirmation) | ✅ |

## Pending before submission

| Check | Why | Status |
|---|---|---|
| **LIVE-04: real call** (Zoom/Meet/Telegram) with ≥ 2 Armenian speakers on the call side + the user | The only independent test of speaker ID (all labelled recordings were used for tuning), and the closest to the interview | ⬜ |
| **Fresh-clone install** following the README on this laptop (new folder) | Proves the setup instructions and the committed prior work | ⬜ |
| **Rehearsal** under demo conditions (plugged in, Best performance, headset, call app running) | Latency and RAM with the call app open | ⬜ |
