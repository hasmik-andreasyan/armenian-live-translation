"""Character and word error rates (pure Python, no dependency).

CER = edit distance between character sequences / number of reference characters
      (spaces count as characters).
WER = edit distance between word sequences / number of reference words.
Corpus versions sum edits and lengths over all clips: longer clips weigh more.
"""

from typing import Sequence


def edit_distance(ref: Sequence, hyp: Sequence) -> int:
    """Levenshtein distance (substitutions, insertions, deletions all cost 1)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    if not ref:
        raise ValueError("empty reference")
    return edit_distance(ref, hyp) / len(ref)


def wer(ref: str, hyp: str) -> float:
    words = ref.split()
    if not words:
        raise ValueError("empty reference")
    return edit_distance(words, hyp.split()) / len(words)


def corpus_cer(refs: list[str], hyps: list[str]) -> float:
    return sum(edit_distance(r, h) for r, h in zip(refs, hyps, strict=True)) / sum(len(r) for r in refs)


def corpus_wer(refs: list[str], hyps: list[str]) -> float:
    edits = sum(edit_distance(r.split(), h.split()) for r, h in zip(refs, hyps, strict=True))
    return edits / sum(len(r.split()) for r in refs)
