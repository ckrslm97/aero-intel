"""Runtime-shaped pivot table over the news archive -- the /analiz page."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.services.pivot_service import (
    DEFAULT_DAYS,
    DIMENSIONS,
    MEASURES,
    build_pivot,
    describe,
)

router = APIRouter(prefix="/pivot", tags=["pivot"])


@router.get("/dimensions")
async def pivot_dimensions(
    response: Response = None,  # type: ignore[assignment]  -- FastAPI injects it
) -> dict:
    """The whitelist itself, so the row/column/value pickers are built from the
    same source of truth the query validates against."""
    public_cache(response, AGGREGATES)
    return describe()


@router.get("")
async def get_pivot(
    rows: str = Query("category", description="Satır boyutu"),
    cols: str | None = Query(None, description="Sütun boyutu (boş bırakılabilir)"),
    measure: str = Query("count", description="Hücrelerde gösterilecek ölçü"),
    days: int = Query(DEFAULT_DAYS, ge=1, le=365),
    category: str | None = None,
    subcategory: str | None = None,
    region: str | None = None,
    sentiment: str | None = None,
    source: str | None = None,
    airline: str | None = Query(
        None,
        max_length=6,
        description="IATA kodu; RIVALS = ana rakipler, ALL = tüm havayolları",
    ),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Validated here rather than left to build_pivot's ValueError so the client
    # gets the list of legal slugs back instead of just "no".
    if rows not in DIMENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz satır boyutu: '{rows}'. Geçerli boyutlar: {', '.join(DIMENSIONS)}",
        )
    if cols and cols not in DIMENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz sütun boyutu: '{cols}'. Geçerli boyutlar: {', '.join(DIMENSIONS)}",
        )
    if measure not in MEASURES:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz ölçü: '{measure}'. Geçerli ölçüler: {', '.join(MEASURES)}",
        )

    public_cache(response, AGGREGATES)
    return await build_pivot(
        db,
        rows=rows,
        cols=cols or None,
        measure=measure,
        filters={
            "days": days,
            "category": category,
            "subcategory": subcategory,
            "region": region,
            "sentiment": sentiment,
            "source": source,
            "airline": airline,
        },
    )
