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
from sqlalchemy import select

from app.api.v1.risks import DEFAULT_WINDOW_DAYS, UNKNOWN_COUNTRY, list_risks
from app.llm.base import EntityMention
from app.llm.heuristic import (
    AVIATION_RELEVANCE_BODY,
    AVIATION_RELEVANCE_GATE,
    AVIATION_RELEVANCE_TITLE,
    LOCATION_CONFIDENCE_AIRPORT_DERIVED,
    LOCATION_CONFIDENCE_CITY_CONFIRMED,
    LOCATION_CONFIDENCE_CONFLICT,
    LOCATION_CONFIDENCE_SOURCE_ONLY,
    _RISK_CONTEXT,
    _RISK_RULES,
    _keyword_pattern,
    classify_risk_heuristic,
    detect_aviation_relevance,
    detect_currency_flags,
    detect_risk_place,
    detect_risk_severity,
    detect_risk_type,
    fold_text,
    is_retrospective,
    resolve_risk_location,
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
    pytest.param(
        "Boeing MH-139A Grey Wolf helicopter cleared to guard US nuclear "
        "missile fields",
        # Faithful to what the fetcher actually stores: the article, then the
        # site's related-articles rail. The story itself reports a procurement
        # milestone and contains no hazard vocabulary at all -- "troops" and
        # the context words that license it come from three different teasers
        # at the bottom of the page.
        "The US Air Force Global Strike Command announced that the Boeing "
        "MH-139A Grey Wolf reached initial operational capability, clearing "
        "the helicopter for the intercontinental ballistic missile security "
        "mission it was procured to perform. It replaces the UH-1N fleet at "
        "Malmstrom Air Force Base. More from AeroTime: airline begins "
        "evacuation flights; rescue crews reach the crash site; troops board "
        "a transport in the disaster response exercise.",
        id="military_procurement_milestone_with_a_related_links_rail",
    ),
    pytest.param(
        'TCMB\'den "Deprem Bölgesi Konut Arzı ve Bölgesel Kira Enflasyonu '
        'Gelişmeleri" analizi',
        "TCMB analizinde, dezenflasyon sürecinde en fazla katılık görülen "
        "kalemlerden birinin kira olduğu, bunda 6 Şubat depremleri sonrası "
        "konut stokundaki kayıp ve bölgeden diğer illere göçlerin etkili "
        "olduğu belirtildi. Deprem bölgesinde konut arzı artmaya devam ediyor.",
        id="central_bank_rent_analysis_naming_the_earthquake_region",
    ),
]


@pytest.mark.parametrize(("title", "content"), PRODUCTION_FALSE_POSITIVES)
def test_production_false_positives_stay_unclassified(title, content):
    assert detect_risk_type(title, content) is None


# The retrospective/anniversary family. Kept in its own list rather than folded
# into PRODUCTION_FALSE_POSITIVES because that one carries a specific claim --
# every row measured over 30 days of production articles -- and these were
# written from the wire conventions the guard targets, not harvested from that
# run. Same discipline, different provenance, so a different name.
#
# All of them describe REAL disasters. That is the point: nothing here is a
# misclassification of the hazard, it is a misplacement in time. Publication
# time is the only clock this pipeline has, so an anniversary piece filed this
# morning becomes a signal from this morning unless the headline's own voice
# stops it. See app/llm/heuristic.py's RETROSPECTIVE GUARD.
RETROSPECTIVE_FALSE_POSITIVES = [
    pytest.param(
        "Kahramanmaraş depreminin yıl dönümünde anma töreni düzenlendi",
        "6 Şubat depremlerinde hayatını kaybedenler anıldı. On binlerce kişi "
        "öldü, on bir ilde binalar yıkıldı, yüz binlerce kişi tahliye edildi.",
        id="turkish_anniversary_commemoration",
    ),
    pytest.param(
        "Remembering Hurricane Katrina, 20 Years On",
        "The hurricane killed more than 1,800 people and destroyed swathes of "
        "New Orleans after it made landfall in 2005.",
        id="english_anniversary_retrospective",
    ),
    pytest.param(
        "On This Day In 1988: The Ramstein Airshow Disaster That Killed 70",
        "A mid-air collision sent a burning jet into the crowd; 70 people died "
        "and hundreds were injured at the air base.",
        id="on_this_day_column",
    ),
    pytest.param(
        "In 2011 A Tsunami And Earthquake Struck Fukushima — How Japan Rebuilt "
        "Its Regional Airports",
        "The magnitude 9.0 earthquake and the tsunami that followed destroyed "
        "the region, killed thousands and forced a mass evacuation.",
        # The year+past-tense trigger rather than a marker phrase: this headline
        # never says "anniversary", it just narrates.
        id="old_year_with_past_tense_narration",
    ),
]


@pytest.mark.parametrize(("title", "content"), RETROSPECTIVE_FALSE_POSITIVES)
def test_retrospective_coverage_is_not_a_live_signal(title, content):
    assert detect_risk_type(title, content) is None


def test_the_retrospective_guard_reads_the_headline_not_the_body():
    """Live coverage reaches backwards all the time -- "the worst since 2020",
    "a similar quake 20 years ago" -- and vetoing on that would suppress the
    event the article is actually reporting. The guard is title-scoped for
    exactly this case."""
    assert detect_risk_type(
        "Elazığ'da deprem: havalimanı geçici olarak kapatıldı",
        "2020 depreminden bu yana bölgedeki en büyük sarsıntı. Onlarca kişi "
        "hayatını kaybetti, ekipler enkaz altında arama yapıyor.",
    ) == "earthquake"


def test_a_year_alone_and_past_tense_alone_are_both_harmless():
    """Neither half of the second trigger fires on its own. A current-year
    headline is not history, and a headline with no year is just a headline."""
    assert is_retrospective("2026 hurricane season forecast raised again") is False
    assert is_retrospective("Storm was severe, airports say") is False
    # Both halves, and now it is a retelling.
    assert is_retrospective("Storm of 2019 was the worst on record", year_now=2026) is True


# Weak tiers found by probing the shipped rules rather than by a production
# run -- each one classified as a live risk event before the fix beside it, and
# each fix narrows the vocabulary rather than widening it.
CONTEXT_HARDENING_FALSE_POSITIVES = [
    pytest.param(
        "Royal Canadian Air Force CH-148 Cyclone helicopters grounded after fleet inspection",
        "The Cyclone fleet returned to service after a maintenance directive "
        "from the air force.",
        # "cyclone" was a STRONG storm keyword and the weather-named-aircraft
        # discount only knew Typhoon, Tornado and Hurricane -- the CH-148
        # Cyclone is an in-service RCAF type and slipped straight through.
        id="cyclone_the_maritime_helicopter",
    ),
    pytest.param(
        "Sikorsky delivers final CH-148 Cyclone to Canada",
        "The Cyclone is the RCAF maritime helicopter replacing the Sea King.",
        id="cyclone_type_designation_in_a_delivery_story",
    ),
    pytest.param(
        "Ryanair and Lufthansa at war over Frankfurt slots",
        "The two carriers are at war over capacity at the hub after the "
        "regulator's ruling.",
        # "at war" was strong, so the commercial construction the other war
        # metaphors were already masked for ("fare war", "bidding war") walked
        # in through a different door.
        id="at_war_over_is_the_commercial_construction",
    ),
    pytest.param(
        "Así se lava un Boeing 747: el proceso completo",
        "Cada cuánto se lava un avión y cómo se hace el lavado exterior en el hangar.",
        # Same shape as the Spanish "junta" bug: "lava" is the third-person
        # present of *lavar*, and it was a STRONG volcano keyword.
        id="spanish_lava_is_a_verb_not_a_volcano",
    ),
    pytest.param(
        "Uçakta yakıt hortumu arızası tespit edildi",
        "Teknik ekip hidrolik hortum değişimi yaptı; uçak servise döndü.",
        # "hortum" is Turkish for both "tornado" and "hose", and it was strong.
        id="turkish_hortum_is_also_a_hose",
    ),
]


@pytest.mark.parametrize(("title", "content"), CONTEXT_HARDENING_FALSE_POSITIVES)
def test_context_hardening_cases_stay_unclassified(title, content):
    assert detect_risk_type(title, content) is None


