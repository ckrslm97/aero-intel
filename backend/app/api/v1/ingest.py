"""Manual ingestion trigger -- useful for local testing without waiting for the
scheduler. The same run_ingestion() call is what the daily APScheduler job uses.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import require_roles
from app.services.ingestion_service import run_ingestion

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/run", dependencies=[Depends(require_roles("admin", "editor"))])
async def trigger_ingestion(db: AsyncSession = Depends(get_db)) -> dict:
    inserted = await run_ingestion(db)
    return {"inserted": inserted}
