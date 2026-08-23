"""No-key fallback pipeline: extractive summarization, keyword categorization,
lexicon sentiment, and gazetteer entity extraction. Runs with zero external
dependencies so the platform works before any LLM is configured, and is what
every other provider falls back to if a live call fails.
"""
import re
from collections import Counter
from functools import lru_cache

from app.llm.base import EntityMention
from app.llm.gazetteer import (
    AIRLINE_ALIASES,
    AIRPORT_COUNTRY,
    AIRPORTS,
    ALIAS_FIRST_TOKENS,
    AMBIGUOUS_BARE_CODES,
    COUNTRY_ALIASES,
    MAX_ALIAS_TOKENS,
    fold_tokens,
)
from app.pipeline.hashing import normalize_text
from app.taxonomy import CATEGORY_KEYWORDS, COUNTRY_TO_REGION, GENERAL_CATEGORY, SUBCATEGORY_KEYWORDS

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "has",
    "have", "had", "it", "its", "this", "that", "will", "would", "said", "also",
    "which", "their", "than", "into", "after", "before", "over", "more", "new",
    "said.",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# How much louder a keyword in the headline counts than one in the body.
_TITLE_WEIGHT = 3


@lru_cache(maxsize=None)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Match keywords as whole words, not substrings.

    Plain `text.count("ask")` also fires on "asked" and "task", and "max" fires
    on "maximum" -- so short metric names silently mis-categorised articles.
    Word boundaries make short keywords like ASK and RPK usable at all.
    """
    return re.compile("|".join(rf"\b{re.escape(kw)}\b" for kw in keywords))


def _score(pattern: re.Pattern[str], title_text: str, body_text: str) -> int:
    return len(pattern.findall(title_text)) * _TITLE_WEIGHT + len(pattern.findall(body_text))

_POSITIVE_WORDS = {
    "growth", "record", "profit", "expand", "launch", "award", "success", "improve",
    "increase", "milestone", "celebrate", "achievement", "strong", "recovery",
}
_NEGATIVE_WORDS = {
    "crash", "delay", "cancel", "loss", "strike", "grounded", "incident", "decline",
    "layoff", "investigation", "emergency", "disruption", "fine", "lawsuit",
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


class HeuristicProvider:
    name = "heuristic"

    async def generate_headline(self, title: str, content: str) -> str:
        return title.strip()

    async def generate_summary(self, title: str, content: str) -> str:
        sentences = _sentences(content)
        if not sentences:
            return ""
        if len(sentences) <= 2:
            return " ".join(sentences)

        words = normalize_text(content).split()
        freq = Counter(w for w in words if w not in _STOPWORDS)

        scored = sorted(
            range(len(sentences)),
            key=lambda i: sum(freq.get(w, 0) for w in normalize_text(sentences[i]).split()),
            reverse=True,
        )
        top_indices = sorted(scored[:3])
        return " ".join(sentences[i] for i in top_indices)

    async def categorize(self, title: str, content: str) -> str:
        # A keyword in the headline says what the story is *about*; the same
        # word buried in the body is often incidental ("...the airport shuttle
        # departs hourly"). Weighting the title heavily keeps a long body from
        # outvoting the headline on sheer word count.
        title_text = normalize_text(title)
        body_text = normalize_text(content)
        best_category = GENERAL_CATEGORY
        best_score = 0
        for category, keywords in CATEGORY_KEYWORDS.items():
            score = _score(_keyword_pattern(tuple(keywords)), title_text, body_text)
            if score > best_score:
                best_score = score
                best_category = category
        return best_category

    async def subcategorize(self, title: str, content: str, category: str) -> str | None:
        """Second keyword pass within the chosen category. Returns None for
        categories with no subcategory taxonomy (safety, regulatory, ...), and
        for "events" -- that one is decided by enrich.py from the detected
        region instead (general vs. regional), not by keyword scoring.
        """
        if category == "events":
            return None
        sub_keywords = SUBCATEGORY_KEYWORDS.get(category)
        if not sub_keywords:
            return None
        title_text = normalize_text(title)
        body_text = normalize_text(content)
        best_sub: str | None = None
        best_score = 0
        for sub, keywords in sub_keywords.items():
            if not keywords:
                continue
            score = _score(_keyword_pattern(tuple(keywords)), title_text, body_text)
            if score > best_score:
                best_score = score
                best_sub = sub
        return best_sub

    async def translate(self, text: str, target: str = "tr") -> str | None:
        """The keyless heuristic engine has no translation capability -- return
        None so callers know to leave the original text untranslated rather
        than silently passing it through as if it were Turkish."""
        return None

    async def sentiment(self, title: str, content: str) -> str:
        words = set(normalize_text(f"{title} {content}").split())
        positive = len(words & _POSITIVE_WORDS)
        negative = len(words & _NEGATIVE_WORDS)
        if positive > negative:
            return "positive"
        if negative > positive:
            return "negative"
        return "neutral"

    async def extract_entities(self, title: str, content: str) -> list[EntityMention]:
        return extract_entity_mentions(title, content)


def _airport_match_is_credible(
    gram: str, cased: list[str], start: int, end: int
) -> bool:
    """Whether an airport alias hit is worth believing.

    Multi-word aliases ("john f kennedy") are self-evidencing, and so is any
    code that is not also an ordinary word. The one case that needs a second
    look is a bare three-letter code that doubles as prose -- see
    `AMBIGUOUS_BARE_CODES`. There the deciding evidence is capitalisation,
    which the folded token view has already thrown away: a wire writes the
    code as "JAN" and the month as "Jan", so requiring the original token to
    be upper-case keeps "flights to JAN" and drops "Okinawa Jan 2027".
    """
    if end != start:  # multi-token alias: not a bare code
        return True
    if gram.upper() not in AMBIGUOUS_BARE_CODES:
        return True
    return cased[start].isupper()


def extract_entity_mentions(title: str, content: str) -> list[EntityMention]:
    """Airlines, airports and countries named in the text, in the order they
    appear.

    Whole-word matching, never substring: plain `in` tagged every article
    containing "management" with All Nippon ("ana") -- 96 false links in
    production. It is done by sliding a token n-gram window over the folded
    text and looking each gram up in the gazetteer's alias tables, which is the
    same whole-word semantics as the old regex-per-alias loop (normalised text
    is space-separated [a-z0-9] tokens, so token edges *are* word boundaries)
    at a fraction of the cost -- the airport table grew from 30 aliases to
    ~11.6k when the OurAirports dataset landed, and 11.6k regex scans per
    article is not a thing you can run over an archive.

    Text order also makes `detect_region` deterministic: it takes the first
    country it sees, and "first" used to mean whatever order a Python set
    happened to iterate in.
    """
    tokens, cased = fold_tokens(f"{title} {content}")
    mentions: list[EntityMention] = []
    seen: set[tuple[str, str]] = set()

    def note(entity_type: str, name: str, code: str | None) -> None:
        key = (entity_type, name)
        if key not in seen:
            seen.add(key)
            mentions.append(EntityMention(entity_type, name, code))

    total = len(tokens)
    for start, first in enumerate(tokens):
        if first not in ALIAS_FIRST_TOKENS:
            continue
        gram = first
        for end in range(start, min(start + MAX_ALIAS_TOKENS, total)):
            if end > start:
                gram = f"{gram} {tokens[end]}"
            airline = AIRLINE_ALIASES.get(gram)
            if airline:
                note("airline", airline[0], airline[1])
            airport = AIRPORTS.get(gram)
            if airport and _airport_match_is_credible(gram, cased, start, end):
                note("airport", airport[0], airport[1])
            country = COUNTRY_ALIASES.get(gram)
            if country:
                note("country", country.title(), None)
    return mentions


def detect_region(entities: list[EntityMention]) -> str | None:
    """Region detection is entity-based, not LLM-based, so it runs the same way
    regardless of which provider (heuristic or live) extracted the entities --
    the first recognized country entity maps to its world-region slug via
    app.taxonomy.COUNTRY_TO_REGION. Articles that name only an airport (very
    common in route news: "Heathrow slot changes") fall back to that airport's
    country. Returns None if nothing mapped.
    """
    for mention in entities:
        if mention.entity_type != "country":
            continue
        region = COUNTRY_TO_REGION.get(mention.name.lower())
        if region:
            return region
    for mention in entities:
        if mention.entity_type != "airport" or not mention.code:
            continue
        country = AIRPORT_COUNTRY.get(mention.code)
        if country:
            region = COUNTRY_TO_REGION.get(country)
            if region:
                return region
    return None
