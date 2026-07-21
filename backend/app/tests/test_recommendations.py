"""The recommendation engine's one promise is that nothing it says is invented:
every item is a count over rows and ships the rows with it. These pin that
promise down -- thresholds hold signal back until it is real, duplicates never
inflate a count, filters only narrow, and an empty archive produces an empty
list instead of a crash.
"""
from datetime import datetime, timedelta, timezone

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.event import AviationEvent
from app.models.source import Source
from app.models.tk_review import TkReview
from app.services.recommendations import (
    PROMO_MIN_ARTICLES,
    ROUTE_SURGE_MIN_CURRENT,
    build_recommendations,
)

NOW = datetime.now(timezone.utc)


async def _source(db, name="S", url="https://example.com/feed") -> Source:
    source = Source(name=name, url=url, source_type="rss")
    db.add(source)
    await db.flush()
    return source


async def _airline(db, name: str, code: str) -> Entity:
    entity = Entity(entity_type="airline", name=name, code=code)
    db.add(entity)
    await db.flush()
    return entity


async def _article(
    db,
    source,
    *,
    url,
    days_ago=1,
    category="revenue_management",
    subcategory="promotion",
    region=None,
    sentiment="neutral",
    is_duplicate=False,
    airline: Entity | None = None,
) -> Article:
    published = NOW - timedelta(days=days_ago)
    article = Article(
        source_id=source.id,
        url=url,
        title="Title",
        raw_content="body",
        published_at=published,
        fetched_at=published,
        content_hash=url,
        status="enriched",
        is_duplicate=is_duplicate,
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id,
            headline="Headline",
            headline_tr="Türkçe başlık",
            category=category,
            subcategory=subcategory,
            region=region,
            sentiment=sentiment,
            importance_score=0.5,
        )
    )
    if airline is not None:
        db.add(ArticleEntity(article_id=article.id, entity_id=airline.id))
    await db.flush()
    return article


async def test_empty_database_returns_empty_list(db_session):
    assert await build_recommendations(db_session) == []


async def test_rival_campaign_cluster_is_cited(db_session):
    source = await _source(db_session)
    emirates = await _airline(db_session, "Emirates", "EK")
    for i in range(PROMO_MIN_ARTICLES):
        await _article(
            db_session, source, url=f"https://example.com/promo{i}", days_ago=i + 1,
            subcategory="promotion", airline=emirates,
        )
    await db_session.commit()

    recs = await build_recommendations(db_session)
    promo = next(r for r in recs if r["id"] == "promo-ek")
    assert promo["airline_code"] == "EK"
    assert promo["category"] == "revenue_management"
    assert promo["metric"]["value"] == PROMO_MIN_ARTICLES
    # Cited, not asserted: the evidence is the very rows the count came from.
    assert len(promo["evidence"]) == PROMO_MIN_ARTICLES
    assert {e["url"] for e in promo["evidence"]} == {
        f"https://example.com/promo{i}" for i in range(PROMO_MIN_ARTICLES)
    }
    assert promo["evidence"][0]["source_name"] == "S"
    assert promo["evidence"][0]["headline"] == "Türkçe başlık"


async def test_signal_below_threshold_produces_no_recommendation(db_session):
    source = await _source(db_session)
    emirates = await _airline(db_session, "Emirates", "EK")
    # One campaign story is news, not a pattern.
    await _article(db_session, source, url="https://example.com/one", airline=emirates)
    # ... and two new-route announcements stay under the regional surge floor.
    for i in range(ROUTE_SURGE_MIN_CURRENT - 1):
        await _article(
            db_session, source, url=f"https://example.com/nr{i}",
            category="network", subcategory="new_route", region="europe",
        )
    await db_session.commit()

    assert await build_recommendations(db_session) == []


async def test_duplicate_articles_never_count_towards_a_pattern(db_session):
    source = await _source(db_session)
    emirates = await _airline(db_session, "Emirates", "EK")
    await _article(db_session, source, url="https://example.com/real", airline=emirates)
    # Same story from a second feed, flagged by the dedupe pass: it must not
    # push the carrier over the campaign threshold on its own.
    for i in range(3):
        await _article(
            db_session, source, url=f"https://example.com/dupe{i}",
            is_duplicate=True, airline=emirates,
        )
    await db_session.commit()

    assert [r for r in await build_recommendations(db_session) if r["id"] == "promo-ek"] == []


