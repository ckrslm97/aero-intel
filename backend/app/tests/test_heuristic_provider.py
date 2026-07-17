from app.llm.base import EntityMention
from app.llm.heuristic import HeuristicProvider, detect_region

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


async def test_categorize_detects_revenue_management_keywords():
    category = await provider.categorize(
        "Airline adjusts fares amid competitor pressure",
        "The carrier cited yield management, load factor gains, and dynamic pricing "
        "against a rival's capacity increase.",
    )
    assert category == "revenue_management"


async def test_categorize_detects_events_keywords():
    category = await provider.categorize(
        "Airline executives to attend industry summit",
        "The airline will present at the upcoming aviation conference and expo.",
    )
    assert category == "events"


async def test_short_metric_keywords_do_not_fire_on_longer_words():
    """ASK/RPK are real keywords but also live inside ordinary words.

    Substring counting scored "asked", "task" and "maximum" as ASK/MAX hits,
    which quietly mis-categorised articles that never mentioned capacity.
    """
    category = await provider.categorize(
        "Passengers asked about baggage",
        "Travellers asked staff about the maximum baggage allowance; it was a simple task.",
    )
    assert category != "revenue_management"


async def test_headline_outweighs_incidental_body_mentions():
    """A long body can otherwise out-vote the headline on sheer word count."""
    category = await provider.categorize(
        "Airline cuts fares in price war with rival",
        # "airport" appears repeatedly, but only incidentally -- the story is
        # about fares, which is what the headline says.
        "The airport shuttle leaves from the airport terminal. Passengers at the "
        "airport can reach the airport by train. The airport is busy.",
    )
    assert category == "revenue_management"


async def test_subcategorize_scores_within_category():
    subcategory = await provider.subcategorize(
        "Airline launches new route",
        "The carrier will launch a new nonstop service next spring.",
        "network",
    )
    assert subcategory == "new_route"


async def test_subcategorize_returns_none_for_flat_categories():
    # safety has no subcategory taxonomy defined
    assert await provider.subcategorize("Emergency landing", "The aircraft was diverted.", "safety") is None
    # events subcategory is decided by region detection in the pipeline, not keywords
    assert await provider.subcategorize("Air show announced", "conference and expo", "events") is None


async def test_translate_returns_none_no_key_engine():
    """The keyless heuristic engine cannot translate -- it must return None so
    callers know to leave the text untranslated rather than faking a translation."""
    assert await provider.translate("Some headline", "tr") is None


def test_detect_region_maps_country_entity_to_region():
    entities = [EntityMention("country", "Turkey", None)]
    assert detect_region(entities) == "middle-east"


def test_detect_region_returns_none_without_country():
    entities = [EntityMention("airline", "Turkish Airlines", "TK")]
    assert detect_region(entities) is None
