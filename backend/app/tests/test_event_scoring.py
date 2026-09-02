"""The read-time event importance score.

The load-bearing assertion in this file is the first one: an event with no
published headcount scores None, not zero. Everything else is ordering.
"""
from datetime import date, timedelta

import pytest

from app.ingest.events_seed import EVENTS, UNSCORED_IMPORTANCE, _article_importance
from app.services.event_scoring import (
    IMPACT_WEIGHTS,
    days_until,
    event_importance,
)

TODAY = date(2026, 9, 2)


def _score(
    impact: str = "high",
    attendance: int | None = 50_000,
    days_out: int = 30,
    length: int = 3,
) -> float | None:
    starts = TODAY + timedelta(days=days_out)
    return event_importance(impact, attendance, starts, starts + timedelta(days=length - 1), TODAY)


# --- the honesty rule -----------------------------------------------------

def test_an_event_with_no_published_headcount_has_no_score():
    """51 of the calendar's 86 rows publish no attendance, and they are
    disproportionately the *large* ones -- trade fairs that count exhibitors,
    religious observances, national holidays. Scoring them as zero would rank a
    1,200-delegate symposium above the Hajj. None means "not measurable"; it
    must never be quietly turned into a small number."""
    assert _score(attendance=None) is None
    assert _score(impact="high", attendance=None, days_out=1, length=1) is None
    # Zero and negative are the same non-answer, not a floor.
    assert _score(attendance=0) is None


def test_an_impact_level_outside_the_closed_set_has_no_score():
    """A level that is not one of the three is a data fault. A defaulted score
    would hide it behind a plausible number."""
    assert _score(impact="hig") is None
    assert _score(impact="") is None
    assert _score(impact="HIGH") == _score(impact="high")


def test_scores_stay_inside_the_unit_interval():
    for event in EVENTS:
        score = event_importance(
            event.impact_level, event.attendance, event.starts, event.ends, TODAY
        )
        assert score is None or 0.0 <= score <= 1.0, event.name


# --- the components, one at a time ---------------------------------------

def test_curated_impact_orders_otherwise_identical_events():
    assert _score(impact="high") > _score(impact="medium") > _score(impact="low")
    assert set(IMPACT_WEIGHTS) == {"high", "medium", "low"}


def test_attendance_is_read_on_a_log_scale():
    """The range is 1,200 to 6,000,000. On a linear scale every event except
    the Hajj would have a zero attendance term."""
    small, mid, large = (
        _score(attendance=4_000), _score(attendance=40_000), _score(attendance=400_000)
    )
    assert small < mid < large
    # Two equal ×10 steps buy the same amount of score. Linear would make the
    # first step invisible and the second one everything.
    assert (mid - small) == pytest.approx(large - mid, abs=0.002)


def test_attendance_beyond_the_top_anchor_does_not_keep_growing():
    """Anchored on fixed decades, so one enormous event cannot re-rank the
    other 85."""
    assert _score(attendance=1_000_000) == _score(attendance=6_000_000)


def test_a_long_event_scores_below_a_short_one_of_the_same_size():
    """Expo 2027 runs 192 days; a summit runs three. Same headcount, very
    different thing to plan capacity around."""
    assert _score(length=3) > _score(length=14) > _score(length=192)


def test_proximity_is_a_tie_break_and_not_a_ranking():
    """The lightest component on purpose: it is the only one that changes
    without the event changing."""
    near, far = _score(days_out=10), _score(days_out=400)
    assert near > far
    # It must not be able to lift a low-impact event over a high-impact one.
    assert _score(impact="low", days_out=1) < _score(impact="high", days_out=400)


def test_an_event_already_under_way_is_maximally_proximate():
    starts = TODAY - timedelta(days=2)
    running = event_importance("high", 50_000, starts, TODAY + timedelta(days=2), TODAY)
    over = event_importance("high", 50_000, starts, TODAY - timedelta(days=1), TODAY)
    assert running is not None and over is not None
    assert running > over


# --- what the whole thing is for -----------------------------------------

def test_big_near_and_short_outranks_small_far_and_endless():
    big_near_short = _score(impact="high", attendance=300_000, days_out=20, length=3)
    small_far_long = _score(impact="low", attendance=2_000, days_out=340, length=180)
    assert big_near_short > small_far_long
    # And by a wide margin -- the components agree rather than cancelling out.
    assert big_near_short - small_far_long > 0.5


def test_the_score_separates_the_fifty_six_high_impact_rows():
    """The reason this exists. 56 of 86 events are impact_level "high", which
    is why services/recommendations.py filters on event_type instead: the
    curated level alone cannot order the calendar."""
    highs = [e for e in EVENTS if e.impact_level == "high" and e.attendance]
    scores = {
        event_importance(e.impact_level, e.attendance, e.starts, e.ends, TODAY) for e in highs
    }
    assert len(highs) > 20
    assert len(scores) > len(highs) * 0.8


# --- days_until -----------------------------------------------------------

def test_days_until_is_signed_and_not_clamped():
    """GET /events keeps an event that has already started (it filters on
    `ends`), so -2 and +2 have to stay distinguishable."""
    assert days_until(date(2026, 9, 12), TODAY) == 10
    assert days_until(TODAY, TODAY) == 0
    assert days_until(date(2026, 8, 23), TODAY) == -10


# --- the seed's use of it -------------------------------------------------

def test_the_seed_falls_back_to_the_old_default_when_it_cannot_score():
    """Unscorable events keep exactly the importance they had before this
    change, so the new score can only move rows it knows something about."""
    unscorable = next(e for e in EVENTS if e.attendance is None)
    assert _article_importance(unscorable, TODAY) == UNSCORED_IMPORTANCE


def test_the_seed_no_longer_gives_every_event_the_same_importance():
    """It was 0.6 for all 86 rows, which made "critical event" a function of
    row order."""
    scores = {_article_importance(e, TODAY) for e in EVENTS}
    assert len(scores) > 20
    assert all(0.0 <= s <= 1.0 for s in scores)


@pytest.mark.parametrize(
    "event", [e for e in EVENTS if e.attendance], ids=lambda e: e.name
)
def test_every_seed_event_with_a_headcount_gets_a_real_score(event):
    """No silent fallback for a row that *does* carry the input: if the seed
    quietly kept 0.6 for a scorable event, the change would be a no-op nobody
    would notice."""
    computed = event_importance(
        event.impact_level, event.attendance, event.starts, event.ends, TODAY
    )
    assert computed is not None
    assert _article_importance(event, TODAY) == computed
