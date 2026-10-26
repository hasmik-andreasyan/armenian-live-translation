"""SPK-EVAL: phrase-level vs window-level speaker embeddings, on all labelled recordings.

Problem (D-031): in fast dialogue many 7 s phrases contain BOTH speakers
(CAL-02: 11 of 25; session 2: 8 of 14). One embedding per phrase is then a
blend of two voices, the first speaker's centroid becomes "interviewer + guest",
and everyone matches it.

Candidate fix: embed shorter windows inside each phrase, run the online
tracker over the windows in time order, and label the phrase with the
majority of its (confident) window labels.

For every labelled recording:
  - prior = mean embedding of the OTHER recordings (+ the earlier capture and
    the EXP-01 clips), never the recording itself (honest);
  - methods: phrase-level (as now) and window-level with W = 1.5 / 2 / 3 s;
  - thresholds × prior weights; scored on the phrases you labelled 1-9
    (mixed and "?" are ignored) → speakers found, purity, coverage, F.
Prints the best settings per recording and on average.

Usage:
    .venv\\Scripts\\python tools\\speaker_eval.py
"""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.speakers import SpeakerEmbedder, SpeakerTracker  # noqa: E402
from app.vad import SAMPLE_RATE, segment_audio  # noqa: E402
from speaker_calibrate import score  # noqa: E402  (same purity/coverage/F as CAL-02)

MODEL = ROOT / "models" / "speaker" / "wespeaker_en_voxceleb_resnet34_LM.onnx"
RECORDINGS = [("interview (CAL-02)", "eval/speakers/loopback.wav", "eval/speakers/labels.json"),
              ("session 2 (LIVE-03b)", "results/session_20261026_164715_loopback.wav", "eval/speakers/labels_session2.json")]
EXTRA_PRIOR = ["eval/capture/loopback.wav", "eval/audio/clip01.wav", "eval/audio/clip02.wav", "eval/audio/clip03.wav"]
WINDOWS = [None, 1.5, 2.0, 3.0]                  # None = one embedding per phrase (current method)
THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.4]
PRIOR_WEIGHTS = [10, 30]


def windows_of(audio: np.ndarray, w: float) -> list[np.ndarray]:
    """Non-overlapping windows of w seconds; a remainder shorter than w/2 joins the last window."""
    n = int(w * SAMPLE_RATE)
    parts = [audio[i:i + n] for i in range(0, len(audio), n)]
    if len(parts) > 1 and len(parts[-1]) < n // 2:
        tail = parts.pop()
        parts[-1] = np.concatenate([parts[-1], tail])
    return parts


def load(embedder, wav: Path) -> list[dict]:
    audio, sr = sf.read(wav, dtype="float32")
    if sr != SAMPLE_RATE or audio.ndim != 1:
        raise SystemExit(f"{wav}: need 16 kHz mono")
    phrases = []
    for s in segment_audio(audio, "loopback"):
        item = {"key": f"{s.t_start:.2f}-{s.t_end:.2f}", "speech_s": s.speech_s, "phrase": None, "win": {}}
        try:
            item["phrase"] = embedder.embed(s.audio)[0]
        except ValueError:
            continue
        for w in WINDOWS[1:]:
            embs = []
            for part in windows_of(s.audio, w):
                try:
                    embs.append(embedder.embed(part)[0])
                except ValueError:
                    pass
            item["win"][w] = embs
        phrases.append(item)
    return phrases


def run(phrases: list[dict], w, th: float, prior: np.ndarray, pw: float) -> list[str]:
    tracker = SpeakerTracker(threshold=th, prior_mean=prior, prior_weight=pw)
    labels = []
    for p in phrases:
        if w is None:
            labels.append(tracker.assign(p["phrase"], p["speech_s"]).label.split()[-1])
            continue
        votes = Counter()
        for e in p["win"][w]:
            m = tracker.assign(e, speech_s=w)          # a full window counts as w seconds of speech
            if not m.uncertain:
                votes[m.label.split()[-1]] += 1
        labels.append(votes.most_common(1)[0][0] if votes else "?")
    return labels


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    embedder = SpeakerEmbedder(MODEL)
    data = {}
    for name, wav, lab in RECORDINGS:
        phrases = load(embedder, ROOT / wav)
        raw = json.loads((ROOT / lab).read_text(encoding="utf-8"))["labels"]
        missing = [p["key"] for p in phrases if p["key"] not in raw]
        if missing:
            raise SystemExit(f"{lab} doesn't match the phrases of {wav} ({len(missing)} missing)")
        truth = [raw[p["key"]] if raw[p["key"]].isdigit() else None for p in phrases]
        data[name] = (phrases, truth)
        print(f"{name}: {len(phrases)} phrases, labels {Counter(raw[p['key']] for p in phrases)}")
    extra = []
    for w in EXTRA_PRIOR:
        audio, _ = sf.read(ROOT / w, dtype="float32")
        for s in segment_audio(audio, "loopback"):
            try:
                extra.append(embedder.embed(s.audio)[0])
            except ValueError:
                pass

    results = []
    for w in WINDOWS:
        for pw in PRIOR_WEIGHTS:
            for th in THRESHOLDS:
                row = {"window_s": w, "prior_weight": pw, "threshold": th}
                fs = []
                for name, (phrases, truth) in data.items():
                    others = [p["phrase"] for n2, (ph2, _) in data.items() if n2 != name for p in ph2]
                    prior = np.mean(np.stack(others + extra), axis=0)
                    pred = run(phrases, w, th, prior, pw)
                    sc = score(pred, truth)
                    row[name] = {**sc, "labels": "".join(pred)}
                    fs.append(sc["F"])
                row["mean_F"] = round(float(np.mean(fs)), 3)
                results.append(row)
    results.sort(key=lambda r: -r["mean_F"])

    names = list(data)
    print("\ntruth:  " + "   ".join(f"{n}: {''.join(t or '.' for t in data[n][1])}" for n in names))
    print(f"\n{'window':>6s} {'w':>3s} {'thr':>4s}  {'meanF':>5s}   " + "   ".join(f"{n[:22]:22s}" for n in names))
    for r in results[:15] + [r for r in results if r["window_s"] is None and r["prior_weight"] == 30 and r["threshold"] == 0.1]:
        cells = "   ".join(f"F {r[n]['F']:.2f} found {r[n]['speakers_found']} {r[n]['labels']}" for n in names)
        print(f"{str(r['window_s'] or 'phrase'):>6s} {r['prior_weight']:3d} {r['threshold']:4.1f}  {r['mean_F']:5.2f}   {cells}")
    print("(last row = current live setting: phrase-level, w=30, th=0.10)")
    out = ROOT / "results" / f"spk_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"recordings": RECORDINGS, "results": results}, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