async def test_home_carrier_campaigns_are_not_a_competitive_alert(db_session):
    source = await _source(db_session)
    turkish = await _airline(db_session, "Turkish Airlines", "TK")
    for i in range(PROMO_MIN_ARTICLES + 1):
        await _article(
            db_session, source, url=f"https://example.com/tk{i}", airline=turkish
        )
    await db_session.commit()

    assert [r for r in await build_recommendations(db_session) if r["id"] == "promo-tk"] == []
    # ... unless the reader explicitly asks about TK.
    focused = await build_recommendations(db_session, airline="TK")
    assert any(r["id"] == "promo-tk" for r in focused)


async def test_regional_route_surge_needs_a_real_increase(db_session):
    source = await _source(db_session)
    # 4 announcements this week in Europe, 1 the week before -> a surge.
    for i in range(4):
        await _article(
            db_session, source, url=f"https://example.com/eu{i}", days_ago=1,
            category="network", subcategory="new_route", region="europe",
        )
    await _article(
        db_session, source, url="https://example.com/eu-prev", days_ago=9,
        category="network", subcategory="new_route", region="europe",
    )
    # Asia: 3 this week but 3 last week too -> flat, no recommendation.
    for i in range(3):
        await _article(
            db_session, source, url=f"https://example.com/as{i}", days_ago=2,
            category="network", subcategory="new_route", region="asia",
        )
        await _article(
            db_session, source, url=f"https://example.com/as-prev{i}", days_ago=10,
            category="network", subcategory="new_route", region="asia",
        )
    await db_session.commit()

    recs = await build_recommendations(db_session)
    europe = next(r for r in recs if r["id"] == "route-surge-europe")
    assert (europe["metric"]["value"], europe["metric"]["previous"]) == (4, 1)
    assert europe["region"] == "europe"
    assert len(europe["evidence"]) == 4
    assert not [r for r in recs if r["id"] == "route-surge-asia"]


async def test_filters_only_narrow_the_result(db_session):
    source = await _source(db_session)
    emirates = await _airline(db_session, "Emirates", "EK")
    for i in range(PROMO_MIN_ARTICLES):
        await _article(
            db_session, source, url=f"https://example.com/promo{i}", days_ago=i + 1,
            region="middle-east", airline=emirates,
        )
    for i in range(4):
        await _article(
            db_session, source, url=f"https://example.com/eu{i}", days_ago=1,
            category="network", subcategory="new_route", region="europe",
        )
    await db_session.commit()

    everything = await build_recommendations(db_session)
    ids = {r["id"] for r in everything}
    assert {"promo-ek", "route-surge-europe"} <= ids

    by_category = await build_recommendations(db_session, category="network")
    assert {r["id"] for r in by_category} == {"route-surge-europe"}

    by_region = await build_recommendations(db_session, region="europe")
    assert {r["id"] for r in by_region} == {"route-surge-europe"}

    by_airline = await build_recommendations(db_session, airline="EK")
    assert {r["id"] for r in by_airline} == {"promo-ek"}

    # A filter combination nothing matches is an empty list, not an invention.
    assert await build_recommendations(db_session, category="network", airline="EK") == []


async def test_negative_sentiment_cluster_cites_the_negative_stories(db_session):
    source = await _source(db_session)
    for i in range(5):
        await _article(
            db_session, source, url=f"https://example.com/neg{i}", days_ago=1,
            category="labor", subcategory=None, sentiment="negative",
        )
    await _article(
        db_session, source, url="https://example.com/pos", days_ago=2,
        category="labor", subcategory=None, sentiment="positive",
    )
    await db_session.commit()

    recs = await build_recommendations(db_session)
    cluster = next(r for r in recs if r["id"] == "negative-labor")
    assert cluster["metric"]["value"] == 83  # 5 of 6
    assert cluster["severity"] == "high"
    assert len(cluster["evidence"]) == 5
    assert "https://example.com/pos" not in {e["url"] for e in cluster["evidence"]}


async def test_tk_review_theme_growth_is_backed_by_the_reviews(db_session):
    today = datetime.now(timezone.utc).date()
    for i in range(3):
        db_session.add(
            TkReview(
                source_name="Skytrax",
                url=f"https://skytrax.example/r{i}",
                dedupe_key=f"k{i}",
                review_date=today - timedelta(days=i + 1),
                excerpt="Uçuş üç saat gecikti.",
                sentiment="negative",
                themes=["delay"],
            )
        )
    await db_session.commit()

    recs = await build_recommendations(db_session)
    theme = next(r for r in recs if r["id"] == "tk-theme-delay")
    assert theme["airline_code"] == "TK"
    assert theme["metric"]["value"] == 3
    assert theme["severity"] == "high"  # every review negative
    assert {e["url"] for e in theme["evidence"]} == {
        f"https://skytrax.example/r{i}" for i in range(3)
    }


