"""The stamp every aggregate endpoint puts on its own answer.

WHY THIS EXISTS
---------------
Five aggregate endpoints -- /biz, /insights, /recommendations, /hubs and
/hubs/network-signals -- returned their numbers with no timestamp on them at
all. The pages that render those numbers still had to print a "last updated",
so they printed the only time they had: the moment the BROWSER's fetch
resolved. That is a fact about the reader's network, not about the data. It
moved every time the tab was refreshed, it read "now" on a cached response
served from disk, and on a page fed by a cron that had stopped it kept
counting up forever -- the freshest possible stamp over the stalest possible
numbers.

`GET /risks` already answers this correctly (`RiskRadarOut.generated_at`, from
the `now` captured where the window is cut), and its comment states the
contract these helpers generalise: the stamp is "the moment the window was
cut, not the moment the response is serialized".

WHAT A CALLER OWES
------------------
One `now`, captured once, used for BOTH the window's SQL cut and the envelope.
That is why every service reached by these endpoints takes an optional `now`:
a helper that stamped `datetime.now()` at serialization time while the service
read its own clock a moment earlier would put a window on screen that is
adjacent to the one that was queried rather than the same one. Adjacent is
usually within milliseconds and occasionally across a midnight -- and a
timestamp nobody can reproduce from the payload is exactly the kind of claim
this codebase does not make.
"""
from datetime import datetime, timedelta


def window_of(now: datetime, days: int) -> dict:
    """One window, stated from both ends.

    `since`/`until` are spelled out rather than left to be re-derived from
    `days`: the reader of a payload should not have to know which end `days`
    counts back from, and a client that renders "son 30 gün" over a window that
    actually ran to a cron's clock is the same lie one layer up.
    """
    return {"days": days, "since": now - timedelta(days=days), "until": now}


def window_envelope(now: datetime, days: int) -> dict:
    """`generated_at` plus the single window everything in the payload shares."""
    return {"generated_at": now, "window": window_of(now, days)}


def windows_envelope(now: datetime, windows: dict[str, int]) -> dict:
    """`generated_at` plus one window PER AGGREGATE, for a payload that is not
    computed over a single window.

    /insights is the case: momentum compares 7-day halves while the route
    signals and the sentiment split each run over 30 days. Publishing one
    `days` for the response would misdescribe two thirds of it, so each part
    names its own -- the alternative to a number that is right about whichever
    block the reader happens to look at first.
    """
    return {
        "generated_at": now,
        "windows": {name: window_of(now, days) for name, days in windows.items()},
    }
