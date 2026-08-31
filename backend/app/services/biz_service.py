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

from sqlalchemy import select
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


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


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


async def competitor_signals(db: AsyncSession, days: int = 30) -> list[dict]:
    """Published events about each watched rival, most-covered rival first.
    An event with no coverage of any rival in the window contributes nothing
    -- rivals with zero events in the window are simply absent, not shown
    at zero, since a per-rival section is itself the "which one" the reader
    is after."""
    since = _since(days)
    out: list[dict] = []
    for code, name in RIVAL_CARRIERS:
        mentions = (
            select(ArticleEntity.article_id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(Entity.entity_type == "airline", Entity.code == code)
        )
        rows = (
            await db.execute(
                select(NewsEvent)
                .where(
                    NewsEvent.primary_article_id.in_(mentions),
                    NewsEvent.is_published.is_(True),
                    NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                    NewsEvent.superseded_at.is_(None),
                    NewsEvent.last_seen >= since,
                )
                .order_by(NewsEvent.last_seen.desc())
                .limit(10)
            )
        ).scalars().all()
        if not rows:
            continue
        out.append(
            {
                "airline_code": code,
                "airline_name": name,
                "count": len(rows),
                "events": [_event_payload(e) for e in rows],
            }
        )
    out.sort(key=lambda r: -r["count"])
    return out


async def strategic_developments(db: AsyncSession, days: int = 30) -> list[dict]:
    rows = (
        await db.execute(
            select(NewsEvent)
            .where(
                NewsEvent.category.in_(STRATEGIC_CATEGORIES),
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                NewsEvent.superseded_at.is_(None),
                NewsEvent.last_seen >= _since(days),
            )
            .order_by(NewsEvent.last_seen.desc())
            .limit(30)
        )
    ).scalars().all()
    return [_event_payload(e) for e in rows]


async def biz_overview(db: AsyncSession, days: int = 30) -> dict:
    competitors = await competitor_signals(db, days=days)
    network = await network_signals(db, days=days)
    commercial = await build_recommendations(db, days=days)
    strategic = await strategic_developments(db, days=days)

    return {
        "days": days,
        "competitor_signals": _section(competitors),
        # network_signals() already groups by region with its own non-empty
        # semantics (a region key only exists if it has events), so an empty
        # list here means exactly what _section()'s empty_message says.
        "network_signals": _section(network),
        "commercial_signals": _section(commercial),
        "strategic_developments": _section(strategic),
    }
