"""/search: the Turkish text is in the index, the total is a real count, and
the two filters actually filter.

Three separate failures, all of them invisible from the outside:

**A Turkish paper could not be searched in Turkish.** The vector held only the
English title, headline and summary, so "yakıt" matched nothing while "fuel"
worked. The Turkish pair is indexed now -- still with the `english`
configuration, so matching is VERBATIM and that limitation is asserted here
rather than left to be discovered.

**`total` was the page size.** A query with four hundred hits reported "20
sonuç", which reads as a fact about the corpus and was a fact about the LIMIT.

**There were no filters at all.** Category and days, sharing one clause with
the list so the count cannot describe a different set of rows.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, update

from app.api.v1 import search as search_api
from app.core.db import get_db
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source

NOW = datetime.now(timezone.utc)


@asynccontextmanager
async def _client(db_session):
    app = FastAPI()
    app.include_router(search_api.router, prefix="/api/v1")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _indexed(
    db, source, slug, *, text, category="general", published_at=NOW, headline_tr=None
):
    """An article whose search_vector is written the way the pipeline writes
    it -- app/pipeline/search_indexing.py, same to_tsvector call."""
    article = Article(
        source_id=source.id,
        url=f"https://example.com/s/{slug}",
        title=text,
        raw_content="body",
        published_at=published_at,
        fetched_at=published_at,
        content_hash=slug,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id, category=category, headline=text, headline_tr=headline_tr
        )
    )
    indexed = f"{text} {headline_tr or ''}".strip()
    await db.execute(
        update(Article)
        .where(Article.id == article.id)
        .values(search_vector=func.to_tsvector("english", indexed))
    )
    await db.flush()
    return article


async def _source(db, name):
    source = Source(name=name, url=f"https://example.com/{name}", source_type="rss")
    db.add(source)
    await db.flush()
    return source


async def test_a_turkish_word_finds_the_article_it_is_in(db_session):
    """The whole point: this returned nothing at all before the Turkish pair
    was indexed."""
    source = await _source(db_session, "tr-search")
    await _indexed(
        db_session,
        source,
        "fuel",
        text="Carrier hedges fuel costs for the winter",
        headline_tr="Taşıyıcı kış için yakıt maliyetini hedge etti",
    )
    await db_session.commit()

    async with _client(db_session) as client:
        body = (await client.get("/api/v1/search?q=yakıt")).json()

    assert [item["title"] for item in body["items"]] == [
        "Carrier hedges fuel costs for the winter"
    ]


async def test_turkish_matching_is_verbatim_and_that_is_documented(db_session):
    """`english` does not stem Turkish, so an inflected form does not match.
    Asserted so the limitation is a known property of the shipped feature
    rather than a bug report later -- a real Turkish text-search configuration
    is a migration with an operational prerequisite, and a separate change."""
    source = await _source(db_session, "tr-stem")
    await _indexed(
        db_session, source, "stem", text="Fuel", headline_tr="Havayolu yakıt aldı"
    )
    await db_session.commit()

    async with _client(db_session) as client:
        exact = (await client.get("/api/v1/search?q=yakıt")).json()
        inflected = (await client.get("/api/v1/search?q=yakıtın")).json()

    assert len(exact["items"]) == 1
    assert inflected["items"] == []


async def test_total_counts_the_matches_not_the_page(db_session):
    source = await _source(db_session, "totals")
    for i in range(5):
        await _indexed(db_session, source, f"cap-{i}", text=f"Capacity report number {i}")
    await db_session.commit()

    async with _client(db_session) as client:
        body = (await client.get("/api/v1/search?q=capacity&limit=2")).json()

    assert len(body["items"]) == 2
    assert body["total"] == 5


async def test_a_short_page_needs_no_count_query(db_session):
    """A page shorter than the limit IS the whole result set -- same skip the
    article list makes, and the total has to stay correct through it."""
    source = await _source(db_session, "short-page")
    await _indexed(db_session, source, "single", text="Slot allocation decided")
    await db_session.commit()

    async with _client(db_session) as client:
        body = (await client.get("/api/v1/search?q=slot&limit=20")).json()

    assert body["total"] == 1


async def test_category_filter_narrows_both_list_and_total(db_session):
    source = await _source(db_session, "cat-filter")
    await _indexed(db_session, source, "rm", text="Pricing review", category="revenue_management")
    await _indexed(db_session, source, "fl", text="Pricing of the fleet deal", category="fleet")
    await db_session.commit()

    async with _client(db_session) as client:
        body = (
            await client.get("/api/v1/search?q=pricing&category=revenue_management&limit=1")
        ).json()

    assert [item["title"] for item in body["items"]] == ["Pricing review"]
    assert body["total"] == 1


async def test_days_filter_excludes_older_matches(db_session):
    source = await _source(db_session, "days-filter")
    await _indexed(db_session, source, "recent", text="Yield strategy today")
    await _indexed(
        db_session,
        source,
        "old",
        text="Yield strategy long ago",
        published_at=NOW - timedelta(days=90),
    )
    await db_session.commit()

    async with _client(db_session) as client:
        body = (await client.get("/api/v1/search?q=yield&days=7")).json()

    assert [item["title"] for item in body["items"]] == ["Yield strategy today"]


async def test_an_unknown_category_is_refused(db_session):
    async with _client(db_session) as client:
        response = await client.get("/api/v1/search?q=x&category=not_a_category")

    assert response.status_code == 422
