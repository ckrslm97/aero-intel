"""Command-line entrypoints for local/manual runs of the daily pipeline stages.
Mirrors what the APScheduler jobs call in production -- see app/scheduler/jobs.py.

Usage: python -m app.cli <command>
"""
import argparse
import asyncio

from app.core.db import AsyncSessionLocal
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def _ingest() -> None:
    from app.services.ingestion_service import run_ingestion

    async with AsyncSessionLocal() as db:
        inserted = await run_ingestion(db)
        print(f"Ingestion complete: {inserted} new articles")


async def _full_cycle() -> None:
    from app.services.daily_cycle import run_daily_ingest_and_enrich

    await run_daily_ingest_and_enrich()
    print("Ingest + dedup + enrichment complete")


async def _build_edition() -> None:
    from datetime import date

    from app.services.edition_service import assemble_edition

    async with AsyncSessionLocal() as db:
        edition = await assemble_edition(db, date.today())
        print(f"Edition assembled for {edition.edition_date}: {edition.headline}")


async def _refresh_kpis() -> None:
    from app.services.kpi_service import refresh_all_kpis

    async with AsyncSessionLocal() as db:
        recorded = await refresh_all_kpis(db)
        print(f"KPI refresh complete: {recorded} observations recorded")


async def _re_enrich(days: int | None) -> None:
    from app.core.config import get_settings
    from app.pipeline.enrich import enrich_pending_articles, reset_enrichment

    async with AsyncSessionLocal() as db:
        reset = await reset_enrichment(db, days=days)
        print(f"Reset enrichment for {reset} articles; re-enriching…")
        # On a live LLM, cap each run to the daily-budget batch (freshest first);
        # re-run the maintenance job to work through the backlog. Heuristic is
        # free, so it re-enriches everything in one pass.
        settings = get_settings()
        batch = settings.llm_enrich_batch_size if settings.llm_provider != "heuristic" else None
        enriched = await enrich_pending_articles(db, limit=batch)
        print(f"Re-enriched {enriched} articles (batch limit: {batch or 'none'})")


async def _translate_backlog(limit: int) -> None:
    from app.pipeline.enrich import translate_pending_articles

    async with AsyncSessionLocal() as db:
        translated = await translate_pending_articles(db, limit=limit)
        print(f"Translated {translated} previously-untranslated articles")


async def _seed_events() -> None:
    from app.ingest.events_seed import seed_events

    async with AsyncSessionLocal() as db:
        inserted = await seed_events(db)
        print(f"Seeded {inserted} curated aviation events")


async def _seed_kpi_history() -> None:
    from app.ingest.historical_seed import seed_kpi_history

    async with AsyncSessionLocal() as db:
        inserted = await seed_kpi_history(db)
        print(f"Seeded {inserted} published historical KPI points")


async def _prune_kpi_duplicates() -> None:
    from app.services.kpi_service import prune_duplicate_estimates

    async with AsyncSessionLocal() as db:
        deleted = await prune_duplicate_estimates(db)
        print(f"Pruned {deleted} duplicate published-estimate rows")


async def _refresh_pdf() -> None:
    from datetime import date

    from app.services.pdf_service import refresh_pdf_for_date

    async with AsyncSessionLocal() as db:
        ok = await refresh_pdf_for_date(db, date.today())
        print("PDF rendered and stored" if ok else "PDF not generated (no edition, or no Chromium here)")


async def _send_newsletter() -> None:
    from app.services.daily_cycle import run_daily_edition_and_newsletter

    await run_daily_edition_and_newsletter()
    print("Edition assembled, PDF rendered (if available), newsletter dispatched")


async def _create_admin(email: str, password: str) -> None:
    from app.repositories.user_repository import UserRepository

    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        if await repo.get_by_email(email) is not None:
            print(f"A user with email {email} already exists")
            return
        await repo.create(email, password, role="admin")
        await db.commit()
        print(f"Admin account created: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AeroIntel pipeline CLI")
    parser.add_argument(
        "command",
        choices=[
            "ingest",
            "full-cycle",
            "re-enrich",
            "translate-backlog",
            "build-edition",
            "refresh-kpis",
            "seed-kpi-history",
            "seed-events",
            "prune-kpi-duplicates",
            "refresh-pdf",
            "send-newsletter",
            "create-admin",
        ],
    )
    parser.add_argument("--email", help="Required for create-admin")
    parser.add_argument("--password", help="Required for create-admin")
    parser.add_argument(
        "--days",
        type=int,
        help="re-enrich: only articles fetched in the last N days (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="translate-backlog: how many articles to translate this run (default: 12)",
    )
    args = parser.parse_args()

    if args.command == "ingest":
        asyncio.run(_ingest())
    elif args.command == "full-cycle":
        asyncio.run(_full_cycle())
    elif args.command == "re-enrich":
        asyncio.run(_re_enrich(args.days))
    elif args.command == "translate-backlog":
        asyncio.run(_translate_backlog(args.limit))
    elif args.command == "build-edition":
        asyncio.run(_build_edition())
    elif args.command == "refresh-kpis":
        asyncio.run(_refresh_kpis())
    elif args.command == "seed-kpi-history":
        asyncio.run(_seed_kpi_history())
    elif args.command == "seed-events":
        asyncio.run(_seed_events())
    elif args.command == "prune-kpi-duplicates":
        asyncio.run(_prune_kpi_duplicates())
    elif args.command == "refresh-pdf":
        asyncio.run(_refresh_pdf())
    elif args.command == "send-newsletter":
        asyncio.run(_send_newsletter())
    elif args.command == "create-admin":
        if not args.email or not args.password:
            parser.error("create-admin requires --email and --password")
        asyncio.run(_create_admin(args.email, args.password))


if __name__ == "__main__":
    main()
