"""No-key fallback pipeline: extractive summarization, keyword categorization,
lexicon sentiment, and gazetteer entity extraction. Runs with zero external
dependencies so the platform works before any LLM is configured, and is what
every other provider falls back to if a live call fails.
"""
import re
from collections import Counter

from app.llm.base import EntityMention
from app.llm.gazetteer import AIRLINES, AIRPORTS, COUNTRIES
from app.pipeline.hashing import normalize_text

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "has",
    "have", "had", "it", "its", "this", "that", "will", "would", "said", "also",
    "which", "their", "than", "into", "after", "before", "over", "more", "new",
    "said.",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "safety": ["crash", "incident", "emergency", "mayday", "diverted", "grounded", "investigation"],
    "finance": ["revenue", "profit", "earnings", "stock", "shares", "ipo", "quarterly", "loss", "margin"],
    "fleet": ["aircraft order", "delivery", "boeing", "airbus", "fleet", "widebody", "narrowbody"],
    "routes": ["route", "nonstop", "launch flight", "service between", "network", "frequency"],
    "regulatory": ["faa", "easa", "icao", "regulation", "certification", "government", "ban"],
    "sustainability": ["saf", "sustainable aviation fuel", "emissions", "carbon", "net zero"],
    "labor": ["union", "strike", "pilots", "contract negotiation", "staffing"],
    "airport": ["airport", "terminal", "runway", "expansion", "slot"],
}

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
        text = normalize_text(f"{title} {content}")
        best_category = "general"
        best_score = 0
        for category, keywords in _CATEGORY_KEYWORDS.items():
            score = sum(text.count(kw) for kw in keywords)
            if score > best_score:
                best_score = score
                best_category = category
        return best_category

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

        for alias, (name, code) in AIRLINES.items():
            if alias in text:
                mentions.append(EntityMention("airline", name, code))
        for alias, (name, code) in AIRPORTS.items():
            if alias in text:
                mentions.append(EntityMention("airport", name, code))
        for country in COUNTRIES:
            if country in text:
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
