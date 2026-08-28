"""The campaign status decision table, asserted exhaustively.

Status is the one field on the campaign surface that changes without anybody
writing to the row -- it is a pure function of four nullable dates and today's
date, evaluated at read time (see app/services/campaign_status.py for why it
is not a column). That makes it both the easiest thing here to test completely
and the easiest to get quietly wrong, because every mistake looks like a
plausible label rather than like an error.

Two things these tests exist to pin down:

* **The boundaries.** A sale advertised "30 Kasım'a kadar" is buyable on the
  30th. `today == sale_ends` is therefore still ACTIVE_BOOKING and the 1st is
  the first day it is not. An off-by-one here shows a live campaign as expired
  for a full day, to a desk whose entire reason for reading this is timing.

* **The two documented edge choices**, both of which are decisions rather than
  consequences and would otherwise be silently "fixed" by the next reader:
  booking-closed-but-travel-not-started-yet is BOOKING_CLOSED_TRAVEL_ACTIVE
  (the benefit is still live), and travel-dates-only is ACTIVE_BOOKING while
  travel has not ended (an unknown edge is an open edge, exactly as
  promo_dedup._windows_overlap reads it) -- but EXPIRED once it has.
"""
from datetime import date

import pytest

from app.services.campaign_status import campaign_status
from app.taxonomy import CAMPAIGN_STATUS_LABELS_TR, CAMPAIGN_STATUSES

TODAY = date(2026, 9, 15)


# (sale_starts, sale_ends, travel_starts, travel_ends, expected, why)
DECISION_TABLE = [
    (None, None, None, None, "UNKNOWN", "hiçbir tarih yok"),
    (date(2026, 10, 1), date(2026, 10, 15), None, None, "UPCOMING", "satış ileride"),
    (date(2026, 9, 16), None, None, None, "UPCOMING", "satış yarın açılıyor"),
    (date(2026, 9, 1), date(2026, 9, 30), None, None, "ACTIVE_BOOKING", "satış sürüyor"),
    (date(2026, 9, 15), date(2026, 9, 30), None, None, "ACTIVE_BOOKING", "bugün başladı"),
    (date(2026, 9, 1), date(2026, 9, 15), None, None, "ACTIVE_BOOKING", "son gün bugün"),
    (date(2026, 9, 1), None, None, None, "ACTIVE_BOOKING", "bitiş belirtilmemiş"),
    (None, date(2026, 9, 30), None, None, "ACTIVE_BOOKING", "başlangıç belirtilmemiş"),
    (date(2026, 9, 1), date(2026, 9, 14), None, None, "EXPIRED", "satış dün kapandı, seyahat yok"),
    (
        date(2026, 9, 1), date(2026, 9, 14), date(2026, 12, 1), date(2026, 12, 31),
        "BOOKING_CLOSED_TRAVEL_ACTIVE", "satış kapandı, seyahat aralıkta",
    ),
    (
        date(2026, 9, 1), date(2026, 9, 14), date(2026, 8, 1), date(2026, 9, 15),
        "BOOKING_CLOSED_TRAVEL_ACTIVE", "seyahatin son günü bugün",
    ),
    (
        date(2026, 9, 1), date(2026, 9, 14), date(2026, 8, 1), date(2026, 9, 14),
        "EXPIRED", "seyahat de bitti",
    ),
    (
        date(2026, 9, 1), date(2026, 9, 14), date(2026, 10, 1), None,
        "BOOKING_CLOSED_TRAVEL_ACTIVE", "seyahat bitişi açık uçlu",
    ),
    (
        date(2026, 9, 1), date(2026, 9, 14), None, date(2026, 12, 31),
        "BOOKING_CLOSED_TRAVEL_ACTIVE", "yalnızca seyahat bitişi biliniyor",
    ),
    (
        None, None, date(2026, 10, 1), date(2026, 12, 31),
        "ACTIVE_BOOKING", "satış dönemi bilinmiyor, seyahat ileride",
    ),
    (
        None, None, date(2026, 1, 1), date(2026, 9, 15),
        "ACTIVE_BOOKING", "satış bilinmiyor, seyahat bugün bitiyor",
    ),
    (
        None, None, date(2026, 1, 1), date(2026, 9, 14),
        "EXPIRED", "satış bilinmiyor, seyahat dün bitti",
    ),
    (None, None, date(2026, 10, 1), None, "ACTIVE_BOOKING", "yalnızca seyahat başlangıcı"),
    (None, None, None, date(2026, 12, 31), "ACTIVE_BOOKING", "yalnızca seyahat bitişi"),
]


