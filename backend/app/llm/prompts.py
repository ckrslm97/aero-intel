"""Shared prompt templates for the live LLM providers (Ollama, OpenAI-compatible)."""

VALID_CATEGORIES = [
    "safety", "finance", "fleet", "routes", "regulatory",
    "sustainability", "labor", "airport", "general",
]
VALID_SENTIMENTS = ["positive", "negative", "neutral"]


def headline_prompt(title: str, content: str) -> str:
    return (
        "Write a concise, factual news headline (max 15 words) for this aviation "
        f"article. Respond with only the headline, no quotes.\n\nTitle: {title}\n"
        f"Content: {content[:1500]}\n\nHeadline:"
    )


def summary_prompt(title: str, content: str) -> str:
    return (
        "Summarize this aviation news article in 2-3 factual, neutral sentences. "
        f"Respond with only the summary.\n\nTitle: {title}\nContent: {content[:3000]}\n\nSummary:"
    )


def categorize_prompt(title: str, content: str) -> str:
    options = ", ".join(VALID_CATEGORIES)
    return (
        f"Classify this aviation article into exactly one category: {options}. "
        f"Respond with only the category word.\n\nTitle: {title}\nContent: {content[:1000]}\n\nCategory:"
    )


def sentiment_prompt(title: str, content: str) -> str:
    return (
        "Classify the overall sentiment as exactly one word: positive, negative, or "
        f"neutral. Respond with only that word.\n\nTitle: {title}\nContent: {content[:1000]}\n\nSentiment:"
    )


def entities_prompt(title: str, content: str) -> str:
    return (
        "Extract aviation entities mentioned in this article as a JSON array of "
        'objects with fields "entity_type" (airline|airport|country), "name", and '
        '"code" (IATA code or null). Only include entities clearly mentioned. '
        "Respond with ONLY a valid JSON array, no explanation, no markdown fences.\n\n"
        f"Title: {title}\nContent: {content[:1500]}\n\nJSON:"
    )
