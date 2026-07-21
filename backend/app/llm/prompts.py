"""Shared prompt templates for the live LLM providers (Ollama, OpenAI-compatible)."""
from app.taxonomy import CATEGORY_SLUGS, SUBCATEGORY_KEYWORDS

# Single source of truth for the taxonomy lives in app/taxonomy.py -- both the
# heuristic engine and these live-provider prompts read from it so they can
# never drift apart.
VALID_CATEGORIES = CATEGORY_SLUGS
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


def subcategorize_prompt(title: str, content: str, category: str) -> str:
    sub_options = SUBCATEGORY_KEYWORDS.get(category)
    options = ", ".join(sub_options.keys()) if sub_options else "none"
    return (
        f"This aviation article was already classified as '{category}'. Pick exactly "
        f"one more specific subcategory from: {options}. If none clearly fits, respond "
        f"with exactly the word 'none'. Respond with only that one word.\n\n"
        f"Title: {title}\nContent: {content[:1000]}\n\nSubcategory:"
    )


def translate_prompt(text: str, target: str = "tr") -> str:
    target_name = "Turkish" if target == "tr" else target
    return (
        f"Translate the following aviation news text into {target_name}. Preserve "
        "airline names, airport names, and IATA/ICAO codes unchanged. Respond with "
        f"ONLY the translation, no explanation, no quotes.\n\nText: {text}\n\nTranslation:"
    )


def translate_pair_prompt(headline: str, summary: str, target: str = "tr") -> str:
    """Both fields in one call. Translation is the entire 70b token budget, and
    sending the headline and the summary separately doubled it for no gain --
    the two are the same story and the model reads them together anyway.

    The delimiters are what the parser splits on, so they are stated twice and
    kept ASCII-only to survive a small model's formatting drift.
    """
    target_name = "Turkish" if target == "tr" else target
    return (
        f"Translate the aviation news below into {target_name}. Preserve airline "
        "names, airport names, and IATA/ICAO codes unchanged.\n"
        "Respond in EXACTLY this format, with these two markers and nothing else:\n"
        "HEADLINE: <translated headline>\n"
        "SUMMARY: <translated summary>\n\n"
        f"Headline: {headline}\n"
        f"Summary: {summary}\n\n"
        "Response:"
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
