from app.llm.heuristic import HeuristicProvider

provider = HeuristicProvider()


async def test_generate_headline_returns_title():
    headline = await provider.generate_headline("Delta announces new route", "body")
    assert headline == "Delta announces new route"


async def test_generate_summary_picks_top_sentences():
    content = (
        "Delta Air Lines announced a new nonstop route to Tokyo today. "
        "The airline said demand for transpacific travel has grown steadily. "
        "A spokesperson also mentioned unrelated catering menu updates. "
        "Delta will operate the Tokyo route with a Boeing 767 starting in March."
    )
    summary = await provider.generate_summary("Delta launches Tokyo route", content)
    assert "Tokyo" in summary
    assert len(summary) > 0


async def test_categorize_detects_safety_keywords():
    category = await provider.categorize(
        "Emergency landing after mayday call",
        "The aircraft was diverted following an in-flight emergency and mayday declaration.",
    )
    assert category == "safety"


async def test_categorize_detects_finance_keywords():
    category = await provider.categorize(
        "Airline reports quarterly earnings",
        "The airline posted record quarterly revenue and profit, beating analyst estimates.",
    )
    assert category == "finance"


async def test_sentiment_positive_and_negative():
    positive = await provider.sentiment("Airline celebrates record growth", "A milestone achievement.")
    negative = await provider.sentiment("Airline hit by strike", "Flights cancelled after strike disruption.")
    assert positive == "positive"
    assert negative == "negative"


async def test_extract_entities_finds_airline_and_country():
    mentions = await provider.extract_entities(
        "Turkish Airlines expands to Egypt",
        "Turkish Airlines announced a new route connecting Istanbul with Egypt.",
    )
    types = {(m.entity_type, m.name) for m in mentions}
    assert ("airline", "Turkish Airlines") in types
    assert ("country", "Egypt") in types
