"""The bundled airport/country reference data and the guards around it.

These pin the two things that can silently rot: the dataset the gazetteer is
now built on, and the refusals that keep a 3.2k-airport table from tagging
every article that contains the word "man".
"""
import re
from pathlib import Path

from app.data import airport, airports_by_iata, country_name, country_regions_by_name
from app.llm.gazetteer import (
    AIRPORT_COUNTRY,
    AIRPORTS,
    COUNTRY_ALIASES,
    fold_for_match,
)
from app.llm.heuristic import HeuristicProvider, detect_region
from app.taxonomy import CURATED_COUNTRY_REGION, COUNTRY_TO_REGION

provider = HeuristicProvider()


# --- the dataset ----------------------------------------------------------

def test_airport_lookup_by_iata_returns_position_and_city():
    agp = airport("AGP")
    assert agp is not None
    assert agp.city == "Málaga"
    assert agp.country == "ES"
    # Roughly Málaga: enough to catch a lat/lon swap or a sign flip.
    assert 36 < agp.lat < 37
    assert -5 < agp.lon < -4
    # Lookup is case-insensitive; the entity table stores upper-case codes.
    assert airport("agp") == agp
    assert airport(None) is None
    assert airport("ZZZ") is None


def test_dataset_is_the_scheduled_service_cut_not_the_whole_world():
    airports = airports_by_iata()
    # Low thousands: the raw OurAirports file is ~86k rows of heliports and
    # closed strips. If this ever jumps an order of magnitude the filter in
    # scripts/build_airports.py has stopped being applied.
    assert 2_000 < len(airports) < 6_000
    assert all(len(code) == 3 and code.isalpha() and code.isupper() for code in airports)
    # The hubs this desk watches must all be present -- app/hubs.py depends on
    # the gazetteer being able to recognise them.
    for code in ("IST", "SAW", "DXB", "AUH", "DOH", "LHR", "LGW", "CDG", "AMS", "FRA"):
        assert code in airports, code


def test_every_airport_country_resolves_to_a_region():
    """The whole point of the airport fallback: code -> country -> region. A
    country in the airport table with no region entry is a silent dead end."""
    for code, country in AIRPORT_COUNTRY.items():
        assert country in COUNTRY_TO_REGION, f"{code} -> {country!r} has no region"


# --- the false-positive guards -------------------------------------------

def test_city_aliases_that_are_common_words_are_not_matchable():
    """"Nice", "Male", "Split", "Reading" and "Mobile" are cities with airports
    and also ordinary English words. A gazetteer that adds every municipality
    as an alias tags an article about a nice split of traffic with two
    airports."""
    for word in ("nice", "male", "split", "reading", "mobile", "eagle", "hope"):
        assert word not in AIRPORTS, word
    # The qualified form is unambiguous, so it stays available.
    assert AIRPORTS["nice airport"][1] == "NCE"
    assert AIRPORTS["split airport"][1] == "SPU"


def test_bare_iata_codes_that_spell_words_are_not_matchable():
    """Measured in production before this data existed: a bare "IST" alias
    matched 38 articles, 33 of them German sentences using "ist" as a verb."""
    for code in ("ist", "saw", "doh", "man", "sin", "den", "the", "mad", "art", "can"):
        assert code not in AIRPORTS, code
    # ...while codes that are not words keep theirs.
    for code, expected in (("agp", "AGP"), ("bgo", "BGO"), ("ruh", "RUH"), ("auh", "AUH")):
        assert AIRPORTS[code][1] == expected


def test_particle_codes_inside_city_names_are_not_matchable():
    """SAN, LAS, DEL and LOS are IATA codes and also the first token of "San
    Diego", "Las Vegas", "Del Rio" and "Los Angeles"."""
    for code in ("san", "las", "del", "los"):
        assert code not in AIRPORTS, code
    assert AIRPORTS["san diego"][1] == "SAN"
    assert AIRPORTS["las vegas"][1] == "LAS"


def test_cities_shared_across_countries_are_dropped_entirely():
    """London is in the UK and in Ontario; Santiago is in four countries. A
    wrong region is worse than no region, so neither becomes an alias."""
    for city in ("london", "santiago", "valencia", "victoria", "manchester"):
        assert city not in AIRPORTS, city


