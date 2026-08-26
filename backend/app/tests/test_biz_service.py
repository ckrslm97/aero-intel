"""BİZ page composition: competitor/network/commercial/strategic sections,
each with the structural no-filler wrapper."""
from datetime import datetime, timezone

from app.models.article import Article
from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent
from app.models.source import Source
from app.services.biz_service import (
    EMPTY_MESSAGE,
    biz_overview,
    competitor_signals,
    strategic_developments,
)

NOW = datetime.now(timezone.utc)


async def _source(db) -> Source:
    source = Source(name="H", url="https://example.com/h", source_type="rss")
    db.add(source)
    await db.flush()
    return source


async def _article(db, source, slug, entities=()):
    article = Article(
        source_id=source.id, url=f"https://example.com/{slug}", title=slug,
        raw_content="body", published_at=NOW, fetched_at=NOW, content_hash=slug,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    for entity in entities:
        db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    await db.flush()
    return article


async def _event(db, *, slug, primary_article_id, **fields):
    event = NewsEvent(
        slug=slug,
        title_tr=fields.pop("title_tr", slug),
        primary_article_id=primary_article_id,
        category=fields.pop("category", None),
        first_seen=NOW,
        last_seen=NOW,
        is_published=fields.pop("is_published", True),
        confidence_band=fields.pop("confidence_band", "high"),
        **fields,
    )
    db.add(event)
    await db.flush()
    return event


async def test_competitor_signals_groups_by_rival_and_skips_untouched_rivals(db_session):
    source = await _source(db_session)
    ek = Entity(entity_type="airline", name="Emirates", code="EK")
    db_session.add(ek)
    await db_session.flush()
    article = await _article(db_session, source, "ek-news", entities=[ek])
    await db_session.commit()

    await _event(db_session, slug="ek-evt", primary_article_id=article.id)
    await db_session.commit()

    signals = await competitor_signals(db_session, days=30)
    assert [s["airline_code"] for s in signals] == ["EK"]
    assert signals[0]["airline_name"] == "Emirates"
    assert signals[0]["count"] == 1
    # Rivals never mentioned in the window don't appear at count=0 -- they're
    # simply absent, not padded onto the list.
    codes = {s["airline_code"] for s in signals}
    assert "QR" not in codes


async def test_competitor_signals_sorts_by_event_count_descending(db_session):
    source = await _source(db_session)
    ek = Entity(entity_type="airline", name="Emirates", code="EK")
    qr = Entity(entity_type="airline", name="Qatar Airways", code="QR")
    db_session.add_all([ek, qr])
    await db_session.flush()

    a1 = await _article(db_session, source, "ek-1", entities=[ek])
    a2 = await _article(db_session, source, "ek-2", entities=[ek])
    a3 = await _article(db_session, source, "qr-1", entities=[qr])
    await db_session.commit()

    await _event(db_session, slug="ek-evt-1", primary_article_id=a1.id)
    await _event(db_session, slug="ek-evt-2", primary_article_id=a2.id)
    await _event(db_session, slug="qr-evt-1", primary_article_id=a3.id)
    await db_session.commit()

    signals = await competitor_signals(db_session, days=30)
    assert [s["airline_code"] for s in signals] == ["EK", "QR"]
    assert [s["count"] for s in signals] == [2, 1]


async def test_strategic_developments_only_includes_strategic_categories(db_session):
    source = await _source(db_session)
    a1 = await _article(db_session, source, "fleet-news")
    a2 = await _article(db_session, source, "route-news")
    await db_session.commit()

    await _event(db_session, slug="fleet-evt", primary_article_id=a1.id, category="fleet")
    # network is Ağ Sinyalleri's category, not a strategic development here.
    await _event(db_session, slug="route-evt", primary_article_id=a2.id, category="network")
    await db_session.commit()

    strategic = await strategic_developments(db_session, days=30)
    assert [e["slug"] for e in strategic] == ["fleet-evt"]


async def test_strategic_developments_excludes_low_confidence_and_superseded(db_session):
    source = await _source(db_session)
    a1 = await _article(db_session, source, "low-conf")
    a2 = await _article(db_session, source, "superseded")
    await db_session.commit()

    await _event(
        db_session, slug="low-conf-evt", primary_article_id=a1.id, category="finance",
        confidence_band="low",
    )
    superseded = await _event(
        db_session, slug="superseded-evt", primary_article_id=a2.id, category="finance",
    )
    superseded.superseded_at = datetime.now(timezone.utc)
    await db_session.commit()

    assert await strategic_developments(db_session, days=30) == []


async def test_biz_overview_marks_an_empty_section_unavailable_with_the_honest_message(db_session):
    overview = await biz_overview(db_session, days=30)

    for key in ("competitor_signals", "network_signals", "commercial_signals", "strategic_developments"):
        section = overview[key]
        assert section["available"] is False
        assert section["items"] == []
        assert section["empty_message"] == EMPTY_MESSAGE


async def test_biz_overview_marks_a_populated_section_available(db_session):
    source = await _source(db_session)
    ek = Entity(entity_type="airline", name="Emirates", code="EK")
    db_session.add(ek)
    await db_session.flush()
    article = await _article(db_session, source, "ek-news", entities=[ek])
    await db_session.commit()
    await _event(db_session, slug="ek-evt", primary_article_id=article.id)
    await db_session.commit()

    overview = await biz_overview(db_session, days=30)
    assert overview["competitor_signals"]["available"] is True
    assert overview["competitor_signals"]["empty_message"] is None
    assert len(overview["competitor_signals"]["items"]) == 1
    # Untouched sections stay honestly empty in the same response.
    assert overview["strategic_developments"]["available"] is False
