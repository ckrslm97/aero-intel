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


async def _refresh_promotions_job() -> None:
    """Both campaign detection paths, on the tightest clock in the scheduler.

    30 minutes, and the interval is the feature. The requirement is "the moment
    an airline launches a campaign it must appear", and a campaign is perishable
    in a way news is not: a two-day flash sale found six hours late is half a
    campaign's worth of intelligence already spent. The news job runs every 2h
    because an article is the same article at 13:00 as it was at 11:00; a
    rival's sale window is not.

    Not shorter than 30, because the ceiling on usefulness is the source rather
    than the poller. Pegasus publishes to a static campaign page that changes a
    handful of times a week, and the article-derived path can only see campaigns
    the 2h news ingest has already filed -- so a 5-minute tick would re-read an
    unchanged page and re-scan the same articles 24 times for nothing. 30 also
    matches the cron in .github/workflows/jobs-promotions.yml exactly, so the
    in-process scheduler and the hosted job describe the same cadence instead of
    two competing ones.
    """
    from app.core.db import AsyncSessionLocal
    from app.ingest.promo_scrape import scrape_promotions
    from app.pipeline.promotions import extract_promotions

    async with AsyncSessionLocal() as db:
        scraped = await scrape_promotions(db)
        extracted = await extract_promotions(db)
        logger.info(
            "promotions_refreshed",
            scraped_new=scraped["inserted"],
            scraped_updated=scraped["updated"],
            scraped_merged=scraped["merged"],
            articles_scanned=extracted["scanned"],
            articles_new=extracted["inserted"],
            articles_updated=extracted["updated"],
            articles_merged=extracted["merged"],
        )


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
    scheduler.add_job(
        _refresh_promotions_job,
        trigger=IntervalTrigger(minutes=30),
        id="refresh_promotions",
        replace_existing=True,
        # Half the interval: a sweep missed while the process was restarting is
        # worth running late, but once the next tick is closer than the missed
        # one, running both back-to-back would just re-read the same page.
        misfire_grace_time=900,
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
