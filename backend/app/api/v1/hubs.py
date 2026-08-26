from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.services.hub_service import hub_detail, hub_overview
from app.services.network_signals_service import network_signals

router = APIRouter(prefix="/hubs", tags=["hubs"])


# Must be registered before GET /{code} -- unlike kpis.py's two-segment CSV
# route, this collides on segment count: "/hubs/network-signals" would
# otherwise match {code}="network-signals" and 404 as an unknown hub.
@router.get("/network-signals")
async def get_network_signals(
    days: int = Query(30, ge=1, le=365),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """New-route announcements grouped by world region -- the Ağ Sinyalleri
    tab, moved here from İçgörüler (see network_signals_service.py)."""
    public_cache(response, AGGREGATES)
    return await network_signals(db, days=days)


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
