from datetime import date, datetime, timezone

from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.services.edition_service import TOP_STORY_COUNT, assemble_edition


async def _make_article(
    db_session, source, *, title, category, importance, url, headline_tr=None
):
    article = Article(
        source_id=source.id,
        url=url,
        title=title,
        raw_content=f"Body for {title}",
        fetched_at=datetime.now(timezone.utc),
        content_hash=url,
        status="enriched",
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id,
            headline=title,
            summary=f"Summary of {title}.",
            category=category,
            importance_score=importance,
            confidence_score=0.7,
            corroborating_source_count=1,
            headline_tr=headline_tr,
            translated_at=datetime.now(timezone.utc) if headline_tr else None,
            translation_provider="openai_compat" if headline_tr else None,
        )
    )
    await db_session.flush()
    return article


async def test_assemble_edition_ranks_top_stories_by_importance(db_session):
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    for i in range(15):
        await _make_article(
            db_session,
            source,
            title=f"Story {i}",
            category="general" if i % 2 == 0 else "fleet",
            importance=i / 15,
            url=f"https://example.com/{i}",
        )
    await db_session.commit()

    edition = await assemble_edition(db_session, date.today())

    top_story_articles = [ea for ea in edition.articles if ea.section == "top_story"]
    assert len(top_story_articles) == TOP_STORY_COUNT
    # highest importance (Story 14, score 14/15) should rank first
    assert top_story_articles[0].rank == 0

    other_sections = {ea.section for ea in edition.articles if ea.section != "top_story"}
    assert other_sections <= {"general", "fleet"}
    assert edition.headline
    assert edition.status == "published"


async def test_edition_headline_uses_turkish_when_top_story_is_translated(db_session):
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    # The clear top story is a translated article; the edition masthead must read
    # its Turkish headline, not the English original.
    await _make_article(
        db_session, source, title="Airline posts record profit", category="finance",
        importance=0.95, url="https://example.com/top", headline_tr="Havayolu rekor kâr açıkladı",
    )
    await _make_article(
        db_session, source, title="Minor fleet update", category="fleet",
        importance=0.2, url="https://example.com/minor",
    )
    await db_session.commit()

    edition = await assemble_edition(db_session, date.today())

    assert edition.headline == "Havayolu rekor kâr açıkladı"
    # The extractive summary is built from Turkish headlines, so it must not echo
    # the English original of the top story.
    assert "Airline posts record profit" not in edition.executive_summary


async def test_assemble_edition_is_idempotent_on_rebuild(db_session):
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    for i in range(3):
        await _make_article(
            db_session,
            source,
            title=f"Story {i}",
            category="general",
            importance=i / 3,
            url=f"https://example.com/{i}",
        )
    await db_session.commit()

    first = await assemble_edition(db_session, date.today())
    second = await assemble_edition(db_session, date.today())

    assert first.id == second.id
    assert len(second.articles) == 3
