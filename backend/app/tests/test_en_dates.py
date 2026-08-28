"""English campaign dates, and the two ways reading them can go wrong.

Airline campaign pages are bilingual far more often than the news feed is --
TK, QR, EK and BA publish the same campaign in English and in Turkish, and the
English page is frequently the one that is fetchable at all. Before this the
extractor read only Turkish month names, so an English-only page became a
dateless point marker on a timeline whose entire purpose is timing.

The two failures worth a test file of their own:

* **Conflating the booking window with the travel window.** "Book until 31
  December 2026 for travel until 31 March 2027" contains two dates, a
  separator between them and sixteen characters in between -- every condition
  the range pairing looks for. Pairing them produces a fifteen-month "booking
  window" made of a booking deadline and a travel deadline, which is precisely
  what the four separate date columns exist to prevent. Several tests here do
  nothing but assert the two windows stayed apart.

* **Guessing a year and not saying so.** "Nov 25 - Dec 2" is a real range with
  a real ambiguity: the year comes from the article's publication date, not
  from the page. `find_dates_flagged` reports which dates were completed that
  way so the row can carry the doubt (`date_flags_json`) instead of drawing an
  inferred date exactly like a published one.
"""
from datetime import date

import pytest

from app.pipeline.promotions import (
    EN_MONTH_ABBREVIATIONS,
    EN_MONTHS,
    find_dates,
    find_dates_flagged,
    heuristic_extract,
)

YEAR = 2026


# --- the month vocabulary ----------------------------------------------------


def test_every_english_month_is_read_in_both_orders():
    """Full names and the British and American orders alike -- the same page
    routinely uses more than one."""
    for index, name in enumerate(EN_MONTHS, start=1):
        assert find_dates(f"on 12 {name} 2026") == [(3, date(2026, index, 12))]
        assert find_dates(f"on {name} 12, 2026") == [(3, date(2026, index, 12))]


def test_every_three_letter_abbreviation_is_read():
    """Marketing copy abbreviates freely ("Book by 28 Aug")."""
    for index, abbr in enumerate(EN_MONTH_ABBREVIATIONS, start=1):
        assert find_dates(f"by 9 {abbr} 2027") == [(3, date(2027, index, 9))]


def test_the_four_letter_september_abbreviation_is_read_too():
    assert find_dates("1 Sept 2026") == [(0, date(2026, 9, 1))]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("28 August 2026", date(2026, 8, 28)),
        ("Aug 28, 2026", date(2026, 8, 28)),
        ("August 28, 2026", date(2026, 8, 28)),
        ("28 Aug 2026", date(2026, 8, 28)),
        ("1st September 2026", date(2026, 9, 1)),
        ("September 1st, 2026", date(2026, 9, 1)),
        ("3rd Nov 2026", date(2026, 11, 3)),
        ("Dec. 24, 2026", date(2026, 12, 24)),
    ],
)
def test_the_shapes_english_campaign_copy_actually_uses(text, expected):
    dates = find_dates(text)
    assert [value for _, value in dates] == [expected]


def test_a_spelled_out_month_is_not_confused_with_a_four_digit_year():
    """"December 2026" states a month and a year, not a date. Reading "20" out
    of the year as a day is the classic version of this bug."""
    assert find_dates("valid in December 2026") == []


def test_an_english_month_name_alone_produces_nothing():
    assert find_dates("summer sale in August") == []


def test_turkish_and_english_month_names_do_not_collide():
    """"mart" is Turkish March and lives inside no English month; "may" is an
    English month and lives inside Turkish "mayıs". Both must resolve to
    exactly one date, not two."""
    assert find_dates("1 Mart 2026") == [(0, date(2026, 3, 1))]
    assert find_dates("1 Mayıs 2026") == [(0, date(2026, 5, 1))]
    assert find_dates("1 May 2026") == [(0, date(2026, 5, 1))]


def test_a_date_is_never_counted_twice_by_two_patterns():
    """Four patterns run over the same string; overlapping matches are
    suppressed. A double-counted date would let the range pairing build a
    window out of one date and itself."""
    assert len(find_dates("Book by 28 August 2026.")) == 1


