"""Risk Radarı: the false-positive guards, the closed taxonomy, and the API's
weighted country grouping.

The false-positive tests carry the most weight here. This vocabulary overlaps
with everyday aviation and business prose more than any other in the app --
"fare war" and "price war" are literally revenue_management keywords, and
"fire" appears in aviation copy constantly without ever meaning a wildfire --
so the guards in app/llm/heuristic.py are the feature, not an optimisation.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.risks import UNKNOWN_COUNTRY, list_risks
from app.llm.base import EntityMention
from app.llm.heuristic import (
    _RISK_CONTEXT,
    _RISK_RULES,
    _keyword_pattern,
    classify_risk_heuristic,
    detect_risk_place,
    detect_risk_severity,
    detect_risk_type,
    fold_text,
)
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.taxonomy import (
    RISK_FAMILIES,
    RISK_SEVERITY_WEIGHT,
    RISK_TYPE_FAMILY,
    RISK_TYPE_LABELS_TR,
    RISK_TYPES,
    is_valid_risk_type,
    risk_family_of,
)

NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# False-positive guards
# --------------------------------------------------------------------------

# Every one of these is ordinary aviation/business copy that contains a risk
# token. All must classify as None.
AVIATION_PROSE_NOT_RISK = [
    pytest.param(
        "Ryanair and Wizz Air enter fare war on Polish routes",
        "A price war broke out. The fare war is expected to compress yields all summer.",
        id="fare_war_is_pricing_not_conflict",
    ),
    pytest.param(
        "Boeing under fire from regulators over MAX certification",
        "The planemaker came under fire from the FAA. Executives were fired up about it.",
        id="under_fire_and_fired_up",
    ),
    pytest.param(
        "Firefighting demo thrills crowds at Farnborough",
        "A firefighting aircraft flew a water-drop demonstration flight for spectators.",
        id="firefighting_demo_at_airshow",
    ),
    pytest.param(
        "Engine fire prompts emergency landing at Heathrow",
        "An engine fire triggered a fire warning. The crew made an emergency landing.",
        id="aircraft_fire_is_safety_not_wildfire",
    ),
    pytest.param(
        "Airline reports flood of bookings after route launch",
        "A flood of bookings followed as the carrier flooded the market with cheap seats.",
        id="flood_as_volume_metaphor",
    ),
    pytest.param(
        "Perfect storm of costs hits European carriers",
        "A perfect storm of fuel and labour costs. Executives brainstorm amid a media storm.",
        id="perfect_storm_metaphor",
    ),
    pytest.param(
        "Chief executive suffers heart attack and steps down",
        "He had a heart attack. The group also fought off a cyber attack last year.",
        id="heart_attack_and_cyberattack",
    ),
    pytest.param(
        "Pilots strike enters second week at Lufthansa",
        "Cabin crew joined the strike. Industrial action over pay continues.",
        id="labour_strike_is_not_civil_unrest",
    ),
    pytest.param(
        "Political earthquake as chief executive resigns",
        "Analysts called it a seismic shift and a political earthquake for the sector.",
        id="political_earthquake_metaphor",
    ),
    pytest.param(
        "Technology demonstration aircraft unveiled at expo",
        "The demonstrator aircraft completed its first demonstration flight this week.",
        id="demonstration_flight_is_not_protest",
    ),
    pytest.param(
        "Airbus wins bidding war for lessor stake",
        "A bidding war and a war of words followed. Trade war tariffs still bite.",
        id="bidding_and_trade_war",
    ),
    pytest.param(
        "Sektore darbe: yeni bilet vergisi geliyor",
        "Yeni vergi sektore darbe vurdu. Ekonomiye darbe niteliginde bir karar.",
        id="turkish_darbe_as_figurative_blow",
    ),
    pytest.param(
        "Conflict of interest probe opened at airport authority",
        "A scheduling conflict delayed the board meeting; conflict resolution is ongoing.",
        id="conflict_of_interest",
    ),
    pytest.param(
        "Thunderstorms delay departures at Atlanta",
        "Thunderstorms caused rolling delays. Severe weather is forecast for tomorrow.",
        id="routine_thunderstorm_delays_need_disaster_context",
    ),
]


@pytest.mark.parametrize(("title", "content"), AVIATION_PROSE_NOT_RISK)
def test_ordinary_aviation_prose_is_not_a_risk_event(title, content):
    assert detect_risk_type(title, content) is None


def test_bare_fire_never_classifies_as_wildfire():
    """The single most dangerous token in this vocabulary.

    "fire" needs an explicit wildland qualifier; on its own it is an aviation
    safety word, and every phrasing below appeared in the reasoning behind the
    wildfire rule's compound-only keyword list.
    """
    for title in (
        "Cargo fire forces diversion",
        "Cabin fire investigation continues",
        "Hangar fire destroys two business jets",
        "Fire drill held at the terminal",
        "Airline comes under fire over refunds",
    ):
        assert detect_risk_type(title, "The fire was extinguished.") is None


def test_wildfire_requires_a_wildland_qualifier_but_then_matches():
    assert detect_risk_type("Wildfires force evacuation of Rhodes", "Forest fires spread.") == (
        "wildfire"
    )
    assert detect_risk_type("Bushfires close Sydney airspace", "A brush fire jumped the road.") == (
        "wildfire"
    )


# Every one of these was a real false positive found by running the classifier
# over 30 days (7.670 articles) of production data -- they are regression
# tests, not hypotheticals.
PRODUCTION_FALSE_POSITIVES = [
    pytest.param(
        "RAF Typhoons scrambled to escort Qatar Airways Boeing 777 to Manchester",
        "Fighter jets intercepted the aircraft after it failed to respond to ATC.",
        id="typhoon_the_fighter_jet",
    ),
    pytest.param(
        "How The Dassault Rafale Stacks Up Against The F-16, Gripen, & Typhoon In 2026",
        "A comparison of European fighter aircraft.",
        id="typhoon_in_a_fighter_comparison",
    ),
    pytest.param(
        "Hawker Hurricane flying alongside a Messerschmitt Bf 109e",
        "The pair flew a display at the air show.",
        id="hurricane_the_warbird",
    ),
    pytest.param(
        "In 1978 the Tornado was a contender in Canada's New Fighter Aircraft Project",
        "The F-18 Hornet won the competition.",
        id="tornado_the_fighter_jet",
    ),
    pytest.param(
        "NOAA's Gulfstream G-IV N49RF 'Gonzo' returning to base",
        "The hurricane hunter aircraft returned to Lakeland.",
        id="hurricane_hunter_research_aircraft",
    ),
    pytest.param(
        "Solo uno de cada cuatro pilotos del Lufthansa Group recomendaria su profesion",
        "La junta directiva presento los resultados del trimestre.",
        id="spanish_junta_is_a_board_not_a_coup",
    ),
    pytest.param(
        "Pilot suffers serious injuries in airshow incident at Stow Maries",
        "The Great War aerodrome hosted a warbird display when the pilot was injured.",
        id="great_war_aerodrome_heritage_prose",
    ),
    pytest.param(
        "400-Year-Old Sairin-ji Temple Destroyed in Devastating Fire in Saga, Japan",
        "A blaze destroyed the historic temple overnight.",
        id="structure_fire_is_not_a_wildfire",
    ),
    pytest.param(
        "Seven killed in Argentine firefighting helicopter crash during training mission",
        "The firefighting helicopter came down during a training flight, killing seven.",
        id="firefighting_aircraft_accident_is_not_a_wildfire",
    ),
    pytest.param(
        "From 76 F-22 Raptors To 200 Next-Gen Fighters",
        "The magnitude of the expansion is huge, with damage to other budgets.",
        id="magnitude_must_not_bootstrap_an_earthquake",
    ),
    pytest.param(
        "Berlin Pride ends in chaos after vehicle drives into crowd",
        "Chaos erupted; nine were injured and an evacuation followed.",
        id="chaos_erupted_is_not_a_volcano",
    ),
    pytest.param(
        "Long-haul Delta flight diverts twice after lavatory leak floods cabin",
        "The leak floods the cabin and caused damage.",
        id="lavatory_leak_floods_cabin",
    ),
    pytest.param(
        "Why The Ilyushin Il-96 Is Making An Unexpected Comeback",
        "Russia's invasion reshaped the fleet picture for domestic carriers.",
        id="invasion_mentioned_without_event_reporting",
    ),
    pytest.param(
        "Nemrut Kalderası Milli Park İlan Edildi: Bitlis Turizminde Yeni Dönem",
        "Türkiye'nin en önemli volkanik oluşumlarından Nemrut Kalderası için yeni "
        "bir dönem başladı. Türkiye'nin en dikkat çekici volkanik peyzajlarından "
        "birine sahip olan göl, Nemrut Kalderası Milli Parkı adıyla Türkiye'nin "
        "milli park destinasyonları arasına girmiş oldu.",
        id="dormant_crater_lake_tourism_is_not_a_volcano",
    ),
]


@pytest.mark.parametrize(("title", "content"), PRODUCTION_FALSE_POSITIVES)
def test_production_false_positives_stay_unclassified(title, content):
    assert detect_risk_type(title, content) is None


def test_weather_named_aircraft_guard_does_not_suppress_real_weather():
    """The discount is aimed at the aircraft, not at the hazard -- a real
    typhoon or hurricane must survive it."""
    assert detect_risk_type(
        "Typhoon Noul threatens air cargo at 36 South China airports",
        "The typhoon forced cancellations and evacuations across Guangdong.",
    ) == "storm"
    assert detect_risk_type(
        "Hurricane Lala threatens Hawaii's Big Island",
        "The hurricane destroyed homes and a state of emergency was declared.",
    ) == "storm"


def test_a_real_eruption_still_classifies_as_volcano():
    """"volkanik"/"volcano" moved to weak after the Nemrut tourism false
    positive -- a real eruption still has to survive that. Breaking coverage
    carries casualty/evacuation language almost immediately, same bet already
    made for storm/war/coup/attack/unrest."""
    assert detect_risk_type(
        "Volcano erupts near Nemrut, ash cloud grounds flights",
        "The eruption forced the evacuation of nearby villages.",
    ) == "volcano"
    assert detect_risk_type(
        "Nemrut Kalderası'nda volkanik patlama",
        "Patlama sonrası bölge tahliye edildi, çok sayıda ev hasar gördü.",
    ) == "volcano"


def test_died_and_became_do_not_collide_into_the_same_severity():
    """ASCII-folding turns "öldü" (died) and "oldu" (became/happened, one of
    the most common Turkish auxiliary verbs) into the identical token --
    "...milli park destinasyonları arasına girmiş oldu" (has thus become a
    national park) inflated a tourism story to HIGH severity in production."""
    assert detect_risk_severity(
        "Nemrut Kalderası Milli Park İlan Edildi",
        "Türkiye'nin milli park destinasyonları arasına girmiş oldu.",
    ) != "high"
    # A real death report must still resolve high through the forms that
    # don't collide with "oldu".
    assert detect_risk_severity(
        "Depremde can kaybı",
        "İki kişi hayatini kaybetti, bir kişi de öldürüldü.",
    ) == "high"


def test_no_weak_term_is_also_a_context_word():
    """A weak term that also appears in _RISK_CONTEXT satisfies its own
    precondition and matches unconditionally. "magnitude" was in both, and
    tagged a fighter-procurement story as an earthquake."""
    context = set(_RISK_CONTEXT)
    for rule in _RISK_RULES:
        assert not (set(rule.weak) & context), f"{rule.slug} weak overlaps context"


def test_empty_keyword_tuple_never_matches():
    """`"|".join(())` is "", and re.compile("") matches at every position -- so
    a rule with an empty tier would score against every character in the
    article. The wildfire rule has exactly such an empty weak tier."""
    assert _keyword_pattern(()).findall("anything at all here") == []
    assert detect_risk_type("Airline reports record profit", "Revenue grew strongly.") is None


def test_masking_is_per_phrase_not_per_article():
    """An article that uses a metaphor AND reports a real event must still
    classify -- the guard removes the phrase, not the article."""
    got = detect_risk_type(
        "Fare war continues as civil war closes airspace",
        "The fare war rages on. Meanwhile the civil war has killed hundreds and shelling continues.",
    )
    assert got == "war"


# --------------------------------------------------------------------------
# Turkish folding
# --------------------------------------------------------------------------


def test_turkish_diacritics_survive_folding():
    """normalize_text's character class is [^a-z0-9\\s], so "yangın" would
    otherwise become "yang n" and never match anything."""
    assert fold_text("Orman Yangını") == "orman yangini"
    assert fold_text("Saldırı") == "saldiri"
    # The apostrophe goes the way of all punctuation (normalize_text), so the
    # Turkish possessive suffix splits off as its own token -- harmless, since
    # matching is whole-word and "istanbul" is what the city gazetteer keys on.
    assert fold_text("İstanbul'da fırtına") == "istanbul da firtina"


def test_turkish_risk_terms_classify():
    assert detect_risk_type("Orman yangini Antalya'yi vurdu", "Tahliye edildi, afet ilan edildi.") == (
        "wildfire"
    )
    assert detect_risk_type("Askeri darbe girisimi", "Darbe girisimi sonrasi ucuslar durdu.") == (
        "coup"
    )


# --------------------------------------------------------------------------
# Closed taxonomy
# --------------------------------------------------------------------------


def test_taxonomy_is_nine_types_in_two_families():
    assert len(RISK_TYPES) == 9
    assert {r.family for r in RISK_TYPES} == set(RISK_FAMILIES) == {"natural", "conflict"}
    assert len({r.slug for r in RISK_TYPES}) == 9


def test_every_type_has_a_family_and_a_turkish_label():
    for rule in RISK_TYPES:
        assert RISK_TYPE_FAMILY[rule.slug] == rule.family
        assert RISK_TYPE_LABELS_TR[rule.slug].strip()


@pytest.mark.parametrize("bad", ["tsunami", "hurricane", "landslide", "", "WAR", None])
def test_off_taxonomy_slugs_are_rejected(bad):
    """A model inventing a plausible-sounding hazard must write null, not a
    slug the frontend has no icon, label or filter chip for."""
    assert is_valid_risk_type(bad) is False
    assert risk_family_of(bad) is None


def test_detector_only_ever_emits_valid_slugs():
    for title, body in [
        ("Magnitude 7 earthquake kills hundreds", "Rescue teams search the rubble."),
        ("Volcanic ash cloud grounds flights", "The volcanic eruption sent ash high."),
        ("Terrorist attack at the airport", "A suicide bomber killed twelve."),
    ]:
        assert is_valid_risk_type(detect_risk_type(title, body))


def test_severity_uses_the_apps_high_medium_low_convention():
    assert detect_risk_severity("earthquake kills hundreds", "") == "high"
    assert detect_risk_severity("flooding injured dozens", "") == "medium"
    assert detect_risk_severity("minor tremor recorded", "") == "low"
    assert set(RISK_SEVERITY_WEIGHT) == {"high", "medium", "low"}


def test_place_resolution_prefers_country_entities_and_never_contradicts_them():
    entities = [EntityMention("country", "Turkey", None)]
    country, city = detect_risk_place(
        "Earthquake hits Kahramanmaras", "Damage reported across the region.", entities
    )
    assert country == "Turkey"
    assert city == "Kahramanmaras"

    # A London dateline on a story about a flood in Jakarta must not place the
    # flood in London.
    country, city = detect_risk_place(
        "Flooding in Jakarta", "Reported from London by our correspondent.",
        [EntityMention("country", "Indonesia", None)],
    )
    assert (country, city) == ("Indonesia", "Jakarta")


def test_non_risk_article_classifies_to_all_none():
    result = classify_risk_heuristic("Airline reports record quarterly profit", "Revenue grew.", [])
    assert result == {"risk_type": None, "severity": None, "country": None, "city": None}


# --------------------------------------------------------------------------
# API: weighted score, ordering, grouping
# --------------------------------------------------------------------------


async def _risk_article(
    db, source, *, url, risk_type, severity, country, city=None, days_ago=1,
    title="t", entities=(),
):
    from app.taxonomy import risk_family_of as family_of

    published = NOW - timedelta(days=days_ago)
    article = Article(
        source_id=source.id,
        url=url,
        title=title,
        raw_content="body",
        published_at=published,
        fetched_at=published,
        content_hash=url,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id,
            headline=f"{risk_type} in {country}",
            category="safety",
            risk_type=risk_type,
            risk_family=family_of(risk_type),
            risk_severity=severity,
            risk_country=country,
            risk_city=city,
        )
    )
    for entity in entities:
        db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    await db.flush()
    return article


async def _source(db, name="S", tier=None):
    from app.models.source import Source

    source = Source(name=name, url=f"https://example.com/{name}", source_type="rss", tier=tier)
    db.add(source)
    await db.flush()
    return source


async def _entity(db, entity_type, name, code=None):
    entity = Entity(entity_type=entity_type, name=name, code=code)
    db.add(entity)
    await db.flush()
    return entity


async def test_the_same_eruption_from_three_outlets_becomes_one_signal(db_session):
    """Real production case: the August 2026 Etna eruption/Catania Airport
    closure was reported by three outlets, independently classified three
    times, and came out as three cards in three different country groups
    (Italy/medium, Malta/low, unspecified/high) -- Malta because an AeroTime
    aside about ash "extending between eastern Malta and northern Libya"
    outranked its own correctly-resolved Catania/Italy city match, and
    unspecified because the eTurboNews tourism-angle piece never named a
    country string at all. One event, one signal: severity takes the most
    severe member (never under-report), country/city takes whichever member
    actually resolved a city (real evidence beats an incidental country
    mention or nothing)."""
    source = await _source(db_session)
    italy = await _entity(db_session, "country", "Italy")
    cta = await _entity(db_session, "airport", "Catania Fontanarossa", code="CTA")

    await _risk_article(
        db_session, source,
        url="https://aviation24.be/etna",
        title="Etna patlaması Catania Havalimanı'nın kapatılmasına neden olurken 700 uçuş iptal edildi",
        risk_type="volcano", severity="medium", country="Italy", city="Catania",
        entities=(italy, cta),
    )
    await _risk_article(
        db_session, source,
        url="https://aerotime.aero/etna",
        title="Mount Etna küllerinin Catania Havalimanı'nı kapatmasıyla birlikte "
        "Sicilya genelinde 700 uçuş iptal edildi",
        # The real bug: an incidental "ash reached Malta" aside resolved the
        # whole article to Malta with no city at all.
        risk_type="volcano", severity="low", country="Malta", city=None,
        entities=(italy, cta),
    )
    await _risk_article(
        db_session, source,
        url="https://eturbonews.com/etna",
        title="Mount Etna Eruption Creates a Tourism Boom and Travel Nightmare in Sicily",
        risk_type="volcano", severity="high", country=None, city=None,
        entities=(italy, cta),
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)

    all_items = [item for country in out.countries for item in country.items]
    assert len(all_items) == 1, f"expected one merged signal, got {len(all_items)}"

    signal = all_items[0]
    assert signal.severity == "high"  # the most severe member, never watered down
    assert signal.country == "Italy"  # the city-bearing member's placement wins
    assert signal.city == "Catania"
    assert signal.source_count == 3
    assert out.total == 1


async def test_two_different_earthquakes_sharing_a_country_stay_separate():
    """Sharing a country entity is necessary but not sufficient -- two
    unrelated earthquakes in Turkey must not merge into one signal just
    because both name the same country. same_event() also requires a shared
    distinctive token (a city, a number), which two genuinely different
    stories will not have."""
    from app.pipeline.clustering import EventCandidate, same_event

    turkey = "TURKEY"
    a = EventCandidate(
        article_id="a",
        title="6.2 magnitude earthquake strikes Izmir, flights diverted",
        entities=frozenset({turkey}),
        tier="trade",
        published_at="2026-08-10T10:00:00",
    )
    b = EventCandidate(
        article_id="b",
        title="Kahramanmaraş'ta deprem: havalimanı kapatıldı",
        entities=frozenset({turkey}),
        tier="trade",
        published_at="2026-08-13T10:00:00",
    )
    assert same_event(a, b) is False


async def test_countries_are_ranked_by_weighted_score_not_article_count(db_session):
    """high=3, medium=2, low=1. A country with one high-severity event must
    outrank a country with two low-severity ones (3 > 2), which raw counts
    would order the other way round."""
    source = await _source(db_session)
    await _risk_article(
        db_session, source, url="https://e.com/1", risk_type="earthquake",
        severity="high", country="Turkey",
    )
    await _risk_article(
        db_session, source, url="https://e.com/2", risk_type="storm",
        severity="low", country="Japan",
    )
    await _risk_article(
        db_session, source, url="https://e.com/3", risk_type="flood",
        severity="low", country="Japan",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)

    assert [c.country for c in out.countries] == ["Turkey", "Japan"]
    assert out.countries[0].score == 3  # one high
    assert out.countries[1].score == 2  # two lows
    assert out.countries[1].count == 3 - 1  # ...but MORE articles
    assert out.total == 3


async def test_severity_counts_are_precomputed_per_country(db_session):
    """The micro-bar must not have to recount them client-side."""
    source = await _source(db_session, "S2")
    for i, severity in enumerate(["high", "high", "medium", "low"]):
        await _risk_article(
            db_session, source, url=f"https://e2.com/{i}", risk_type="wildfire",
            severity=severity, country="Greece",
        )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    greece = next(c for c in out.countries if c.country == "Greece")
    assert (greece.severity_counts.high, greece.severity_counts.medium, greece.severity_counts.low) == (2, 1, 1)
    assert greece.score == 3 + 3 + 2 + 1
    assert greece.count == 4


async def test_items_are_grouped_by_country_and_worst_first_within_it(db_session):
    source = await _source(db_session, "S3")
    await _risk_article(
        db_session, source, url="https://e3.com/low", risk_type="flood",
        severity="low", country="Italy", city="Milan",
    )
    await _risk_article(
        db_session, source, url="https://e3.com/high", risk_type="earthquake",
        severity="high", country="Italy", city="Naples",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    italy = next(c for c in out.countries if c.country == "Italy")
    assert [i.severity for i in italy.items] == ["high", "low"]
    assert [i.city for i in italy.items] == ["Naples", "Milan"]
    # Family and Turkish label are resolved server-side.
    assert italy.items[0].risk_family == "natural"
    assert italy.items[0].risk_type_label_tr == "Deprem"


async def test_unplaced_events_are_kept_but_sorted_last(db_session):
    """An event with no resolved country is real -- only its placement is
    unknown -- so it must not be dropped, and must not top the ranking."""
    source = await _source(db_session, "S4")
    await _risk_article(
        db_session, source, url="https://e4.com/1", risk_type="war",
        severity="high", country=None,
    )
    await _risk_article(
        db_session, source, url="https://e4.com/2", risk_type="storm",
        severity="low", country="Spain",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert [c.country for c in out.countries] == ["Spain", UNKNOWN_COUNTRY]
    assert out.total == 2


async def test_window_excludes_older_articles_and_flags_fresh_ones(db_session):
    source = await _source(db_session, "S5")
    await _risk_article(
        db_session, source, url="https://e5.com/fresh", risk_type="flood",
        severity="medium", country="France", days_ago=0,
    )
    await _risk_article(
        db_session, source, url="https://e5.com/old", risk_type="flood",
        severity="medium", country="France", days_ago=40,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.countries[0].items[0].is_fresh is True

    wide = await list_risks(days=90, response=Response(), db=db_session)
    assert wide.total == 2
    assert [i.is_fresh for i in wide.countries[0].items] == [True, False]


async def test_type_and_family_counts_are_returned_for_the_filter_chips(db_session):
    source = await _source(db_session, "S6")
    await _risk_article(
        db_session, source, url="https://e6.com/1", risk_type="wildfire",
        severity="high", country="Portugal",
    )
    await _risk_article(
        db_session, source, url="https://e6.com/2", risk_type="wildfire",
        severity="low", country="Spain",
    )
    await _risk_article(
        db_session, source, url="https://e6.com/3", risk_type="attack",
        severity="high", country="Egypt",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.type_counts == {"wildfire": 2, "attack": 1}
    assert out.family_counts == {"natural": 2, "conflict": 1}


async def test_empty_radar_is_a_valid_empty_response(db_session):
    """A quiet radar is a good outcome, not an error."""
    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 0
    assert out.countries == []
    assert out.type_counts == {}
