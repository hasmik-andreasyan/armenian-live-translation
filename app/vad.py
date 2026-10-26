"""Voice activity detection and phrase segmentation (one Segmenter per source).

Input:  AudioChunk(source, t_start, samples) at 16 kHz, in time order.
Output: Segment(source, t_start, t_end, audio, forced_cut) when a phrase ends.

A phrase starts after `start_frames` consecutive speech frames, keeping
`preroll_s` of audio before it. It ends after `end_silence_s` of silence, or,
on reaching `max_segment_s` (D-014: the ASR budget allows ~7-8 s), is cut at
the quietest frame of the last `cut_lookback_s`, so it rarely cuts mid-word.
Segments with less than `min_speech_s` of speech are dropped. A gap in the
timestamps longer than `gap_s` counts as silence (WASAPI loopback can pause).

The frame classifier is pluggable: EnergyVad (default, no dependency) decides
speech vs. silence by loudness relative to an adaptive noise floor. A trained
VAD (e.g. Silero) can replace it with the same `(frame) -> bool` interface.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

SAMPLE_RATE = 16000
FRAME = 480                      # 30 ms
FRAME_S = FRAME / SAMPLE_RATE


@dataclass
class Segment:
    source: str
    t_start: float               # session time of the first sample
    t_end: float                 # session time where speech ended
    audio: np.ndarray            # float32 mono 16 kHz
    forced_cut: bool = False
    speech_s: float = 0.0
    meta: dict = field(default_factory=dict)


def segment_audio(audio: np.ndarray, source: str = "file", max_segment_s: float = 7.0) -> list[Segment]:
    """Split a whole recording exactly as the live app would (deterministic)."""
    seg = Segmenter(source, max_segment_s=max_segment_s)
    out: list[Segment] = []
    for i in range(0, len(audio), 800):          # 50 ms chunks, like the capture callbacks
        out += seg.push(i / SAMPLE_RATE, audio[i:i + 800])
    return out + seg.flush()


class EnergyVad:
    """Speech if the frame is `margin_db` above an adaptive noise floor and above `min_db`."""

    def __init__(self, margin_db: float = 15.0, min_db: float = -55.0, floor_rise_db_per_s: float = 1.0) -> None:
        self.margin_db = margin_db
        self.min_db = min_db
        self.rise = floor_rise_db_per_s * FRAME_S
        self.floor = -70.0

    def __call__(self, frame: np.ndarray) -> bool:
        db = 20 * np.log10(float(np.sqrt(np.mean(frame ** 2))) + 1e-12)
        db = max(db, -90.0)
        # the floor falls immediately to quieter frames and rises slowly otherwise
        self.floor = db if db < self.floor else self.floor + self.rise
        return db > max(self.floor + self.margin_db, self.min_db)


class Segmenter:
    def __init__(self, source: str, is_speech: Callable[[np.ndarray], bool] | None = None,
                 start_frames: int = 3, end_silence_s: float = 0.6, max_segment_s: float = 7.0,
                 min_speech_s: float = 0.4, preroll_s: float = 0.3, tail_s: float = 0.15, gap_s: float = 0.5,
                 cut_lookback_s: float = 1.5) -> None:
        self.cut_lookback_frames = round(cut_lookback_s / FRAME_S)
        self.source = source
        self.is_speech = is_speech or EnergyVad()
        self.start_frames = start_frames
        self.end_silence_frames = round(end_silence_s / FRAME_S)
        self.max_frames = round(max_segment_s / FRAME_S)
        self.min_speech_frames = round(min_speech_s / FRAME_S)
        self.tail_frames = round(tail_s / FRAME_S)
        self.gap_s = gap_s
        self._buf = np.zeros(0, dtype=np.float32)
        self._buf_t: float | None = None           # session time of _buf[0]
        self._preroll: deque = deque(maxlen=round(preroll_s / FRAME_S) + start_frames)
        self._reset_phrase()

    def _reset_phrase(self) -> None:
        self._in_speech = False
        self._frames: list[tuple[float, np.ndarray, bool]] = []
        self._voiced_run = 0
        self._silence_run = 0

    def push(self, t_start: float, samples: np.ndarray) -> list[Segment]:
        out: list[Segment] = []
        if self._buf_t is not None:
            expected = self._buf_t + len(self._buf) / SAMPLE_RATE
            if t_start - expected > self.gap_s:      # a gap in the stream counts as silence
                out += self._finish(forced=False)
                self._buf, self._buf_t = np.zeros(0, dtype=np.float32), None
                self._preroll.clear()
        if self._buf_t is None:
            self._buf_t = t_start
        self._buf = np.concatenate([self._buf, samples.astype(np.float32, copy=False)])
        n = len(self._buf) // FRAME
        for i in range(n):
            frame = self._buf[i * FRAME:(i + 1) * FRAME]
            out += self._step(self._buf_t + i * FRAME_S, frame)
        self._buf = self._buf[n * FRAME:]
        self._buf_t += n * FRAME_S
        return out

    def flush(self) -> list[Segment]:
        return self._finish(forced=False)

    def _step(self, t: float, frame: np.ndarray) -> list[Segment]:
        voiced = self.is_speech(frame)
        if not self._in_speech:
            self._preroll.append((t, frame, voiced))
            self._voiced_run = self._voiced_run + 1 if voiced else 0
            if self._voiced_run >= self.start_frames:
                self._in_speech = True
                self._frames = list(self._preroll)
                self._preroll.clear()
                self._silence_run = 0
            return []
        self._frames.append((t, frame, voiced))
        self._silence_run = 0 if voiced else self._silence_run + 1
        if self._silence_run >= self.end_silence_frames:
            return self._finish(forced=False)
        if len(self._frames) >= self.max_frames:
            return self._cut_at_quietest()
        return []

    def _cut_at_quietest(self) -> list[Segment]:
        """Phrase hit max length: cut at the quietest frame in the last `cut_lookback_s`
        (usually a short pause between words) instead of mid-word at exactly max length.
        The frames after the cut start the next part, still in speech."""
        frames = self._frames
        lo = max(len(frames) - self.cut_lookback_frames, self.min_speech_frames)
        energies = [float(np.mean(f[1] ** 2)) for f in frames[lo:]]
        cut = lo + int(np.argmin(energies))          # last frame of the first part
        first, rest = frames[: cut + 1], frames[cut + 1:]
        self._frames = first
        segs = self._finish(forced=True)
        self._in_speech = True
        self._frames = rest
        self._silence_run = 0
        return segs

    def _finish(self, forced: bool) -> list[Segment]:
        frames = self._frames
        self._reset_phrase()
        if not frames:
            return []
        voiced_idx = [i for i, f in enumerate(frames) if f[2]]
        if len(voiced_idx) < self.min_speech_frames:
            return []
        last = len(frames) - 1 if forced else min(voiced_idx[-1] + self.tail_frames, len(frames) - 1)
        kept = frames[: last + 1]
        t_end = frames[voiced_idx[-1]][0] + FRAME_S if not forced else kept[-1][0] + FRAME_S
        return [Segment(self.source, kept[0][0], t_end, np.concatenate([f[1] for f in kept]),
                        forced_cut=forced, speech_s=round(len(voiced_idx) * FRAME_S, 2))]
