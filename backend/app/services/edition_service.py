"""Assembles a daily edition: ranks enriched articles fetched that day by
importance, takes the top N as headline stories, and buckets the rest into
category sections. Re-running for the same date rebuilds it from scratch, so
a same-day edition always reflects the latest ingested articles.
"""
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.llm.factory import get_llm_provider
from app.models.article import Article, ArticleEnrichment
from app.models.edition import Edition, EditionArticle

logger = get_logger(__name__)

TOP_STORY_COUNT = 10


async def assemble_edition(db: AsyncSession, edition_date: date) -> Edition:
    day_start = datetime.combine(edition_date, time.min, tzinfo=timezone.utc)
    day_end = datetime.combine(edition_date, time.max, tzinfo=timezone.utc)

    result = await db.execute(
        select(Article)
        .options(selectinload(Article.enrichment), selectinload(Article.source))
        .join(ArticleEnrichment)
        .where(
            Article.status == "enriched",
            Article.is_duplicate.is_(False),
            Article.fetched_at >= day_start,
            Article.fetched_at <= day_end,
        )
        .order_by(ArticleEnrichment.importance_score.desc())
    )
    articles = list(result.scalars().unique().all())

    top_stories = articles[:TOP_STORY_COUNT]
    remaining = articles[TOP_STORY_COUNT:]

    new_edition_articles = [
        EditionArticle(article_id=article.id, section="top_story", rank=rank)
        for rank, article in enumerate(top_stories)
    ]

    by_category: dict[str, list[Article]] = {}
    for article in remaining:
        by_category.setdefault(article.enrichment.category, []).append(article)
    for category, category_articles in by_category.items():
        new_edition_articles.extend(
            EditionArticle(article_id=article.id, section=category, rank=rank)
            for rank, article in enumerate(category_articles)
        )

    # edition.articles must already be loaded (selectinload below) before a bulk
    # collection assignment -- otherwise the ORM needs to lazy-load the prior
    # state to compute the delete-orphan diff, which can't happen synchronously
    # under an AsyncSession. Building a brand-new Edition with its collection
    # passed at construction time sidesteps that (nothing to reconcile yet).
    edition_result = await db.execute(
        select(Edition)
        .options(selectinload(Edition.articles))
        .where(Edition.edition_date == edition_date)
    )
    edition = edition_result.scalar_one_or_none()
    if edition is None:
        edition = Edition(edition_date=edition_date, articles=new_edition_articles)
        db.add(edition)
    else:
        # Two separate flushes: a rebuild reuses the same article_ids, and
        # (edition_id, article_id) is unique -- inserting the new rows before
        # the old ones are deleted would collide on that constraint.
        edition.articles = []
        await db.flush()
        edition.articles = new_edition_articles

    if top_stories:
        edition.headline = top_stories[0].enrichment.headline or top_stories[0].title
        provider = get_llm_provider()
        # Headlines carry no terminal punctuation, so join them as explicit
        # sentences -- otherwise the extractive summarizer sees one run-on
        # "sentence" and can't pick out the top themes.
        headlines_blob = ". ".join((a.enrichment.headline or a.title) for a in top_stories[:5]) + "."
        edition.executive_summary = await provider.generate_summary(
            "Today's aviation news roundup", headlines_blob
        )
    else:
        edition.headline = "No stories yet today"
        edition.executive_summary = ""

    edition.status = "published"

    await db.commit()

    # db.refresh() only reloads column attributes, not relationships -- re-query
    # with articles eager-loaded so callers can safely access edition.articles.
    result = await db.execute(
        select(Edition).options(selectinload(Edition.articles)).where(Edition.id == edition.id)
    )
    edition = result.scalar_one()

    logger.info(
        "edition_assembled",
        edition_date=str(edition_date),
        top_stories=len(top_stories),
        total_articles=len(articles),
    )
    return edition
