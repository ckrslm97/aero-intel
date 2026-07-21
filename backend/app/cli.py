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
    from datetime import datetime, timezone

    from app.services.edition_service import assemble_edition

    async with AsyncSessionLocal() as db:
        edition = await assemble_edition(db, datetime.now(timezone.utc).date())
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


async def _build_insight() -> None:
    from app.services.insights_service import build_daily_digest

    async with AsyncSessionLocal() as db:
        digest = await build_daily_digest(db)
        print(f"Insight digest built for {digest.digest_date} via {digest.provider}")


async def _reclassify() -> None:
    from app.pipeline.enrich import reclassify_articles

    async with AsyncSessionLocal() as db:
        result = await reclassify_articles(db)
        print(
            f"Reclassified {result['articles']} articles in place: "
            f"{result['region_changes']} region changes, "
            f"{result['subcategory_changes']} subcategory changes"
        )


async def _repair_translations() -> None:
    from app.pipeline.enrich import repair_corrupt_translations

    async with AsyncSessionLocal() as db:
        result = await repair_corrupt_translations(db)
        print(
            f"Repaired {result['repaired']} translations in place; "
            f"{result['renulled']} sent back to the translate queue"
        )


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


async def _clean_headlines() -> None:
    from app.pipeline.enrich import clean_stored_headlines

    async with AsyncSessionLocal() as db:
        result = await clean_stored_headlines(db)
        print(f"Cleaned {result['cleaned']} of {result['scanned']} stored headlines")


async def _refresh_tk_reviews() -> None:
    from app.ingest.tk_reviews_live import refresh_tk_reviews
    from app.services.tk_service import build_tk_digest

    async with AsyncSessionLocal() as db:
        result = await refresh_tk_reviews(db)
        sources = ", ".join(f"{name}={count}" for name, count in result["sources"].items())
        print(f"Fetched {result['fetched']} TK reviews ({sources})")
        for name, error in result.get("errors", {}).items():
            print(f"  ! {name} unavailable: {error}")
        if result["inserted"]:
            # Only worth a 70b call when the corpus actually changed.
            digest = await build_tk_digest(db)
            print(f"Inserted {result['inserted']} new reviews; digest rebuilt [{digest.provider}]")
        else:
            print("No new reviews; digest left as is")


async def _seed_tk_reviews() -> None:
    from app.ingest.tk_reviews_seed import seed_tk_reviews
    from app.services.tk_service import build_tk_digest

    async with AsyncSessionLocal() as db:
        inserted = await seed_tk_reviews(db)
        # Rebuild the synthesis whenever the corpus changes -- one 70b call.
        digest = await build_tk_digest(db)
        print(f"Seeded {inserted} TK reviews; digest rebuilt [{digest.provider}]")


async def _seed_promos() -> None:
    from app.ingest.promos_seed import seed_promos

    async with AsyncSessionLocal() as db:
        inserted = await seed_promos(db)
        print(f"Seeded {inserted} curated rival promo articles")


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
    from datetime import datetime, timezone

    from app.services.pdf_service import refresh_pdf_for_date

    async with AsyncSessionLocal() as db:
        ok = await refresh_pdf_for_date(db, datetime.now(timezone.utc).date())
        print("PDF rendered and stored" if ok else "PDF not generated (no edition, or no Chromium here)")


async def _send_newsletter() -> None:
    from app.services.daily_cycle import run_daily_edition_and_newsletter

    await run_daily_edition_and_newsletter()
    print("Edition assembled, PDF rendered (if available), newsletter dispatched")


async def _daily_if_due() -> None:
    """Assemble the edition, and send it only when the send window is open.

    The workflow runs this many times through the small hours because GitHub's
    scheduler cannot be trusted to fire punctually (see
    app/services/delivery_window.py). Runs outside the window do nothing.
    """
    from app.services.daily_cycle import run_daily_edition_and_newsletter
    from app.services.delivery_window import (
        build_window_is_open,
        local_now,
        newsletter_is_due,
    )

    async with AsyncSessionLocal() as db:
        due, reason = await newsletter_is_due(db)

    if due:
        await run_daily_edition_and_newsletter()
        print(f"Newsletter sent — {reason}")
        return

    if build_window_is_open():
        # Keep the edition warm so the send, when it comes, is instant and
        # complete rather than assembled from scratch at nine o'clock.
        from app.services.edition_service import assemble_edition

        async with AsyncSessionLocal() as db:
            edition = await assemble_edition(db, local_now().date())
            print(f"Edition ready ({edition.headline[:60]}) — not sending: {reason}")
        return

    print(f"Nothing to do — {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AeroIntel pipeline CLI")
    parser.add_argument(
        "command",
        choices=[
            "ingest",
            "full-cycle",
            "re-enrich",
            "reclassify",
            "build-insight",
            "repair-translations",
            "clean-headlines",
            "translate-backlog",
            "build-edition",
            "refresh-kpis",
            "seed-kpi-history",
            "seed-events",
            "seed-tk-reviews",
            "refresh-tk-reviews",
            "seed-promos",
            "prune-kpi-duplicates",
            "refresh-pdf",
            "send-newsletter",
            "daily-if-due",
        ],
    )
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
    elif args.command == "build-insight":
        asyncio.run(_build_insight())
    elif args.command == "reclassify":
        asyncio.run(_reclassify())
    elif args.command == "repair-translations":
        asyncio.run(_repair_translations())
    elif args.command == "clean-headlines":
        asyncio.run(_clean_headlines())
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
    elif args.command == "seed-tk-reviews":
        asyncio.run(_seed_tk_reviews())
    elif args.command == "refresh-tk-reviews":
        asyncio.run(_refresh_tk_reviews())
    elif args.command == "seed-promos":
        asyncio.run(_seed_promos())
    elif args.command == "prune-kpi-duplicates":
        asyncio.run(_prune_kpi_duplicates())
    elif args.command == "refresh-pdf":
        asyncio.run(_refresh_pdf())
    elif args.command == "send-newsletter":
        asyncio.run(_send_newsletter())
    elif args.command == "daily-if-due":
        asyncio.run(_daily_if_due())


if __name__ == "__main__":
    main()