async def test_upcoming_event_is_its_own_evidence(db_session):
    today = datetime.now(timezone.utc).date()
    db_session.add(
        AviationEvent(
            name="Farnborough Airshow",
            starts=today + timedelta(days=5),
            ends=today + timedelta(days=9),
            city="Farnborough",
            country="United Kingdom",
            region="europe",
            url="https://farnborough.example/",
            summary_tr="Fuar",
            event_type="airshow",
        )
    )
    # Outside the 14-day planning horizon -> not yet actionable.
    db_session.add(
        AviationEvent(
            name="Uzak Fuar",
            starts=today + timedelta(days=40),
            ends=today + timedelta(days=42),
            city="Dubai",
            region="middle-east",
            url="https://far.example/",
            summary_tr="Fuar",
            event_type="airshow",
        )
    )
    await db_session.commit()

    recs = await build_recommendations(db_session)
    events = [r for r in recs if r["category"] == "events"]
    assert len(events) == 1
    assert events[0]["evidence"][0]["url"] == "https://farnborough.example/"
    assert events[0]["metric"]["value"] == 5


async def test_every_recommendation_is_sourced_and_sorted_by_urgency(db_session):
    source = await _source(db_session)
    emirates = await _airline(db_session, "Emirates", "EK")
    for i in range(3):
        await _article(
            db_session, source, url=f"https://example.com/promo{i}", days_ago=i + 1,
            airline=emirates,
        )
    today = datetime.now(timezone.utc).date()
    db_session.add(
        AviationEvent(
            name="Yaklaşan Konferans",
            starts=today + timedelta(days=12),
            ends=today + timedelta(days=13),
            city="Cenevre",
            region="europe",
            url="https://conf.example/",
            summary_tr="Konferans",
            event_type="conference",
        )
    )
    await db_session.commit()

    recs = await build_recommendations(db_session)
    assert len(recs) >= 2
    assert all(r["evidence"] for r in recs)  # the invariant of the module
    assert all(r["title"] and r["rationale"] for r in recs)
    severities = [r["severity"] for r in recs]
    assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s])
    assert recs[0]["id"] == "promo-ek"  # high beats the low-severity calendar item


async def test_momentum_is_withheld_when_the_two_windows_are_not_comparable(db_session):
    """Caught in production right after the enrichment backlog drained: 772
    enriched articles in the last 14 days against 60 in the 14 before turned
    "Emirates 5 -> 153 haber" into a claim about our own ingest history. When
    collection itself changed rate, momentum says nothing at all."""
    from datetime import datetime, timedelta, timezone

    from app.models.article import Article, ArticleEnrichment
    from app.models.entity import ArticleEntity, Entity
    from app.models.source import Source
    from app.services.recommendations import build_recommendations

    now = datetime.now(timezone.utc)
    source = Source(name="Ramp", url="https://example.com/ramp", source_type="rss")
    entity = Entity(entity_type="airline", name="Emirates", code="EK")
    db_session.add_all([source, entity])
    await db_session.flush()

    # One story in the older window, twenty in the recent one -- the shape of a
    # pipeline catching up, not of a carrier making news.
    async def _story(url: str, published_at: datetime) -> None:
        article = Article(
            source_id=source.id, url=url, title="Emirates fare and capacity update",
            raw_content="Emirates moved fares and capacity.", published_at=published_at,
            fetched_at=published_at, content_hash=url, status="enriched",
        )
        db_session.add(article)
        await db_session.flush()
        db_session.add(
            ArticleEnrichment(
                article_id=article.id, headline="Emirates update",
                category="revenue_management",
            )
        )
        db_session.add(ArticleEntity(article_id=article.id, entity_id=entity.id))

    await _story("https://example.com/old", now - timedelta(days=10))
    for i in range(20):
        await _story(f"https://example.com/new{i}", now - timedelta(days=1))
    await db_session.commit()

    items = await build_recommendations(db_session, days=7)
    assert not [i for i in items if i["id"].startswith("momentum-")]
