"""Orchestrates the automated daily cycle: ingest -> enrich -> assemble edition -> send newsletter.

Each stage is implemented in its own milestone (ingest in M1, dedup/enrichment in
M2, edition assembly in M3, newsletter dispatch in M5) and wired in here so the
scheduler always has a single, stable entrypoint to call.
"""
from app.core.logging import get_logger

logger = get_logger(__name__)


async def run_daily_ingest_and_enrich() -> None:
    from app.core.db import AsyncSessionLocal
    from app.pipeline.dedup import deduplicate_new_articles
    from app.pipeline.enrich import enrich_pending_articles
    from app.services.ingestion_service import run_ingestion

    from app.core.config import get_settings

    async with AsyncSessionLocal() as db:
        fetched = await run_ingestion(db)
        deduped = await deduplicate_new_articles(db)
        # Cap per-run enrichment so a single scheduled run stays within the LLM's
        # daily budget; the backlog is worked off over subsequent runs. The
        # heuristic pipeline (no key) ignores the cap and enriches everything.
        settings = get_settings()
        batch = settings.llm_enrich_batch_size if settings.llm_provider != "heuristic" else None
        enriched = await enrich_pending_articles(db, limit=batch)
        logger.info(
            "daily_ingest_cycle_complete", fetched=fetched, deduped=deduped, enriched=enriched
        )


async def run_daily_edition_and_newsletter() -> None:
    from datetime import datetime, timezone

    from app.core.db import AsyncSessionLocal
    from app.repositories.edition_repository import EditionRepository
    from app.services.edition_service import assemble_edition
    from app.services.newsletter_service import send_newsletter_for_edition
    from app.services.pdf_service import store_edition_pdf

    async with AsyncSessionLocal() as db:
        assembled = await assemble_edition(db, datetime.now(timezone.utc).date())

        # assemble_edition's own return only eager-loads Edition.articles, not
        # the nested article.source/article.enrichment that HTML rendering
        # needs -- re-fetch through the repository, which loads both.
        edition = await EditionRepository(db).get_by_date(assembled.edition_date)

        await store_edition_pdf(db, edition)

        stats = await send_newsletter_for_edition(db, edition)
        logger.info(
            "daily_edition_cycle_complete", edition_date=str(edition.edition_date), **stats
        )