@pytest.mark.parametrize(
    "sale_starts,sale_ends,travel_starts,travel_ends,expected,why",
    DECISION_TABLE,
    ids=[row[5] for row in DECISION_TABLE],
)
def test_the_decision_table(sale_starts, sale_ends, travel_starts, travel_ends, expected, why):
    assert (
        campaign_status(sale_starts, sale_ends, travel_starts, travel_ends, TODAY) == expected
    ), why


def test_every_status_the_table_produces_is_a_declared_slug():
    """A status the taxonomy does not know about is a filter chip that renders
    blank and a label lookup that raises."""
    produced = {
        campaign_status(row[0], row[1], row[2], row[3], TODAY) for row in DECISION_TABLE
    }
    assert produced <= set(CAMPAIGN_STATUSES)
    assert all(slug in CAMPAIGN_STATUS_LABELS_TR for slug in produced)


def test_the_table_exercises_every_declared_status():
    """If a status is unreachable it is either dead or the engine is missing a
    branch; either way it should not sit in the taxonomy unnoticed."""
    produced = {
        campaign_status(row[0], row[1], row[2], row[3], TODAY) for row in DECISION_TABLE
    }
    assert produced == set(CAMPAIGN_STATUSES)


def test_the_last_day_of_the_sale_is_still_a_selling_day():
    assert campaign_status(date(2026, 9, 1), TODAY, None, None, TODAY) == "ACTIVE_BOOKING"


def test_the_day_after_the_sale_closes_is_the_first_non_selling_day():
    yesterday = date(2026, 9, 14)
    assert campaign_status(date(2026, 9, 1), yesterday, None, None, TODAY) == "EXPIRED"


def test_the_day_the_sale_opens_is_already_a_selling_day():
    assert campaign_status(TODAY, date(2026, 9, 30), None, None, TODAY) == "ACTIVE_BOOKING"


def test_the_day_before_the_sale_opens_is_still_upcoming():
    assert campaign_status(date(2026, 9, 16), date(2026, 9, 30), None, None, TODAY) == "UPCOMING"


def test_booking_closed_before_travel_even_starts_is_not_expired():
    """The documented edge choice: a sale that closed in September for travel
    in December is still shaping December. Calling it EXPIRED would delete a
    competitor's committed capacity from the analyst's view."""
    assert (
        campaign_status(
            date(2026, 8, 1), date(2026, 9, 1), date(2026, 12, 1), date(2026, 12, 31), TODAY
        )
        == "BOOKING_CLOSED_TRAVEL_ACTIVE"
    )


def test_travel_dates_alone_are_read_as_an_open_sale_window():
    """The second documented edge choice. An unknown edge is an open edge
    everywhere else in this codebase (promo_dedup._windows_overlap), so a row
    that states only a live travel window is ACTIVE_BOOKING rather than
    UNKNOWN -- we do know something, and it is that this is running."""
    assert (
        campaign_status(None, None, date(2026, 9, 1), date(2026, 10, 31), TODAY)
        == "ACTIVE_BOOKING"
    )


def test_travel_dates_alone_that_are_already_over_are_expired_not_active():
    """The one place the open-edge rule bends, and the reason it has to: there
    is nothing left to book or fly, and "Satışta" would be the single most
    misleading label this module could produce."""
    assert (
        campaign_status(None, None, date(2026, 1, 1), date(2026, 2, 1), TODAY) == "EXPIRED"
    )


def test_an_incoherent_row_is_labelled_not_repaired():
    """A sale opening in October against a travel window that ended in August
    is contradictory data. pipeline/promotions._coherent drops backwards
    ranges before they are written; inventing a second repair here would make
    the same row read differently depending on which layer you asked."""
    assert (
        campaign_status(date(2026, 10, 1), date(2026, 10, 15), None, date(2026, 8, 1), TODAY)
        == "UPCOMING"
    )


def test_status_moves_with_today_and_nothing_else():
    """The whole reason this is a function: the same row reads differently on
    three consecutive days without anybody writing to it."""
    row = (date(2026, 9, 10), date(2026, 9, 15), date(2026, 10, 1), date(2026, 10, 31))
    assert campaign_status(*row, date(2026, 9, 9)) == "UPCOMING"
    assert campaign_status(*row, date(2026, 9, 15)) == "ACTIVE_BOOKING"
    assert campaign_status(*row, date(2026, 9, 16)) == "BOOKING_CLOSED_TRAVEL_ACTIVE"
    assert campaign_status(*row, date(2026, 11, 1)) == "EXPIRED"
