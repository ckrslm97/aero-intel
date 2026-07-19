"""The insights page's aggregates must be traceable to rows -- these pin the
arithmetic (momentum deltas, route signals, digest fallback) to known inputs.
"""
from datetime import datetime, timedelta, timezone

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.services.insights_service import (
    airline_momentum,
    build_daily_digest,
    new_route_signals,
)

NOW = datetime.now(timezone.utc)


async def _article(db, source, *, url, published_at, category="fleet", subcategory=None,
                   region=None, corroborating=1, headline_tr=None):
    article = Article(
        source_id=source.id,
        url=url,
        title="t",
        raw_content="body",
        published_at=published_at,
        fetched_at=published_at,
        content_hash=url,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id,
            headline="Headline",
            headline_tr=headline_tr,
            category=category,
            subcategory=subcategory,
            region=region,
            corroborating_source_count=corroborating,
            confidence_score=0.8,
        )
    )
    await db.flush()
    return article


async def test_airline_momentum_computes_week_over_week_delta(db_session):
    from app.models.source import Source

    source = Source(name="S", url="https://example.com/feed", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    emirates = Entity(entity_type="airline", name="Emirates", code="EK")
    db_session.add(emirates)
    await db_session.flush()

    # 3 mentions this week, 1 mention last week -> delta +2.
    for i, days_ago in enumerate([1, 2, 3, 9]):
        article = await _article(
            db_session, source, url=f"https://example.com/{i}",
            published_at=NOW - timedelta(days=days_ago),
        )
        db_session.add(ArticleEntity(article_id=article.id, entity_id=emirates.id))
    await db_session.commit()

    movers = await airline_momentum(db_session)
    ek = next(m for m in movers if m["code"] == "EK")
    assert (ek["current"], ek["previous"], ek["delta"]) == (3, 1, 2)


async def test_new_route_signals_group_by_region_with_cited_articles(db_session):
    from app.models.source import Source

    source = Source(name="S2", url="https://example.com/feed2", source_type="rss")
    db_session.add(source)
    await db_session.flush()
    lufthansa = Entity(entity_type="airline", name="Lufthansa", code="LH")
    db_session.add(lufthansa)
    await db_session.flush()

    articles = []
    for i, region in enumerate(["europe", "europe", "asia"]):
        articles.append(
            await _article(
                db_session, source, url=f"https://example.com/nr{i}", published_at=NOW,
                category="network", subcategory="new_route", region=region,
                headline_tr=f"Yeni hat {i}",
            )
        )
    db_session.add(ArticleEntity(article_id=articles[0].id, entity_id=lufthansa.id))
    # A network article that is NOT a new route must not count.
    await _article(
        db_session, source, url="https://example.com/nr-x", published_at=NOW,
        category="network", subcategory="cancellation", region="europe",
    )
    await db_session.commit()

    signals = await new_route_signals(db_session)
    europe = signals[0]
    assert (europe["region"], europe["count"]) == ("europe", 2)
    assert len(europe["articles"]) == 2
    # Every signal is citable: Turkish headline preferred, source named, URL kept.
    first = next(a for a in europe["articles"] if a["url"] == "https://example.com/nr0")
    assert first["headline"] == "Yeni hat 0"
    assert first["source_name"] == "S2"
    assert first["airlines"] == ["LH"]
    asia = next(s for s in signals if s["region"] == "asia")
    assert asia["count"] == 1


async def test_digest_falls_back_to_deterministic_turkish_without_llm(db_session, monkeypatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")

    digest = await build_daily_digest(db_session)
    assert digest.provider == "heuristic"
    assert digest.body  # never empty

    # Same-day rebuild upserts, not duplicates.
    again = await build_daily_digest(db_session)
    assert again.id == digest.id
    get_settings.cache_clear()
