from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.api.window import window_envelope
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
) -> dict:
    """New-route announcements grouped by world region -- the Ağ Sinyalleri
    tab, moved here from İçgörüler (see network_signals_service.py).

    Returns an ENVELOPE, where it used to return the bare `regions` list. The
    tab prints a "son güncelleme" and had nothing in the payload to print, so
    it printed the browser's fetch time -- a stamp that refreshes itself
    forever over a feed that may have stopped. The list is unchanged, under
    `regions`.

    A BREAKING SHAPE CHANGE that this response's own cache headers make
    non-atomic: `AGGREGATES` is 300s fresh plus 1500s stale-while-revalidate,
    so for up to ~30 minutes after a deploy the new bundle can be handed the
    old array out of the edge. The clients read it through
    `frontend/src/lib/network-signals.regionsOf`, which understands both
    shapes, precisely so that window renders signals rather than "sinyal yok".
    """
    public_cache(response, AGGREGATES)
    now = datetime.now(timezone.utc)
    return {
        **window_envelope(now, days),
        "regions": await network_signals(db, days=days, now=now),
    }


@router.get("")
async def list_hubs(
    days: int = Query(30, ge=1, le=365),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Every watched hub with its live coverage count, plus the co-mention
    lines the world map draws between them."""
    public_cache(response, AGGREGATES)
    # One clock: the counts and the map's lines are two queries, and the stamp
    # names the instant both were cut at (app/api/window.py).
    now = datetime.now(timezone.utc)
    return {
        **window_envelope(now, days),
        **await hub_overview(db, days=days, now=now),
    }


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
