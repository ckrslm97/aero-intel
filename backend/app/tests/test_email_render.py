from datetime import date, datetime, timezone

from app.email.render import render_newsletter_html
from app.models.article import Article, ArticleEnrichment
from app.models.edition import Edition, EditionArticle
from app.models.source import Source


async def test_render_newsletter_html_includes_headline_and_articles(db_session):
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    article = Article(
        source_id=source.id,
        url="https://example.com/a",
        title="Delta launches Tokyo route",
        raw_content="body",
        fetched_at=datetime.now(timezone.utc),
        content_hash="hash-a",
        status="enriched",
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id,
            headline="Delta launches new Tokyo route",
            summary="Delta will begin nonstop service to Tokyo.",
            category="routes",
            importance_score=0.8,
            confidence_score=0.9,
            corroborating_source_count=2,
        )
    )
    await db_session.flush()

    edition = Edition(
        edition_date=date(2026, 7, 12),
        headline="Delta launches new Tokyo route",
        executive_summary="A quiet news day.",
        status="published",
    )
    db_session.add(edition)
    await db_session.flush()
    db_session.add(EditionArticle(edition_id=edition.id, article_id=article.id, section="top_story", rank=0))
    await db_session.commit()

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await db_session.execute(
        select(Edition)
        .options(
            selectinload(Edition.articles).selectinload(EditionArticle.article).selectinload(Article.source),
            selectinload(Edition.articles).selectinload(EditionArticle.article).selectinload(Article.enrichment),
        )
        .where(Edition.id == edition.id)
    )
    loaded_edition = result.scalar_one()

    html = render_newsletter_html(loaded_edition)

    assert "Delta launches new Tokyo route" in html
    assert "Delta will begin nonstop service to Tokyo." in html
    assert "Test Source" in html
    assert "90% confidence" in html
    assert "2 sources" in html
    assert "Top Stories" in html
