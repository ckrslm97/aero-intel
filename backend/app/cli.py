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


async def _repair_etna_article_content() -> None:
    """ONE-OFF, TEMPORARY -- see PR that added this / the PR that removes it.

    Two articles about the August 2026 Etna eruption (Aviation24.be,
    eTurboNews) were ingested with only a short RSS-snippet-length
    raw_content, so extract_entities() never found ITALY/CTA in them and
    app/api/v1/risks.py's new event-clustering (PR #35) couldn't merge them
    with a third report (AeroTime) of the same event. This backfills the
    real article bodies (fetched by hand from the source URLs) into just
    these two specific rows and re-extracts entities from them -- it does
    not touch the general ingestion pipeline, and is not meant to run again.
    """
    from app.llm.heuristic import extract_entity_mentions
    from app.models.article import Article
    from app.models.entity import ArticleEntity
    from app.repositories.entity_repository import EntityRepository
    from sqlalchemy import select

    REPAIRS = {
        "9aabd9ca-31de-41ac-9ef8-19cfafa5d2e5": (
            "The continuing eruption of Mount Etna has caused major disruption to air "
            "travel in Sicily, with Catania Fontanarossa Airport remaining closed until "
            "at least 08:00 on 14 August as volcanic ash continues to affect the region. "
            "Between 7 and 12 August, around 700 flights were cancelled, leaving tens of "
            "thousands of passengers facing disrupted journeys during one of the busiest "
            "periods of the summer season. More than 400 flights have been redirected or "
            "rescheduled through other airports, including around 330 at Palermo, more "
            "than 100 at Comiso and 22 at Trapani, with some services transferred to "
            "Lamezia Terme on the Italian mainland. The situation was further complicated "
            "when Comiso Airport itself temporarily closed for around 12 hours because of "
            "volcanic ash contamination before reopening. Etna remains highly active, "
            "producing intense Strombolian explosions and a volcanic plume several "
            "kilometres high. Ash has reportedly travelled as far as Malta and North "
            "Africa, while lava continues to flow from several fractures towards the "
            "Valle del Bove. Italy's National Institute of Geophysics and Volcanology "
            "(INGV) warned that it is impossible to predict when the eruption will end."
        ),
        "854dcaea-b6e9-4e6f-83b2-a97eeb2f78f0": (
            "CATANIA, Sicily -- Mount Etna is demonstrating one of tourism's strangest "
            "contradictions: the same eruption that is canceling hundreds of flights, "
            "stranding tens of thousands of passengers, and costing Sicily's tourism "
            "economy millions of euros is attracting extraordinary numbers of visitors to "
            "the volcano itself. Europe's highest and most active volcano has been "
            "erupting continuously for seven days. Catania-Fontanarossa Airport, the "
            "principal gateway to eastern Sicily and Italy's fifth-busiest airport, has "
            "repeatedly suspended operations as volcanic ash entered surrounding "
            "airspace. On Thursday, August 13, airport operator SAC extended the "
            "suspension of arrivals until 8:00 a.m. Friday, August 14. Catania Airport "
            "handled 12.37 million passengers in 2025, illustrating how dependent "
            "eastern Sicily's tourism economy has become on this single aviation "
            "gateway."
        ),
    }

    async with AsyncSessionLocal() as db:
        entity_repo = EntityRepository(db)
        for article_id, content in REPAIRS.items():
            article = (
                await db.execute(select(Article).where(Article.id == article_id))
            ).scalar_one_or_none()
            if article is None:
                print(f"Skipped {article_id}: not found")
                continue
            article.raw_content = content
            mentions = extract_entity_mentions(article.title, content)
            for mention in mentions:
                entity = await entity_repo.get_or_create(
                    mention.entity_type, mention.name, mention.code
                )
                exists = (
                    await db.execute(
                        select(ArticleEntity).where(
                            ArticleEntity.article_id == article.id,
                            ArticleEntity.entity_id == entity.id,
                        )
                    )
                ).scalar_one_or_none()
                if exists is None:
                    db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
            await db.flush()
            print(f"Repaired {article_id}: {[ (m.entity_type, m.name) for m in mentions ]}")
        await db.commit()


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


