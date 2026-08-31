"""The campaign alert strip: what changed on the competitive board, unread.

Read-only and unacknowledged-only. The list is the inbox, not the archive --
`services/campaign_alerts.py` is what fills it, and acknowledging is what
empties it (no acknowledge endpoint in v1; see the plan's out-of-scope list).

Ordered by priority and only then by recency, because that is the order the
strip is read in: a CRITICAL from this morning outranks an INFO from ten
minutes ago, and sorting by time alone would bury the one line that mattered
under five that did not.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.models.campaign_alert import ALERT_PRIORITIES, CampaignAlert

router = APIRouter(prefix="/campaign-alerts", tags=["campaign-alerts"])

# The declared order in ALERT_PRIORITIES is the display order, so the SQL sort
# is derived from it rather than restated. Renaming or inserting a level then
# cannot leave the endpoint sorting by a list nobody remembered to update.
_PRIORITY_RANK = case(
    {name: rank for rank, name in enumerate(ALERT_PRIORITIES)},
    value=CampaignAlert.priority,
    # An unknown priority sorts last instead of first: a bad value must not be
    # able to push itself to the top of the strip.
    else_=len(ALERT_PRIORITIES),
)


class CampaignAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    promotion_id: uuid.UUID
    alert_type: str
    priority: str
    #: Already a full Turkish sentence -- composed once at generation time so
    #: the mail, the strip and any future channel say the same thing.
    title_tr: str
    detail_json: dict | None
    created_at: datetime


async def open_alerts(db: AsyncSession, *, limit: int = 20) -> list[CampaignAlert]:
    """The unacknowledged alert inbox, priority first and only then recency.

    Split out of the endpoint so the Sinyaller aggregate reads the same inbox
    the strip does rather than writing a second query for it -- one that would
    eventually differ on the acknowledged filter or on the priority ordering,
    and put a row on one surface that the other had already retired.
    """
    return list(
        (
            await db.execute(
                select(CampaignAlert)
                .where(CampaignAlert.acknowledged_at.is_(None))
                .order_by(_PRIORITY_RANK, CampaignAlert.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )


@router.get("", response_model=list[CampaignAlertOut])
async def list_campaign_alerts(
    limit: int = Query(20, ge=1, le=100, description="How many alerts to return"),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[CampaignAlertOut]:
    # AGGREGATES rather than FRESH: alerts are written twice a day by cron, so
    # a 30-second edge cache would buy nothing that five minutes does not.
    public_cache(response, AGGREGATES)
    return [CampaignAlertOut.model_validate(row) for row in await open_alerts(db, limit=limit)]
