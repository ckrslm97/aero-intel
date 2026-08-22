"""The airline campaign timeline behind the /kampanyalar page and the calendar's
campaign ribbons."""
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import Date, and_, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import FRESH, public_cache
from app.core.db import get_db
from app.core.tr_dates import format_optional_range
from app.models.promotion import NEW_WINDOW_HOURS, Promotion

router = APIRouter(prefix="/promotions", tags=["promotions"])


class PromotionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    airline_code: str
    airline_name: str
    title_tr: str
    summary_tr: str
    discount_pct: int | None
    markets: str | None
    sale_starts: date | None
    sale_ends: date | None
    travel_starts: date | None
    travel_ends: date | None
    url: str
    source_name: str
    region: str | None
    detected_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sale_range_tr(self) -> str:
        """Pre-formatted Turkish range so the frontend never re-implements
        month names -- the same contract as EventOut.date_range_tr, but through
        `format_optional_range` because every date here is nullable and a
        half-known window has to say which half is missing."""
        return format_optional_range(self.sale_starts, self.sale_ends)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def travel_range_tr(self) -> str:
        return format_optional_range(self.travel_starts, self.travel_ends)


@router.get("", response_model=list[PromotionOut])
async def list_promotions(
    # Multi-select, same convention as /recommendations: `?airline=PC&airline=TK`
    # widens to either. An absent or empty list means "every carrier".
    airline: list[str] | None = Query(None, description="IATA airline codes, e.g. PC"),
    date_from: date | None = Query(
        None, description="Only campaigns whose sale window reaches this date or later"
    ),
    date_to: date | None = Query(
        None, description="Only campaigns whose sale window starts on/before this date"
    ),
    days: int | None = Query(
        None,
        ge=1,
        le=365,
        description="Only campaigns DETECTED in the last N days (freshness, not sale window)",
    ),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[PromotionOut]:
    public_cache(response, FRESH)
    # Newest sighting first: this endpoint's headline job is "what just
    # launched", and the timeline re-sorts into lanes client-side anyway.
    query = select(Promotion).order_by(Promotion.detected_at.desc())

    if airline:
        query = query.where(Promotion.airline_code.in_(airline))

    # Every date filter below has to survive nulls, because every date column
    # is nullable. The three cases match exactly what the timeline draws:
    #   dated window  -> a bar, filtered on its real edges;
    #   open-ended    -> a bar that fades out; it is still running, so it
    #                    reaches any date_from;
    #   no start date -> a point marker at detected_at, filtered on that.
    if date_from:
        query = query.where(
            or_(
                Promotion.sale_ends >= date_from,
                and_(Promotion.sale_ends.is_(None), Promotion.sale_starts.isnot(None)),
                and_(
                    Promotion.sale_starts.is_(None),
                    cast(Promotion.detected_at, Date) >= date_from,
                ),
            )
        )
    if date_to:
        query = query.where(
            or_(
                Promotion.sale_starts <= date_to,
                and_(
                    Promotion.sale_starts.is_(None),
                    cast(Promotion.detected_at, Date) <= date_to,
                ),
            )
        )
    if days:
        query = query.where(
            Promotion.detected_at >= datetime.now(timezone.utc) - timedelta(days=days)
        )

    rows = (await db.execute(query)).scalars().all()
    return [PromotionOut.model_validate(row) for row in rows]


@router.get("/new-count")
async def count_new_promotions(
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """How many campaigns we first saw in the last 48 hours.

    Its own endpoint so the "Son 48 saatte N yeni kampanya" banner is a number
    over the whole table, not a count of whatever happened to fall inside the
    timeline's eight-week window.
    """
    public_cache(response, FRESH)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEW_WINDOW_HOURS)
    rows = (
        await db.execute(
            select(Promotion.airline_code).where(Promotion.detected_at >= cutoff)
        )
    ).scalars().all()
    return {
        "window_hours": NEW_WINDOW_HOURS,
        "count": len(rows),
        "airline_codes": sorted(set(rows)),
    }