def test_country_names_that_are_also_people_and_places_are_not_matched():
    """Georgia is a US state, Jordan is a surname, Chad is a given name. Those
    countries stay reachable through their airports instead."""
    for name in ("georgia", "jordan", "chad", "guinea", "mali", "niger"):
        assert name not in COUNTRY_ALIASES, name
    assert AIRPORT_COUNTRY["AMM"] == "jordan"
    assert AIRPORT_COUNTRY["TBS"] == "georgia"


def test_curated_entries_survive_the_generated_layer():
    """The hand-written table is an overlay, not a peer -- a dataset rebuild
    must not be able to overwrite it."""
    assert AIRPORTS["heathrow"] == ("London Heathrow", "LHR")
    assert AIRPORTS["istanbul"] == ("Istanbul Airport", "IST")
    assert AIRPORTS["sabiha gokcen"][1] == "SAW"
    # Curated over a dataset entry that would otherwise win: OurAirports files
    # both DOH (Hamad) and DIA (the closed Doha International) under "Doha".
    assert AIRPORTS["doha"][1] == "DOH"


def test_folding_lets_accented_and_turkish_names_match_at_all():
    """normalize_text() deletes every non-ASCII byte, so "Málaga" became
    "m laga" and could never match its own alias -- which is why the curated
    "sabiha gökçen" entry had been dead since it was written."""
    assert fold_for_match("Málaga") == "malaga"
    assert fold_for_match("Sabiha Gökçen") == "sabiha gokcen"
    assert fold_for_match("İstanbul") == "istanbul"


# --- what it all buys -----------------------------------------------------

async def test_region_resolves_via_an_airport_the_old_table_never_knew():
    """The bug this stage exists to fix. The old gazetteer knew 19 IATA codes,
    none of them secondary; route news names cities, so "Riyadh-Málaga" and
    "Bergen" stored region = NULL."""
    entities = await provider.extract_entities(
        "Turkish Airlines launches Riyadh–Málaga service",
        "The carrier will fly the route from March.",
    )
    codes = {m.code for m in entities if m.entity_type == "airport"}
    assert {"RUH", "AGP"} <= codes
    assert detect_region(entities) == "middle-east"

    entities = await provider.extract_entities(
        "Norwegian adds Bergen route", "New service to Bergen starts in June."
    )
    assert detect_region(entities) == "europe"


async def test_common_words_do_not_produce_airport_entities():
    entities = await provider.extract_entities(
        "Airline saw record demand",
        "The airline saw a nice split of traffic while reading the mobile gate reports.",
    )
    assert [m for m in entities if m.entity_type == "airport"] == []


async def test_german_ist_still_does_not_mean_istanbul():
    entities = await provider.extract_entities(
        "Das ist ein Test", "Hintergrund ist die Nachfrage am Flughafen."
    )
    assert entities == []


# --- the widened country map ---------------------------------------------

def test_country_map_covers_the_world_without_reclassifying_anything():
    assert len(COUNTRY_TO_REGION) > 200
    # Every assignment the product made by hand still holds.
    for country, region in CURATED_COUNTRY_REGION.items():
        assert COUNTRY_TO_REGION[country] == region
    # Countries the old 47-entry table had no answer for.
    assert COUNTRY_TO_REGION["malta"] == "europe"
    assert COUNTRY_TO_REGION["kazakhstan"] == "asia"
    assert COUNTRY_TO_REGION["oman"] == "middle-east"
    assert COUNTRY_TO_REGION["tanzania"] == "africa"
    assert COUNTRY_TO_REGION["bolivia"] == "south-america"
    assert set(COUNTRY_TO_REGION.values()) <= {
        "europe", "middle-east", "africa", "north-america", "central-america",
        "south-america", "asia", "southeast-asia", "oceania",
    }


def test_turkey_is_filed_with_the_gulf_everywhere_it_is_filed():
    """One call, made once. app/hubs.py used to say IST/SAW were in Europe
    while the taxonomy said Turkey was in the Middle East, so the Hub Explorer
    and the newspaper's region badge disagreed about the home hub."""
    from app.hubs import HUBS

    assert COUNTRY_TO_REGION["turkey"] == "middle-east"
    turkish = [hub for hub in HUBS if hub.country == "Turkey"]
    assert turkish, "expected the Turkish hubs to still be in the table"
    assert {hub.region for hub in turkish} == {"middle-east"}


