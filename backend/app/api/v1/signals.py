"""SİNYALLER: the early-warning page's one composed feed.

Read-only, and composed rather than queried -- see
app/services/signals_service.py for which seven existing streams reach it and
why nothing new is detected here.
"""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.schemas.signals import SignalsOut
from app.services.signals_service import NEWS_WINDOW_DAYS, unified_signals

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=SignalsOut)
async def get_signals(
    days: int = Query(
        NEWS_WINDOW_DAYS,
        ge=1,
        le=365,
        description=(
            "News lookback for the event-derived streams (rival events, "
            "strategic developments, new routes). The risk rollup keeps its own "
            "14-day window and the campaign alert inbox has none at all -- both "
            "are the windows the pages that own them already use, and widening "
            "them from here would put a number on this page that the page it "
            "links to cannot reproduce"
        ),
    ),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> SignalsOut:
    # AGGREGATES, matching every stream this composes: the slowest-moving of
    # them is a twice-daily cron and the fastest is the 45-minute campaign
    # scan, so five minutes at the edge is never the reason a signal is late.
    public_cache(response, AGGREGATES)
    return await unified_signals(db, days=days)
