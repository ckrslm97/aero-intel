"""Command-line entrypoints for every stage of the daily pipeline.

This is not a convenience wrapper: the GitHub Actions workflows in
.github/workflows/ are the only scheduler, and they invoke these commands.
Nothing schedules itself in-process.

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


async def _pipeline_v2(limit: int | None) -> None:
    """The Faz 7 gate -> cluster -> classify -> confidence -> news_events run.

    Gated on the flag here, not inside run_pipeline_v2 itself, so the function
    stays directly testable without monkeypatching settings -- this command is
    the one place that has an opinion about whether it should run at all.
    """
    from app.agents.runner import DEFAULT_BATCH_SIZE, run_pipeline_v2
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.pipeline_v2:
        print("PIPELINE_V2 is not enabled -- nothing to do. Set PIPELINE_V2=true to run it.")
        return

    async with AsyncSessionLocal() as db:
        stats = await run_pipeline_v2(db, limit=limit or DEFAULT_BATCH_SIZE)
        print(
            f"Kaydedildi {stats['events']} olay ({stats['published']} yayınlanabilir) "
            f"— {stats['candidates']} aday işlendi: "
            f"{stats['rejected_language']} dil reddi, {stats['rejected_gate']} kapı reddi, "
            f"{stats['not_relevant']} ilgisiz, {stats['failed']} başarısız sınıflandırma."
        )


async def _backfill_regions(limit: int | None) -> None:
    from app.pipeline.enrich import backfill_regions

    async with AsyncSessionLocal() as db:
        result = await backfill_regions(db, limit=limit)
        print(
            f"Scanned {result['scanned']} enriched articles: "
            f"{result['resolved']} previously-unresolved regions filled in, "
            f"{result['links_added']} airport links added"
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


async def _backfill_risks(limit: int | None) -> None:
    from app.pipeline.enrich import backfill_risk_classification

    async with AsyncSessionLocal() as db:
        result = await backfill_risk_classification(db, limit=limit)
        print(
            f"Scanned {result['scanned']} articles: {result['classified']} classified "
            f"as risk events, {result['cleared']} stale classifications cleared"
        )


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


async def _extract_promotions(limit: int | None) -> None:
    from app.pipeline.promotions import extract_promotions

    async with AsyncSessionLocal() as db:
        stats = await extract_promotions(db, limit=limit)
        print(
            f"Scanned {stats['scanned']} campaign articles: "
            f"{stats['inserted']} new promotions, {stats['updated']} refreshed, "
            f"{stats['merged']} merged into an existing campaign, "
            f"{stats['skipped']} skipped ({stats['llm']} via LLM)"
        )


async def _scrape_promotions() -> None:
    from app.ingest.promo_scrape import scrape_promotions

    async with AsyncSessionLocal() as db:
        result = await scrape_promotions(db)
        print(
            f"Fetched {result['fetched']} campaigns from airline pages: "
            f"{result['inserted']} new, {result['updated']} refreshed, "
            f"{result['merged']} merged into an article-derived row"
        )
        for name, error in result.get("errors", {}).items():
            print(f"  ! {name} unavailable: {error}")


async def _refresh_promotions() -> None:
    """Both detection paths in one pass -- what the scheduled job runs."""
    from app.ingest.promo_scrape import scrape_promotions
    from app.pipeline.promotions import extract_promotions

    async with AsyncSessionLocal() as db:
        scraped = await scrape_promotions(db)
        extracted = await extract_promotions(db)
        print(
            f"Scrape: {scraped['inserted']} new / {scraped['updated']} refreshed "
            f"/ {scraped['merged']} merged. "
            f"Articles: {extracted['inserted']} new / {extracted['updated']} refreshed "
            f"/ {extracted['merged']} merged, from {extracted['scanned']} scanned"
        )


async def _dedupe_promotions() -> None:
    """Collapse campaigns already stored twice under two different URLs.

    The write paths now merge on the way in, so this is the backfill for rows
    that predate that -- and the repair after any run that inserted a duplicate
    before the matcher knew about it.
    """
    from app.pipeline.promo_dedup import dedupe_existing_promotions

    async with AsyncSessionLocal() as db:
        result = await dedupe_existing_promotions(db)
        print(
            f"Scanned {result['scanned']} promotions: merged {result['merged']} "
            f"duplicate rows away, {result['remaining']} campaigns remain"
        )


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


async def _seed_curated_data() -> None:
    from app.ingest.curated_seed import seed_curated_data

    async with AsyncSessionLocal() as db:
        result = await seed_curated_data(db)
        print(
            f"Curated data reconciled: {result['fx_forecasts_new']} new FX forecasts, "
            f"{result['iata_indicators_new']} new IATA indicators"
        )


async def _refresh_market_pulse() -> None:
    from app.services.market_pulse_service import generate_market_pulse

    async with AsyncSessionLocal() as db:
        pulse = await generate_market_pulse(db)
        if pulse is None:
            print("Market Pulse not regenerated (no LLM configured, no grounding data, or generation failed)")
        else:
            print(f"Market Pulse generated: {len(pulse.citations)} citations")


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
            "backfill-regions",
            "backfill-risks",
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
            "extract-promotions",
            "scrape-promotions",
            "refresh-promotions",
            "dedupe-promotions",
            "prune-kpi-duplicates",
            "seed-curated-data",
            "refresh-market-pulse",
            "refresh-pdf",
            "send-newsletter",
            "daily-if-due",
            "pipeline-v2",
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
        # No default, so "not given" is distinguishable from a number: an
        # absent --limit means "everything" for extract-promotions,
        # backfill-regions and backfill-risks, while translate-backlog needs a
        # real batch size and supplies its own.
        default=None,
        help=(
            "translate-backlog: articles to translate this run (default: 12). "
            "extract-promotions: campaign articles to scan (default: all). "
            "backfill-regions: articles to walk (default: all). "
            "backfill-risks: articles to reclassify (default: all)"
            "pipeline-v2: articles to process this run (default: 40)"
        ),
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
    elif args.command == "backfill-regions":
        asyncio.run(_backfill_regions(args.limit))
    elif args.command == "backfill-risks":
        # An absent --limit means the whole archive: the risk backfill is free,
        # heuristic-only, and a partial pass would leave the radar half-blind.
        asyncio.run(_backfill_risks(args.limit))
    elif args.command == "repair-translations":
        asyncio.run(_repair_translations())
    elif args.command == "clean-headlines":
        asyncio.run(_clean_headlines())
    elif args.command == "translate-backlog":
        asyncio.run(_translate_backlog(args.limit if args.limit is not None else 12))
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
    elif args.command == "extract-promotions":
        asyncio.run(_extract_promotions(args.limit))
    elif args.command == "scrape-promotions":
        asyncio.run(_scrape_promotions())
    elif args.command == "refresh-promotions":
        asyncio.run(_refresh_promotions())
    elif args.command == "dedupe-promotions":
        asyncio.run(_dedupe_promotions())
    elif args.command == "prune-kpi-duplicates":
        asyncio.run(_prune_kpi_duplicates())
    elif args.command == "seed-curated-data":
        asyncio.run(_seed_curated_data())
    elif args.command == "refresh-market-pulse":
        asyncio.run(_refresh_market_pulse())
    elif args.command == "refresh-pdf":
        asyncio.run(_refresh_pdf())
    elif args.command == "send-newsletter":
        asyncio.run(_send_newsletter())
    elif args.command == "daily-if-due":
        asyncio.run(_daily_if_due())
    elif args.command == "pipeline-v2":
        asyncio.run(_pipeline_v2(args.limit))


if __name__ == "__main__":
    main()
