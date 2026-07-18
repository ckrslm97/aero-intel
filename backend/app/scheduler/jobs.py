"""APScheduler-based daily automation (no Redis/Celery broker required).

Jobs are registered here and wired up incrementally: ingestion -> pipeline ->
edition assembly -> newsletter dispatch. Each job is idempotent per day so a
missed run can simply be re-triggered.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _refresh_kpis_job() -> None:
    from app.core.db import AsyncSessionLocal
    from app.services.kpi_service import refresh_all_kpis

    async with AsyncSessionLocal() as db:
        await refresh_all_kpis(db)


async def _refresh_funds_job() -> None:
    """Fund/ETF data + analysis for the /invest module. Idempotent per day:
    price backfill is guarded by exists_price_at and analysis regeneration
    skips when the input fingerprint hasn't changed."""
    from app.core.db import AsyncSessionLocal
    from app.services.fund_analysis_service import regenerate_fund_analyses
    from app.services.fund_service import refresh_all_funds

    async with AsyncSessionLocal() as db:
        await refresh_all_funds(db)
        await regenerate_fund_analyses(db)


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    settings = get_settings()

    from app.services.daily_cycle import run_daily_ingest_and_enrich, run_daily_edition_and_newsletter

    scheduler.add_job(
        run_daily_ingest_and_enrich,
        trigger=CronTrigger(hour="*/2"),
        id="ingest_and_enrich",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_daily_edition_and_newsletter,
        trigger=CronTrigger(hour=settings.daily_edition_hour_utc, minute=0),
        id="daily_edition_and_newsletter",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _refresh_kpis_job,
        trigger=IntervalTrigger(minutes=15),
        id="refresh_kpis",
        replace_existing=True,
        misfire_grace_time=600,
    )
    # 07:30 UTC catches TEFAS's morning publication of previous-day NAVs;
    # 22:30 UTC catches the US market close.
    scheduler.add_job(
        _refresh_funds_job,
        trigger=CronTrigger(hour="7,22", minute=30),
        id="refresh_funds",
        replace_existing=True,
        misfire_grace_time=3600,
    )


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _register_jobs(_scheduler)
    _scheduler.start()
    logger.info("scheduler_started", jobs=[j.id for j in _scheduler.get_jobs()])


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler_stopped")


def get_scheduler_status() -> list[dict]:
    if _scheduler is None:
        return []
    return [
        {
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in _scheduler.get_jobs()
    ]