async def _deep_scan(carriers: str | None, dry_run: bool, max_llm_calls: int) -> None:
    """The 2x/day Playwright sweep of the bot-walled carrier campaign pages.

    The totals printed here are the summary; the answer the first dispatch is
    actually asked -- which carriers a real Chromium gets through -- is one
    `deep_scan_page` log line per page and one `scrape_runs` row per attempt.
    """
    from app.ingest.deep_scan import deep_scan

    codes = [part for part in carriers.split(",") if part.strip()] if carriers else None

    async with AsyncSessionLocal() as db:
        summary = await deep_scan(
            db, carriers=codes, dry_run=dry_run, max_llm_calls=max_llm_calls
        )
        print(
            f"Deep scan{' (dry run)' if dry_run else ''}: "
            f"{summary['scanned']} sayfa tarandı, {summary['changed']} değişti, "
            f"{summary['blocked']} bot duvarına takıldı, {summary['errors']} hata, "
            f"{summary['skipped_static']} statik taşıyıcı atlandı. "
            f"Çıkarım: {summary['llm_calls']} LLM çağrısı, "
            f"{summary['campaigns_inserted']} yeni / "
            f"{summary['campaigns_updated']} güncellenen / "
            f"{summary['campaigns_merged']} birleştirilen kampanya, "
            f"{summary['campaigns_dropped']} eleme, "
            f"{summary['extraction_capped']} sayfa bütçe nedeniyle sonraki koşuya bırakıldı"
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


async def _mark_legacy_campaigns_superseded() -> None:
    """Faz 13/K8 one-time migration: the pre-validation campaign rows stop
    being served, kept (not deleted) so the before/after stays checkable."""
    from app.pipeline.promo_dedup import mark_legacy_campaigns_superseded

    async with AsyncSessionLocal() as db:
        result = await mark_legacy_campaigns_superseded(db)
        print(f"Marked {result['marked_superseded']} legacy campaign rows as superseded")


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


async def _evaluate_golden(full_surface: str | None) -> None:
    """Faz 13: the golden-set checks. Always runs the two deterministic ones
    (no LLM, no network); `--full-surface` additionally runs the live
    re-fetch + classify pass for one surface (risk | news | campaign), which
    costs one LLM call and one HTTP fetch per record with a URL and does
    nothing (prints why) if no LLM is configured."""
    from app.services.golden_eval_service import (
        evaluate_campaign_guards,
        evaluate_full_pipeline,
        evaluate_risk_country_normalisation,
    )

    guards = evaluate_campaign_guards()
    print(
        f"Campaign guards: {guards.bad_records_caught}/{guards.bad_records_parsed} "
        f"golden 'bad' campaigns caught (narrow check -- see module docstring); "
        f"{guards.ok_records_wrongly_rejected} genuine campaigns wrongly rejected"
    )

    country = evaluate_risk_country_normalisation()
    pct = 100 * country.resolved / country.checked if country.checked else 0.0
    print(f"Risk country normalisation: {country.resolved}/{country.checked} ({pct:.1f}%)")

    if full_surface is None:
        return

    report = await evaluate_full_pipeline(surface=full_surface)
    if report is None:
        print("Full-pipeline evaluation skipped: no LLM configured")
        return

    # "warn" was the judge's own uncertainty on the OLD system's output --
    # forcing it into agree/disagree here would manufacture false precision
    # out of a verdict that was never a clean yes/no. Graded only against
    # ok/bad, reported separately.
    graded = [r for r in report.results if r.golden_verdict in ("ok", "bad")]
    agree = sum(1 for r in graded if r.classified == (r.golden_verdict == "ok"))
    warn_count = len(report.results) - len(graded)
    print(
        f"Full pipeline ({full_surface}): {agree}/{len(graded)} agree with the golden "
        f"ok/bad verdict ({warn_count} 'warn' records excluded from grading; "
        f"{report.skipped_no_url} skipped, no URL; {report.skipped_fetch_failed} skipped, fetch failed)"
    )


async def _check_data_quality() -> None:
    """Faz 13's daily quality gate. Exits non-zero on any violation -- a
    failed step in the scheduled workflow run is the "task" this opens, see
    data_quality_service.py's module docstring."""
    import sys

    from app.services.data_quality_service import check_data_quality

    async with AsyncSessionLocal() as db:
        violations = await check_data_quality(db)

    if not violations:
        print("Data quality: all checks passed")
        return

    print(f"Data quality: {len(violations)} violation(s)")
    for v in violations:
        print(f"  [{v.check}] {v.detail}")
    sys.exit(1)


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
    # Imported here rather than at module scope for the same reason every
    # command's own imports are lazy: `python -m app.cli ingest` should not pay
    # for the ingest package. The default has to be readable at parse time, so
    # this is the one value that comes in early.
    from app.ingest.deep_scan import DEFAULT_MAX_LLM_CALLS

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
            "repair-etna-article-content",
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
            "deep-scan",
            "dedupe-promotions",
            "prune-kpi-duplicates",
            "seed-curated-data",
            "refresh-market-pulse",
            "refresh-pdf",
            "send-newsletter",
            "daily-if-due",
            "pipeline-v2",
            "evaluate-golden",
            "check-data-quality",
            "mark-legacy-campaigns-superseded",
        ],
    )
    parser.add_argument(
        "--days",
        type=int,
        help="re-enrich: only articles fetched in the last N days (default: all)",
    )
    parser.add_argument(
        "--full-surface",
        choices=["risk", "news", "campaign"],
        default=None,
        help=(
            "evaluate-golden: additionally run the live re-fetch + classify pass "
            "for this surface (costs an LLM call + HTTP fetch per record). "
            "Omit to run only the two deterministic, no-LLM checks."
        ),
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
    parser.add_argument(
        "--carriers",
        default=None,
        help=(
            "deep-scan: comma-separated carrier codes or names to scan "
            "(e.g. TK,VF or ajet). Default: every carrier in "
            "app/ingest/carriers.py CARRIER_MASTER."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "deep-scan: fetch and record scrape_runs telemetry without handing "
            "changed pages to extraction. The bot-wall go/no-go gate -- the run "
            "log is written either way, which is what makes the gate readable."
        ),
    )
    parser.add_argument(
        "--max-llm-calls",
        type=int,
        default=DEFAULT_MAX_LLM_CALLS,
        help=(
            "deep-scan: how many campaign-extraction LLM calls this sweep may "
            f"spend in total (default: {DEFAULT_MAX_LLM_CALLS}). Pages beyond the "
            "cap keep their previous content hash, so the next run still sees "
            "them as changed and extracts them then -- the cap defers work, it "
            "does not drop it."
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
    elif args.command == "repair-etna-article-content":
        asyncio.run(_repair_etna_article_content())
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
    elif args.command == "deep-scan":
        asyncio.run(_deep_scan(args.carriers, args.dry_run, args.max_llm_calls))
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
    elif args.command == "evaluate-golden":
        asyncio.run(_evaluate_golden(args.full_surface))
    elif args.command == "check-data-quality":
        asyncio.run(_check_data_quality())
    elif args.command == "mark-legacy-campaigns-superseded":
        asyncio.run(_mark_legacy_campaigns_superseded())


if __name__ == "__main__":
    main()
