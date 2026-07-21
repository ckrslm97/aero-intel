"""The evidence-backed action recommendations behind the /oneriler page."""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.services.recommendations import build_recommendations

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("")
async def list_recommendations(
    days: int = Query(7, ge=1, le=90, description="Comparison window, in days"),
    category: str | None = None,
    region: str | None = None,
    airline: str | None = Query(
        None, max_length=6, description="IATA airline code, e.g. EK"
    ),
    response: Response = None,  # type: ignore[assignment]  -- FastAPI injects it
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deterministic patterns only -- every item carries the rows it came from,
    and an empty list is a valid, honest answer."""
    public_cache(response, AGGREGATES)
    items = await build_recommendations(
        db, days=days, category=category, region=region, airline=airline
    )
    return {"days": days, "count": len(items), "items": items}
