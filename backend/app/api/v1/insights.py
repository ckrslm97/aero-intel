"""Aggregated news-pattern data behind the /insights page."""
import asyncio

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db, run_with_own_session
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
    # Four independent aggregates that used to cost four serial round trips.
    # Each gets its own session because one AsyncSession cannot back several
    # concurrent tasks (see `run_with_own_session`).
    digest, momentum, routes, sentiment = await asyncio.gather(
        run_with_own_session(latest_digest, db),
        run_with_own_session(airline_momentum, db),
        run_with_own_session(new_route_signals, db),
        run_with_own_session(sentiment_by_category, db),
    )
    return {
        "airline_momentum": momentum,
        "new_route_signals": routes,
        "sentiment_by_category": sentiment,
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
