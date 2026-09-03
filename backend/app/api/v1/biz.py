"""BİZ page: competitor, network, commercial and strategic signals. The
passenger-review block is a separate, existing endpoint (GET /tk) -- not
duplicated here, same reasoning /tk's own docstring gives for TK news."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.api.window import window_envelope
from app.core.db import get_db
from app.services.biz_service import biz_overview

router = APIRouter(prefix="/biz", tags=["biz"])


@router.get("")
async def get_biz(
    days: int = Query(30, ge=1, le=365),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    public_cache(response, AGGREGATES)
    # One clock, captured here and handed down: `biz_overview` cuts all four
    # sections to it, and the same instant is what the page stamps as its
    # freshness. Without it the page had no timestamp at all and printed the
    # browser's fetch time -- a number that says the data is fresh whenever the
    # reader hits reload, including when the cron behind it stopped days ago.
    now = datetime.now(timezone.utc)
    return {
        **window_envelope(now, days),
        **await biz_overview(db, days=days, now=now),
    }