# --- inferred years ----------------------------------------------------------


def test_a_stated_year_is_not_flagged_as_inferred():
    assert find_dates_flagged("28 August 2026", YEAR) == [(0, date(2026, 8, 28), False)]


def test_a_yearless_english_date_is_flagged_as_inferred():
    assert find_dates_flagged("28 August", YEAR) == [(0, date(2026, 8, 28), True)]


def test_a_yearless_turkish_date_is_flagged_as_inferred_the_same_way():
    assert find_dates_flagged("15 Ekim", YEAR) == [(0, date(2026, 10, 15), True)]


def test_a_numeric_date_always_states_its_year_and_is_never_inferred():
    assert find_dates_flagged("02/05/2026", YEAR) == [(0, date(2026, 5, 2), False)]


def test_a_yearless_date_is_still_dropped_when_no_year_can_be_supplied():
    """Unchanged behaviour: an inferred year is a reading, but an invented one
    is a guess, and this module's whole rule is that it does not guess."""
    assert find_dates_flagged("28 August") == []


def test_the_legacy_two_tuple_view_agrees_with_the_flagged_one():
    text = "Book 28 August 2026 for travel 5 Dec"
    assert find_dates(text, YEAR) == [
        (offset, value) for offset, value, _ in find_dates_flagged(text, YEAR)
    ]


def test_a_mixed_range_reports_the_inferred_end_only():
    """"Book from 1 September 2026 to 30 September" -- one stated year, one
    inferred, and the row should be able to say which was which."""
    flagged = find_dates_flagged("Book from 1 September 2026 to 30 September", YEAR)
    assert [inferred for _, _, inferred in flagged] == [False, True]


# --- windows stay apart ------------------------------------------------------


def test_a_booking_deadline_and_a_travel_deadline_are_not_conflated():
    fields = heuristic_extract(
        "Turkish Airlines promotion",
        "Book until 31 December 2026 for travel until 31 March 2027.",
        default_year=YEAR,
    )
    assert fields.sale_ends == date(2026, 12, 31)
    assert fields.travel_ends == date(2027, 3, 31)
    # Neither deadline may be read as the other window's start.
    assert fields.sale_starts is None
    assert fields.travel_starts is None


def test_a_booking_deadline_next_to_a_travel_range_keeps_all_three_dates_straight():
    fields = heuristic_extract(
        "Qatar Airways offer",
        "Book by 28 Aug 2026. Travel between 1 October 2026 and 31 December 2026.",
        default_year=YEAR,
    )
    assert (fields.sale_starts, fields.sale_ends) == (None, date(2026, 8, 28))
    assert (fields.travel_starts, fields.travel_ends) == (
        date(2026, 10, 1),
        date(2026, 12, 31),
    )


def test_an_english_sale_range_is_filed_under_sale():
    fields = heuristic_extract(
        "Emirates sale",
        "Sale period 28 August 2026 - 15 September 2026.",
        default_year=YEAR,
    )
    assert (fields.sale_starts, fields.sale_ends) == (date(2026, 8, 28), date(2026, 9, 15))
    assert fields.travel_starts is None


def test_the_american_order_pairs_into_a_range_as_well():
    fields = heuristic_extract(
        "British Airways",
        "On sale Aug 28, 2026 to Sep 15, 2026.",
        default_year=YEAR,
    )
    assert (fields.sale_starts, fields.sale_ends) == (date(2026, 8, 28), date(2026, 9, 15))


def test_a_yearless_range_pairs_and_takes_the_articles_year():
    """"Nov 25 - Dec 2" is how a Black Friday window is written."""
    fields = heuristic_extract("Black Friday", "Fares on sale Nov 25 - Dec 2.", default_year=YEAR)
    assert (fields.sale_starts, fields.sale_ends) == (date(2026, 11, 25), date(2026, 12, 2))
    assert all(inferred for _, _, inferred in find_dates_flagged("Nov 25 - Dec 2", YEAR))