def test_backend_and_frontend_agree_on_every_region_they_share():
    """The map colours countries from its own table. If the two drift, a signal
    lands in one region on the map and another in the ledger."""
    path = (
        Path(__file__).resolve().parents[3]
        / "frontend" / "src" / "lib" / "geo" / "region-countries.ts"
    )
    if not path.exists():  # backend-only checkout
        return
    frontend = dict(re.findall(r'"([^"]+)":\s*"([a-z-]+)"', path.read_text(encoding="utf-8")))
    backend = country_regions_by_name()
    shared = {name: region for name, region in frontend.items() if name.lower() in backend}
    # The GeoJSON spells ~30 names differently ("Bosnia and Herz."); the ones
    # that do match are plenty to catch a drift.
    assert len(shared) > 150
    for name, region in shared.items():
        assert backend[name.lower()] == region, name


def test_country_name_lookup_matches_the_taxonomy_keys():
    assert country_name("TR") == "turkey"
    assert country_name("ES") == "spain"
    assert country_name(None) is None
    for name in country_regions_by_name():
        assert name == name.lower()


# --- extraction precision -------------------------------------------------
#
# The gazetteer grew from 19 airports to ~3.2k, and recall came with a
# precision cost that the /insights map makes visible: every extracted
# airport becomes a marker a reader reads as a destination, so a false
# airport is a wrong claim rather than a silent mis-tag.


def test_month_abbreviation_is_not_read_as_an_airport_code():
    """"Okinawa Jan 2027 Launch" was matching JAN (Jackson, Mississippi) and
    filing a Taiwan-Japan story under north-america."""
    from app.llm.heuristic import extract_entity_mentions

    codes = [
        m.code
        for m in extract_entity_mentions("China Airlines Okinawa Jan 2027 Launch", "")
        if m.entity_type == "airport"
    ]
    assert "JAN" not in codes


def test_capitalised_bare_code_still_resolves():
    """The blocklist must not cost a real reference: a wire writes the code as
    JAN and the month as Jan, and that casing is the whole signal."""
    from app.llm.heuristic import extract_entity_mentions

    codes = [
        m.code
        for m in extract_entity_mentions("New flights to JAN announced", "")
        if m.entity_type == "airport"
    ]
    assert "JAN" in codes


def test_real_route_pair_is_untouched_by_the_blocklist():
    from app.llm.heuristic import extract_entity_mentions

    codes = {
        m.code
        for m in extract_entity_mentions(
            "Turkish Airlines launches Istanbul-Bergen route", ""
        )
        if m.entity_type == "airport"
    }
    assert {"IST", "BGO"} <= codes


def test_signal_airports_drop_the_carriers_own_hub():
    """TK naming IST is stating its origin, not announcing a route to it."""
    from app.services.insights_service import _destination_airports

    def ap(code: str) -> dict:
        return {"code": code, "name": code, "city": code, "country": "x",
                "lat": 0.0, "lon": 0.0}

    kept = [a["code"] for a in _destination_airports([ap("IST"), ap("BGO")], ["TK"])]
    assert kept == ["BGO"]


def test_signal_airports_are_capped_in_text_order():
    from app.services.insights_service import MAX_SIGNAL_AIRPORTS, _destination_airports

    def ap(code: str) -> dict:
        return {"code": code, "name": code, "city": code, "country": "x",
                "lat": 0.0, "lon": 0.0}

    kept = [
        a["code"]
        for a in _destination_airports(
            [ap("BGO"), ap("LHR"), ap("CDG"), ap("AMS")], ["TK"]
        )
    ]
    assert kept == ["BGO", "LHR", "CDG"]
    assert len(kept) == MAX_SIGNAL_AIRPORTS


def test_a_signal_whose_every_airport_is_a_hub_still_shows_them():
    """Dropping the last airport would erase the signal from the map."""
    from app.services.insights_service import _destination_airports

    def ap(code: str) -> dict:
        return {"code": code, "name": code, "city": code, "country": "x",
                "lat": 0.0, "lon": 0.0}

    assert [a["code"] for a in _destination_airports([ap("IST")], ["TK"])] == ["IST"]