def test_the_hardening_never_suppresses_the_real_hazard():
    """Each fix above is a narrowing, and a narrowing is only correct if the
    thing it was aimed at still gets through. A real cyclone brings no
    military-aviation vocabulary, a real hortum flattens greenhouses, and a
    real lava flow is a compound."""
    assert detect_risk_type(
        "Cyclone Chido batters Mayotte, airport closed",
        "The cyclone destroyed homes and killed dozens across the island.",
    ) == "storm"
    assert detect_risk_type(
        "Antalya'da hortum: seralar yıkıldı, yaralılar var",
        "Şiddetli hortum seraları yıktı; birçok kişi yaralı, ekipler bölgede.",
    ) == "storm"
    assert detect_risk_type(
        "Etna'da lava akıntısı Catania Havalimanı'nı kapattı",
        "Volkanik kül bulutu nedeniyle uçuşlar iptal edildi, köyler tahliye edildi.",
    ) == "volcano"
    # "at war" without the commercial "over" is still a war.
    assert detect_risk_type(
        "Sudan has been at war since April",
        "Airstrikes and shelling continue; thousands have been killed.",
    ) == "war"


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
    title="t", entities=(), summary_tr=None,
    # The corpus median (see risks.py CONFIDENCE_GATING), not 0.0. Two reasons:
    # 0.0 is a score pipeline/verify.py's formula cannot produce -- its floor is
    # 0.4 -- so a fixture claiming it was never describing a real row, and every
    # test below that is not about the confidence gate wants an ordinary,
    # publishable signal rather than one the gate is entitled to drop.
    confidence_score=0.61,
    corroborating_source_count=1,
    headline_tr=None, translated_at=None,
    # The verification columns, all defaulting to NULL -- which is what every
    # row written before this revision carries, and what each gate is required
    # to publish rather than drop. Tests that are ABOUT a gate pass a value;
    # every other test here doubles as a check that an unscored row still
    # reaches the page.
    is_current_event=None,
    aviation_relevance_score=None,
    aviation_relevance_source=None,
    aviation_impact_evidence=None,
    aviation_impact_status=None,
    location_confidence=None,
    mentioned_locations=None,
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
            headline_tr=headline_tr,
            translated_at=translated_at,
            summary_tr=summary_tr,
            confidence_score=confidence_score,
            corroborating_source_count=corroborating_source_count,
            is_current_event=is_current_event,
            aviation_relevance_score=aviation_relevance_score,
            aviation_relevance_source=aviation_relevance_source,
            aviation_impact_evidence=aviation_impact_evidence,
            aviation_impact_status=aviation_impact_status,
            location_confidence=location_confidence,
            mentioned_locations=mentioned_locations,
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
    # Still stamped: "we looked at 09:14 and there was nothing" is a different
    # statement from "we have not looked", and the page shows the first one.
    assert out.generated_at is not None


# --------------------------------------------------------------------------
# API: the cluster, unpacked
#
# Every field below was already loaded by the same query and discarded before
# serialization -- the page could show a headline and a country while the
# evidence behind the signal sat in memory on every request. These tests pin
# down both what is now served and, as importantly, what it is allowed to
# claim: publication times are never event times, and a named airport is
# never an affected one.
# --------------------------------------------------------------------------


