"""The insights page's aggregates must be traceable to rows -- these pin the
arithmetic (momentum deltas, route signals, digest fallback) to known inputs.
"""
from datetime import datetime, timedelta, timezone

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.insight import InsightDigest
from app.services.insights_service import (
    DIGEST_MAX_AGE_DAYS,
    airline_momentum,
    build_daily_digest,
    latest_digest,
    new_route_signals,
)
from app.services.tk_service import latest_tk_digest

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


# --- the digest's age -------------------------------------------------------
#
# `latest_digest` returned the newest row with no age bound at all, so a
# stopped job left last week's paragraph on the paper under a heading that says
# TODAY'S INTELLIGENCE -- beside aggregates recomputed live on every request.
# Both directions are pinned: a current digest is served, a stale one is not,
# and the caller whose surface makes no freshness claim keeps its own.


async def _digest(db, *, days_ago: int, topic: str = "daily", body: str = "gövde"):
    row = InsightDigest(
        # The UTC calendar day, because that is the day both sides of this
        # boundary use: `build_daily_digest` writes `datetime.now(timezone.utc)
        # .date()` and `latest_digest` cuts on it. `date.today()` is the LOCAL
        # day, which after 21:00 in UTC+3 is already tomorrow's -- a row one
        # day younger than this fixture claims, and a test whose edge moves
        # with the hour it is run at.
        digest_date=datetime.now(timezone.utc).date() - timedelta(days=days_ago),
        topic=topic,
        body=body,
        provider="heuristic",
    )
    db.add(row)
    await db.flush()
    return row


async def test_a_digest_from_five_days_ago_is_not_todays_intelligence(db_session):
    await _digest(db_session, days_ago=5)
    assert await latest_digest(db_session) is None


async def test_the_age_bound_is_exactly_where_it_says_it_is(db_session):
    """Both sides of the real edge, which no other test in this block touched.

    The cases below use 0, 1 and 5 days, so DIGEST_MAX_AGE_DAYS could be
    anything from 2 to 4 and every one of them would pass. The boundary is the
    claim -- "two days" is the number the heading TODAY'S INTELLIGENCE is
    allowed to stretch to -- so it is asserted from both sides.
    """
    row = await _digest(db_session, days_ago=DIGEST_MAX_AGE_DAYS)
    served = await latest_digest(db_session)
    assert served is not None and served.id == row.id


async def test_one_day_past_the_bound_is_not_todays_intelligence(db_session):
    await _digest(db_session, days_ago=DIGEST_MAX_AGE_DAYS + 1)
    assert await latest_digest(db_session) is None


async def test_todays_digest_is_served(db_session):
    row = await _digest(db_session, days_ago=0)
    served = await latest_digest(db_session)
    assert served is not None and served.id == row.id


async def test_yesterdays_digest_survives_a_job_that_has_not_run_yet(db_session):
    """The reason the bound is two days and not zero: the job writes in the
    morning, and a reader before it runs must still get the last paragraph."""
    row = await _digest(db_session, days_ago=1)
    served = await latest_digest(db_session)
    assert served is not None and served.id == row.id


async def test_a_stale_digest_does_not_hide_behind_a_fresh_one_of_another_topic(
    db_session,
):
    """The age filter must not become a topic filter by accident: a fresh TK
    digest is no evidence that the daily one ran."""
    await _digest(db_session, days_ago=0, topic="tk_reviews")
    await _digest(db_session, days_ago=9, topic="daily")
    assert await latest_digest(db_session) is None


async def test_the_bound_can_be_lifted_by_a_caller_that_claims_no_freshness(
    db_session,
):
    """`latest_tk_digest`'s case: a manually curated corpus re-collected in
    explicit passes, rendered with its own date and no "today" over it."""
    row = await _digest(db_session, days_ago=40, topic="tk_reviews")
    served = await latest_tk_digest(db_session)
    assert served is not None and served.id == row.id
