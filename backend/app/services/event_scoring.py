"""How much an events-calendar row matters -- computed at read time, from the
four columns that were actually measured.

Why a function and not a column
-------------------------------
Same reason as services/campaign_status.py: two of the four inputs are dates,
so any stored answer is wrong the next morning. An event three weeks out and
the same event three weeks later are not equally actionable, and a nightly job
that refreshed a stored score would still be wrong for most of the day. The
score is a pure function of (the row, today), evaluated once, where it is read.

It also means no migration and no new column -- the calendar's 86 rows already
carry every input this needs.

The honesty rule: no attendance, no score
-----------------------------------------
`attendance` is populated on 35 of 86 rows. The tempting shortcut is to treat
the other 51 as zero, and it is wrong in the most damaging possible direction:
the events that do not publish a headcount are disproportionately the large
ones -- trade fairs that count exhibitors instead of visitors, religious
observances, national holidays. Scoring them as attendance-zero would rank a
1,200-delegate symposium above the Hajj.

So an event with no published headcount returns None, and every caller has to
decide what to do about a missing score rather than being handed a small one.
The seed keeps its existing 0.6 default for exactly this case; the API sends
`null` and the UI can show a dash. None means "not measurable", never "small".

What the score is made of
-------------------------
Four components, each normalised to 0-1, weighted to sum to 1. Every one of
them reads a field a human either wrote by hand or copied from an organiser --
there is no derived-from-derived term anywhere in here.

    impact_level   0.45   The only *judgement* in the row: a person looked at
                          the event and said how hard it moves the market
                          (app/ingest/events_seed.py writes it next to the
                          dates and never infers it). It gets the largest
                          share because it is the only input that knows
                          anything the arithmetic cannot see. It does not get
                          a majority because it is nearly uniform in practice
                          -- 56 of 86 rows are "high" -- so on its own it
                          cannot order the calendar at all. That uniformity is
                          why services/recommendations.py filters events by
                          `event_type` instead, and it is the specific problem
                          the other three components exist to fix.

    attendance     0.30   The only independently published magnitude, and the
                          only component that separates those 56 "high" rows
                          from each other. Log scale, because the range is
                          1,200 to 6,000,000: on a linear scale the Hajj would
                          be the only event with a non-zero attendance term.
                          Anchored on fixed decades (1e3 -> 0, 1e6 -> 1) rather
                          than on the calendar's own min and max, so adding one
                          enormous event does not silently re-rank all 85
                          others.

    duration       0.15   Daily concentration. A 3-day summit puts its whole
                          demand into one booking window; Expo 2027 runs 192
                          days and its visitors arrive across six months. Same
                          headcount, very different thing to plan capacity
                          around. Corrective rather than primary: at 0.15 it
                          can pull a long event below a short one of equal
                          size, but it can never make a small event large.

    proximity      0.10   Days until the event starts. Lightest on purpose,
                          because it is the only component that changes without
                          the event changing: a calendar entry does not become
                          more important as it approaches, it becomes more
                          *actionable*. That is worth a tie-break between
                          comparable events and nothing more.

What is deliberately not here
-----------------------------
No `demand_potential`, `market_impact`, `rm_relevance`,
`international_relevance` or `airline_relevance`. The first four would be
`impact_level` under another name -- there is no second input to compute them
from, so they would carry no information beyond the field they were derived
from while reading like four independent measurements. `airline_relevance` has
no input at all: the calendar has no carrier dimension, which
services/recommendations.py already says outright at the point where it wants
one.
"""
from __future__ import annotations

import math
from datetime import date

__all__ = [
    "IMPACT_WEIGHTS",
    "MAX_ATTENDANCE_ANCHOR",
    "MIN_ATTENDANCE_ANCHOR",
    "PROXIMITY_HORIZON_DAYS",
    "days_until",
    "event_importance",
]

# The three curated levels, as fractions rather than 3/2/1: "low" is not a
# third of "high", it is "newsworthy, not a demand event" (see the impact_level
# comment in app/models/event.py).
IMPACT_WEIGHTS: dict[str, float] = {"high": 1.0, "medium": 0.55, "low": 0.2}

# Fixed decades, not the calendar's own extremes -- see the docstring.
MIN_ATTENDANCE_ANCHOR = 1_000
MAX_ATTENDANCE_ANCHOR = 1_000_000

# Beyond a year out, proximity stops discriminating: everything is "next year".
PROXIMITY_HORIZON_DAYS = 365

# A window short enough that the whole event is one booking decision.
_CONCENTRATED_DAYS = 3

_WEIGHT_IMPACT = 0.45
_WEIGHT_ATTENDANCE = 0.30
_WEIGHT_DURATION = 0.15
_WEIGHT_PROXIMITY = 0.10


def days_until(starts: date, today: date) -> int:
    """Signed days from `today` to `starts`.

    Negative for an event that has already begun, and deliberately not clamped
    to zero: GET /events keeps an in-progress event on the calendar (it filters
    on `ends`, not `starts`), so -2 and +2 are two different things a reader
    needs to be able to tell apart. None would collapse "started on Monday"
    into "unknown".
    """
    return (starts - today).days


def _attendance_component(attendance: int) -> float:
    """Log10 position between the two anchors, clamped to 0-1."""
    span = math.log10(MAX_ATTENDANCE_ANCHOR) - math.log10(MIN_ATTENDANCE_ANCHOR)
    position = (math.log10(attendance) - math.log10(MIN_ATTENDANCE_ANCHOR)) / span
    return min(1.0, max(0.0, position))


def _duration_component(starts: date, ends: date) -> float:
    """1.0 for anything a booking window can hold, decaying as 1/days.

    Inclusive of both end dates: a one-day event lasts one day, not zero.
    """
    days = max(1, (ends - starts).days + 1)
    return min(1.0, _CONCENTRATED_DAYS / days)


def _proximity_component(starts: date, ends: date, today: date) -> float:
    """1.0 while the event is running, decaying linearly over a year before it,
    0.0 once it is over."""
    if today > ends:
        return 0.0
    if today >= starts:
        return 1.0
    remaining = (starts - today).days
    return max(0.0, 1.0 - remaining / PROXIMITY_HORIZON_DAYS)


def event_importance(
    impact_level: str | None,
    attendance: int | None,
    starts: date,
    ends: date,
    today: date,
) -> float | None:
    """0-1 importance for one calendar row, or None when it cannot be scored.

    Returns None when `attendance` is missing -- read the docstring's honesty
    rule before changing that; a zero here is a lie about the largest events on
    the calendar. Also returns None for an `impact_level` outside
    `IMPACT_WEIGHTS`, rather than defaulting it: a level that is not one of the
    three curated ones is a data fault, and a plausible-looking score would
    hide it.
    """
    if attendance is None or attendance <= 0:
        return None
    weight = IMPACT_WEIGHTS.get((impact_level or "").lower())
    if weight is None:
        return None

    score = (
        _WEIGHT_IMPACT * weight
        + _WEIGHT_ATTENDANCE * _attendance_component(attendance)
        + _WEIGHT_DURATION * _duration_component(starts, ends)
        + _WEIGHT_PROXIMITY * _proximity_component(starts, ends, today)
    )
    # Three decimals: the inputs are a 3-level judgement and a rounded
    # headcount, so more precision than this would be decoration.
    return round(min(1.0, max(0.0, score)), 3)
