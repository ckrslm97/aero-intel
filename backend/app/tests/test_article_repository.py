import itertools
from datetime import datetime, timedelta, timezone

from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.repositories.article_repository import ArticleRepository
from app.schemas.article import ArticleOut

_url_counter = itertools.count()


async def _make_article(db_session, source, *, category, subcategory, region, published_at):
    article = Article(
        source_id=source.id,
        url=f"https://example.com/{category}-{subcategory}-{region}-{next(_url_counter)}",
        title="Test article",
        raw_content="word " * 250,
        published_at=published_at,
        fetched_at=published_at,
        content_hash=f"hash-{category}-{subcategory}-{region}",
        status="enriched",
    )
    db_session.add(article)
    await db_session.flush()
    db_session.add(
        ArticleEnrichment(
            article_id=article.id,
            headline="Test headline",
            summary="Test summary",
            category=category,
            subcategory=subcategory,
            region=region,
        )
    )
    await db_session.flush()
    return article


async def test_list_recent_filters_by_category_subcategory_and_region(db_session):
    source = Source(name="Test Source", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    match = await _make_article(
        db_session, source, category="revenue_management", subcategory="competitor", region="europe",
        published_at=now,
    )
    await _make_article(
        db_session, source, category="revenue_management", subcategory="pricing", region="europe",
        published_at=now,
    )
    await _make_article(
        db_session, source, category="events", subcategory="general", region=None, published_at=now,
    )
    await db_session.commit()

    repo = ArticleRepository(db_session)
    results = await repo.list_recent(category="revenue_management", subcategory="competitor")
    assert {a.id for a in results} == {match.id}

    region_results = await repo.list_recent(region="europe")
    assert len(region_results) == 2


async def test_count_matches_the_filtered_list_for_load_more(db_session):
    source = Source(name="Test Source", url="https://example.com/feed-count", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    for sub in ("competitor", "pricing", "forecasting"):
        await _make_article(
            db_session, source, category="revenue_management", subcategory=sub, region="europe",
            published_at=now,
        )
    await _make_article(
        db_session, source, category="events", subcategory="general", region=None, published_at=now,
    )
    # A duplicate must not inflate the total the way it must not appear in the list.
    dup = await _make_article(
        db_session, source, category="revenue_management", subcategory="pricing", region="europe",
        published_at=now,
    )
    dup.is_duplicate = True
    await db_session.commit()

    repo = ArticleRepository(db_session)
    # Total is scoped to the same filter the list uses -- 3 RM stories, not 5 total.
    assert await repo.count(category="revenue_management") == 3
    listed = await repo.list_recent(category="revenue_management", limit=200)
    assert await repo.count(category="revenue_management") == len(listed)
    # Unfiltered still excludes the duplicate: 3 RM + 1 events = 4.
    assert await repo.count() == 4


async def test_airline_filter_matches_articles_mentioning_the_airline(db_session):
    from app.models.entity import ArticleEntity, Entity

    source = Source(name="Test Source", url="https://example.com/feed-air", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    emirates_story = await _make_article(
        db_session, source, category="fleet", subcategory=None, region=None, published_at=now,
    )
    await _make_article(
        db_session, source, category="fleet", subcategory=None, region=None, published_at=now,
    )
    entity = Entity(entity_type="airline", name="Emirates", code="EK")
    db_session.add(entity)
    await db_session.flush()
    db_session.add(ArticleEntity(article_id=emirates_story.id, entity_id=entity.id))
    await db_session.commit()

    repo = ArticleRepository(db_session)
    results = await repo.list_recent(airline="EK")
    assert {a.id for a in results} == {emirates_story.id}
    # The rival filter crosses categories -- and total matches the list.
    assert await repo.count(airline="EK") == 1
    assert await repo.count(category="fleet", airline="EK") == 1


async def test_list_recent_since_filter_excludes_older_articles(db_session):
    source = Source(name="Test Source", url="https://example.com/feed3", source_type="rss")
    db_session.add(source)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    recent = await _make_article(
        db_session, source, category="finance", subcategory="results", region=None, published_at=now,
    )
    await _make_article(
        db_session,
        source,
        category="finance",
        subcategory="results",
        region=None,
        published_at=now - timedelta(days=30),
    )
    await db_session.commit()

    repo = ArticleRepository(db_session)
    results = await repo.list_recent(since=now - timedelta(days=7))
    assert {a.id for a in results} == {recent.id}


def _fake_article(**overrides):
    import uuid
    from types import SimpleNamespace

    source = SimpleNamespace(
        id=uuid.uuid4(), name="Src", url="https://example.com", category="other", trust_weight=0.5
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        url="https://example.com/a",
        title="Title",
        author=None,
        published_at=None,
        fetched_at=datetime.now(timezone.utc),
        status="enriched",
        source=source,
        enrichment=None,
        **overrides,
    )


def test_article_out_computes_reading_time_from_stored_word_count():
    # 400 words at 200 wpm -> 2 minutes. The count is read from the column, not
    # from raw_content, which list queries deliberately never load.
    out = ArticleOut.model_validate(_fake_article(word_count=400), from_attributes=True)
    assert out.reading_time_minutes == 2


def test_reading_time_survives_a_deferred_or_missing_word_count():
    # Rows ingested before the column existed, or a deferred load, must not
    # raise -- the badge just reports the one-minute floor.
    out = ArticleOut.model_validate(_fake_article(word_count=None), from_attributes=True)
    assert out.reading_time_minutes == 1