async def test_members_are_the_publication_chronology_oldest_first(db_session):
    """The drawer draws this as a timeline, so the order is load-bearing: it
    is the order the story was TOLD in, which is the only chronology this data
    has. Oldest first, because that is the first telling the rest are echoing
    -- the same preference pick_primary already makes."""
    source = await _source(db_session, "S7", tier="agency")
    italy = await _entity(db_session, "country", "Italy")
    cta = await _entity(db_session, "airport", "Catania Fontanarossa", code="CTA")

    await _risk_article(
        db_session, source, url="https://m.com/late",
        title="Etna küllerinin Catania Havalimanı'nı kapatmasıyla 700 uçuş iptal edildi",
        risk_type="volcano", severity="medium", country="Italy", city="Catania",
        days_ago=1, entities=(italy, cta),
    )
    await _risk_article(
        db_session, source, url="https://m.com/early",
        title="Etna patlaması Catania Havalimanı'nın kapanmasına yol açtı, 700 uçuş iptal",
        risk_type="volcano", severity="high", country="Italy", city="Catania",
        days_ago=3, entities=(italy, cta),
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    signal = out.countries[0].items[0]

    assert [m.url for m in signal.members] == ["https://m.com/early", "https://m.com/late"]
    assert signal.members[0].published_at < signal.members[1].published_at
    assert signal.first_reported_at == signal.members[0].published_at
    assert signal.last_reported_at == signal.members[1].published_at
    # The tier the drawer badges each row with, resolved server-side so the
    # frontend never has to know the trust_weight bucketing rules.
    assert {m.source_tier for m in signal.members} == {"agency"}
    assert signal.members_truncated is False


async def test_a_long_cluster_says_its_chronology_is_truncated(db_session):
    """A wire story republished by every aggregator must not turn one card's
    payload into a hundred rows -- but a silently clipped timeline is worse
    than a clipped one that says so."""
    from app.api.v1.risks import MEMBER_CAP

    source = await _source(db_session, "S8")
    turkey = await _entity(db_session, "country", "Turkey")
    for i in range(MEMBER_CAP + 3):
        await _risk_article(
            db_session, source, url=f"https://wire.com/{i}",
            title="Kahramanmaraş'ta 7.2 deprem: havalimanı kapatıldı, tahliye sürüyor",
            risk_type="earthquake", severity="high", country="Turkey", city="Kahramanmaras",
            days_ago=2, entities=(turkey,),
        )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    signal = out.countries[0].items[0]

    assert signal.source_count == MEMBER_CAP + 3  # the count is never clipped
    assert len(signal.members) == MEMBER_CAP
    assert signal.members_truncated is True


async def test_airports_are_distinct_capped_and_ordered(db_session):
    """One code once, however many members named it, and a stable order --
    otherwise the same event lists its airports differently on every request
    depending on how the join came back."""
    from app.api.v1.risks import AIRPORT_CAP

    source = await _source(db_session, "S9")
    turkey = await _entity(db_session, "country", "Turkey")
    airports = [
        await _entity(db_session, "airport", f"Havalimanı {i}", code=f"A{i:02d}")
        for i in range(AIRPORT_CAP + 2)
    ]
    # Both members name IST; it must appear once, not twice.
    ist = await _entity(db_session, "airport", "İstanbul Havalimanı", code="IST")
    await _risk_article(
        db_session, source, url="https://ap.com/1",
        title="İstanbul'da fırtına: uçuşlar iptal edildi, tahliye başladı",
        risk_type="storm", severity="high", country="Turkey", city="Istanbul",
        entities=(turkey, ist, *airports),
    )
    await _risk_article(
        db_session, source, url="https://ap.com/2",
        title="İstanbul'daki fırtına nedeniyle uçuşlar iptal, tahliye sürüyor",
        risk_type="storm", severity="medium", country="Turkey", city="Istanbul",
        entities=(turkey, ist),
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    signal = out.countries[0].items[0]

    assert signal.source_count == 2  # both members feed the airport union
    codes = [a.code for a in signal.airports]
    assert len(codes) == AIRPORT_CAP
    assert len(set(codes)) == len(codes)
    assert codes == sorted(codes)
    # Names ride along so a code chip can carry a title attribute; a bare
    # three-letter code is not a place to anyone who does not already know it.
    assert all(a.name for a in signal.airports)


async def test_a_named_airport_makes_the_aviation_link_direct(db_session):
    """The rule, stated: an aviation-operational event type, or an airport
    named in the coverage. Nothing else. It says why the signal is on an
    aviation desk's radar -- never that a flight moved, which this product
    has no data to claim."""
    from app.api.v1.risks import aviation_link_for

    # The rule table, independent of the database.
    assert aviation_link_for("earthquake", "natural", 0) == "indirect"
    assert aviation_link_for("earthquake", "natural", 1) == "direct"
    assert aviation_link_for("war", "conflict", 0) == "indirect"
    # v2's aviation-operational types are direct on their own merit, with or
    # without an airport entity -- see AVIATION_OPERATIONAL_TYPES on why they
    # cannot occur on today's v1 feed.
    assert aviation_link_for("atc_disruption", "infrastructure", 0) == "direct"
    assert aviation_link_for("accident_incident", "operational", 0) == "direct"

    source = await _source(db_session, "S10")
    greece = await _entity(db_session, "country", "Greece")
    ath = await _entity(db_session, "airport", "Atina Uluslararası", code="ATH")
    await _risk_article(
        db_session, source, url="https://av.com/with",
        title="Atina'da orman yangını: havalimanı kapatıldı",
        risk_type="wildfire", severity="high", country="Greece", city="Athens",
        entities=(greece, ath),
    )
    await _risk_article(
        db_session, source, url="https://av.com/without",
        title="Portekiz'de sel felaketi köyleri vurdu, tahliye edildi",
        risk_type="flood", severity="medium", country="Portugal",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    by_country = {c.country: c.items[0] for c in out.countries}
    assert by_country["Greece"].aviation_link == "direct"
    assert by_country["Portugal"].aviation_link == "indirect"
    assert by_country["Portugal"].airports == []


async def test_is_updated_needs_an_old_first_telling_and_a_new_last_one(db_session):
    """Both halves, and the boundary is 24h on each. This is a statement about
    COVERAGE -- "somebody is still writing about this" -- and never about the
    event, which this data has no lifecycle for."""
    source = await _source(db_session, "S11")
    japan = await _entity(db_session, "country", "Japan")

    # Two tellings three days apart, the newer one inside the last 24h.
    for days_ago, url in ((3, "https://u.com/first"), (0, "https://u.com/latest")):
        await _risk_article(
            db_session, source, url=url,
            title="Sendai'de 6.8 deprem: havalimanı kapandı, tahliye sürüyor",
            risk_type="earthquake", severity="high", country="Japan", city="Sendai",
            days_ago=days_ago, entities=(japan,),
        )
    # A one-article cluster cannot be "updated": its first and last telling are
    # the same moment, so one of the two halves always fails.
    await _risk_article(
        db_session, source, url="https://u.com/single",
        title="Şili'de volkanik patlama sonrası kül bulutu, tahliye edildi",
        risk_type="volcano", severity="medium", country="Chile", days_ago=3,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    by_country = {c.country: c.items[0] for c in out.countries}

    japan_signal = by_country["Japan"]
    assert japan_signal.is_updated is True
    # ...and it is NOT "fresh": the signal itself is three days old. The two
    # badges answer different questions and must not collapse into one.
    assert japan_signal.is_fresh is False

    stale = by_country["Chile"]
    assert stale.is_updated is False
    assert stale.is_fresh is False


async def test_the_region_follows_the_resolved_country_not_the_article(db_session):
    """A Pentagon story about Middle East operations has
    ArticleEnrichment.region = middle-east (it names those countries) and
    risk_country = United States. The detail panel shows Ülke and Bölge side by
    side, so taking the article's region put "United States / Orta Doğu" in one
    card. Both are true about the ARTICLE; only the country's own region is
    true about the PLACE the signal is pinned to."""
    source = await _source(db_session, "S12b")
    article = Article(
        source_id=source.id,
        url="https://r.com/1",
        title="Pentagon awards laser weapon contracts",
        raw_content="body",
        published_at=NOW - timedelta(days=1),
        fetched_at=NOW - timedelta(days=1),
        content_hash="https://r.com/1",
        status="enriched",
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id,
            headline="Laser weapons",
            category="safety",
            region="middle-east",  # every country the article mentions
            risk_type="war",
            risk_family="conflict",
            risk_severity="high",
            risk_country="United States",
        )
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.countries[0].items[0].region == "north-america"


async def test_the_primary_summary_and_confidence_ride_along(db_session):
    source = await _source(db_session, "S12")
    await _risk_article(
        db_session, source, url="https://s.com/1", risk_type="flood",
        severity="medium", country="France",
        summary_tr="Lyon çevresinde sel; birkaç yol kapandı.",
        confidence_score=0.82, corroborating_source_count=3,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    signal = out.countries[0].items[0]
    assert signal.summary_tr == "Lyon çevresinde sel; birkaç yol kapandı."
    assert signal.confidence_score == pytest.approx(0.82)
    assert signal.corroborating_source_count == 3


async def test_an_unsummarised_signal_reports_none_not_an_empty_string(db_session):
    """ArticleEnrichment.summary defaults to "", and "" would render as a card
    with a blank paragraph under the headline -- a summary that says nothing,
    presented as a summary. None is the honest value and the UI hides it."""
    source = await _source(db_session, "S13")
    await _risk_article(
        db_session, source, url="https://s.com/2", risk_type="storm",
        severity="low", country="Spain",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.countries[0].items[0].summary_tr is None


# --------------------------------------------------------------------------
# API: the confidence gate
#
# The thresholds are measured, not chosen -- see app/api/v1/risks.py's
# CONFIDENCE GATING block for the distribution they came out of. What these
# tests pin down is the shape of the rule: where each boundary sits, that
# corroboration overrides it, and that a row nobody scored is not treated as a
# row that scored badly.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        # At or below the gate, with no exemption: not published. This is the
        # calibration this revision moved -- the old floor was 0.58 and let
        # these through quietly. 0.58 and 0.595 are real values from the
        # measured corpus (6 of its 18 risk rows), so this is a deliberate
        # trade of coverage for verification, not a rounding change.
        (0.535, None), (0.565, None), (0.58, None), (0.595, None), (0.60, None),
        # Strictly above the gate. The 0.60-0.61 sliver publishes quietly;
        # from the corpus median up it publishes at full emphasis.
        (0.6099, "low"),
        (0.61, "normal"), (0.67, "normal"), (0.9, "normal"),
    ],
)
async def test_confidence_thresholds_decide_publish_and_emphasis(db_session, score, expected):
    source = await _source(db_session, f"SC{score}")
    await _risk_article(
        db_session, source, url=f"https://c.com/{score}", risk_type="flood",
        severity="high", country="France", confidence_score=score,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)

    if expected is None:
        assert out.total == 0
        assert out.countries == []
        # Counted, not swallowed: a page that silently drops rows is a page
        # whose numbers nobody can reconcile.
        assert out.suppressed_low_confidence == 1
    else:
        assert out.total == 1
        assert out.suppressed_low_confidence == 0
        assert out.countries[0].items[0].visibility == expected


async def test_corroboration_exempts_a_cluster_from_the_floor(db_session):
    """A second newsroom telling the same story is the evidence this score is
    mostly made of, and the primary's own row cannot see it: confidence is
    computed from the duplicate group, not from the cluster. Two outlets below
    the floor still publish -- and publish at full emphasis, because the thing
    the floor is looking for (a lone weak telling) is not what this is."""
    weak_a = await _source(db_session, "WeakA")
    weak_b = await _source(db_session, "WeakB")
    turkey = await _entity(db_session, "country", "Turkey")

    for source, url in ((weak_a, "https://w.com/a"), (weak_b, "https://w.com/b")):
        await _risk_article(
            db_session, source, url=url,
            title="İzmir'de 6.2 büyüklüğünde deprem: havalimanı kapatıldı",
            risk_type="earthquake", severity="high", country="Turkey", city="Izmir",
            confidence_score=0.535, entities=(turkey,),
        )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)

    assert out.total == 1
    assert out.suppressed_low_confidence == 0
    signal = out.countries[0].items[0]
    assert signal.source_count == 2
    assert signal.visibility == "normal"


async def test_one_outlet_republishing_itself_is_not_corroboration(db_session):
    """The exemption counts distinct SOURCES, not cluster members. An outlet
    that runs its own story twice has told it once, and letting that clear the
    floor would let any weak source exempt itself."""
    source = await _source(db_session, "SelfRepub")
    greece = await _entity(db_session, "country", "Greece")

    for url in ("https://r.com/first", "https://r.com/second"):
        await _risk_article(
            db_session, source, url=url,
            title="Rodos'ta orman yangını: 3.000 kişi tahliye edildi",
            risk_type="wildfire", severity="high", country="Greece", city="Rhodes",
            confidence_score=0.535, entities=(greece,),
        )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 0
    assert out.suppressed_low_confidence == 1


async def test_a_duplicate_group_also_exempts_even_without_a_cluster(db_session):
    """The other corroboration mechanism. Near-duplicate detection
    (`corroborating_source_count`) and event clustering are two different
    passes that answer the same question, and either answering "more than one"
    is enough."""
    source = await _source(db_session, "DupGroup")
    await _risk_article(
        db_session, source, url="https://d.com/1", risk_type="storm",
        severity="medium", country="Japan",
        confidence_score=0.55, corroborating_source_count=3,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.countries[0].items[0].visibility == "normal"


async def test_an_unscored_row_publishes_normally(db_session):
    """ArticleEnrichment.confidence_score is NOT NULL and defaults to 0.0 --
    a value the formula (whose minimum is 0.4) cannot produce. It means the
    verification pass never ran, and hiding on it would be reading a number
    nobody wrote."""
    source = await _source(db_session, "Unscored")
    await _risk_article(
        db_session, source, url="https://u.com/1", risk_type="attack",
        severity="high", country="Egypt", confidence_score=0.0,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.suppressed_low_confidence == 0
    assert out.countries[0].items[0].visibility == "normal"


async def test_low_visibility_signals_sort_last_within_their_country(db_session):
    """Severity does not promote a weak signal past a solid one. How bad the
    story would be if true is not evidence that it is, and the page collapses
    this tail into its own "Düşük güvenli sinyaller" block."""
    source = await _source(db_session, "SortVis")
    await _risk_article(
        db_session, source, url="https://v.com/weak-high", risk_type="war",
        severity="high", country="Italy", city="Rome", confidence_score=0.605,
    )
    await _risk_article(
        db_session, source, url="https://v.com/solid-low", risk_type="flood",
        severity="low", country="Italy", city="Milan", confidence_score=0.67,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    italy = next(c for c in out.countries if c.country == "Italy")
    assert [i.visibility for i in italy.items] == ["normal", "low"]
    assert [i.city for i in italy.items] == ["Milan", "Rome"]
    # Still counted in the country's own totals: it is de-emphasised, not
    # removed, and a score the visible items do not add up to is worse than a
    # loud one.
    assert italy.count == 2
    assert italy.severity_counts.high == 1


# --------------------------------------------------------------------------
# API: which headline, and in which language
# --------------------------------------------------------------------------


async def test_a_translated_headline_carries_its_original_along(db_session):
    """The card shows Turkish and reveals the source-language wording on
    hover, so a reader can check the translation against what was written."""
    source = await _source(db_session, "TrYes")
    await _risk_article(
        db_session, source, url="https://tr.com/1", risk_type="wildfire",
        severity="high", country="Greece",
        headline_tr="Rodos'ta orman yangını: tahliye sürüyor",
        translated_at=NOW,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    signal = out.countries[0].items[0]
    assert signal.headline == "Rodos'ta orman yangını: tahliye sürüyor"
    assert signal.is_translated is True
    # _risk_article writes `headline` as "<type> in <country>".
    assert signal.headline_original == "wildfire in Greece"


async def test_an_untranslated_headline_says_so_rather_than_passing_as_turkish(db_session):
    source = await _source(db_session, "TrNo")
    await _risk_article(
        db_session, source, url="https://tr.com/2", risk_type="flood",
        severity="low", country="France",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    signal = out.countries[0].items[0]
    assert signal.is_translated is False
    assert signal.headline == "flood in France"
    # Nothing to reveal on hover -- the headline shown IS the original.
    assert signal.headline_original is None


async def test_turkish_text_without_a_translation_timestamp_is_not_a_translation(db_session):
    """The same test schemas/article.py's is_translated uses: `translated_at IS
    NOT NULL`, never the mere presence of Turkish text. A row carrying
    headline_tr with no timestamp is an inconsistency, and the app reads it the
    conservative way everywhere else."""
    source = await _source(db_session, "TrHalf")
    await _risk_article(
        db_session, source, url="https://tr.com/3", risk_type="storm",
        severity="low", country="Spain",
        headline_tr="Bir başlık", translated_at=None,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    signal = out.countries[0].items[0]
    assert signal.is_translated is False
    assert signal.headline == "storm in Spain"


# --------------------------------------------------------------------------
# API: trend
# --------------------------------------------------------------------------


async def test_trend_buckets_by_utc_day_and_splits_by_family_and_severity(db_session):
    from fastapi import Response

    from app.api.v1.risks import risk_trend

    source = await _source(db_session, "S14")
    await _risk_article(
        db_session, source, url="https://t.com/1", risk_type="wildfire",
        severity="high", country="Greece", days_ago=1,
    )
    await _risk_article(
        db_session, source, url="https://t.com/2", risk_type="flood",
        severity="high", country="Italy", days_ago=1,
    )
    await _risk_article(
        db_session, source, url="https://t.com/3", risk_type="attack",
        severity="low", country="Egypt", days_ago=1,
    )
    await db_session.commit()

    out = await risk_trend(days=30, response=Response(), db=db_session)

    day = (NOW - timedelta(days=1)).date().isoformat()
    assert {(p.family, p.severity, p.count) for p in out.points} == {
        # Two natural/high articles on one day fold into one point of 2 --
        # wildfire and flood are different types but the same family.
        ("natural", "high", 2),
        ("conflict", "low", 1),
    }
    assert {p.day for p in out.points} == {day}
    assert out.days == 30


async def test_trend_counts_articles_not_clustered_signals(db_session):
    """Deliberately different from GET /risks's `total`: three outlets on one
    eruption is ONE signal there and THREE publications here, because that is
    what a daily shape can be consistent about. The response's own `note` is
    what stops the two numbers reading as a contradiction."""
    from fastapi import Response

    from app.api.v1.risks import risk_trend

    source = await _source(db_session, "S15")
    italy = await _entity(db_session, "country", "Italy")
    for i in range(3):
        await _risk_article(
            db_session, source, url=f"https://t2.com/{i}",
            title="Etna patlaması Catania Havalimanı'nı kapattı, 700 uçuş iptal edildi",
            risk_type="volcano", severity="high", country="Italy", city="Catania",
            days_ago=1, entities=(italy,),
        )
    await db_session.commit()

    out = await risk_trend(days=30, response=Response(), db=db_session)
    listed = await list_risks(days=30, response=Response(), db=db_session)

    assert sum(p.count for p in out.points) == 3
    assert listed.total == 1
    assert "yayın hacmini" in out.note


async def test_trend_excludes_articles_outside_the_window(db_session):
    from fastapi import Response

    from app.api.v1.risks import risk_trend

    source = await _source(db_session, "S16")
    await _risk_article(
        db_session, source, url="https://t3.com/in", risk_type="storm",
        severity="medium", country="Japan", days_ago=5,
    )
    await _risk_article(
        db_session, source, url="https://t3.com/out", risk_type="storm",
        severity="medium", country="Japan", days_ago=60,
    )
    await db_session.commit()

    out = await risk_trend(days=30, response=Response(), db=db_session)
    assert sum(p.count for p in out.points) == 1


async def test_an_empty_trend_is_an_empty_series_not_zero_filled_days(db_session):
    """Thirty rows of zero would look like thirty measured days; no rows is the
    truth, and the chart fills its own axis."""
    from fastapi import Response

    from app.api.v1.risks import risk_trend

    out = await risk_trend(days=30, response=Response(), db=db_session)
    assert out.points == []


# ==========================================================================
# VERIFICATION: where the event happened, vs. where somebody talked about it
#
# The rule under test, stated once: a place name that is the SUBJECT of a
# discourse verb ("Washington said"), or that is qualified by government
# vocabulary ("Japan's foreign ministry"), is the SOURCE of the statement and
# is never the location of the event. The old resolver took the first country
# entity in the text and had no way to express the difference.
# ==========================================================================


def _mentions(location):
    return {(m.name, m.role) for m in location.mentioned}


def test_a_discourse_verbs_subject_is_not_the_event_location():
    """The spec's own example. `Washington said an earthquake struck Japan` has
    exactly one country in it as far as the earthquake is concerned, and it is
    not the one that appears first."""
    location = resolve_risk_location(
        "Washington said an earthquake struck Japan",
        "The Japanese government confirmed the quake near Sendai.",
        [EntityMention("country", "United States", None), EntityMention("country", "Japan", None)],
    )
    assert location.country == "Japan"
    assert ("Washington", "source") in _mentions(location)


def test_the_rejected_place_is_recorded_rather_than_discarded():
    """A rejection nobody can inspect is indistinguishable from a bug. The
    dateline stays in mentioned_locations with the role that disqualified it."""
    location = resolve_risk_location(
        "Ankara condemned the attack in Damascus",
        "",
        [EntityMention("country", "Turkey", None), EntityMention("country", "Syria", None)],
    )
    assert ("Ankara", "source") in _mentions(location)
    assert location.country != "Turkey"


def test_government_vocabulary_marks_a_place_as_the_speaker():
    """No discourse verb at all -- the institution words alone are enough.
    "France's foreign ministry" is a speaker however the sentence ends."""
    location = resolve_risk_location(
        "France's foreign ministry on the Chile earthquake",
        "The ministry issued travel advice. Santiago was badly shaken.",
        [EntityMention("country", "France", None), EntityMention("country", "Chile", None)],
    )
    assert location.country == "Chile"
    assert ("France", "source") in _mentions(location)


def test_a_place_that_both_speaks_and_hosts_the_event_stays_the_event_location():
    """The asymmetry that keeps the rule from over-firing: "source" removes a
    candidate, so it has to be unanimous. One dateline does not disqualify a
    country the same article puts the event in."""
    location = resolve_risk_location(
        "Turkey said the tremor was felt widely",
        "A magnitude 6 earthquake struck southern Turkey overnight.",
        [EntityMention("country", "Turkey", None)],
    )
    assert location.country == "Turkey"
    assert ("Turkey", "event") in _mentions(location)


def test_a_discourse_verb_in_the_next_sentence_cannot_reach_back():
    """Folding strips punctuation, so a character window over the whole article
    reads across full stops: "Flooding in Jakarta. Reported from London." would
    mark Jakarta itself as a dateline. Roles are scoped to one sentence."""
    location = resolve_risk_location(
        "Flooding in Jakarta",
        "Reported from London by our correspondent.",
        [EntityMention("country", "Indonesia", None)],
    )
    assert (location.country, location.city) == ("Indonesia", "Jakarta")


def test_several_countries_in_one_article_resolve_to_the_one_hosting_the_event():
    location = resolve_risk_location(
        "Earthquake devastates central Chile",
        "Argentina and Peru sent rescue teams. Santiago reported major damage.",
        [
            EntityMention("country", "Chile", None),
            EntityMention("country", "Argentina", None),
            EntityMention("country", "Peru", None),
        ],
    )
    assert location.country == "Chile"


def test_a_city_that_contradicts_its_country_is_dropped_and_costs_confidence():
    """§12. The article named a city that is not in the country it also named.
    That is the article disagreeing with itself, which is information -- the
    city goes, and the placement stops being pin-worthy."""
    location = resolve_risk_location(
        "Earthquake near Tokyo",
        "France was also affected by the tsunami warning.",
        [EntityMention("country", "France", None)],
    )
    assert location.country == "France"
    assert location.city is None
    assert location.confidence == LOCATION_CONFIDENCE_CONFLICT
    assert location.mappable is False


def test_a_city_that_agrees_with_its_country_is_the_strongest_placement():
    location = resolve_risk_location(
        "Earthquake hits Kahramanmaras",
        "Damage reported across the region.",
        [EntityMention("country", "Turkey", None)],
    )
    assert (location.country, location.city) == ("Turkey", "Kahramanmaras")
    assert location.confidence == LOCATION_CONFIDENCE_CITY_CONFIRMED
    assert location.mappable is True


def test_a_source_only_country_is_kept_but_never_pinned():
    """The soft landing. The old behaviour -- use it anyway -- is preserved so
    no event vanishes, but below the pin threshold so it cannot masquerade as a
    confident placement."""
    location = resolve_risk_location(
        "France condemned the attack",
        "Paris said it would respond.",
        [EntityMention("country", "France", None)],
    )
    assert location.country == "France"
    assert location.confidence == LOCATION_CONFIDENCE_SOURCE_ONLY
    assert location.mappable is False


def test_an_airport_places_an_event_the_text_never_names_a_country_for():
    location = resolve_risk_location(
        "Wildfire forces evacuation",
        "Smoke reached the terminal.",
        [EntityMention("airport", "Catania Airport", "CTA")],
    )
    assert location.country == "Italy"
    assert location.confidence == LOCATION_CONFIDENCE_AIRPORT_DERIVED
    assert location.mappable is True


def test_an_unresolvable_place_scores_nothing_rather_than_zero():
    location = resolve_risk_location("Storm warning issued", "Heavy rain expected.", [])
    assert (location.country, location.city, location.confidence) == (None, None, None)
    assert location.mappable is False


def test_detect_risk_place_still_answers_the_two_value_question():
    """The old signature is what enrich.py and the backfill call. It must keep
    returning exactly (country, city) after the resolver grew a dataclass."""
    assert detect_risk_place(
        "Earthquake hits Kahramanmaras", "Damage reported.",
        [EntityMention("country", "Turkey", None)],
    ) == ("Turkey", "Kahramanmaras")


# ==========================================================================
# VERIFICATION: aviation relevance
#
# One sentence under test: the presence of an aviation WORD is not aviation
# relevance. What counts is a stated operational fact.
# ==========================================================================


def test_aviation_words_without_operational_impact_score_nothing():
    """§5's exact rule. Every one of these says "airline", "aviation" or
    "flight" and none of them reports anything happening to an operation."""
    for title, body in [
        ("Earthquake kills dozens in Chile",
         "The airline industry sent condolences. Aviation groups pledged aid."),
        ("Protests continue in the capital",
         "Flight attendants joined the march. The aviation sector is watching."),
        ("Wildfire burns through national park",
         "The area is popular with airline crews on layover."),
    ]:
        assert detect_aviation_relevance(title, body) is None


def test_an_airspace_closure_in_the_headline_scores_highest():
    relevance = detect_aviation_relevance(
        "Airspace closed over eastern Poland after drone incursion", ""
    )
    assert relevance is not None
    assert relevance.score == AVIATION_RELEVANCE_TITLE
    assert relevance.score >= AVIATION_RELEVANCE_GATE
    assert relevance.status == "ACTUAL"


def test_an_operational_fact_in_the_body_still_clears_the_gate():
    relevance = detect_aviation_relevance(
        "Wildfire spreads near Athens",
        "Residents were evacuated. Flights were diverted from Athens airport overnight.",
    )
    assert relevance is not None
    assert relevance.score == AVIATION_RELEVANCE_BODY
    assert relevance.score >= AVIATION_RELEVANCE_GATE


def test_the_evidence_is_quoted_from_the_article_not_paraphrased():
    """An evidence field a reader cannot find in the source is decoration."""
    body = "Residents fled. Flights were diverted from Athens airport overnight. Aid arrived."
    relevance = detect_aviation_relevance("Wildfire near Athens", body)
    assert relevance is not None
    assert relevance.evidence in body
    assert "diverted" in relevance.evidence


def test_a_forecast_closure_is_potential_and_a_reported_one_is_actual():
    """Not a severity: a forecast closure and a reported one are equally worth
    a planner's attention and differ only in kind."""
    forecast = detect_aviation_relevance(
        "Storm approaches", "Officials warned that flights could be cancelled tomorrow."
    )
    reported = detect_aviation_relevance(
        "Storm hits", "Flights were cancelled at the airport this morning."
    )
    assert forecast is not None and forecast.status == "POTENTIAL"
    assert reported is not None and reported.status == "ACTUAL"


def test_turkish_operational_phrases_score_the_same_as_english_ones():
    relevance = detect_aviation_relevance("Deprem sonrası hava sahası kapatıldı", "")
    assert relevance is not None
    assert relevance.score >= AVIATION_RELEVANCE_GATE


def test_an_airport_specific_event_clears_the_gate():
    relevance = detect_aviation_relevance(
        "Volcanic ash closes Catania airport", "Catania airport closed until Thursday."
    )
    assert relevance is not None and relevance.score >= AVIATION_RELEVANCE_GATE


def test_a_conflict_with_no_stated_flight_effect_scores_nothing():
    assert detect_aviation_relevance(
        "Shelling continues along the border",
        "Dozens were killed overnight as artillery fire resumed.",
    ) is None


# ==========================================================================
# VERIFICATION: currency flags
# ==========================================================================


def test_a_retrospective_headline_sets_historical_and_recap_but_never_invents():
    """The guard has evidence for two of the five flags. The other three stay
    None, because None means "nobody looked" and False is a claim."""
    flags = detect_currency_flags("Remembering the 2013 crash, 10 years on")
    assert flags["is_current_event"] is False
    assert flags["is_historical"] is True
    assert flags["is_recap"] is True
    assert flags["is_analysis"] is None
    assert flags["is_opinion"] is None


def test_an_ordinary_headline_leaves_every_flag_unknown():
    """Not-retrospective is not the same as proven-current. A heuristic that
    cannot recognise currency must not assert it."""
    assert set(detect_currency_flags("Earthquake strikes Japan").values()) == {None}


# ==========================================================================
# API: the three gates, and the graduated rollout that keeps them from
# emptying the page on the deploy that ships them
# ==========================================================================


async def test_the_default_window_is_five_days(db_session):
    """Backend and frontend must agree; this pins the backend half. Asserted
    through aggregate_risks rather than the endpoint because the endpoint's
    default is a FastAPI Query object until the framework resolves it."""
    from app.api.v1.risks import aggregate_risks

    assert DEFAULT_WINDOW_DAYS == 5
    out = await aggregate_risks(db_session)
    assert out.days == 5


async def test_an_explicitly_stale_article_never_reaches_the_page(db_session):
    source = await _source(db_session, "Stale")
    await _risk_article(
        db_session, source, url="https://s.com/old", risk_type="earthquake",
        severity="high", country="Japan", is_current_event=False,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 0
    assert out.suppressed_not_current == 1


async def test_an_unflagged_article_passes_the_currency_gate(db_session):
    """`IS NOT FALSE`, not `IS TRUE`. Coverage is partial, so reading NULL as
    "not current" would delete the archive rather than filter it."""
    source = await _source(db_session, "Unflagged")
    await _risk_article(
        db_session, source, url="https://s.com/null", risk_type="earthquake",
        severity="high", country="Japan", is_current_event=None,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.suppressed_not_current == 0


async def test_a_measured_irrelevant_event_is_removed_from_the_radar(db_session):
    source = await _source(db_session, "Irrelevant")
    await _risk_article(
        db_session, source, url="https://a.com/no", risk_type="earthquake",
        severity="high", country="Chile",
        aviation_relevance_score=0.2, aviation_relevance_source="llm",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 0
    assert out.suppressed_aviation_irrelevant == 1


async def test_an_unscored_event_survives_the_aviation_gate(db_session):
    """The graduated rollout. NULL is "nobody measured it", and a gate that
    reads it as a low score deletes every row written before this revision."""
    source = await _source(db_session, "Unscored")
    await _risk_article(
        db_session, source, url="https://a.com/unscored", risk_type="earthquake",
        severity="high", country="Chile", aviation_relevance_score=None,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.suppressed_aviation_irrelevant == 0
    assert out.countries[0].items[0].aviation_relevance_score is None


async def test_a_relevant_event_passes_and_carries_its_evidence(db_session):
    source = await _source(db_session, "Relevant")
    await _risk_article(
        db_session, source, url="https://a.com/yes", risk_type="volcano",
        severity="high", country="Italy",
        aviation_relevance_score=0.85, aviation_relevance_source="llm",
        aviation_impact_evidence="Catania airport closed until Thursday.",
        aviation_impact_status="ACTUAL",
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    item = out.countries[0].items[0]
    assert item.aviation_relevance_score == 0.85
    assert item.aviation_relevance_source == "llm"
    assert item.aviation_impact_evidence == "Catania airport closed until Thursday."
    assert item.aviation_impact_status == "ACTUAL"


async def test_one_member_reporting_the_operational_effect_carries_the_cluster(db_session):
    """max() across the cluster, not the primary's own score. The primary is
    picked for source tier and earliness, not for how completely it reported
    the operational detail."""
    source_a = await _source(db_session, "ClusterA", tier="agency")
    source_b = await _source(db_session, "ClusterB")
    italy = await _entity(db_session, "country", "Italy")
    for url, score, src in (
        ("https://m.com/vague", 0.1, source_a),
        ("https://m.com/detailed", 0.9, source_b),
    ):
        await _risk_article(
            db_session, src, url=url, risk_type="volcano", severity="high",
            country="Italy", title="Etna eruption closes Catania airport",
            entities=(italy,), aviation_relevance_score=score,
        )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.countries[0].items[0].aviation_relevance_score == 0.9


async def test_an_official_source_publishes_below_the_confidence_gate(db_session):
    """A civil-aviation authority's own notice is verified by BEING the
    authority's statement. Published -- quietly, because one telling is one
    telling -- rather than hidden for want of a second outlet."""
    source = await _source(db_session, "CAA", tier="regulator")
    await _risk_article(
        db_session, source, url="https://caa.gov/notam", risk_type="storm",
        severity="high", country="Japan", confidence_score=0.58,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.suppressed_low_confidence == 0
    assert out.countries[0].items[0].visibility == "low"


async def test_the_same_score_from_an_ordinary_outlet_is_hidden(db_session):
    """The control for the test above: the exemption is the tier, not the
    score."""
    source = await _source(db_session, "Trade", tier="trade")
    await _risk_article(
        db_session, source, url="https://trade.com/story", risk_type="storm",
        severity="high", country="Japan", confidence_score=0.58,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 0
    assert out.suppressed_low_confidence == 1


async def test_a_weak_placement_is_listed_but_never_pinned(db_session):
    """§13. `country` is BLANKED rather than merely flagged: the map reads it
    to find a centroid, and a dot drawn on a guess is indistinguishable from a
    dot drawn on a fact."""
    source = await _source(db_session, "WeakPlace")
    await _risk_article(
        db_session, source, url="https://p.com/weak", risk_type="war",
        severity="high", country="United States", location_confidence=0.4,
        mentioned_locations=[{"name": "Washington", "kind": "city", "role": "source"}],
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.unplaced_low_confidence == 1
    assert [c.country for c in out.countries] == [UNKNOWN_COUNTRY]
    item = out.countries[0].items[0]
    assert item.country is None
    assert item.is_mappable is False
    assert item.location_confidence == 0.4
    # The audit trail survives the blanking -- otherwise "konum belirsiz" is
    # a statement the reader has no way to check.
    assert item.mentioned_locations == [
        {"name": "Washington", "kind": "city", "role": "source"}
    ]


async def test_a_confident_placement_keeps_its_country_and_its_pin(db_session):
    source = await _source(db_session, "StrongPlace")
    await _risk_article(
        db_session, source, url="https://p.com/strong", risk_type="earthquake",
        severity="high", country="Japan", city="Tokyo", location_confidence=0.9,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert [c.country for c in out.countries] == ["Japan"]
    item = out.countries[0].items[0]
    assert item.is_mappable is True
    assert (item.country, item.city) == ("Japan", "Tokyo")
    assert out.unplaced_low_confidence == 0


async def test_an_unscored_placement_keeps_its_pin_during_the_transition(db_session):
    """Every row written before this revision carries NULL here. Reading NULL
    as "weak" would blank the map on the deploy, in the name of a check that
    has not run yet."""
    source = await _source(db_session, "LegacyPlace")
    await _risk_article(
        db_session, source, url="https://p.com/legacy", risk_type="flood",
        severity="medium", country="France", location_confidence=None,
    )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert [c.country for c in out.countries] == ["France"]
    assert out.countries[0].items[0].is_mappable is True
    assert out.unplaced_low_confidence == 0


async def test_an_event_role_anywhere_in_the_cluster_beats_a_source_role(db_session):
    """One outlet's dateline does not disqualify a place another outlet puts
    the event in."""
    source_a = await _source(db_session, "RoleA", tier="agency")
    source_b = await _source(db_session, "RoleB")
    japan = await _entity(db_session, "country", "Japan")
    for url, role, src in (
        ("https://r.com/dateline", "source", source_a),
        ("https://r.com/scene", "event", source_b),
    ):
        await _risk_article(
            db_session, src, url=url, risk_type="earthquake", severity="high",
            country="Japan", title="Earthquake strikes Sendai region",
            entities=(japan,), location_confidence=0.8,
            mentioned_locations=[{"name": "Japan", "kind": "country", "role": role}],
        )
    await db_session.commit()

    from fastapi import Response

    out = await list_risks(days=14, response=Response(), db=db_session)
    assert out.total == 1
    assert out.countries[0].items[0].mentioned_locations == [
        {"name": "Japan", "kind": "country", "role": "event"}
    ]


async def test_the_trend_series_applies_the_same_currency_gate(db_session):
    """A retrospective the list refuses must not raise the trend line: a spike
    with no signals behind it is a chart contradicting its own page."""
    from fastapi import Response

    from app.api.v1.risks import risk_trend

    source = await _source(db_session, "TrendCurrency")
    await _risk_article(
        db_session, source, url="https://tc.com/now", risk_type="flood",
        severity="high", country="France",
    )
    await _risk_article(
        db_session, source, url="https://tc.com/anniversary", risk_type="flood",
        severity="high", country="France", is_current_event=False,
    )
    await db_session.commit()

    out = await risk_trend(days=30, response=Response(), db=db_session)
    assert sum(p.count for p in out.points) == 1


# ==========================================================================
# The funnel report (spec §23)
# ==========================================================================


async def test_the_funnel_report_counts_every_stage_and_why_each_gate_passed(db_session):
    from app.services.risk_quality import render_report_tr, risk_quality_report

    source = await _source(db_session, "Funnel")
    # Survives everything, on evidence.
    await _risk_article(
        db_session, source, url="https://f.com/keep", risk_type="volcano",
        severity="high", country="Italy", aviation_relevance_score=0.9,
        aviation_relevance_source="llm", location_confidence=0.9,
    )
    # Rejected by the currency gate.
    await _risk_article(
        db_session, source, url="https://f.com/old", risk_type="volcano",
        severity="high", country="Italy", is_current_event=False,
    )
    # Rejected by the confidence gate.
    await _risk_article(
        db_session, source, url="https://f.com/weak", risk_type="flood",
        severity="low", country="France", confidence_score=0.55,
    )
    # Rejected by the aviation gate.
    await _risk_article(
        db_session, source, url="https://f.com/irrelevant", risk_type="earthquake",
        severity="high", country="Chile", aviation_relevance_score=0.1,
    )
    # Rejected by the location gate.
    await _risk_article(
        db_session, source, url="https://f.com/unplaced", risk_type="storm",
        severity="low", country="Japan", location_confidence=0.3,
    )
    await db_session.commit()

    report = await risk_quality_report(db_session, days=14)
    assert report.total_articles == 5
    # `risk_adayi` is measured BEFORE the currency gate, so all five count
    # here: from that stage down every number is over risk candidates only,
    # which is what makes the rejection list exactly the union of the stages'
    # drops rather than a subset of it.
    assert report.risk_candidates == 5
    assert report.in_window == 5
    assert report.unique == 5
    assert report.current == 4
    assert report.confidence_passed == 3
    assert report.aviation_passed == 2
    assert report.location_passed == 1
    assert report.clusters == 1
    assert report.rejected_not_current == 1
    assert report.rejected_confidence == 1
    assert report.rejected_aviation == 1
    assert report.rejected_location == 1

    rendered = render_report_tr(report)
    assert "Risk Radarı veri kalitesi hunisi" in rendered
    assert "Konum doğrulandı" in rendered


async def test_the_funnel_report_clusters_articles_that_have_entity_links(db_session):
    """Regression: the report's query eager-loads entity_links but not the
    `.entity` behind each one, and `entity_codes()` reads `link.entity.code`.
    An article with no links never touches the attribute, so a fixture without
    them cannot catch it -- against a real corpus it raised MissingGreenlet on
    the first row."""
    from app.services.risk_quality import risk_quality_report

    source = await _source(db_session, "Linked")
    italy = await _entity(db_session, "country", "Italy")
    catania = await _entity(db_session, "airport", "Catania Airport", "CTA")
    await _risk_article(
        db_session, source, url="https://l.com/linked", risk_type="volcano",
        severity="high", country="Italy", entities=(italy, catania),
    )
    await db_session.commit()

    report = await risk_quality_report(db_session, days=14)
    assert report.clusters == 1


async def test_the_funnel_report_separates_measured_passes_from_unmeasured_ones(db_session):
    """The report's most important lines. A gate passing everything unscored is
    a gate not yet doing anything, and that has to be visible rather than
    flattering."""
    from app.services.risk_quality import risk_quality_report

    source = await _source(db_session, "FunnelSource")
    await _risk_article(
        db_session, source, url="https://fs.com/measured", risk_type="volcano",
        severity="high", country="Italy", aviation_relevance_score=0.9,
        aviation_relevance_source="llm", location_confidence=0.9,
    )
    await _risk_article(
        db_session, source, url="https://fs.com/unmeasured", risk_type="flood",
        severity="low", country="France",
    )
    await db_session.commit()

    report = await risk_quality_report(db_session, days=14)
    assert report.aviation_passed == 2
    assert report.aviation_unscored == 1
    assert report.location_unscored == 1
    assert report.aviation_by_source == {"llm": 1, "unscored": 1}


# ==========================================================================
# The enrichment writer: which path filled each column
# ==========================================================================


async def test_enrichment_falls_back_to_the_deterministic_aviation_floor():
    """No LLM configured is the normal state for most of this feed. The keyword
    floor answers, and the row records that it was the keyword floor."""
    from app.pipeline.enrich import _classify_risk

    result = await _classify_risk(
        object(),
        "Volcanic ash closes Catania airport",
        "Catania airport closed until Thursday as ash fell across Sicily.",
        [EntityMention("country", "Italy", None)],
    )
    assert result["risk_type"] == "volcano"
    assert result["aviation_relevance_source"] == "heuristic"
    assert result["aviation_relevance_score"] >= AVIATION_RELEVANCE_GATE
    assert "Catania airport closed" in result["aviation_impact_evidence"]


async def test_enrichment_marks_an_unfindable_signal_unscored_rather_than_zero():
    """The distinction the whole graduated rollout rests on: "the keyword pass
    found nothing" is not "there is no aviation impact"."""
    from app.pipeline.enrich import _classify_risk

    result = await _classify_risk(
        object(),
        "Earthquake kills dozens in Chile",
        "The airline industry sent condolences.",
        [EntityMention("country", "Chile", None)],
    )
    assert result["risk_type"] == "earthquake"
    assert result["aviation_relevance_score"] is None
    assert result["aviation_relevance_source"] == "unscored"


async def test_enrichment_records_the_location_roles_it_rejected():
    from app.pipeline.enrich import _classify_risk

    result = await _classify_risk(
        object(),
        "Washington said an earthquake struck Japan",
        "The Japanese government confirmed the quake near Sendai.",
        [EntityMention("country", "United States", None), EntityMention("country", "Japan", None)],
    )
    assert result["risk_country"] == "Japan"
    assert result["location_confidence"] is not None
    assert {"name": "Washington", "kind": "city", "role": "source"} in result[
        "mentioned_locations"
    ]


async def test_a_non_risk_article_clears_every_verification_column():
    """A verification column left behind after its classification was withdrawn
    is a fact about a row that no longer exists."""
    from app.pipeline.enrich import _NO_RISK, _classify_risk

    result = await _classify_risk(
        object(), "Airline reports record quarterly profit", "Revenue grew.", []
    )
    assert result == _NO_RISK
    assert set(result.values()) == {None}


# ==========================================================================
# The verification surface: GET /risks/quality and GET /risks/rejected
# (spec §23-24). The 30-case round itself lives in
# app/tests/test_risk_verification_cases.py.
# ==========================================================================


async def test_the_funnel_arithmetic_closes_at_every_stage(db_session):
    """passed + dropped == the stage above's passed, all the way down.

    The one property that makes the funnel a measurement rather than a picture.
    A reader who cannot subtract their way from "toplam makale" to "sinyal" has
    no way to tell a gate that removed forty rows from a query that never
    returned them, which is the exact confusion this screen exists to end.
    """
    from app.services.risk_quality import risk_quality_report

    source = await _source(db_session, "Arithmetic")
    await _risk_article(
        db_session, source, url="https://a.com/keep", risk_type="volcano",
        severity="high", country="Italy", aviation_relevance_score=0.9,
        location_confidence=0.9,
    )
    await _risk_article(
        db_session, source, url="https://a.com/stale", risk_type="flood",
        severity="low", country="France", is_current_event=False,
    )
    await _risk_article(
        db_session, source, url="https://a.com/weak", risk_type="storm",
        severity="low", country="Japan", confidence_score=0.55,
    )
    await _risk_article(
        db_session, source, url="https://a.com/old", risk_type="earthquake",
        severity="high", country="Chile", days_ago=40,
    )
    duplicate = await _risk_article(
        db_session, source, url="https://a.com/dup", risk_type="volcano",
        severity="high", country="Italy",
    )
    duplicate.is_duplicate = True
    # A non-risk article, so `toplam` is genuinely larger than `risk_adayi`.
    plain = Article(
        source_id=source.id, url="https://a.com/plain", title="Route news",
        raw_content="body", published_at=NOW - timedelta(days=1),
        fetched_at=NOW - timedelta(days=1), content_hash="plain", status="enriched",
    )
    db_session.add(plain)
    await db_session.flush()
    db_session.add(ArticleEnrichment(article_id=plain.id, headline="Route news"))
    await db_session.commit()

    report = await risk_quality_report(db_session, days=5)
    stages = report.stages
    assert [s.key for s in stages] == [
        "toplam", "risk_adayi", "pencere", "tekil", "guncel",
        "guven", "havacilik", "konum", "kume",
    ]
    for previous, stage in zip(stages, stages[1:]):
        assert stage.passed + stage.dropped == previous.passed, (
            f"stage {stage.key} does not close: {stage.passed} + {stage.dropped} "
            f"!= {previous.passed} ({previous.key})"
        )
        assert stage.dropped >= 0

    # And every rejecting stage's per-reason split adds up to its own drop.
    # The location stage is the one that splits (unresolved vs conflict), and
    # this is what stops a filter chip labelled "3 elendi · location_unresolved"
    # from returning one row when a reader clicks it.
    for stage in stages:
        if stage.drop_kind != "rejected":
            assert stage.reason_counts == {}
            continue
        assert sum(stage.reason_counts.values()) == stage.dropped, (
            f"stage {stage.key} claims {stage.dropped} rejections but its "
            f"reasons add up to {sum(stage.reason_counts.values())}"
        )
        # The same numbers as the flat tally, not a second count of them.
        for slug, count in stage.reason_counts.items():
            assert report.rejected_counts.get(slug, 0) == count


async def test_the_merge_stage_is_never_reported_as_a_rejection(db_session):
    """Clustering removes rows from the count and none of them from the radar.
    Labelling that as a rejection would have the screen tell a reader their
    event was thrown away when it is on the page under another headline."""
    from app.services.risk_quality import risk_quality_report

    source = await _source(db_session, "Merge")
    italy = await _entity(db_session, "country", "Italy")
    for i in range(3):
        await _risk_article(
            db_session, source, url=f"https://m.com/{i}",
            title="Etna eruption closes Catania Airport as 700 flights are cancelled",
            risk_type="volcano", severity="high", country="Italy", city="Catania",
            entities=(italy,),
        )
    await db_session.commit()

    report = await risk_quality_report(db_session, days=14)
    merge = next(s for s in report.stages if s.key == "kume")
    assert merge.passed == 1
    assert merge.dropped == 2
    assert merge.drop_kind == "merged"
    assert merge.reason is None
    assert merge.reason_counts == {}
    assert "BİRLEŞME" in (merge.note_tr or "")


async def test_the_quality_endpoint_serves_the_funnel_and_the_reason_labels(db_session):
    from fastapi import Response

    from app.api.v1.risks import risk_quality

    source = await _source(db_session, "QualityApi")
    await _risk_article(
        db_session, source, url="https://q.com/keep", risk_type="volcano",
        severity="high", country="Italy",
    )
    await _risk_article(
        db_session, source, url="https://q.com/irrelevant", risk_type="earthquake",
        severity="high", country="Chile", aviation_relevance_score=0.1,
    )
    await db_session.commit()

    out = await risk_quality(days=14, response=Response(), db=db_session)
    assert [s.key for s in out.stages][0] == "toplam"
    assert out.rejected_counts["aviation_relevance_low"] == 1
    # Every reason a stage can carry has a Turkish label, or the screen renders
    # a slug at a reader.
    for stage in out.stages:
        if stage.reason:
            assert out.reason_labels_tr[stage.reason]
    assert out.aviation_unscored == 1


async def test_the_rejected_endpoint_filters_by_reason_and_carries_the_evidence(db_session):
    from fastapi import Response

    from app.api.v1.risks import risk_rejected

    source = await _source(db_session, "RejectedApi")
    await _risk_article(
        db_session, source, url="https://r.com/irrelevant", risk_type="earthquake",
        severity="high", country="Chile", aviation_relevance_score=0.1,
        aviation_relevance_source="llm", location_confidence=0.9,
    )
    await _risk_article(
        db_session, source, url="https://r.com/stale", risk_type="flood",
        severity="low", country="France", is_current_event=False,
    )
    await db_session.commit()

    everything = await risk_rejected(
        days=14, limit=50, reason=None, response=Response(), db=db_session
    )
    assert {row.reason for row in everything} == {
        "aviation_relevance_low",
        "not_current_event",
    }

    only_aviation = await risk_rejected(
        days=14, limit=50, reason="aviation_relevance_low", response=Response(), db=db_session
    )
    assert len(only_aviation) == 1
    row = only_aviation[0]
    assert row.aviation_relevance_score == 0.1
    assert row.aviation_relevance_source == "llm"
    assert row.detected_country == "Chile"
    assert row.reason_label_tr == "Havacılıkla ilgisiz"


async def test_a_rejected_row_names_every_other_gate_it_would_have_failed(db_session):
    """`reason` is the FIRST gate that refused the row, which is an ordering
    choice and not a claim the rest are fine. Without `also_failed` a reader
    fixes one rule and the article stays hidden for a reason nothing told them
    about."""
    from fastapi import Response

    from app.api.v1.risks import risk_rejected

    source = await _source(db_session, "Cascade")
    await _risk_article(
        db_session, source, url="https://c.com/everything", risk_type="storm",
        severity="low", country="Japan", is_current_event=False,
        confidence_score=0.55, aviation_relevance_score=0.1, location_confidence=0.3,
    )
    await db_session.commit()

    rows = await risk_rejected(
        days=14, limit=50, reason=None, response=Response(), db=db_session
    )
    assert len(rows) == 1
    assert rows[0].reason == "not_current_event"
    assert rows[0].also_failed == [
        "confidence_below_floor",
        "aviation_relevance_low",
        "location_unresolved",
    ]


async def test_an_unknown_reason_is_an_empty_list_not_an_error(db_session):
    """The filter is a UI affordance over a set that grows as gates are added.
    A screen that 422s because it remembered last week's slug is worse than one
    that shows nothing."""
    from fastapi import Response

    from app.api.v1.risks import risk_rejected

    source = await _source(db_session, "Unknown")
    await _risk_article(
        db_session, source, url="https://u.com/x", risk_type="volcano",
        severity="high", country="Italy", is_current_event=False,
    )
    await db_session.commit()

    assert await risk_rejected(
        days=14, limit=50, reason="no_such_reason", response=Response(), db=db_session
    ) == []


async def test_an_empty_window_is_an_empty_funnel_not_a_missing_one(db_session):
    """Nothing classified is a valid state and must render as zeroes with
    labels, not as an absent section."""
    from fastapi import Response

    from app.api.v1.risks import risk_quality, risk_rejected

    out = await risk_quality(days=5, response=Response(), db=db_session)
    assert len(out.stages) == 9
    assert all(stage.passed == 0 for stage in out.stages)
    assert out.rejected_counts["outside_window"] == 0
    assert await risk_rejected(
        days=5, limit=50, reason=None, response=Response(), db=db_session
    ) == []


async def test_the_location_stage_splits_its_drop_into_both_reasons(db_session):
    """The one stage that rejects for two different reasons, and the reason a
    stage carries a per-reason tally at all.

    Before it did, the funnel drew "3 elendi · location_unresolved" over a drop
    that was one unresolved and two conflicts -- a filter chip that returns a
    third of what its own label promises."""
    from fastapi import Response

    from app.api.v1.risks import risk_quality

    source = await _source(db_session, "SplitLocation")
    await _risk_article(
        db_session, source, url="https://s.com/weak", risk_type="storm",
        severity="low", country="Japan", location_confidence=0.4,
    )
    for i in range(2):
        await _risk_article(
            db_session, source, url=f"https://s.com/conflict{i}", risk_type="flood",
            severity="low", country="Indonesia", location_confidence=0.5,
        )
    await db_session.commit()

    out = await risk_quality(days=14, response=Response(), db=db_session)
    stage = next(s for s in out.stages if s.key == "konum")
    assert stage.dropped == 3
    assert stage.reason_counts == {"location_unresolved": 1, "location_conflict": 2}


# --------------------------------------------------------------------------
# Backfill honours the veto
# --------------------------------------------------------------------------


async def test_backfill_applies_the_same_veto_as_live_enrichment(db_session):
    """A guard that only runs on fresh articles never reaches the archive.

    Measured in production: after a full `backfill-risks` run, a military
    procurement piece ("Boeing MH-139A Grey Wolf helicopter, US nuclear
    missile fields") and a central-bank housing report about an earthquake
    region were both still classified as live risk events -- because the
    backfill called classify_risk_heuristic directly and skipped risk_veto,
    which is where every false-positive guard in this repo lives. Shipping a
    keyword fix and re-running the backfill left the story it was written to
    remove sitting on the radar.
    """
    from app.ingest.sources_seed import SourceSeed  # noqa: F401 -- parity with peers
    from app.models.source import Source
    from app.pipeline.enrich import backfill_risk_classification

    source = Source(
        name="Veto backfill kaynagi",
        url="https://example.test/veto",
        source_type="rss",
        category="other",
        trust_weight=0.7,
    )
    db_session.add(source)
    await db_session.flush()

    published = NOW - timedelta(days=1)
    article = Article(
        source_id=source.id,
        url="https://example.test/veto/grey-wolf",
        title="Boeing MH-139A Grey Wolf helicopter enters service at missile wing",
        raw_content=(
            "The Air Force accepted its first MH-139A Grey Wolf helicopters for "
            "security patrols over the nuclear missile fields, replacing the UH-1N."
        ),
        published_at=published,
        fetched_at=published,
        content_hash="veto-grey-wolf",
        status="enriched",
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id,
            headline=article.title,
            summary="",
            category="safety",
            # The state a previous backfill left behind: classified, published.
            risk_type="attack",
            risk_family="conflict",
            risk_severity="medium",
            risk_country="United States",
            importance_score=0.5,
            sentiment="neutral",
            confidence_score=0.61,
            corroborating_source_count=1,
        )
    )
    await db_session.commit()

    stats = await backfill_risk_classification(db_session)

    refreshed = (
        await db_session.execute(
            select(ArticleEnrichment).where(ArticleEnrichment.article_id == article.id)
        )
    ).scalar_one()
    assert refreshed.risk_type is None, (
        "vetoed article must lose its stale risk classification"
    )
    assert stats["cleared"] >= 1


def test_one_weak_word_in_the_body_is_not_an_event_but_two_are():
    """The floor that removed the Grey Wolf story, stated as the rule itself.

    Weak keywords ("war", "troops", "coup") are the ones that carry ordinary
    prose, so a single body occurrence -- which on a real page is as likely to
    come from a related-articles rail as from the story -- must not classify.
    The same article with the word twice does classify: this is a threshold,
    not a ban, and a test that only checked the negative side would be
    satisfied by deleting the keyword.
    """
    context = " Passengers were evacuated and rescue teams arrived."
    once = "Carriers rerouted after troops moved to the border." + context
    twice = (
        "Carriers rerouted after troops moved to the border. More troops "
        "followed overnight." + context
    )
    headline = "Airlines adjust Middle East routings"

    assert detect_risk_type(headline, once) is None
    assert detect_risk_type(headline, twice) == "war"


def test_a_weak_word_in_the_headline_still_classifies_on_its_own():
    """The floor is scored, not counted, and _TITLE_WEIGHT clears it alone --
    otherwise "Troops seize the airport" would need the word twice in the body
    to be believed."""
    assert (
        detect_risk_type(
            "Troops seize control of the airport",
            "The terminal was closed and passengers were evacuated.",
        )
        == "war"
    )


def test_the_earthquake_region_is_a_place_and_a_quake_in_it_is_still_an_event():
    """Masking "deprem bölgesi" must not deafen the radar to earthquakes that
    happen there. The mask removes a place name; a reported quake brings its
    own verb."""
    assert (
        detect_risk_type(
            "Deprem bölgesinde konut arzı ve kira enflasyonu raporu",
            "Kira artışının nedenleri incelendi.",
        )
        is None
    )
    assert (
        detect_risk_type(
            "Deprem bölgesinde 5.4 büyüklüğünde deprem meydana geldi",
            "AFAD sarsıntının merkez üssünü açıkladı, vatandaşlar tahliye edildi.",
        )
        == "earthquake"
    )
