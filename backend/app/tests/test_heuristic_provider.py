import pytest

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


async def test_entity_aliases_match_whole_words_only():
    # Production bug: the substring alias "ana" fired inside "management",
    # linking All Nippon Airways to 96 revenue-management articles.
    provider = HeuristicProvider()
    entities = await provider.extract_entities(
        "Revenue management strategies for 2027",
        "Airlines refine revenue management and capacity management practices.",
    )
    assert all(e.name != "All Nippon Airways" for e in entities)


async def test_region_falls_back_to_airport_country():
    # Route news often names only an airport ("Heathrow slots"), no country.
    provider = HeuristicProvider()
    entities = await provider.extract_entities(
        "Heathrow slot changes announced",
        "New slot allocations at Heathrow for the winter season.",
    )
    from app.llm.heuristic import detect_region

    assert detect_region(entities) == "europe"


async def test_rival_airline_name_lands_rm_article_in_competitor():
    provider = HeuristicProvider()
    sub = await provider.subcategorize(
        "Emirates undercuts fares on Gulf routes",
        "Emirates lowered fares in a bid for market share.",
        "revenue_management",
    )
    assert sub == "competitor"


# --- the nine Gelir Yönetimi beats -------------------------------------------
#
# One realistic story per slug, headline and body written the way the wires
# actually file them. They are a specification, not coverage padding: the
# keyword lists are tuned against these, and a list that stops answering one of
# them has stopped answering the beat it was written for.


@pytest.mark.parametrize(
    "expected,title,body",
    [
        (
            "competitor",
            "Ryanair enters the Italian market as Wizz Air exits",
            "The new entrant is chasing market share from a rival that is pulling out of three bases.",
        ),
        (
            "pricing",
            "Transatlantic airfares fall as carriers cut fares for winter",
            "The fare war pushed average ticket prices down; one carrier lowers fares on 20 routes.",
        ),
        (
            "promotion",
            "Emirates launches flash sale with promo code for summer",
            "The promotional fare covers selected routes until August.",
        ),
        (
            "load_factor",
            "Load factor climbs to 86% in June",
            "The passenger load factor beat last year's occupancy rate across the network.",
        ),
        (
            "ancillary",
            "Carrier lifts ancillary revenue with paid seat selection",
            "Baggage fees and extra legroom drove the ancillary income; priority boarding was bundled.",
        ),
        (
            "distribution",
            "Lufthansa pushes NDC content through Amadeus",
            "The GDS deal covers offer and order retailing, with a new API for travel agency bookings.",
        ),
        (
            "forecasting",
            "IATA lifts its 20-year industry forecast for air travel",
            "The market outlook projection sees traffic doubling; the forecast revision follows a strong year.",
        ),
    ],
)
async def test_revenue_management_subcategories(expected, title, body):
    assert await provider.subcategorize(title, body, "revenue_management") == expected


async def test_demand_and_capacity_are_told_apart():
    """The split that this taxonomy round exists for. Both stories used to land
    in one "demand_capacity" bucket, which is the one distinction an RM desk
    cannot afford to lose: the first says what the market wants, the second says
    what a carrier decided to supply, and they are opposite sides of the trade.
    """
    demand = await provider.subcategorize(
        "Bookings to Europe up 12% for summer",
        "Forward bookings show strong demand from leisure travel, with booking trends improving.",
        "revenue_management",
    )
    capacity = await provider.subcategorize(
        "Airline adds third daily frequency on IST-LHR",
        "The schedule change lifts seat capacity on the route; the carrier adds flights from March.",
        "revenue_management",
    )
    assert demand == "demand"
    assert capacity == "capacity"


# --- the nine Havalimanı beats -----------------------------------------------


