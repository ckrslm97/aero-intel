"""The structured events calendar behind the /events page."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.tr_dates import format_date_range
from app.models.event import EVENT_TYPES, AviationEvent

router = APIRouter(prefix="/events", tags=["events"])


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def date_range_tr(self) -> str:
        """Pre-formatted Turkish range ("20-24 Temmuz 2026") so the frontend
        never re-implements month names."""
        return format_date_range(self.starts, self.ends)


@router.get("", response_model=list[EventOut])
async def list_events(
    region: str | None = None,
    event_type: str | None = Query(None, enum=list(EVENT_TYPES)),
    date_from: date | None = Query(None, description="Only events ending on/after this date"),
    date_to: date | None = Query(None, description="Only events starting on/before this date"),
    db: AsyncSession = Depends(get_db),
) -> list[EventOut]:
    query = select(AviationEvent).order_by(AviationEvent.starts)
    if region:
        query = query.where(AviationEvent.region == region)
    if event_type:
        query = query.where(AviationEvent.event_type == event_type)
    if date_from:
        # An event still in progress belongs on the calendar -> filter on `ends`.
        query = query.where(AviationEvent.ends >= date_from)
    if date_to:
        query = query.where(AviationEvent.starts <= date_to)
    rows = (await db.execute(query)).scalars().all()
    return [EventOut.model_validate(row) for row in rows]
