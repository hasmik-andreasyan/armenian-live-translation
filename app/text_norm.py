"""Text normalisation used ONLY for scoring (CER/WER), never for display.

Eastern Armenian details handled here:
- The ligature "և" and the spelling "եւ" are treated as the same thing.
  The capitalised conjunction "Եվ" ("and" at a sentence start) becomes "եւ" too.
- The question, exclamation and emphasis marks (՞ ՜ ՛) sit INSIDE a word,
  e.g. "ինչպե՞ս", so they are deleted, not replaced by a space.
- Other punctuation (։ ՝ ֊ , . ? ! ...) becomes a space.
"""

import re
import unicodedata

IN_WORD_MARKS = {"՞", "՜", "՛", "'", "’", "՚"}  # ՞ ՜ ՛ ' ’ ՚
_SPACES = re.compile(r"\s+")
_STANDALONE_YEV = re.compile(r"(?<!\w)եվ(?!\w)")


def normalize_for_scoring(text: str) -> str:
    t = unicodedata.normalize("NFC", text).lower()
    t = t.replace("և", "եւ")          # "և" → "եւ"
    t = _STANDALONE_YEV.sub("եւ", t)       # "Եվ" (lowercased "եվ") → "եւ"
    chars = []
    for c in t:
        if c in IN_WORD_MARKS:
            continue
        chars.append(" " if unicodedata.category(c).startswith("P") else c)
    return _SPACES.sub(" ", "".join(chars)).strip()
