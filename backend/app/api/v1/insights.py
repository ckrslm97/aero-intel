"""Aggregated news-pattern data behind the /insights page."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.api.window import windows_envelope
from app.core.db import get_db, run_with_own_session
from app.services.insights_service import (
    airline_momentum,
    latest_digest,
    new_route_signals,
    sentiment_by_category,
)

router = APIRouter(prefix="/insights", tags=["insights"])

# The three aggregates' windows, named here because the payload now states
# them. They were each a default buried in the service's signature, so the page
# printed three differently-scoped numbers under one heading with nothing on
# screen saying they were differently scoped.
MOMENTUM_WINDOW_DAYS = 7
ROUTE_WINDOW_DAYS = 30
SENTIMENT_WINDOW_DAYS = 30


@router.get("")
async def get_insights(
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    public_cache(response, AGGREGATES)
    # ONE clock for the whole response: the same instant anchors all three SQL
    # windows and the `generated_at` the page prints. Read separately inside
    # each aggregate (as it used to be), the stamp would describe a window
    # slightly different from any of the ones actually queried -- and the page,
    # having no stamp at all, was printing the browser's fetch time instead,
    # which is a fact about the reader's network and not about this data.
    now = datetime.now(timezone.utc)

    # Four independent aggregates that used to cost four serial round trips.
    # Each gets its own session because one AsyncSession cannot back several
    # concurrent tasks (see `run_with_own_session`).
    digest, momentum, routes, sentiment = await asyncio.gather(
        run_with_own_session(latest_digest, db),
        run_with_own_session(
            airline_momentum, db, window_days=MOMENTUM_WINDOW_DAYS, now=now
        ),
        run_with_own_session(new_route_signals, db, days=ROUTE_WINDOW_DAYS, now=now),
        run_with_own_session(
            sentiment_by_category, db, days=SENTIMENT_WINDOW_DAYS, now=now
        ),
    )
    return {
        **windows_envelope(
            now,
            {
                "airline_momentum": MOMENTUM_WINDOW_DAYS,
                "new_route_signals": ROUTE_WINDOW_DAYS,
                "sentiment_by_category": SENTIMENT_WINDOW_DAYS,
            },
        ),
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
