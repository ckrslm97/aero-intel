"""Cleans raw LLM translation output before it is stored or displayed.

Small models don't reliably stop at the translation: in production,
llama-3.1-8b appended invented article prose and translator meta-commentary
("(Çevirisi yok, metni tam olarak çeviriyorum)") after otherwise-correct
headline translations -- 61 stored rows grew past 200 chars, one reaching
7,513. The correct translation was consistently the *first* line, so the same
cleaner both guards live calls and repairs stored rows without new LLM calls.
"""
import re

# Lines that are the model talking about translating rather than translating:
# parenthesized asides mentioning çeviri/translation, or "Not:"/"Note:" prefixes.
_META_LINE = re.compile(
    r"^\s*(\(.*(çevir|translat).*\)|not[:\s].*|note[:\s].*)\s*$",
    re.IGNORECASE,
)

# Inputs up to this length are headlines/titles: their translation must be a
# single line, so anything after the first line is model invention.
_SHORT_SOURCE = 200


def clean_translation(source: str, raw: str | None) -> str | None:
    """Return a trustworthy translation of `source`, or None if `raw` can't be
    salvaged -- None keeps the article honestly untranslated (badge shows)
    rather than displaying junk."""
    if not raw:
        return None

    lines = [line for line in raw.splitlines() if not _META_LINE.match(line)]
    if len(source) <= _SHORT_SOURCE:
        # A headline translates to one line; drop everything past the first.
        lines = [next((line for line in lines if line.strip()), "")]

    cleaned = "\n".join(lines).strip().strip('"“”').strip()
    if not cleaned:
        return None

    # A translation dramatically longer than its source is not a translation.
    # Turkish runs a bit longer than English, so allow generous headroom.
    if len(cleaned) > 4 * len(source) + 40:
        return None
    return fix_vowel_harmony(cleaned)


# --- Turkish vowel harmony repair ---------------------------------------

# Small models occasionally break vowel harmony on the progressive suffix:
# "tanıtüyor" for "tanıtıyor". Measured across 1067 stored headlines it hits
# 0.4% -- rare, but it is the kind of error a Turkish reader notices instantly.
# The suffix is fully determined by the last vowel of the stem, so this is a
# deterministic repair, not a guess; rejecting the translation instead would
# show English in place of otherwise-good Turkish.
_PROGRESSIVE = re.compile(r"(\w+?)(ıyor|iyor|uyor|üyor)", re.IGNORECASE)
_HARMONY = {
    "a": "ıyor", "ı": "ıyor",
    "e": "iyor", "i": "iyor",
    "o": "uyor", "u": "uyor",
    "ö": "üyor", "ü": "üyor",
}
_VOWELS = "aeıioöuü"


def fix_vowel_harmony(text: str) -> str:
    """Correct a progressive suffix that disagrees with its stem's last vowel."""

    def repair(match: re.Match[str]) -> str:
        stem, suffix = match.group(1), match.group(2)
        vowels = [c for c in stem.lower() if c in _VOWELS]
        if not vowels:
            return match.group(0)
        expected = _HARMONY[vowels[-1]]
        if expected == suffix.lower():
            return match.group(0)
        # Preserve the original casing of the suffix.
        return stem + (expected.upper() if suffix.isupper() else expected)

    return _PROGRESSIVE.sub(repair, text)