def test_through_reads_as_a_range_separator():
    fields = heuristic_extract(
        "AJet", "Booking window 1 Sept 2026 through 30 Sept 2026.", default_year=YEAR
    )
    assert (fields.sale_starts, fields.sale_ends) == (date(2026, 9, 1), date(2026, 9, 30))


def test_and_reads_as_a_range_separator_after_between():
    fields = heuristic_extract(
        "Etihad", "Travel between 1 June 2027 and 30 September 2027.", default_year=YEAR
    )
    assert (fields.travel_starts, fields.travel_ends) == (
        date(2027, 6, 1),
        date(2027, 9, 30),
    )
    assert fields.sale_starts is None


# --- English deadline and start cues ----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Book until 31 December 2026.",
        "Valid until 31 December 2026.",
        "Book by 31 December 2026.",
        "Purchase before 31 December 2026.",
        "Offer ends 31 December 2026.",
        "Last day is 31 December 2026.",
        "On sale through 31 December 2026.",
    ],
)
def test_an_english_deadline_is_an_end_date_not_a_start(text):
    """English states the cue before the date, Turkish after it. Reading the
    English form as a start would draw the bar in entirely the wrong place --
    the same failure test_promotions.py pins down for "30 Kasım'a kadar"."""
    fields = heuristic_extract("Kampanya", text, default_year=YEAR)
    assert fields.sale_ends == date(2026, 12, 31)
    assert fields.sale_starts is None


@pytest.mark.parametrize(
    "text",
    [
        "Book from 1 September 2026.",
        "Tickets on sale starting 1 September 2026.",
        "Booking opens as of 1 September 2026.",
    ],
)
def test_an_english_start_cue_is_a_start_date(text):
    fields = heuristic_extract("Kampanya", text, default_year=YEAR)
    assert fields.sale_starts == date(2026, 9, 1)
    assert fields.sale_ends is None


def test_a_preposition_that_merely_precedes_a_date_is_not_a_deadline():
    """The head cues are anchored to the word immediately before the date. An
    unanchored "by" turns "announced by Turkish Airlines on 5 January" into a
    booking deadline of 5 January, which is not what it says."""
    fields = heuristic_extract(
        "Haber",
        "The campaign was announced by Turkish Airlines on 5 January 2027.",
        default_year=YEAR,
    )
    assert fields.sale_ends is None


# --- bilingual pages ---------------------------------------------------------


def test_a_turkish_sale_window_and_an_english_travel_deadline_coexist():
    """The common shape on a carrier's own page: Turkish body, English
    fine print, one campaign."""
    fields = heuristic_extract(
        "THY kampanyası",
        "Satış dönemi 15 Ekim 2026 - 30 Kasım 2026 arasındadır. "
        "Travel until 31 March 2027.",
        default_year=YEAR,
    )
    assert (fields.sale_starts, fields.sale_ends) == (date(2026, 10, 15), date(2026, 11, 30))
    assert fields.travel_ends == date(2027, 3, 31)


def test_an_english_discount_and_an_english_window_are_read_together():
    fields = heuristic_extract(
        "Pegasus",
        "Up to 40% off. Book by 28 August 2026 for travel between "
        "1 October 2026 and 31 December 2026.",
        default_year=YEAR,
    )
    assert fields.discount_pct == 40
    assert fields.sale_ends == date(2026, 8, 28)
    assert (fields.travel_starts, fields.travel_ends) == (
        date(2026, 10, 1),
        date(2026, 12, 31),
    )


def test_english_prose_with_no_dates_still_yields_no_dates():
    """The rule the whole module is built on survives the new patterns: an
    absent date stays absent rather than becoming a plausible one."""
    fields = heuristic_extract(
        "Emirates", "The airline says it will offer attractive fares this summer.", YEAR
    )
    assert (
        fields.sale_starts,
        fields.sale_ends,
        fields.travel_starts,
        fields.travel_ends,
    ) == (None, None, None, None)
