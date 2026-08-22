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
        "airline names, airport names, IATA/ICAO codes, aircraft type "
        "designators (e.g. A321neo, 777X), and standard aviation/travel industry "
        "terms (e.g. Business Class, Economy, Premium Economy, First Class, "
        "codeshare, layover, slot, hub, ferry flight) in their original English or "
        "internationally recognized form rather than translating them literally. "
        "Respond with ONLY the translation, no explanation, no quotes.\n\n"
        f"Text: {text}\n\nTranslation:"
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
        "names, airport names, IATA/ICAO codes, aircraft type designators "
        "(e.g. A321neo, 777X), and standard aviation/travel industry terms "
        "(e.g. Business Class, Economy, Premium Economy, First Class, codeshare, "
        "layover, slot, hub, ferry flight) in their original English or "
        "internationally recognized form rather than translating them literally.\n"
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


def promotion_extraction_prompt(title: str, content: str) -> str:
    """Pull a campaign's structured window out of prose.

    Everything here pushes the model towards `null` rather than a guess. A
    promotion row is drawn on a timeline as a dated bar, so a hallucinated
    `sale_ends` is not a soft error -- it renders identically to a date the
    airline actually published. "Bu yaz" must come back as null, not as a
    31 August the model reasoned its way to.
    """
    return (
        "Extract the structured details of an airline ticket campaign/promotion "
        "from the Turkish or English aviation news text below.\n"
        "Respond with ONLY a valid JSON object, no explanation, no markdown fences, "
        "with exactly these keys:\n"
        '  "discount_pct": integer percentage discount, or null\n'
        '  "sale_starts": "YYYY-MM-DD" first day tickets can be bought, or null\n'
        '  "sale_ends": "YYYY-MM-DD" last day tickets can be bought, or null\n'
        '  "travel_starts": "YYYY-MM-DD" first day of valid travel, or null\n'
        '  "travel_ends": "YYYY-MM-DD" last day of valid travel, or null\n'
        '  "markets": comma-separated destinations/regions covered, or null\n\n'
        "Rules:\n"
        "- Use null for anything the text does not state explicitly. Do NOT infer, "
        "estimate, or complete a partial date. Vague phrases ('bu yaz', 'this "
        "summer', 'önümüzdeki aylarda', 'for a limited time') are null.\n"
        "- Only fill a date if the text gives a real calendar date. If the year is "
        "missing but the day and month are stated, use the year the text is about.\n"
        "- discount_pct is the headline rate as a plain integer: '%40'a varan "
        "indirim' -> 40. A fare floor ('9 Euro'dan başlayan') is NOT a percentage "
        "-> null.\n"
        "- Never invent a market list; null when the text does not name any.\n\n"
        f"Title: {title}\nContent: {content[:2500]}\n\nJSON:"
    )
