"""Unit tests for scoring and decoding. Run: .venv\\Scripts\\python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.asr import greedy_ctc_decode  # noqa: E402
from app.metrics import cer, corpus_cer, edit_distance, wer  # noqa: E402
from app.text_norm import normalize_for_scoring  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_in_word_question_mark_is_deleted(self):
        self.assertEqual(normalize_for_scoring("Բարև, ինչպե՞ս ես։"), "բարեւ ինչպես ես")

    def test_yev_variants_match(self):
        self.assertEqual(normalize_for_scoring("Երևան"), normalize_for_scoring("Երեւան"))
        self.assertEqual(normalize_for_scoring("Եվ նա եկավ"), normalize_for_scoring("և նա եկավ"))

    def test_word_containing_ev_is_untouched(self):
        self.assertEqual(normalize_for_scoring("Թևեվ"), "թեւեվ")  # only a standalone "եվ" changes

    def test_spaces_and_case(self):
        self.assertEqual(normalize_for_scoring("  Python   ԼԵԶՈՒ  "), "python լեզու")


class TestMetrics(unittest.TestCase):
    def test_edit_distance(self):
        self.assertEqual(edit_distance("kitten", "sitting"), 3)

    def test_cer_wer(self):
        self.assertAlmostEqual(cer("abcd", "abed"), 0.25)
        self.assertAlmostEqual(wer("a b c d", "a x c"), 0.5)

    def test_corpus_cer_weights_by_length(self):
        self.assertAlmostEqual(corpus_cer(["ab", "abcdefgh"], ["xb", "abcdefgh"]), 0.1)


class TestCtcDecode(unittest.TestCase):
    vocab = {0: "<s>", 1: "<pad>", 2: "</s>", 3: "<unk>", 4: " ", 5: "ա", 6: "բ"}

    def test_merges_repeats_and_drops_blank(self):
        ids = [0, 5, 5, 0, 5, 4, 4, 6, 0, 1, 2, 3]
        text, unk = greedy_ctc_decode(ids, self.vocab, blank_id=0, drop_ids={1, 2}, unk_id=3)
        self.assertEqual(text, "աա բ")
        self.assertEqual(unk, 1)


if __name__ == "__main__":
    unittest.main()
