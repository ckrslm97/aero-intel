"""No-key fallback pipeline: extractive summarization, keyword categorization,
lexicon sentiment, and gazetteer entity extraction. Runs with zero external
dependencies so the platform works before any LLM is configured, and is what
every other provider falls back to if a live call fails.
"""
import re
from collections import Counter
from functools import lru_cache

from app.llm.base import EntityMention
from app.llm.gazetteer import AIRLINES, AIRPORT_COUNTRY, AIRPORTS, COUNTRIES
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
        text = normalize_text(f"{title} {content}")
        mentions: list[EntityMention] = []

        # Whole-word matching, same as categorisation: plain substring search
        # tagged every article containing "management" with All Nippon ("ana")
        # -- 96 false links in production.
        for alias, (name, code) in AIRLINES.items():
            if _keyword_pattern((alias,)).search(text):
                mentions.append(EntityMention("airline", name, code))
        for alias, (name, code) in AIRPORTS.items():
            if _keyword_pattern((alias,)).search(text):
                mentions.append(EntityMention("airport", name, code))
        for country in COUNTRIES:
            if _keyword_pattern((country,)).search(text):
                mentions.append(EntityMention("country", country.title(), None))

        # de-duplicate while preserving order
        seen: set[tuple[str, str]] = set()
        unique: list[EntityMention] = []
        for m in mentions:
            key = (m.entity_type, m.name)
            if key not in seen:
                seen.add(key)
                unique.append(m)
        return unique


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
