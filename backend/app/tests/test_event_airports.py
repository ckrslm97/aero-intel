"""The curated city -> airport table, and the measurement that made it curated.

The risk here is not a crash. It is a plausible-looking wrong airport: a
Venezuelan code under a Barcelona conference reads exactly like a correct
answer, and nothing downstream can tell the difference. These tests exist so a
typo'd code or an uncurated city fails loudly instead.
"""
from app.data import airports_by_iata
from app.data.event_airports import CITY_AIRPORTS, airports_for_city, fold_city
from app.ingest.events_seed import EVENTS
from app.llm.gazetteer import fold_for_match


def test_every_curated_code_is_a_real_airport():
    """A typo'd IATA code would otherwise pass silently and render in the UI as
    a real airport -- there is nothing downstream that could catch it."""
    known = airports_by_iata()
    for city, codes in CITY_AIRPORTS.items():
        for code in codes:
            assert code in known, f"{city}: {code} is not in app/data/airports.json"


def test_no_city_lists_the_same_airport_twice():
    for city, codes in CITY_AIRPORTS.items():
        assert len(codes) == len(set(codes)), city


def test_keys_are_already_folded():
    """Lookups fold the query, so an unfolded key ("Münih") is a dead entry."""
    for key in CITY_AIRPORTS:
        assert fold_city(key) == key, key


def test_the_fold_matches_the_gazetteers():
    """This module deliberately re-implements `fold_for_match` rather than
    importing it (see its docstring: layering, and an 800KB cold-start cost).
    That is only safe while the two agree, so they are pinned here."""
    samples = [event.city for event in EVENTS] + [
        "Münih", "Şikago", "İstanbul", "Málaga", "Sabiha Gökçen",
        "Adare Manor (Limerick)", "Aichi-Nagoya", "Şanlıurfa",
    ]
    for sample in samples:
        assert fold_city(sample) == fold_for_match(sample), sample


# --- the coverage the calendar actually needs -----------------------------

def test_every_seeded_city_is_curated():
    """Not "resolves to something" -- *is a key*. An event added with a new
    city has to be curated deliberately; falling through to an empty list would
    make the omission invisible."""
    uncurated = sorted({e.city for e in EVENTS if fold_city(e.city) not in CITY_AIRPORTS})
    assert uncurated == [], uncurated


def test_most_seeded_cities_resolve_to_at_least_one_airport():
    resolved = [e.city for e in EVENTS if airports_for_city(e.city)]
    # 51 of the calendar's 65 distinct cities are real cities; the rest are
    # country-wide or global scopes.
    assert len(resolved) > len(EVENTS) * 0.7


def test_turkish_and_english_spellings_give_the_same_answer():
    """The seed writes the city in Turkish; everyone reading this table thinks
    in English. A lookup that works for "Munich" and not "Münih" works
    everywhere except production."""
    for turkish, english in (
        ("Münih", "Munich"),
        ("Lizbon", "Lisbon"),
        ("Riyad", "Riyadh"),
        ("Londra", "London"),
        ("Milano", "Milan"),
        ("Şikago", "Chicago"),
        ("Barselona", "Barcelona"),
        ("Pekin", "Beijing"),
        ("Viyana", "Vienna"),
        ("Budapeşte", "Budapest"),
        ("Seul", "Seoul"),
        ("Singapur", "Singapore"),
        ("Belgrad", "Belgrade"),
        ("Mekke", "Mecca"),
        ("Yeni Delhi", "New Delhi"),
    ):
        assert airports_for_city(turkish) == airports_for_city(english), turkish
        assert airports_for_city(turkish), turkish


def test_lookup_ignores_case_and_punctuation():
    assert airports_for_city("MÜNIH") == ("MUC",)
    assert airports_for_city("  münih  ") == ("MUC",)
    assert airports_for_city("Aichi-Nagoya") == airports_for_city("Aichi Nagoya")


def test_scopes_that_are_not_cities_resolve_to_nothing():
    """"Çin geneli" is a country, "Küresel" is the whole world, "Türkiye ve
    İslam dünyası" is a religious observance. Inventing a gateway for any of
    them would put a confident airport code under an event that has none."""
    for scope in (
        "Çin geneli", "Küresel", "Türkiye ve İslam dünyası", "ABD geneli",
        "Avrupa geneli", "Hindistan geneli", "Brezilya (8 şehir)",
        "İslam dünyası geneli", "Kenya, Tanzanya ve Uganda geneli",
    ):
        assert airports_for_city(scope) == (), scope


def test_unknown_and_empty_input_resolve_to_nothing():
    assert airports_for_city("Atlantis") == ()
    assert airports_for_city("") == ()
    assert airports_for_city(None) == ()


# --- the seven cities automatic resolution got wrong ----------------------
#
# Each of these is a measurement, not a preference: the module docstring's
# table is what `airport.city == event.city` returns today.

def test_paris_resolves_to_the_airports_paris_actually_flies_through():
    """Matching on airport.city returns only LBG, because CDG is filed under
    "Paris (Roissy-en-France, Val-d'Oise)" and ORY under "Paris (Orly,
    Val-de-Marne)" -- the two that matter are the two that do not match."""
    assert airports_for_city("Paris") == ("CDG", "ORY")


def test_milan_and_frankfurt_resolve_at_all():
    """Automatic resolution returns nothing for either: MXP is filed under
    "Ferno (VA)", LIN under "Segrate (MI)", FRA under "Frankfurt am Main"."""
    assert airports_for_city("Milano") == ("MXP", "LIN", "BGY")
    assert airports_for_city("Frankfurt") == ("FRA",)


def test_secondary_airports_filed_under_their_own_town_are_not_lost():
    """NRT is filed under "Narita" and EWR under "Newark", so neither is
    reachable from its metropolitan area's name."""
    assert "NRT" in airports_for_city("Tokyo")
    assert "EWR" in airports_for_city("New York")


def test_same_named_cities_in_other_countries_are_excluded():
    """The dangerous failure. YXU is London, Ontario; BLA is Barcelona,
    Venezuela. Both are returned by name matching, and both read as correct."""
    assert "YXU" not in airports_for_city("Londra")
    assert "BLA" not in airports_for_city("Barselona")
    assert airports_for_city("Barselona") == ("BCN",)


def test_venues_without_an_airport_point_at_the_gateway_people_actually_use():
    """Davos has no airport; the WEF's delegates land at Zurich. Mecca has
    none; pilgrims arrive at Jeddah. Pilton is a Somerset village."""
    assert airports_for_city("Davos") == ("ZRH",)
    assert airports_for_city("Mekke") == ("JED", "MED")
    assert airports_for_city("Pilton") == ("BRS",)


def test_farnborough_lists_where_the_visitors_land_not_the_showground():
    """FAB is a business-aviation field and is not even in the bundled
    scheduled-service cut; the airshow's 80k visitors arrive at LHR and LGW,
    which is what the event's own demand line says."""
    assert airports_for_city("Farnborough") == ("LHR", "LGW")
    assert "FAB" not in airports_by_iata()
