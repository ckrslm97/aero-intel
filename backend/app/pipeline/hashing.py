"""Shared content normalization + hashing, used by ingestion (to catch identical
re-fetches) and by the dedup pipeline (to catch the same story from two sources).
"""
import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")


def normalize_text(text: str) -> str:
    text = text.lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def content_hash(title: str, content: str) -> str:
    normalized = normalize_text(title) + " " + normalize_text(content[:2000])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def shingles(text: str, k: int = 5) -> set[str]:
    """Word k-shingles of normalized text, used as MinHash input for near-dup detection."""
    words = normalize_text(text).split()
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}
