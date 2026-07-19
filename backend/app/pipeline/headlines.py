"""Trimming the publisher credit aggregators append to a headline.

Google News rewrites every title as "<headline> - <Publisher>", so the
newspaper, the newsletter and the PDF all repeated the outlet name that is
already displayed beside the story. Only a suffix that actually names the
publisher is removed -- a headline that legitimately ends in a dashed clause
("Delta cuts Tokyo - here is why") keeps it.
"""
import re

# " - Publisher", " – Publisher", " — Publisher", " | Publisher"
_SUFFIX = re.compile(r"\s+[-–—|]\s+([^-–—|]{2,60})\s*$")


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def strip_publisher_suffix(headline: str, source_name: str | None = None) -> str:
    """Drop a trailing publisher credit. `source_name` is the feed's own name;
    when it is a Google News radar ("Google News · Fiyatlandırma") the suffix is
    some third-party outlet we can't match by name, so fall back to shape: a
    short trailing clause with no sentence punctuation is a credit, not part of
    the headline."""
    match = _SUFFIX.search(headline)
    if not match:
        return headline

    candidate = match.group(1).strip()
    head = headline[: match.start()].strip()
    # Never leave a stub behind -- if the "headline" was mostly the suffix,
    # the pattern matched something else.
    if len(head) < 25:
        return headline

    normalized_candidate = _normalize(candidate)
    if source_name:
        normalized_source = _normalize(source_name)
        # Exact-ish match against the feed name, e.g. "Simple Flying".
        if normalized_candidate and normalized_candidate in normalized_source:
            return head

    # Aggregator case: a credit is short, title-shaped and has no terminal
    # punctuation or digits-heavy content.
    words = candidate.split()
    if len(words) <= 6 and not candidate.endswith((".", "!", "?", ":")):
        return head
    return headline
