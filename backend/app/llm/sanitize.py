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
    return cleaned
