"""AI enrichment: headline, summary, category, sentiment, entities, and
cross-source confidence for every deduped (canonical) article.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.factory import get_llm_provider
from app.llm.heuristic import HeuristicProvider, detect_region
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity
from app.pipeline.headlines import strip_publisher_suffix
from app.pipeline.relevance import score_article
from app.pipeline.search_indexing import index_article_text
from app.pipeline.verify import compute_confidence
from app.repositories.entity_repository import EntityRepository

logger = get_logger(__name__)

# Share of each capped run reserved for the oldest waiting articles, so the
# backlog always drains even while fresh news keeps arriving. See _select_pending.
BACKLOG_SHARE = 0.35


async def _translate_pair(engine, headline: str, summary: str) -> tuple[str | None, str | None]:
    """Headline + summary in one LLM call where the provider supports it.

    Not every provider does (the heuristic can't translate at all, and Ollama
    has no paired path), so this degrades to the original two calls rather than
    requiring every implementation to grow a method.
    """
    pair = getattr(engine, "translate_pair", None)
    if pair is not None:
        return await pair(headline, summary)
    return (
        await engine.translate(headline),
        await engine.translate(summary) if summary else None,
    )


def _importance_score(confidence: float, corroborating_count: int) -> float:
    """More corroborating independent sources -> higher importance; this is what
    the Top-10 story board (M3) ranks by."""
    return round(min(1.0, confidence * 0.7 + min(corroborating_count, 5) * 0.06), 3)


async def _select_pending(db: AsyncSession, limit: int | None) -> list[Article]:
    """The articles this run will work on.

    Freshest-first alone starved the backlog into unreachability: ingest
    delivers 20-60 new articles every two hours, all of them newer than
    anything already waiting, so a fixed batch of "the newest N" never reached
    the older rows -- 934 articles sat at status 'deduped' indefinitely while
    the queue looked like it was draining.

    So each capped run reserves a share for the oldest waiting articles. The
    newest still lead (a reader opening the site wants today's news), but the
    tail is guaranteed to move every single run.
    """
    # selectinload: the enrichment loop reads article.source.name to strip the
    # aggregator's " - Publisher" suffix. Left lazy, that attribute access is a
    # SELECT issued mid-iteration, which asyncio SQLAlchemy rejects with
    # MissingGreenlet -- it took down every scheduled ingest run for a day.
    base = (
        select(Article)
        .options(selectinload(Article.source))
        .where(
            Article.status == "deduped",
            # Never re-enrich something that already has a row. Two workers on
            # the same database -- a scheduled run and a manual dispatch, say --
            # both selected the same 'deduped' articles and the second INSERT
            # died on the unique constraint, taking the whole run down with it.
            # article_id is unique on article_enrichment, so this is also what
            # heals a row whose status update was lost to an earlier crash.
            ~select(ArticleEnrichment.article_id)
            .where(ArticleEnrichment.article_id == Article.id)
            .exists(),
        )
    )
    if limit is None:
        return list((await db.execute(base)).scalars().all())

    oldest_share = max(1, round(limit * BACKLOG_SHARE))
    newest_share = max(1, limit - oldest_share)

    newest = list(
        (
            await db.execute(
                base.order_by(Article.published_at.desc().nulls_last()).limit(newest_share)
            )
        )
        .scalars()
        .all()
    )
    oldest = list(
        (
            await db.execute(
                base.order_by(Article.published_at.asc().nulls_first()).limit(oldest_share)
            )
        )
        .scalars()
        .all()
    )
    # The two ends can overlap once the queue is short enough.
    seen: set = set()
    selected: list[Article] = []
    for article in [*newest, *oldest]:
        if article.id not in seen:
            seen.add(article.id)
            selected.append(article)
    return selected


async def enrich_pending_articles(db: AsyncSession, limit: int | None = None) -> int:
    """Enrich every deduped article, or `limit` of them per run.

    A limit exists so a single scheduled run can't blow the LLM's daily budget
    (see app/core/config.py llm_enrich_batch_size); the heuristic path passes no
    limit (it's free and instant).

    Articles that score below `llm_relevance_threshold` on the local relevance
    pass (app/pipeline/relevance.py) are enriched *without* the LLM: they get a
    category, a summary and entities from the heuristic, stay searchable and
    filterable, and are honestly marked untranslated. That gate is what keeps
    the budget on the stories this portal exists for instead of spending it on
    whatever an aggregator happened to return.
    """
    settings = get_settings()
    provider = get_llm_provider()
    local = HeuristicProvider()
    entity_repo = EntityRepository(db)

    articles = await _select_pending(db, limit)
    skipped = 0

    for article in articles:
        # The gate. Scored locally, before a single network call: an article
        # with no commercial-aviation signal is enriched by the heuristic alone
        # so the LLM budget goes to the stories this portal is about.
        relevance = score_article(article.title, article.raw_content)
        worth_llm = relevance.score >= settings.llm_relevance_threshold
        engine = provider if worth_llm else local
        if not worth_llm:
            skipped += 1

        headline = await engine.generate_headline(article.title, article.raw_content)
        summary = await engine.generate_summary(article.title, article.raw_content)
        category = await engine.categorize(article.title, article.raw_content)
        sentiment = await engine.sentiment(article.title, article.raw_content)
        entities = await engine.extract_entities(article.title, article.raw_content)

        # Region is entity-derived (country -> world region), so it works the
        # same regardless of which provider extracted the entities.
        region = detect_region(entities)
        subcategory = await engine.subcategorize(article.title, article.raw_content, category)
        if category == "events":
            # Events don't have keyword-detectable subcategories -- they're
            # "regional" whenever a region was detected, "general" otherwise.
            subcategory = "regional" if region else "general"

        headline = headline[:500] or article.title
        # Aggregator feeds append " - Publisher"; the source is shown beside
        # the story anyway (see app/pipeline/headlines.py).
        headline = strip_publisher_suffix(
            headline, article.source.name if article.source else None
        )
        # Real Turkish translation only happens when a translation-capable LLM
        # is configured (see app/llm/base.py); the heuristic fallback always
        # returns None here, and both fields stay null -- surfaced honestly by
        # the API as is_translated=False rather than faked.
        #
        # One call for both fields: sending headline and summary separately
        # doubled 70b traffic, and translation is the whole of the daily token
        # budget. translate_pair falls back to two calls on any provider that
        # doesn't implement it.
        headline_tr, summary_tr = await _translate_pair(engine, headline, summary)
        # A successful headline translation used to be thrown away whenever the
        # summary failed. The card shows the headline, so keep what we got.
        translated = headline_tr is not None

        corroborating_count, confidence = await compute_confidence(db, article)

        enrichment = ArticleEnrichment(
            article_id=article.id,
            headline=headline,
            summary=summary,
            category=category,
            subcategory=subcategory,
            region=region,
            importance_score=_importance_score(confidence, corroborating_count),
            sentiment=sentiment,
            confidence_score=confidence,
            corroborating_source_count=corroborating_count,
            verified_at=datetime.now(timezone.utc),
            llm_provider_used=provider.name,
            tags=",".join(sorted({e.entity_type for e in entities})),
            headline_tr=headline_tr,
            summary_tr=summary_tr,
            translated_at=datetime.now(timezone.utc) if translated else None,
            translation_provider=provider.name if translated else None,
        )
        db.add(enrichment)
        await db.flush()

        for mention in entities:
            entity = await entity_repo.get_or_create(mention.entity_type, mention.name, mention.code)
            db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))

        await index_article_text(
            db, article.id, f"{article.title} {headline} {summary} {enrichment.tags}"
        )
        article.status = "enriched"

    await db.commit()
    logger.info(
        "enrichment_run_complete",
        enriched=len(articles),
        # How many took the free path -- the ratio is how much budget the
        # relevance gate saved this run.
        heuristic_only=skipped,
        llm_enriched=len(articles) - skipped,
    )
    return len(articles)


async def translate_pending_articles(db: AsyncSession, limit: int = 12) -> int:
    """Fill in Turkish translation for already-enriched articles that don't have
    it yet -- in place, without touching status, category, or anything else.

    The steady-state cron translates new articles as they're ingested, but a
    backlog enriched before a translator was configured (or by the heuristic,
    which can't translate) stays English. This backfills it a batch at a time,
    freshest first, so the site fills with Turkish over successive runs without
    ever un-publishing an article the way a full re-enrich would.

    Only rows with translated_at IS NULL are touched, which by construction
    excludes the curated events (they carry translation_provider='curated' and a
    translated_at) -- their hand-written Turkish is never overwritten.
    """
    provider = get_llm_provider()

    result = await db.execute(
        select(ArticleEnrichment)
        .join(Article, Article.id == ArticleEnrichment.article_id)
        .where(
            Article.is_duplicate.is_(False),
            Article.status == "enriched",
            ArticleEnrichment.translated_at.is_(None),
        )
        .order_by(Article.published_at.desc().nulls_last())
        .limit(limit)
    )
    enrichments = list(result.scalars().all())

    translated = 0
    for enrichment in enrichments:
        headline_tr = await provider.translate(enrichment.headline) if enrichment.headline else None
        summary_tr = await provider.translate(enrichment.summary) if enrichment.summary else None
        # translate() returns None when no real translator ran; only mark the row
        # translated when we actually got Turkish back, so is_translated stays honest.
        if headline_tr is None and summary_tr is None:
            continue
        enrichment.headline_tr = headline_tr
        enrichment.summary_tr = summary_tr
        enrichment.translated_at = datetime.now(timezone.utc)
        enrichment.translation_provider = provider.name
        translated += 1

    await db.commit()
    logger.info("translation_backfill_complete", translated=translated, considered=len(enrichments))
    return translated


async def reclassify_articles(db: AsyncSession, batch_size: int = 50) -> dict[str, int]:
    """Recompute entities, region, and subcategory in place with the *current*
    heuristic -- category, translations, headlines and status stay untouched.

    Exists because those three fields are derived once at ingest: when the
    gazetteer or keyword tables improve (word-boundary entity matching, rival
    names as competitor signals, airport->country region fallback), the archive
    keeps its stale derivations until something recomputes them. `re-enrich`
    would also wipe the Turkish translations; this doesn't.
    """
    from app.llm.heuristic import HeuristicProvider

    provider = HeuristicProvider()
    entity_repo = EntityRepository(db)

    result = await db.execute(
        select(Article)
        .options(selectinload(Article.enrichment))
        .where(Article.is_duplicate.is_(False), Article.status == "enriched")
    )
    articles = list(result.scalars().all())

    region_changes = subcategory_changes = 0
    for index, article in enumerate(articles, start=1):
        enrichment = article.enrichment
        if enrichment is None:
            continue

        entities = await provider.extract_entities(article.title, article.raw_content)
        await db.execute(delete(ArticleEntity).where(ArticleEntity.article_id == article.id))
        for mention in entities:
            entity = await entity_repo.get_or_create(mention.entity_type, mention.name, mention.code)
            db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))

        region = detect_region(entities)
        subcategory = await provider.subcategorize(
            article.title, article.raw_content, enrichment.category
        )
        if enrichment.category == "events":
            subcategory = "regional" if region else "general"

        if region != enrichment.region:
            region_changes += 1
        if subcategory != enrichment.subcategory:
            subcategory_changes += 1
        enrichment.region = region
        enrichment.subcategory = subcategory

        # Periodic commits: a single end-of-run commit over a remote pooled DB
        # lost entire batches to idle timeouts in production. Small and often.
        if index % batch_size == 0:
            await db.commit()

    await db.commit()
    logger.info(
        "reclassify_complete",
        articles=len(articles),
        region_changes=region_changes,
        subcategory_changes=subcategory_changes,
    )
    return {
        "articles": len(articles),
        "region_changes": region_changes,
        "subcategory_changes": subcategory_changes,
    }


async def repair_corrupt_translations(db: AsyncSession) -> dict[str, int]:
    """Fix stored translations where the model wrote past the translation.

    llama-3.1-8b appended invented prose / translator meta-commentary after
    otherwise-correct headline translations (61 rows in production, worst case
    7,513 chars). The good translation is the first line, so most rows are
    repaired *in place* by re-running the sanitizer over the stored value -- no
    LLM calls. Rows the sanitizer can't salvage get their translation fields
    nulled, which returns them to the translate-backlog queue (and the honest
    "otomatik çeviri yok" badge) instead of showing junk.
    """
    from app.llm.sanitize import clean_translation

    result = await db.execute(
        select(ArticleEnrichment).where(
            ArticleEnrichment.translated_at.is_not(None),
            (
                func.length(ArticleEnrichment.headline_tr) > 220
            )
            | ArticleEnrichment.headline_tr.ilike("%çevir%")
            | ArticleEnrichment.summary_tr.ilike("%çeviriyorum%"),
        )
    )
    rows = list(result.scalars().all())

    repaired = renulled = 0
    for enrichment in rows:
        cleaned_headline = clean_translation(enrichment.headline or "", enrichment.headline_tr)
        cleaned_summary = (
            clean_translation(enrichment.summary or "", enrichment.summary_tr)
            if enrichment.summary_tr
            else None
        )
        if cleaned_headline:
            enrichment.headline_tr = cleaned_headline
            enrichment.summary_tr = cleaned_summary
            repaired += 1
        else:
            # Unsalvageable: back to the untranslated queue, honestly badged.
            enrichment.headline_tr = None
            enrichment.summary_tr = None
            enrichment.translated_at = None
            enrichment.translation_provider = None
            renulled += 1

    await db.commit()
    logger.info("translation_repair_complete", repaired=repaired, renulled=renulled)
    return {"repaired": repaired, "renulled": renulled}


async def reset_enrichment(db: AsyncSession, days: int | None = None) -> int:
    """Drop existing enrichment so the next run redoes it from scratch.

    Needed whenever the pipeline itself changes -- a new categorisation
    taxonomy, or an LLM becoming available where there was none -- because
    enrichment is only ever computed once per article, at ingest. Deletes the
    derived rows (enrichment + entity links) and rewinds status to "deduped";
    the raw article is never touched.
    """
    query = select(Article).where(Article.is_duplicate.is_(False))
    if days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.where(Article.fetched_at >= since)

    articles = list((await db.execute(query)).scalars().all())
    article_ids = [a.id for a in articles]
    if not article_ids:
        return 0

    await db.execute(delete(ArticleEntity).where(ArticleEntity.article_id.in_(article_ids)))
    await db.execute(
        delete(ArticleEnrichment).where(ArticleEnrichment.article_id.in_(article_ids))
    )
    for article in articles:
        article.status = "deduped"

    await db.commit()
    logger.info("enrichment_reset", articles=len(article_ids), days=days)
    return len(article_ids)


async def clean_stored_headlines(db: AsyncSession, batch_size: int = 200) -> dict[str, int]:
    """Strip aggregator publisher credits from headlines already in the archive.

    Google News rewrites titles as "<headline> - <Publisher>", and the archive
    kept those suffixes in `headline`, `headline_tr` and the article title, so
    the newspaper, newsletter and PDF all repeated the outlet name shown beside
    the story. Only suffixes that look like a credit are removed
    (app/pipeline/headlines.py). Commits per batch: a single end-of-run commit
    over a pooled remote database has lost whole runs to idle timeouts here
    before.
    """
    result = await db.execute(
        select(Article)
        .options(selectinload(Article.enrichment), selectinload(Article.source))
        .where(Article.is_duplicate.is_(False))
    )
    articles = list(result.scalars().unique().all())

    cleaned = 0
    for index, article in enumerate(articles, start=1):
        source_name = article.source.name if article.source else None
        changed = False

        new_title = strip_publisher_suffix(article.title, source_name)
        if new_title != article.title:
            article.title = new_title
            changed = True

        enrichment = article.enrichment
        if enrichment is not None:
            for field in ("headline", "headline_tr"):
                value = getattr(enrichment, field)
                if not value:
                    continue
                new_value = strip_publisher_suffix(value, source_name)
                if new_value != value:
                    setattr(enrichment, field, new_value)
                    changed = True

        if changed:
            cleaned += 1
        if index % batch_size == 0:
            await db.commit()

    await db.commit()
    logger.info("headlines_cleaned", cleaned=cleaned, scanned=len(articles))
    return {"cleaned": cleaned, "scanned": len(articles)}
