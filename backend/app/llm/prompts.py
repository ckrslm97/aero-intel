"""Shared prompt templates for the live LLM providers (Ollama, OpenAI-compatible)."""
from app.llm.terminology import terminology_clause_en
from app.taxonomy import CATEGORY_SLUGS, RISK_SEVERITIES, RISK_TYPE_SLUGS, SUBCATEGORY_KEYWORDS

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
        f"designators (e.g. A321neo, 777X), and {terminology_clause_en()}. "
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
        f"(e.g. A321neo, 777X), and {terminology_clause_en()}.\n"
        "Respond in EXACTLY this format, with these two markers and nothing else:\n"
        "HEADLINE: <translated headline>\n"
        "SUMMARY: <translated summary>\n\n"
        f"Headline: {headline}\n"
        f"Summary: {summary}\n\n"
        "Response:"
    )


def why_important_prompt(title: str, content: str, category: str) -> str:
    """"Neden önemli?" -- one or two Turkish sentences for the desk.

    Generated for a handful of the day's highest-scoring stories only (see
    app/pipeline/enrich.py WHY_IMPORTANT_MIN_IMPORTANCE), because it is a
    second live call on top of translation and translation already is the token
    budget.

    Every clause below exists to keep it grounded. The model is told to read
    only the article, told that the reader is an RM analyst rather than a
    general audience, and told explicitly not to forecast -- an unhedged "bu,
    bilet fiyatlarını %10 artıracak" is indistinguishable on screen from
    something the article said, and this text is rendered as a quote. When the
    article genuinely says nothing beyond its own facts, "" is the right answer
    and the caller stores NULL.
    """
    return (
        "Sen bir havayolu gelir yönetimi masası için çalışan bir haber "
        "analistisin. Aşağıdaki haberin bu masa için NEDEN önemli olduğunu "
        "en fazla iki cümleyle Türkçe yaz.\n\n"
        "Kurallar:\n"
        "- SADECE haberin kendisinde yazanlara dayan. Tahmin, öngörü ve "
        "senaryo yazma; 'olabilir', 'beklenebilir' gibi kurgular ekleme.\n"
        "- Haberi ÖZETLEME. Özet zaten var; sen sonucun ne anlama geldiğini "
        "yaz: kapasite, talep, fiyat, rekabet veya maliyet tarafında neyi "
        "değiştiriyor.\n"
        "- Sayı, tarih veya oran yazacaksan yalnızca metinde geçenleri kullan.\n"
        "- Havacılık ve gelir yönetimi terimlerini çevirme.\n"
        "- Haber bu masa için gerçekten bir şey ifade etmiyorsa hiçbir şey "
        "yazma, boş cevap ver.\n\n"
        f"Kategori: {category}\n"
        f"Başlık: {title}\n"
        f"Metin: {content[:2000]}\n\n"
        "Değerlendirme:"
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


VALID_RISK_TYPES = list(RISK_TYPE_SLUGS)
VALID_RISK_SEVERITIES = list(RISK_SEVERITIES)


def risk_prompt(title: str, content: str) -> str:
    """Risk Radarı classification: which real-world hazard, if any, this
    article reports.

    Two things are load-bearing in the wording. First, null is stated as the
    expected answer -- an aviation wire is overwhelmingly not disaster
    reporting, and a model asked "which of these nine" without a way out will
    pick one for a fare-war story. Second, the metaphor carve-out is explicit,
    because "fare war", "perfect storm" and "under fire" are exactly the
    phrasings this feed is full of; the keyword fallback in
    app/llm/heuristic.py masks the same idioms for the same reason.

    Whatever comes back is still validated against the closed taxonomy by the
    caller (app.taxonomy.is_valid_risk_type) -- this prompt is a request, not a
    guarantee.
    """
    options = ", ".join(VALID_RISK_TYPES)
    severities = ", ".join(VALID_RISK_SEVERITIES)
    return (
        "You classify news articles for a natural-disaster and conflict radar.\n"
        f"If this article reports a REAL-WORLD hazard event, pick exactly one type from: {options}.\n"
        'If it does not, set "risk_type" to null. Null is the correct answer for most '
        "aviation business news.\n\n"
        "Rules:\n"
        '- Figurative language is NOT an event. "fare war", "price war", "trade war", '
        '"perfect storm", "under fire", "political earthquake", "a flood of bookings" '
        'and "heart attack" all mean risk_type null.\n'
        "- An aircraft fire, engine fire or cabin fire is an aviation safety incident, "
        'NOT "wildfire". Only wildland/forest/bush fires count.\n'
        "- A pilot or cabin-crew strike is a labour dispute, NOT \"unrest\". Only civil "
        "riots, violent or anti-government protests count.\n"
        "- A cyber attack is not \"attack\"; this radar covers physical events.\n"
        f'- "severity" is one of: {severities}. Use "high" for loss of life or '
        'destruction, "medium" for injuries, evacuation or damage, "low" otherwise.\n'
        '- "country" and "city" are where the EVENT happened (English names), or null '
        "if the article does not say.\n\n"
        "Respond with ONLY a valid JSON object, no explanation, no markdown fences:\n"
        '{"risk_type": <one of the types above or null>, "severity": <severity or null>, '
        '"country": <string or null>, "city": <string or null>}\n\n'
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
