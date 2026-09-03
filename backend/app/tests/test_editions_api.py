"""Reading the paper must never publish it.

GET /editions/{date} is the most-linked public URL this product has, and it
used to assemble the day's edition whenever it missed: it ranked every enriched
article of the day, called the summariser, inserted rows and committed -- all
inside an anonymous read. Three failures came out of that one line, and each is
pinned below:

* `editions.edition_date` is UNIQUE. Two readers arriving together both saw
  "no edition", both inserted, and the loser's request died on an
  IntegrityError -- a 500 served to a reader, most likely on the morning of a
  new day when the paper is busiest and the row is genuinely absent.
* Assembly is a job, not a request. It belongs to the cron that already runs it
  (.github/workflows/jobs-daily-edition.yml -> `python -m app.cli daily-if-due`)
  and to POST /editions/{date}/rebuild, which requires an operator token.
* A response that writes cannot be cached. A past day's edition is stable --
  only POST /{date}/rebuild rewrites one -- and the edge could not be told so.

What a miss returns now is a status, not an accident: `not_prepared_yet` for a
day the job has not reached, `not_found` for a past day nobody built. The two
are different facts and the frontend has to be able to say the right one.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import cache_headers
from app.api.v1 import editions as editions_api
from app.core.db import get_db
from app.models.article import Article, ArticleEnrichment
from app.models.edition import Edition, EditionArticle
from app.models.source import Source

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(editions_api.router, prefix="/api/v1")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _published_edition(db, edition_date: date) -> Edition:
    source = Source(
        name=f"E {edition_date}",
        url=f"https://example.com/e-{edition_date}",
        source_type="rss",
    )
    db.add(source)
    await db.flush()
    article = Article(
        source_id=source.id,
        url=f"https://example.com/{edition_date}",
        title="Manşet",
        raw_content="body",
        published_at=NOW,
        fetched_at=NOW,
        content_hash=str(edition_date),
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id, headline="Manşet", category="network", importance_score=0.9
        )
    )
    edition = Edition(
        edition_date=edition_date,
        status="published",
        headline="Manşet",
        executive_summary="Özet",
        articles=[EditionArticle(article_id=article.id, section="top_story", rank=0)],
    )
    db.add(edition)
    await db.commit()
    return edition


async def _edition_count(db) -> int:
    return (await db.execute(select(func.count()).select_from(Edition))).scalar_one()


async def test_an_existing_edition_is_read(client, db_session):
    """The whole point of the endpoint, kept working."""
    await _published_edition(db_session, YESTERDAY)

    async with client as c:
        response = await c.get(f"/api/v1/editions/{YESTERDAY}")

    assert response.status_code == 200
    body = response.json()
    assert body["edition_date"] == str(YESTERDAY)
    assert body["headline"] == "Manşet"
    assert body["sections"][0]["section"] == "top_story"


async def test_a_missing_edition_for_today_says_it_is_not_ready_yet(client, db_session):
    """Not an error and not a lie: the job builds today, so today's paper is
    coming. The reader is told that, and the database is untouched."""
    async with client as c:
        response = await c.get(f"/api/v1/editions/{TODAY}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == editions_api.NOT_PREPARED
    assert "henüz hazırlanmadı" in response.json()["detail"]["message"]
    assert await _edition_count(db_session) == 0


async def test_a_missing_edition_for_a_past_day_says_there_is_none(client, db_session):
    """A day the job never ran for will not gain an edition by being read.
    Saying "henüz hazırlanmadı" about 2020 would be a promise nothing keeps."""
    async with client as c:
        response = await c.get("/api/v1/editions/2020-01-01")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == editions_api.NOT_FOUND
    assert await _edition_count(db_session) == 0


async def test_reading_never_assembles(client, db_session, monkeypatch):
    """The guard against the whole class: no request path may reach the
    assembler, whether the day exists or not. `assemble_edition` stays imported
    for POST /editions/{date}/rebuild, so a future edit could quietly wire it
    back in here -- this fails when it does."""

    async def _explode(*args, **kwargs):
        raise AssertionError("GET /editions/{date} called the assembler")

    monkeypatch.setattr(editions_api, "assemble_edition", _explode)
    await _published_edition(db_session, YESTERDAY)

    async with client as c:
        assert (await c.get(f"/api/v1/editions/{YESTERDAY}")).status_code == 200
        assert (await c.get(f"/api/v1/editions/{TODAY}")).status_code == 404


async def test_two_simultaneous_first_requests_do_not_500(db_session):
    """The original bug, reproduced as it happened: two readers hitting the
    same absent day at the same moment. Both used to race an INSERT against a
    UNIQUE constraint and one of them lost with a 500. Each request gets its
    own session, because that is what two requests are -- one AsyncSession
    cannot back two concurrent tasks either.
    """
    from fastapi import HTTPException, Response

    bind = db_session.bind

    async def _one():
        async with AsyncSession(bind=bind, expire_on_commit=False) as session:
            return await editions_api.get_edition(
                TODAY, response=Response(), db=session
            )

    first, second = await asyncio.gather(_one(), _one(), return_exceptions=True)

    for outcome in (first, second):
        assert isinstance(outcome, HTTPException), f"expected an honest 404, got {outcome!r}"
        assert outcome.status_code == 404
        assert outcome.detail["code"] == editions_api.NOT_PREPARED
    assert await _edition_count(db_session) == 0


async def test_a_past_edition_caches_long_and_todays_only_briefly(client, db_session):
    """A finished day can sit at the edge for a day; today's can still be
    assembled by the job within the minute, so it must not be pinned there."""
    await _published_edition(db_session, YESTERDAY)
    await _published_edition(db_session, TODAY)

    async with client as c:
        past = await c.get(f"/api/v1/editions/{YESTERDAY}")
        today = await c.get(f"/api/v1/editions/{TODAY}")

    assert f"max-age={cache_headers.ARCHIVE}" in past.headers["cache-control"]
    assert f"max-age={editions_api.FRESH}" in today.headers["cache-control"]


async def test_a_past_edition_stays_revalidatable_after_a_rebuild(client, db_session):
    """`immutable` would forbid revalidation for a whole day -- and POST
    /{date}/rebuild reassembles past days, so an operator's fix would reach
    nobody: the URL does not change and there is no ETag to break the tie."""
    await _published_edition(db_session, YESTERDAY)

    async with client as c:
        past = await c.get(f"/api/v1/editions/{YESTERDAY}")

    assert "immutable" not in past.headers["cache-control"]
    assert "stale-while-revalidate" in past.headers["cache-control"]


async def test_every_cached_edition_response_varies_on_origin(client, db_session):
    """A shared cache keys one visitor's CORS answer for everyone otherwise --
    the production incident `public_cache` documents. The past-day branch is
    the one cached for a day, so it is the worst place to omit it."""
    await _published_edition(db_session, YESTERDAY)
    await _published_edition(db_session, TODAY)

    async with client as c:
        past = await c.get(f"/api/v1/editions/{YESTERDAY}")
        today = await c.get(f"/api/v1/editions/{TODAY}")

    assert past.headers["vary"] == "Origin"
    assert today.headers["vary"] == "Origin"
