from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.services.hub_service import hub_detail, hub_overview

router = APIRouter(prefix="/hubs", tags=["hubs"])


@router.get("")
async def list_hubs(
    days: int = Query(30, ge=1, le=365),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Every watched hub with its live coverage count, plus the co-mention
    lines the world map draws between them."""
    public_cache(response, AGGREGATES)
    return await hub_overview(db, days=days)


@router.get("/{code}")
async def get_hub(
    code: str,
    days: int = Query(90, ge=1, le=365),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    public_cache(response, AGGREGATES)
    detail = await hub_detail(db, code, days=days)
    if detail is None:
        raise HTTPException(status_code=404, detail="Bilinmeyen hub kodu")
    return detail
