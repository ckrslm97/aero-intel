"""Ağ Sinyalleri: new-route events (pipeline v2) grouped by region."""
from datetime import datetime, timezone

from app.models.article import Article
from app.models.entity import ArticleEntity, Entity
from app.models.news_event import NewsEvent
from app.models.source import Source
from app.services.network_signals_service import network_signals

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


async def _event(db, *, slug, primary_article_id, region, **fields):
    event = NewsEvent(
        slug=slug,
        title_tr=fields.pop("title_tr", slug),
        primary_article_id=primary_article_id,
        region=region,
        category=fields.pop("category", "network"),
        subcategory=fields.pop("subcategory", "new_route"),
        first_seen=NOW,
        last_seen=NOW,
        is_published=fields.pop("is_published", True),
        confidence_band=fields.pop("confidence_band", "high"),
        **fields,
    )
    db.add(event)
    await db.flush()
    return event


async def test_network_signals_groups_a_new_route_event_by_region_and_resolves_airports(db_session):
    source = await _source(db_session)
    tk = Entity(entity_type="airline", name="Turkish Airlines", code="TK")
    ist = Entity(entity_type="airport", name="Istanbul Airport", code="IST")
    lhr = Entity(entity_type="airport", name="Heathrow", code="LHR")
    db_session.add_all([tk, ist, lhr])
    await db_session.flush()
    article = await _article(db_session, source, "tk-yeni-hat", entities=[tk, ist, lhr])
    await db_session.commit()

    await _event(
        db_session, slug="tk-yeni-hat-evt", primary_article_id=article.id, region="europe"
    )
    await db_session.commit()

    signals = await network_signals(db_session, days=30)
    assert len(signals) == 1
    assert signals[0]["region"] == "europe"
    assert signals[0]["count"] == 1
    entry = signals[0]["articles"][0]
    assert entry["slug"] == "tk-yeni-hat-evt"
    assert entry["airlines"] == ["TK"]
    # IST is the carrier's own hub (see app/hubs.py) so only LHR is the
    # destination -- the same origin/destination correction insights_service
    # already applies.
    assert [a["code"] for a in entry["airports"]] == ["LHR"]


async def test_network_signals_ignores_other_categories(db_session):
    source = await _source(db_session)
    article = await _article(db_session, source, "not-a-route")
    await db_session.commit()

    await _event(
        db_session, slug="fleet-evt", primary_article_id=article.id, region="europe",
        category="fleet", subcategory=None,
    )
    await db_session.commit()

    assert await network_signals(db_session, days=30) == []


async def test_network_signals_excludes_low_confidence_and_unpublished(db_session):
    source = await _source(db_session)
    a1 = await _article(db_session, source, "low-conf")
    a2 = await _article(db_session, source, "unpublished")
    await db_session.commit()

    await _event(
        db_session, slug="low-conf-evt", primary_article_id=a1.id, region="europe",
        confidence_band="low",
    )
    await _event(
        db_session, slug="unpublished-evt", primary_article_id=a2.id, region="europe",
        is_published=False,
    )
    await db_session.commit()

    assert await network_signals(db_session, days=30) == []


async def test_network_signals_skips_events_with_no_primary_article(db_session):
    await _event(db_session, slug="orphan-evt", primary_article_id=None, region="europe")
    await db_session.commit()

    assert await network_signals(db_session, days=30) == []


async def test_network_signals_sorts_regions_by_count_descending(db_session):
    source = await _source(db_session)
    for i in range(3):
        article = await _article(db_session, source, f"eu-{i}")
        await db_session.commit()
        await _event(db_session, slug=f"eu-evt-{i}", primary_article_id=article.id, region="europe")
    article = await _article(db_session, source, "as-0")
    await db_session.commit()
    await _event(db_session, slug="as-evt-0", primary_article_id=article.id, region="asia")
    await db_session.commit()

    signals = await network_signals(db_session, days=30)
    assert [s["region"] for s in signals] == ["europe", "asia"]
    assert [s["count"] for s in signals] == [3, 1]
