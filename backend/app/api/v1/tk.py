"""The BİZ page's data: aggregated Turkish Airlines passenger-review analysis.

TK *news* is not duplicated here -- the page fetches /articles?airline=TK for
that, same endpoint and types the newspaper already uses.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.tk_service import latest_tk_digest, review_stats

router = APIRouter(prefix="/tk", tags=["tk"])


@router.get("")
async def get_tk(db: AsyncSession = Depends(get_db)) -> dict:
    stats = await review_stats(db)
    digest = await latest_tk_digest(db)
    return {
        **stats,
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