@pytest.mark.parametrize(
    "expected,title,body",
    [
        (
            "slot",
            "Heathrow slot allocation reshuffled for the winter season",
            "The slot coordinator approved a slot swap between two carriers under use it or lose it rules.",
        ),
        (
            "airport_capacity",
            "Schiphol keeps its capacity cap for another year",
            "The declared capacity stays at 500,000 movements; the capacity constraint bites in summer.",
        ),
        (
            "terminal",
            "Istanbul opens new terminal pier for wide-body aircraft",
            "The terminal expansion adds a concourse and 20 boarding gates.",
        ),
        (
            "infrastructure",
            "Third runway construction begins at Gatwick",
            "The master plan covers a new taxiway and apron modernisation.",
        ),
        (
            "disruption",
            "Congestion and delays hit Frankfurt after power outage",
            "The closure of one pier caused queues and overcrowding; restrictions stay in place.",
        ),
        (
            "traffic",
            "Passenger traffic at Dubai up 8% in the first half",
            "Passenger numbers reached 45 million; cargo volume and tonnage also rose.",
        ),
        (
            "new_service",
            "Riga wins new airline as Wizz opens a new base",
            "The new carrier starts flights in March, part of the airport's hub development.",
        ),
        (
            "ground_handling",
            "Ground handling contract at Oslo goes to new agent",
            "The handling agent takes over baggage handling, de icing and ramp turnaround duties.",
        ),
        (
            "passenger_experience",
            "Biometric e gate rollout speeds security checkpoint queues",
            "The airport added fast track lanes, a new lounge and duty free wayfinding.",
        ),
    ],
)
async def test_airport_subcategories(expected, title, body):
    """Havalimanı had no subcategories at all until this round -- every airport
    story landed in one undifferentiated pile, which was survivable as one tab
    of six and is not as one of the paper's three sections."""
    assert await provider.subcategorize(title, body, "airport") == expected


# --- the fleet/finance -> revenue_management shift ---------------------------


@pytest.mark.parametrize(
    "title,body",
    [
        (
            "Wizz Air adds capacity in Italy with 20 new Airbus jets",
            "The Airbus deal covers A321 aircraft. Deliveries begin in 2027 and the "
            "fleet plan calls for further deliveries from Toulouse.",
        ),
        (
            "Emirates deploys new Boeing 777 fleet to add flights on India routes",
            "The widebody deliveries let the carrier run an additional frequency to "
            "three cities; the fleet renewal continues.",
        ),
        (
            "Q3 profit funds a capacity increase across Southeast Asia",
            "The airline said full year guidance is unchanged; net income of $400 "
            "million and a lower debt load pay for the expansion.",
        ),
    ],
)
async def test_fleet_or_finance_news_with_a_market_effect_becomes_revenue_management(title, body):
    """The owner's rule: an order is not a story this desk publishes, but the
    capacity it lands in a market we sell is. Every case here keeps scoring
    highest as fleet or finance on raw keywords -- the shift is what files it
    where the desk will see it."""
    assert await provider.categorize(title, body) == "revenue_management"


@pytest.mark.parametrize(
    "expected,title,body",
    [
        (
            "fleet",
            "Airline orders 50 Boeing 737 MAX aircraft",
            "The firm order covers deliveries from 2028. The aircraft purchase is "
            "valued at $6 billion and includes an option for 25 more Boeing jets.",
        ),
        (
            "fleet",
            "SR Technics signs engine maintenance agreement",
            "The MRO deal covers overhaul and inspection work on the lessor's A320 "
            "fleet, with a retrofit programme to follow.",
        ),
        (
            "finance",
            "Airline posts $1.2 billion net income for the third quarter",
            "Quarterly earnings beat estimates. The full year guidance was raised and "
            "the dividend held; investors pushed the stock up.",
        ),
    ],
)
async def test_plain_order_and_results_news_stays_put(expected, title, body):
    """The other half of the same rule, and the half that keeps it honest. The
    shift is a correctness rule, not a way to refill the sections the newspaper
    just dropped: a bare order, a maintenance deal and a set of quarterly
    results carry no market signal and must not move."""
    assert await provider.categorize(title, body) == expected


async def test_the_shift_never_fires_outside_fleet_and_finance():
    """A safety story is a safety story however commercially it is worded --
    the rule reads only the two categories it names."""
    category = await provider.categorize(
        "Emergency landing after mayday call on a new route",
        "The aircraft was diverted following an in-flight emergency and mayday "
        "declaration; an investigation is under way.",
    )
    assert category == "safety"
