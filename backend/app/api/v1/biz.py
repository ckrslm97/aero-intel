"""BİZ page: competitor, network, commercial and strategic signals. The
passenger-review block is a separate, existing endpoint (GET /tk) -- not
duplicated here, same reasoning /tk's own docstring gives for TK news."""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
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
    return await biz_overview(db, days=days)
