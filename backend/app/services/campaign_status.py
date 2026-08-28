"""Where a campaign is in time -- computed, never stored.

Why this is a function and not a column
---------------------------------------
A stored status is wrong the morning after it is written. `promotions` is
refreshed by cron jobs whose measured delay on this repo is 2-2.75 hours
(see services/delivery_window.py for the same measurement), so a status column
would be stale for a few hours every single day, and permanently stale for any
row the scraper stops seeing -- which is exactly the row whose campaign just
ended. The spec's rule is "never hard-code dates"; the operational consequence
of it is that status is a pure function of (the four date columns, today) and
is evaluated at read time, once, in one place.

That also makes this module trivially testable without a database, which is
why the decision table below can be asserted exhaustively rather than sampled.

The decision table
------------------
Reading `today` as a whole day (dates, never timestamps -- a cron delay must
not be able to move a row between buckets):

    sale window          travel window            -> status
    -------------------- ------------------------ ---------------------------
    nothing known        nothing known               UNKNOWN
    starts after today   (any)                       UPCOMING
    open                 (any, unless see below)     ACTIVE_BOOKING
    closed               still open or still future  BOOKING_CLOSED_TRAVEL_ACTIVE
    closed               over, or never stated       EXPIRED

"Open" means started-or-unknown-start AND not-yet-ended, where a missing edge
counts as open. That is the same convention as promo_dedup._windows_overlap
("a campaign with no stated end has not been said to stop") and as how the
timeline draws a half-known bar, so the three agree by construction instead of
by coincidence.

Boundaries are inclusive on both ends: `today == sale_ends` is still
ACTIVE_BOOKING, because a sale advertised as running "30 Kasım'a kadar" is
buyable on the 30th. The next day is the first day it is not.

Two edge cases worth stating outright
-------------------------------------
**Booking closed, travel not started yet.** Sale ended 15 September, travel
runs 1-30 December, today is 1 October. This is BOOKING_CLOSED_TRAVEL_ACTIVE,
not EXPIRED: the campaign's benefit is still live for everyone holding a
ticket, and a competitor's capacity is still committed to those dates. That is
the intelligence the status is for. Calling it EXPIRED would hide a campaign
that is very much still shaping December.

**Travel dates only, no sale dates at all.** The honest reading is that we do
not know when booking opened or closed -- and an unknown edge is an open edge
everywhere else in this codebase, so the sale window is treated as open and
the row is ACTIVE_BOOKING while the travel window has not ended. The
alternatives were both worse: UNKNOWN throws away the one thing we do know
(travel is live), and BOOKING_CLOSED_TRAVEL_ACTIVE asserts a booking deadline
nobody stated. The one place this rule bends is when the travel window is
already over -- there is nothing left to book or fly, so that row is EXPIRED
rather than ACTIVE_BOOKING, which is the single most misleading label this
module could produce.

Incoherent inputs (a sale starting after the travel window ended, say) are not
repaired here. pipeline/promotions._coherent already drops backwards ranges
before they are written, and inventing a repair at read time would make the
same row read differently depending on which layer you asked.
"""
from datetime import date

from app.taxonomy import CAMPAIGN_STATUSES

__all__ = ["CAMPAIGN_STATUSES", "campaign_status"]


def campaign_status(
    sale_starts: date | None,
    sale_ends: date | None,
    travel_starts: date | None,
    travel_ends: date | None,
    today: date,
) -> str:
    """One of `CAMPAIGN_STATUSES`, from the four nullable date columns.

    Positional rather than keyword-only on purpose: the argument order is the
    column order on `promotions` and on PromoCandidate, so a call site reads
    the same way the row does.
    """
    sale_known = sale_starts is not None or sale_ends is not None
    travel_known = travel_starts is not None or travel_ends is not None

    if not sale_known and not travel_known:
        # Nothing at all was stated. Not a guess, not a default -- the honest
        # answer, and the one the UI renders as "Belirsiz" rather than as a bar.
        return "UNKNOWN"

    if sale_starts is not None and sale_starts > today:
        return "UPCOMING"

    # A stated end that is in the past is the only way a sale window closes.
    # No end date means it has not been said to stop.
    sale_closed = sale_ends is not None and sale_ends < today

    if not sale_closed:
        travel_over = travel_ends is not None and travel_ends < today
        if not sale_known and travel_over:
            # Travel-dates-only rows whose travel window is already behind us:
            # treating the unknown sale window as open would publish a finished
            # campaign as "Satışta". See the module docstring.
            return "EXPIRED"
        return "ACTIVE_BOOKING"

    # Booking is over. What is left is whether the travel benefit still is.
    if travel_known and (travel_ends is None or travel_ends >= today):
        return "BOOKING_CLOSED_TRAVEL_ACTIVE"

    return "EXPIRED"
