"""Aggregated news-pattern data behind the /insights page."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.services.insights_service import (
    airline_momentum,
    latest_digest,
    new_route_signals,
    sentiment_by_category,
)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
async def get_insights(
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    public_cache(response, AGGREGATES)
    digest = await latest_digest(db)
    return {
        "airline_momentum": await airline_momentum(db),
        "new_route_signals": await new_route_signals(db),
        "sentiment_by_category": await sentiment_by_category(db),
        "digest": (
            {
                "date": digest.digest_date.isoformat(),
                "body": digest.body,
                "provider": digest.provider,
            }
            if digest
            else None
        ),
    }
