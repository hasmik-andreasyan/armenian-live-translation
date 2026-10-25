"""Segmenter tests on synthetic audio. Run: .venv\\Scripts\\python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.vad import SAMPLE_RATE, Segmenter  # noqa: E402

RNG = np.random.default_rng(0)


def noise(seconds: float, dbfs: float) -> np.ndarray:
    return (RNG.standard_normal(int(seconds * SAMPLE_RATE)) * 10 ** (dbfs / 20)).astype(np.float32)


def feed(seg: Segmenter, audio: np.ndarray, t0: float = 0.0, chunk_s: float = 0.05) -> list:
    out, step = [], int(chunk_s * SAMPLE_RATE)
    for i in range(0, len(audio), step):
        out += seg.push(t0 + i / SAMPLE_RATE, audio[i:i + step])
    return out + seg.flush()


class TestSegmenter(unittest.TestCase):
    def test_one_phrase_with_boundaries(self):
        audio = np.concatenate([noise(1, -68), noise(2, -25), noise(1.5, -68)])
        segs = feed(Segmenter("mic"), audio)
        self.assertEqual(len(segs), 1)
        s = segs[0]
        self.assertAlmostEqual(s.t_start, 1.0 - 0.3, delta=0.15)   # includes ~0.3 s preroll
        self.assertAlmostEqual(s.t_end, 3.0, delta=0.1)
        self.assertFalse(s.forced_cut)

    def test_two_phrases(self):
        audio = np.concatenate([noise(0.5, -68), noise(1, -25), noise(1, -68), noise(1, -25), noise(1, -68)])
        self.assertEqual(len(feed(Segmenter("mic"), audio)), 2)

    def test_short_blip_is_dropped(self):
        audio = np.concatenate([noise(1, -68), noise(0.15, -25), noise(1, -68)])
        self.assertEqual(feed(Segmenter("mic"), audio), [])

    def test_long_speech_is_force_cut(self):
        audio = np.concatenate([noise(0.5, -68), noise(10, -25), noise(1, -68)])
        segs = feed(Segmenter("mic", max_segment_s=7.0), audio)
        self.assertEqual(len(segs), 2)
        self.assertTrue(segs[0].forced_cut)
        self.assertLessEqual(len(segs[0].audio) / SAMPLE_RATE, 7.05)
        self.assertAlmostEqual(segs[1].t_end, 10.5, delta=0.1)

    def test_forced_cut_lands_in_the_quiet_dip(self):
        # 10 s of speech with a short quiet dip (0.2 s, too short to end a phrase) at 6.0 s
        audio = np.concatenate([noise(0.5, -68), noise(5.5, -25), noise(0.2, -40), noise(4.3, -25), noise(1, -68)])
        segs = feed(Segmenter("mic", max_segment_s=7.0), audio)
        self.assertEqual(len(segs), 2)
        self.assertTrue(segs[0].forced_cut)
        self.assertAlmostEqual(segs[0].t_end, 6.1, delta=0.15)       # inside the dip, not at 7 s
        self.assertAlmostEqual(segs[1].t_start, segs[0].t_end, delta=0.05)  # no audio lost between parts

    def test_timestamp_gap_ends_phrase(self):
        seg = Segmenter("loopback")
        out = feed(seg, np.concatenate([noise(0.5, -68), noise(1.5, -25)]))  # flush ends it
        self.assertEqual(len(out), 1)
        seg2 = Segmenter("loopback")
        out2 = []
        out2 += [s for i in range(0, 32000, 800) for s in seg2.push(i / SAMPLE_RATE, noise(0.05, -25))]
        out2 += seg2.push(10.0, noise(0.05, -68))     # 8 s jump in time
        self.assertEqual(len(out2), 1)

    def test_digital_silence_never_speech(self):
        self.assertEqual(feed(Segmenter("loopback"), np.zeros(SAMPLE_RATE * 3, dtype=np.float32)), [])


if __name__ == "__main__":
    unittest.main()
