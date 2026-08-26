"""Turkish-correct text normalisation, shared by everything that matches text.

Turkish breaks the assumptions a Latin-alphabet pipeline quietly makes:

* `"I".lower()` is `"i"` and `"İ".lower()` is `"i"` plus a combining dot -- both
  wrong, because the dotted and dotless letters are separate letters. `"İNDİRİM"
  .lower()` does not equal `"indirim"`.
* It is agglutinative. `THY'nin`, `THY'den` and `THY` are the same subject, and
  `uçuş` / `uçuşlar` / `uçuşlarında` are the same word. Token overlap between
  two tellings of one story is far lower than the same comparison in English,
  which is how a 12% unmerged-duplicate rate survived a MinHash pipeline.
* Diacritics are optional in practice. A headline written `Kibris` and one
  written `Kıbrıs` are the same place.

This module was extracted from pipeline/promo_dedup.py, where it was written
for campaign matching and then needed again for event clustering. It is here so
there is one answer to "how do we compare Turkish text", not two that drift.
"""
from __future__ import annotations

import re
import unicodedata

#: Truncation length for the crude stemmer. Turkish suffixes stack, so removing
#: them properly needs a morphological analyser; truncating to a fixed prefix
#: gets `uçuş` and `uçuşlarında` to the same token for a fraction of the cost.
#: Six is long enough to keep `havayolu` and `havalimanı` distinct.
STEM_LEN = 6

# Map the two Turkish i's before lowercasing -- see the module docstring.
_TR_UPPER = {ord("I"): "ı", ord("İ"): "i"}
_TR_ASCII = str.maketrans(
    {
        "ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c",
        "â": "a", "î": "i", "û": "u", "å": "a", "é": "e",
    }
)

#: `Pegasus'tan`, `%40'a`, `Salı'dan`: Turkish attaches case endings after an
#: apostrophe. The ending carries no meaning for matching and differs between
#: two tellings of the same story, so it goes.
_APOSTROPHE_SUFFIX = re.compile(r"['’`´]\s*[a-z]*")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def tr_normalize(text: str) -> str:
    """Lowercase, de-diacritic and de-punctuate, Turkish-correctly."""
    lowered = unicodedata.normalize("NFC", text or "").translate(_TR_UPPER).lower()
    # A stray "İ" that reached us already lowercased leaves its combining dot.
    lowered = lowered.replace("̇", "")
    folded = lowered.translate(_TR_ASCII)
    folded = _APOSTROPHE_SUFFIX.sub(" ", folded)
    return " ".join(_NON_ALNUM.sub(" ", folded).split())


def stem_tokens(text: str) -> set[str]:
    """Stemmed content tokens.

    Single characters are dropped: they are what is left of a mangled word,
    never a word.
    """
    return {token[:STEM_LEN] for token in tr_normalize(text).split() if len(token) > 1}


def jaccard(left: set[str], right: set[str]) -> float:
    """0.0 when either side is empty, rather than a division error or a 1.0
    that would merge two things we know nothing about."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
