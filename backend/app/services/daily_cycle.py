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

    async with AsyncSessionLocal() as db:
        fetched = await run_ingestion(db)
        deduped = await deduplicate_new_articles(db)
        enriched = await enrich_pending_articles(db)
        logger.info(
            "daily_ingest_cycle_complete", fetched=fetched, deduped=deduped, enriched=enriched
        )


async def run_daily_edition_and_newsletter() -> None:
    from datetime import date

    from app.core.db import AsyncSessionLocal
    from app.pdf.render import render_edition_pdf
    from app.repositories.edition_repository import EditionRepository
    from app.services.edition_service import assemble_edition
    from app.services.newsletter_service import send_newsletter_for_edition

    async with AsyncSessionLocal() as db:
        assembled = await assemble_edition(db, date.today())

        # assemble_edition's own return only eager-loads Edition.articles, not
        # the nested article.source/article.enrichment that HTML rendering
        # needs -- re-fetch through the repository, which loads both.
        edition = await EditionRepository(db).get_by_date(assembled.edition_date)

        pdf_path = await render_edition_pdf(edition)
        if pdf_path:
            edition.pdf_path = pdf_path
            await db.commit()

        stats = await send_newsletter_for_edition(db, edition)
        logger.info(
            "daily_edition_cycle_complete", edition_date=str(edition.edition_date), **stats
        )
