"""BİZ page: competitor, network, commercial and strategic signals. The
passenger-review block is a separate, existing endpoint (GET /tk) -- not
duplicated here, same reasoning /tk's own docstring gives for TK news."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.api.window import window_of, windows_envelope
from app.core.db import get_db
from app.services.biz_service import biz_overview
from app.services.recommendations import recommendation_windows

router = APIRouter(prefix="/biz", tags=["biz"])


@router.get("")
async def get_biz(
    days: int = Query(30, ge=1, le=365),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    public_cache(response, AGGREGATES)
    # One clock, captured here and handed down: `biz_overview` cuts all four
    # sections to it, and the same instant is what a page rendering this would
    # stamp as its freshness. (Nothing calls this endpoint yet -- see
    # app/api/window.py -- so the envelope is groundwork, not a repair.)
    now = datetime.now(timezone.utc)
    return {
        # Three of the four sections share `days`. The commercial block does
        # not: it is `build_recommendations`, whose review themes run four
        # times wider and whose event items sit FORWARD of every other window
        # in this payload. Declaring one `window` over all of it would have the
        # response misdescribe its own contents.
        **windows_envelope(
            now,
            {
                "competitor_signals": window_of(now, days),
                "network_signals": window_of(now, days),
                "strategic_developments": window_of(now, days),
                **{
                    f"commercial_{name}": win
                    for name, win in recommendation_windows(now, days).items()
                },
            },
        ),
        **await biz_overview(db, days=days, now=now),
    }
