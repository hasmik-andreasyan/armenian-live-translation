"""SpeakerTracker tests with synthetic embeddings. Run: .venv\\Scripts\\python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.speakers import SpeakerTracker, unit  # noqa: E402

RNG = np.random.default_rng(1)
DIM = 256


def voice() -> np.ndarray:
    return unit(RNG.standard_normal(DIM))


def sample(center: np.ndarray, noise: float = 0.6) -> np.ndarray:
    """An utterance embedding near `center` (cosine to center ≈ 0.85)."""
    return center + noise * RNG.standard_normal(DIM) / np.sqrt(DIM)


class TestSpeakerTracker(unittest.TestCase):
    def test_two_speakers_keep_their_labels_raw(self):
        a, b = voice(), voice()
        t = SpeakerTracker(threshold=0.5)
        labels = [t.assign(sample(v), 3.0).label for v in (a, b, a, a, b, a, b, b)]
        self.assertEqual(labels, ["Speaker 1", "Speaker 2", "Speaker 1", "Speaker 1",
                                  "Speaker 2", "Speaker 1", "Speaker 2", "Speaker 2"])

    def test_shared_channel_needs_centring(self):
        # Like CAL-01: a strong shared "channel" direction makes two people look alike in raw space.
        channel = voice()
        a, b = unit(3 * channel + voice()), unit(3 * channel + voice())
        seq = (a, b, a, b, b, a, a, b)
        raw = SpeakerTracker(threshold=0.7)
        self.assertEqual(len({raw.assign(sample(v, 0.15), 3.0).label for v in seq}), 1)   # merged
        prior = unit(3 * channel)                       # prior mean ≈ the shared direction
        cen = SpeakerTracker(threshold=0.0, prior_mean=prior, prior_weight=30)
        labels = [cen.assign(sample(v, 0.15), 3.0).label for v in seq]
        self.assertEqual(labels, ["Speaker 1", "Speaker 2", "Speaker 1", "Speaker 2",
                                  "Speaker 2", "Speaker 1", "Speaker 1", "Speaker 2"])

    def test_short_unclear_segment_does_not_create_a_speaker(self):
        a = voice()
        t = SpeakerTracker(threshold=0.5, min_new_speech_s=1.0)
        t.assign(sample(a), 3.0)
        m = t.assign(voice(), 0.6)            # unlike anyone, but too short to trust
        self.assertEqual((m.label, m.uncertain, len(t.counts)), ("Speaker 1", True, 1))

    def test_max_speakers_cap(self):
        t = SpeakerTracker(threshold=0.9, max_speakers=3)
        for _ in range(6):
            t.assign(voice(), 3.0)
        self.assertEqual(len(t.counts), 3)


if __name__ == "__main__":
    unittest.main()
