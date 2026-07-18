"""Aggregated news-pattern data behind the /insights page."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.insights_service import (
    airline_momentum,
    category_volume_by_week,
    latest_digest,
    new_route_signals,
    sentiment_by_category,
    top_corroborated_stories,
)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
async def get_insights(db: AsyncSession = Depends(get_db)) -> dict:
    digest = await latest_digest(db)
    return {
        "volume_by_week": await category_volume_by_week(db),
        "airline_momentum": await airline_momentum(db),
        "new_route_signals": await new_route_signals(db),
        "sentiment_by_category": await sentiment_by_category(db),
        "top_stories": await top_corroborated_stories(db),
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
