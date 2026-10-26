"""Optional session recording for diagnostics (`python -m app.main --record`).

Writes what each source delivered (16 kHz mono, after resampling) to
results/session_<timestamp>_<source>.wav, which is gitignored like all audio. Gaps in a
stream (WASAPI loopback can pause) are filled with silence, so that file
time = session time and the WAVs line up with the timestamps in the session log.
"""

from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


class SessionRecorder:
    def __init__(self, base: Path, sources: list[str]) -> None:
        import soundfile as sf

        self.paths = {s: base.with_name(f"{base.name}_{s}.wav") for s in sources}
        self._files = {s: sf.SoundFile(p, "w", samplerate=SAMPLE_RATE, channels=1, subtype="PCM_16")
                       for s, p in self.paths.items()}
        self._written = {s: 0 for s in sources}       # samples written so far

    def write(self, source: str, t_start: float, samples: np.ndarray) -> None:
        start = max(int(round(t_start * SAMPLE_RATE)), 0)
        gap = start - self._written[source]
        if gap > SAMPLE_RATE // 10:                   # > 100 ms missing: fill with silence
            self._files[source].write(np.zeros(gap, dtype=np.float32))
            self._written[source] += gap
        self._files[source].write(samples)
        self._written[source] += len(samples)

    def close(self) -> None:
        for f in self._files.values():
            f.close()
