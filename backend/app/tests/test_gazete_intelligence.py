"""The Gazete's new read surface: hour windows, source tiers, and the list
behind "Doğrulayan N kaynak".

Three things are worth pinning down here, and each one was a decision rather
than an implementation detail:

**A time window is one window.** `hours`, `days` and `date` all answer the same
question, and a request carrying two of them has no defensible answer -- so it
is rejected instead of silently resolved to whichever the code checks first.

**Tier is the EFFECTIVE tier.** Source.tier is nullable and, in the database
this was written against, null on every row; a filter reading the raw column
would have matched nothing and looked like "no news". The API resolves the same
ladder the Risk Radarı's chronology already uses, in SQL, from the same table.

**The corroboration count now has a list under it.** The number has been on the
drawer since it shipped with nothing behind it. The endpoint must return
exactly the group app/pipeline/verify.py counted -- not a similar one.

Driven over HTTP rather than by calling the path functions, because half of
what is being tested is the query string: repeated `?tier=` values, the 422 on
two windows at once, and the parsing of `hours` all live in FastAPI's layer.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import articles as articles_api
from app.core.db import get_db
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.pipeline.clustering import tier_for_source
from app.schemas.article import SourceOut
from app.taxonomy import SOURCE_TIERS, effective_source_tier

NOW = datetime.now(timezone.utc)


@asynccontextmanager
async def _client(db_session):
    app = FastAPI()
    app.include_router(articles_api.router, prefix="/api/v1")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _source(db, name, *, trust_weight=0.7, tier=None) -> Source:
    source = Source(
        name=name,
        url=f"https://example.com/{name}",
        source_type="rss",
        trust_weight=trust_weight,
        tier=tier,
    )
    db.add(source)
    await db.flush()
    return source


async def _article(
    db, source, slug, *, published_at=NOW, category="general", duplicate_of=None
) -> Article:
    article = Article(
        source_id=source.id,
        url=f"https://example.com/a/{slug}",
        title=slug,
        raw_content="body",
        published_at=published_at,
        fetched_at=published_at,
        content_hash=slug,
        status="enriched",
        is_duplicate=duplicate_of is not None,
        duplicate_of_id=duplicate_of.id if duplicate_of else None,
    )
    db.add(article)
    await db.flush()
    db.add(ArticleEnrichment(article_id=article.id, category=category))
    await db.flush()
    return article


# --- the hour window ------------------------------------------------------

async def test_hours_keeps_only_the_last_n_hours(db_session):
    source = await _source(db_session, "hours-feed")
    await _article(db_session, source, "fresh", published_at=NOW - timedelta(hours=2))
    await _article(db_session, source, "stale", published_at=NOW - timedelta(hours=30))
    await db_session.commit()

    async with _client(db_session) as client:
        body = (await client.get("/api/v1/articles?hours=6")).json()

    assert [item["title"] for item in body["items"]] == ["fresh"]
    assert body["total"] == 1


async def test_hours_and_days_together_are_refused(db_session):
    """6 hours or 30 days? The intersection is 6 hours, which would make the
    `days` the caller sent a lie. Neither answer is defensible, so neither is
    given."""
    async with _client(db_session) as client:
        response = await client.get("/api/v1/articles?hours=6&days=30")

    assert response.status_code == 422
    assert "mutually exclusive" in response.json()["detail"]


async def test_hours_and_date_together_are_refused(db_session):
    async with _client(db_session) as client:
        response = await client.get("/api/v1/articles?hours=6&date=2026-08-01")

    assert response.status_code == 422


async def test_a_lone_window_is_still_accepted(db_session):
    """The guard must not make the three existing callers illegal: the Gazete
    sends `days`, the archive sends `date`, and most callers send neither."""
    source = await _source(db_session, "lone-window")
    await _article(db_session, source, "any")
    await db_session.commit()

    async with _client(db_session) as client:
        for query in ("", "?days=30", "?hours=48", f"?date={NOW.date().isoformat()}"):
            response = await client.get(f"/api/v1/articles{query}")
            assert response.status_code == 200, query


async def test_counts_take_the_same_hour_window_as_the_list(db_session):
    """A badge counting rows the filtered list will not render is a badge that
    lies -- the reason /counts mirrors every filter the list has."""
    source = await _source(db_session, "hours-counts")
    await _article(
        db_session, source, "c-fresh", category="fleet", published_at=NOW - timedelta(hours=1)
    )
    await _article(
        db_session, source, "c-stale", category="fleet", published_at=NOW - timedelta(hours=48)
    )
    await db_session.commit()

    async with _client(db_session) as client:
        body = (await client.get("/api/v1/articles/counts?hours=6")).json()

    assert body == {"fleet": 1}


# --- source tiers ---------------------------------------------------------

def test_the_effective_tier_matches_what_the_risk_radar_already_shows():
    """Two callers, one ladder. A card badging an outlet "Ajans" while the same
    outlet reads "Düzenleyici" three pages over is the failure this prevents."""

    class FakeSource:
        def __init__(self, tier, trust_weight):
            self.tier = tier
            self.trust_weight = trust_weight

    for tier, weight in [(None, 0.95), (None, 0.8), (None, 0.6), (None, 0.2), ("official", 0.1)]:
        assert effective_source_tier(tier, weight) == tier_for_source(FakeSource(tier, weight))


def test_an_undeclared_source_is_never_promoted_to_official():
    """Being an airline's or a regulator's own newsroom is a fact about who
    publishes the feed, not something a trust weight can be read backwards
    into."""
    assert effective_source_tier(None, 1.0) != "official"
    assert effective_source_tier("official", 0.1) == "official"


def test_source_out_always_carries_a_tier():
    """Never null, so a card badging it needs no fallback of its own."""
    undeclared = SourceOut.model_validate(
        Source(id=uuid.uuid4(), name="n", url="u", category="other", trust_weight=0.95, tier=None)
    )
    declared = SourceOut.model_validate(
        Source(
            id=uuid.uuid4(), name="n", url="u", category="other", trust_weight=0.5, tier="official"
        )
    )
    assert undeclared.tier == "regulator"
    assert declared.tier == "official"
    # The raw column stays off the wire: two tier fields would invite a client
    # to badge with the wrong one.
    assert "declared_tier" not in declared.model_dump()


async def test_tier_filter_uses_the_trust_weight_fallback(db_session):
    """Source.tier is null on every row seeded before that column existed. A
    filter reading the raw column would match nothing and render as "no news"."""
    regulator = await _source(db_session, "faa-like", trust_weight=0.95)
    aggregator = await _source(db_session, "wire-like", trust_weight=0.2)
    await _article(db_session, regulator, "official-story")
    await _article(db_session, aggregator, "wire-story")
    await db_session.commit()

    async with _client(db_session) as client:
        body = (await client.get("/api/v1/articles?tier=regulator")).json()

    assert [item["title"] for item in body["items"]] == ["official-story"]
    assert body["items"][0]["source"]["tier"] == "regulator"


async def test_tier_filter_prefers_a_declared_tier_over_the_bucket(db_session):
    declared = await _source(db_session, "airline-newsroom", trust_weight=0.5, tier="official")
    await _article(db_session, declared, "press-release")
    await db_session.commit()

    async with _client(db_session) as client:
        kept = (await client.get("/api/v1/articles?tier=official")).json()
        dropped = (await client.get("/api/v1/articles?tier=trade")).json()

    assert len(kept["items"]) == 1
    assert dropped["items"] == []


async def test_several_tiers_are_a_union(db_session):
    regulator = await _source(db_session, "reg", trust_weight=0.95)
    agency = await _source(db_session, "agc", trust_weight=0.8)
    aggregator = await _source(db_session, "agg", trust_weight=0.2)
    await _article(db_session, regulator, "r")
    await _article(db_session, agency, "a")
    await _article(db_session, aggregator, "g")
    await db_session.commit()

    async with _client(db_session) as client:
        body = (await client.get("/api/v1/articles?tier=regulator&tier=agency")).json()

    assert sorted(item["title"] for item in body["items"]) == ["a", "r"]


async def test_an_unknown_tier_is_refused_rather_than_returning_nothing(db_session):
    """An empty page and a typo look identical on screen."""
    async with _client(db_session) as client:
        response = await client.get("/api/v1/articles?tier=oficial")

    assert response.status_code == 422
    assert "oficial" in response.json()["detail"]


def test_every_tier_the_api_accepts_is_one_the_ladder_can_produce():
    for tier in SOURCE_TIERS:
        assert effective_source_tier(tier, 0.5) == tier


# --- the corroborating-sources list ---------------------------------------

async def test_sources_returns_the_group_confidence_counted(db_session):
    """Exactly `id == x OR duplicate_of_id == x` -- the same set
    app/pipeline/verify.py counts, so the list can never disagree with the
    number the drawer printed above it."""
    reuters = await _source(db_session, "reuters-like", trust_weight=0.95)
    trade = await _source(db_session, "trade-like", trust_weight=0.6)
    blog = await _source(db_session, "blog-like", trust_weight=0.3)

    canonical = await _article(
        db_session, reuters, "canonical", published_at=NOW - timedelta(hours=5)
    )
    await _article(
        db_session, trade, "dupe-1", published_at=NOW - timedelta(hours=3), duplicate_of=canonical
    )
    await _article(
        db_session, blog, "dupe-2", published_at=NOW - timedelta(hours=1), duplicate_of=canonical
    )
    # An unrelated story from the same outlet must not join the group.
    await _article(db_session, trade, "unrelated")
    await db_session.commit()

    async with _client(db_session) as client:
        rows = (await client.get(f"/api/v1/articles/{canonical.id}/sources")).json()

    assert [row["source_name"] for row in rows] == ["reuters-like", "trade-like", "blog-like"]
    assert [row["is_primary"] for row in rows] == [True, False, False]
    assert rows[0]["source_tier"] == "regulator"
    assert rows[2]["source_tier"] == "aggregator"


async def test_sources_are_ordered_oldest_first(db_session):
    """A chronology, so it reads as "who ran it first, who followed"."""
    fast = await _source(db_session, "fast-wire")
    slow = await _source(db_session, "slow-wire")
    canonical = await _article(db_session, fast, "chron", published_at=NOW - timedelta(hours=1))
    await _article(
        db_session, slow, "chron-late", published_at=NOW - timedelta(hours=9), duplicate_of=canonical
    )
    await db_session.commit()

    async with _client(db_session) as client:
        rows = (await client.get(f"/api/v1/articles/{canonical.id}/sources")).json()

    assert [row["title"] for row in rows] == ["chron-late", "chron"]


async def test_a_single_sourced_story_returns_itself(db_session):
    """One row, not zero: the story was reported by somebody."""
    source = await _source(db_session, "lonely")
    article = await _article(db_session, source, "alone")
    await db_session.commit()

    async with _client(db_session) as client:
        rows = (await client.get(f"/api/v1/articles/{article.id}/sources")).json()

    assert len(rows) == 1
    assert rows[0]["is_primary"] is True


async def test_an_unknown_article_is_a_404_not_an_empty_list(db_session):
    """`[]` would render as "no source corroborated this", which is a claim
    about the story rather than about the id."""
    async with _client(db_session) as client:
        response = await client.get(f"/api/v1/articles/{uuid.uuid4()}/sources")

    assert response.status_code == 404
