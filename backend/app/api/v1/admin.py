"""Real operational status for the admin panel -- data freshness, queue
health, and scheduler state, all pulled from tables the pipeline already
writes to (no separate monitoring stack required for this to be useful).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import require_roles
from app.models.article import Article
from app.models.edition import Edition
from app.models.email_delivery import EmailDelivery
from app.models.entity import Entity
from app.models.source import Source
from app.models.subscriber import Subscriber
from app.scheduler.jobs import get_scheduler_status
from app.schemas.admin import (
    AdminStatusOut,
    ArticleStatusCountOut,
    EmailDeliveryStatusCountOut,
    SchedulerJobOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/status", response_model=AdminStatusOut, dependencies=[Depends(require_roles("admin"))])
async def admin_status(db: AsyncSession = Depends(get_db)) -> AdminStatusOut:
    settings = get_settings()

    try:
        await db.execute(select(1))
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False

    sources_count = (await db.execute(select(func.count()).select_from(Source))).scalar_one()
    entities_count = (await db.execute(select(func.count()).select_from(Entity))).scalar_one()
    editions_count = (await db.execute(select(func.count()).select_from(Edition))).scalar_one()
    subscribers_count = (
        await db.execute(select(func.count()).select_from(Subscriber).where(Subscriber.is_active.is_(True)))
    ).scalar_one()

    status_rows = await db.execute(select(Article.status, func.count()).group_by(Article.status))
    articles_by_status = [ArticleStatusCountOut(status=s, count=c) for s, c in status_rows.all()]

    delivery_rows = await db.execute(select(EmailDelivery.status, func.count()).group_by(EmailDelivery.status))
    deliveries_by_status = [
        EmailDeliveryStatusCountOut(status=s, count=c) for s, c in delivery_rows.all()
    ]

    latest_article = (
        await db.execute(select(func.max(Article.fetched_at)))
    ).scalar_one()
    latest_edition = (
        await db.execute(select(func.max(Edition.edition_date)))
    ).scalar_one()

    return AdminStatusOut(
        database_ok=database_ok,
        llm_provider=settings.llm_provider,
        sources_count=sources_count,
        articles_by_status=articles_by_status,
        entities_count=entities_count,
        editions_count=editions_count,
        latest_edition_date=str(latest_edition) if latest_edition else None,
        subscribers_count=subscribers_count,
        email_deliveries_by_status=deliveries_by_status,
        latest_article_fetched_at=latest_article,
        scheduler_jobs=[SchedulerJobOut(**job) for job in get_scheduler_status()],
    )
