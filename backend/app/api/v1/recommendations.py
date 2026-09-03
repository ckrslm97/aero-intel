"""The evidence-backed action recommendations behind İçgörüler' Öneriler tab
(/insights?tab=oneriler; the old /oneriler path redirects there)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.api.window import window_envelope
from app.core.db import get_db
from app.services.recommendations import build_recommendations

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("")
async def list_recommendations(
    days: int = Query(7, ge=1, le=90, description="Comparison window, in days"),
    # Multi-select: `?region=europe&region=asia` narrows to either. A missing
    # or empty list means "don't filter on this dimension at all". `days` stays
    # single -- a comparison window is not a set.
    category: list[str] | None = Query(None),
    region: list[str] | None = Query(None),
    airline: list[str] | None = Query(None, description="IATA airline codes, e.g. EK"),
    response: Response = None,  # type: ignore[assignment]  -- FastAPI injects it
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deterministic patterns only -- every item carries the rows it came from,
    and an empty list is a valid, honest answer."""
    public_cache(response, AGGREGATES)
    # One clock for the six concurrent detectors and for the stamp on the
    # payload -- see build_recommendations' docstring for why they must share
    # it, and app/api/window.py for what the page was printing instead.
    now = datetime.now(timezone.utc)
    items = await build_recommendations(
        db, days=days, category=category, region=region, airline=airline, now=now
    )
    return {
        **window_envelope(now, days),
        "days": days,
        "count": len(items),
        "items": items,
    }
