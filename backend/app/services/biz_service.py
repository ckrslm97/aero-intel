"""BİZ page composition: where THY stands, told from data the platform
actually has.

Four sections, all queried from real tables -- no v1-style generated
narrative text here (see recommendations.py's own docstring on why that
engine stays deterministic; the same discipline applies to the two sections
new to this module). The no-filler rule is structural, not a convention to
remember: `_section()` is the only way a section reaches the response, and it
returns `available=False` with an honest empty_message instead of an empty
list, so a caller cannot accidentally render a bare `[]` as if it meant
something.

commercial_signals reuses recommendations.build_recommendations() as-is --
Öneriler was never one of the audit's broken surfaces (unlike the news/risk/
campaign pipelines this rebuild replaced), so folding it in here is a
relocation, not a rewrite. network_signals reuses network_signals_service.py
from the Hub phase for the same reason: one implementation, two pages.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent
from app.services.network_signals_service import network_signals
from app.services.recommendations import build_recommendations

EMPTY_MESSAGE = "Bu dönemde sinyal yok."

# The desk's established set of main rivals (see the golden-set cross-check
# audit earlier in this rebuild) -- watched individually so the section can
# say *which* competitor moved, not just that "competitors" did something.
RIVAL_CARRIERS: tuple[tuple[str, str], ...] = (
    ("EK", "Emirates"),
    ("QR", "Qatar Airways"),
    ("EY", "Etihad Airways"),
    ("LH", "Lufthansa"),
    ("AF", "Air France"),
    ("KL", "KLM"),
    ("BA", "British Airways"),
    ("PC", "Pegasus"),
    ("VF", "AJet"),
)

# finance: M&A, equity, partnerships. fleet: orders/deliveries -- a capacity
# commitment is a strategic move, not a route announcement (that's Ağ
# Sinyalleri). sustainability: SAF/decarbonisation commitments. regulatory:
# rules that reshape how the industry operates. Deliberately excludes
# revenue_management/network -- those already have their own sections here
# and on the Hub page, and a category counted twice would double the same
# signal's apparent weight.
STRATEGIC_CATEGORIES: tuple[str, ...] = ("finance", "fleet", "sustainability", "regulatory")

PUBLISHABLE_BANDS = ("high", "medium")


def _since(days: int, now: datetime | None = None) -> datetime:
    """The window's near edge. `now` is the caller's anchor when the caller
    has to report the window it served -- see `biz_overview`."""
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def _event_payload(event: NewsEvent) -> dict:
    return {
        "id": str(event.id),
        "slug": event.slug,
        "headline": event.title_tr,
        "category": event.category,
        # Carried so the Sinyaller aggregate can put a region on a card without
        # a second query -- the column is already loaded with the row.
        "region": event.region,
        "confidence_band": event.confidence_band,
        "last_seen": event.last_seen.isoformat(),
    }


def _section(items: list) -> dict:
    return (
        {"available": True, "items": items, "empty_message": None}
        if items
        else {"available": False, "items": [], "empty_message": EMPTY_MESSAGE}
    )


#: How many of a rival's events travel in the payload. A cap on the CARDS, and
#: emphatically not the count -- see `count` vs `events` below.
RIVAL_EVENT_CAP = 10


async def competitor_signals(
    db: AsyncSession, days: int = 30, now: datetime | None = None
) -> list[dict]:
    """Published events about each watched rival, most-covered rival first.
    An event with no coverage of any rival in the window contributes nothing
    -- rivals with zero events in the window are simply absent, not shown
    at zero, since a per-rival section is itself the "which one" the reader
    is after.

    `count` IS THE REAL TOTAL AND `events` IS THE HEAD OF IT. They used to be
    the same list: `count` was `len(rows)` over a query capped at ten, so every
    rival the news covered more than ten times in the window reported exactly
    "10 olay". A month in which Emirates was written about forty times and KLM
    ten rendered the two identically -- and the ranking underneath, sorted on
    that same saturated number, then ordered the rivals by nothing at all.

    So the total is its own `count(*)` over the same predicate, the ordering
    reads that total, and the cap applies only to the event payload the cards
    draw. Sinyaller's per-rival card (services/signals_service.py
    from_rival_events) prints this `count` verbatim and inherits the fix
    rather than carrying a second copy of it.
    """
    since = _since(days, now)
    out: list[dict] = []
    for code, name in RIVAL_CARRIERS:
        mentions = (
            select(ArticleEntity.article_id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(Entity.entity_type == "airline", Entity.code == code)
        )
        # One predicate, two reads of it: the total and the head. Written once
        # so the number on the card can never describe a different set than
        # the events under it.
        published_in_window = (
            NewsEvent.primary_article_id.in_(mentions),
            NewsEvent.is_published.is_(True),
            NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
            NewsEvent.superseded_at.is_(None),
            NewsEvent.last_seen >= since,
        )
        total = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(NewsEvent)
                    .where(*published_in_window)
                )
            ).scalar_one()
        )
        if not total:
            continue
        rows = (
            await db.execute(
                select(NewsEvent)
                .where(*published_in_window)
                .order_by(NewsEvent.last_seen.desc())
                .limit(RIVAL_EVENT_CAP)
            )
        ).scalars().all()
        out.append(
            {
                "airline_code": code,
                "airline_name": name,
                "count": total,
                # The newest RIVAL_EVENT_CAP of `count`, never all of them.
                # `events_truncated` says so on the wire, so that a card
                # listing ten events under a headline reading 40 CAN be
                # explained rather than merely inconsistent. No surface reads
                # it yet -- /biz does not render competitor_signals at all --
                # so this is a contract the frontend can honour, not a claim
                # that it already does.
                "events": [_event_payload(e) for e in rows],
                "events_truncated": total > len(rows),
            }
        )
    out.sort(key=lambda r: -r["count"])
    return out


async def strategic_developments(
    db: AsyncSession, days: int = 30, now: datetime | None = None
) -> list[dict]:
    rows = (
        await db.execute(
            select(NewsEvent)
            .where(
                NewsEvent.category.in_(STRATEGIC_CATEGORIES),
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                NewsEvent.superseded_at.is_(None),
                NewsEvent.last_seen >= _since(days, now),
            )
            .order_by(NewsEvent.last_seen.desc())
            .limit(30)
        )
    ).scalars().all()
    return [_event_payload(e) for e in rows]


async def biz_overview(db: AsyncSession, days: int = 30, now: datetime | None = None) -> dict:
    """The four BİZ sections, cut to ONE instant.

    `now` is threaded into all four rather than left to each: they are four
    sequential reads, so without an anchor the last section's window starts
    later than the first's, and the page's `generated_at` matches none of them.
    The differences are small and the claim is not.

    ONE INSTANT, NOT ONE WINDOW. Three sections are cut to `days` from this
    anchor; `commercial_signals` is `build_recommendations`, which runs its
    review themes four times wider and its event items FORWARD of today. The
    endpoint therefore publishes `windows` per section rather than a single
    `window` -- see app/api/v1/biz.py and
    services/recommendations.recommendation_windows.
    """
    anchor = now or datetime.now(timezone.utc)
    competitors = await competitor_signals(db, days=days, now=anchor)
    network = await network_signals(db, days=days, now=anchor)
    commercial = await build_recommendations(db, days=days, now=anchor)
    strategic = await strategic_developments(db, days=days, now=anchor)

    return {
        # `generated_at`/`window` are added by the endpoint, which owns the
        # envelope shape -- but from THIS anchor, handed to it by the caller,
        # so the stamp names the instant these four queries were cut at.
        "days": days,
        "competitor_signals": _section(competitors),
        # network_signals() already groups by region with its own non-empty
        # semantics (a region key only exists if it has events), so an empty
        # list here means exactly what _section()'s empty_message says.
        "network_signals": _section(network),
        "commercial_signals": _section(commercial),
        "strategic_developments": _section(strategic),
    }
