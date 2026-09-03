"""The stamp every aggregate endpoint puts on its own answer.

WHY THIS EXISTS
---------------
Five aggregate endpoints -- /biz, /insights, /recommendations, /hubs and
/hubs/network-signals -- returned their numbers with no timestamp on them at
all.

On ONE of them that had already become a visible lie. The Ağ Sinyalleri tab
(frontend/src/components/hub-network-signals.tsx) prints a "son güncelleme" and
had nothing in the payload to print, so it printed the only time it had: the
moment the BROWSER's fetch resolved. That is a fact about the reader's network,
not about the data -- it moved on every refresh, it read "now" on a cached
response served from disk, and over a feed whose cron had stopped it counted up
forever: the freshest possible stamp on the stalest possible numbers.

The other four printed no time at all, which is not a lie but is not an answer
either: /hubs, /insights and /recommendations render windowed counts with no
way to say when the window was cut, and /insights states its scope in a
hand-written "(son 30 gün)" that no longer has to guess. For those four the
envelope is groundwork, not a repair, and the honest reading of this module is
that ONE surface was fixed and four were given something true to print when
they come to print it. (GET /biz is further back still: nothing in the
frontend calls it yet -- `BizOverviewOut` in frontend/src/lib/types.ts is a
type without a caller.)

What `generated_at` does and does not fix
----------------------------------------
It names the instant the SERVER cut the window, so a reader can reproduce the
window from the payload. It does NOT by itself expose a stopped cron: these
endpoints recompute on every request, so `generated_at` advances every time,
exactly as the browser's clock did. What it fixes for certain is the CACHED
response -- `public_cache(response, AGGREGATES)` lets an answer be served for
minutes, and a cached body now carries the moment it was actually computed
instead of the moment it was handed over. Staleness of the underlying feed is a
separate claim, made by the data's own timestamps.

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

And: a payload states EVERY window it was built from. `window_envelope` is only
for a response where one window genuinely covers everything; the moment a
section reaches outside it -- a longer look-back, a forward horizon --
`windows_envelope` names them one by one. A single declared `[since, until]`
with items from outside it is a payload misdescribing its own contents.
"""
from datetime import datetime, timedelta


def window_of(now: datetime, days: int) -> dict:
    """One window BACK from `now`, stated from both ends.

    `since`/`until` are spelled out rather than left to be re-derived from
    `days`: the reader of a payload should not have to know which end `days`
    counts back from, and a client that renders "son 30 gün" over a window that
    actually ran to a cron's clock is the same lie one layer up.

    A detector that compares this window against the one before it still
    declares THIS one: the earlier window is its baseline, not what it reports.
    """
    return {"days": days, "since": now - timedelta(days=days), "until": now}


def horizon_of(now: datetime, days: int) -> dict:
    """One window FORWARD from `now` -- for a section that reports on what has
    not happened yet.

    `/recommendations` carries upcoming aviation events, which by definition sit
    past `until` of every backward window in the same payload. Folding them into
    one is how a response ends up declaring a range that a third of its items
    are outside of. `days` stays positive and the direction is in the name, so
    that `since`/`until` read forwards the same way they read backwards.
    """
    return {"days": days, "since": now, "until": now + timedelta(days=days)}


def window_envelope(now: datetime, days: int) -> dict:
    """`generated_at` plus the one window everything in the payload shares.

    Only for payloads where that is actually true -- /hubs and
    /hubs/network-signals, whose every row comes out of the same `days` cut. A
    payload with a section on a different clock uses `windows_envelope`.
    """
    return {"generated_at": now, "window": window_of(now, days)}


def windows_envelope(now: datetime, windows: dict[str, dict]) -> dict:
    """`generated_at` plus one window PER AGGREGATE, for a payload that is not
    computed over a single window.

    /insights is the plainest case: momentum compares 7-day halves while the
    route signals and the sentiment split each run over 30 days. Publishing one
    `days` for the response would misdescribe two thirds of it, so each part
    names its own -- the alternative to a number that is right about whichever
    block the reader happens to look at first.

    /recommendations and /biz are the same problem with a wider spread: the TK
    review themes widen the comparison fourfold because reviews arrive in
    occasional curated passes, and the upcoming-events section looks FORWARD
    past the end of every other window in the payload.

    Takes built windows rather than day counts, because not every window is a
    look-back -- see `horizon_of`.
    """
    return {"generated_at": now, "windows": dict(windows)}
