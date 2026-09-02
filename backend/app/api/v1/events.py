"""The structured events calendar behind the /events page.

Three of `EventOut`'s fields are computed at read time rather than stored:
`relevant_airports` (from the curated table in app/data/event_airports.py),
`importance_score` (app/services/event_scoring.py) and `days_until`. None of
them needs a column -- they are pure functions of the row and of today, and a
stored copy of any of them would be wrong the next morning. Same reasoning as
services/campaign_status.py, and the same reason this endpoint needed no
migration to grow them.
"""
import uuid
from datetime import date, datetime, timezone
from enum import StrEnum

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import STATIC, public_cache
from app.core.db import get_db
from app.core.tr_dates import format_date_range
from app.data.event_airports import airports_for_city
from app.models.event import EVENT_TYPES, IMPACT_LEVELS, AviationEvent
from app.services.event_scoring import days_until, event_importance
from app.taxonomy import REGION_LABELS_TR

router = APIRouter(prefix="/events", tags=["events"])

# Real enums rather than `Query(..., enum=[...])`. The latter only decorates
# the OpenAPI schema -- FastAPI does not enforce it, which is why
# `?region=erupoe` used to return 200 and an empty calendar instead of telling
# the caller the region does not exist. A typo that silently looks like "no
# events this quarter" is the worst possible failure for a calendar.
#
# Built from the existing constants so the API cannot drift from the taxonomy
# or the model.
EventTypeParam = StrEnum("EventTypeParam", {slug: slug for slug in EVENT_TYPES})
ImpactParam = StrEnum("ImpactParam", {slug: slug for slug in IMPACT_LEVELS})
RegionParam = StrEnum(
    "RegionParam", {slug.replace("-", "_"): slug for slug in REGION_LABELS_TR}
)


class EventOrder(StrEnum):
    starts = "starts"
    importance = "importance"


# `impact_level` is a rank, not a category, so `min_impact` means "at least
# this hard-hitting" rather than "exactly this".
_IMPACT_AT_LEAST: dict[str, tuple[str, ...]] = {
    "high": ("high",),
    "medium": ("high", "medium"),
    "low": ("high", "medium", "low"),
}

# High enough that no realistic calendar view hits it, low enough that a
# scripted `?limit=1000000` cannot ask the database for the world.
MAX_LIMIT = 500


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    starts: date
    ends: date
    city: str
    country: str | None
    region: str | None
    url: str
    summary_tr: str
    event_type: str
    # What the calendar is for: how hard this moves demand, and what to expect.
    impact_level: str
    attendance: int | None
    demand_effect_tr: str

    # --- computed at read time (see the module docstring) -----------------

    #: IATA codes the event's traffic actually uses. Empty for an entry that is
    #: not a city ("Çin geneli", "Küresel") and for a city nobody has curated
    #: yet -- see app/data/event_airports.py for why this is not resolved
    #: automatically.
    relevant_airports: list[str]
    #: 0-1, or null when the event publishes no headcount. Null means "not
    #: measurable", never "small": app/services/event_scoring.py refuses to
    #: score an event with no attendance rather than treating it as zero.
    importance_score: float | None
    #: Signed days to the start. Negative for an event already under way --
    #: which the calendar keeps, because it filters on `ends`. Never null:
    #: `starts` is NOT NULL, so "unknown" is not one of the answers.
    days_until: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def date_range_tr(self) -> str:
        """Pre-formatted Turkish range ("20-24 Temmuz 2026") so the frontend
        never re-implements month names."""
        return format_date_range(self.starts, self.ends)

    @classmethod
    def from_row(cls, row: AviationEvent, today: date) -> "EventOut":
        return cls(
            id=row.id,
            name=row.name,
            starts=row.starts,
            ends=row.ends,
            city=row.city,
            country=row.country,
            region=row.region,
            url=row.url,
            summary_tr=row.summary_tr,
            event_type=row.event_type,
            impact_level=row.impact_level,
            attendance=row.attendance,
            demand_effect_tr=row.demand_effect_tr,
            relevant_airports=list(airports_for_city(row.city)),
            importance_score=event_importance(
                row.impact_level, row.attendance, row.starts, row.ends, today
            ),
            days_until=days_until(row.starts, today),
        )


def _today() -> date:
    """UTC, and a whole day. Same convention as api/v1/promotions.py: a
    read-time computation must not shift because the reader is in a different
    timezone from the deployment."""
    return datetime.now(timezone.utc).date()


def _importance_sort_key(event: EventOut) -> tuple[int, float, date]:
    """Highest score first; unscorable events keep their date order at the end.

    They are placed last, not scored as zero: an event with no published
    headcount is not small, it is not comparable on this axis (see
    app/services/event_scoring.py). Putting them after the ranked ones is the
    only ordering that does not assert something about them.
    """
    if event.importance_score is None:
        return (1, 0.0, event.starts)
    return (0, -event.importance_score, event.starts)


@router.get("", response_model=list[EventOut])
async def list_events(
    region: RegionParam | None = None,
    event_type: EventTypeParam | None = None,
    date_from: date | None = Query(None, description="Only events ending on/after this date"),
    date_to: date | None = Query(None, description="Only events starting on/before this date"),
    min_impact: ImpactParam | None = Query(
        None, description="Keep events at least this impactful (high < medium < low)"
    ),
    order: EventOrder = Query(
        EventOrder.starts, description="Calendar order (default) or importance-ranked"
    ),
    limit: int | None = Query(None, ge=1, le=MAX_LIMIT),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[EventOut]:
    public_cache(response, STATIC)
    query = select(AviationEvent).order_by(AviationEvent.starts)
    if region:
        query = query.where(AviationEvent.region == region.value)
    if event_type:
        query = query.where(AviationEvent.event_type == event_type.value)
    if date_from:
        # An event still in progress belongs on the calendar -> filter on `ends`.
        query = query.where(AviationEvent.ends >= date_from)
    if date_to:
        query = query.where(AviationEvent.starts <= date_to)
    if min_impact:
        query = query.where(
            AviationEvent.impact_level.in_(_IMPACT_AT_LEAST[min_impact.value])
        )
    if limit is not None and order is EventOrder.starts:
        # Only pushable to SQL for the date order; the importance rank is
        # computed per row, so its limit has to be applied after sorting.
        query = query.limit(limit)

    rows = (await db.execute(query)).scalars().all()
    today = _today()
    events = [EventOut.from_row(row, today) for row in rows]
    if order is EventOrder.importance:
        events.sort(key=_importance_sort_key)
        if limit is not None:
            events = events[:limit]
    return events
