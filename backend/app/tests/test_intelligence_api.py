"""`min_intelligence` on the article endpoints, and the old path left intact.

The frontend still sends `min_importance` and will keep doing so until a
separate PR moves it over. Changing what that parameter means under a deployed
client is how a filter silently starts answering a different question, so the
regression half of this file matters as much as the new half.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_db
from app.main import app
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.repositories.article_repository import ArticleRepository

NOW = datetime.now(timezone.utc) - timedelta(hours=1)


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


async def _seed(db):
    """Three articles whose two scores disagree on purpose.

    `intelligence_score` and `importance_score` are deliberately inverted, so a
    filter reading the wrong column returns the wrong set rather than
    accidentally the right one.
    """
    source = Source(
        name="IntelSrc", url="https://example.com/is", source_type="rss", trust_weight=0.7
    )
    db.add(source)
    await db.flush()

    rows = [
        # slug,           intelligence, importance, category
        ("critical", 0.90, 0.10, "revenue_management"),
        ("middling", 0.50, 0.50, "airport"),
        ("routine", 0.10, 0.90, "revenue_management"),
        ("unscored", None, 0.95, "events"),
    ]
    for slug, intelligence, importance, category in rows:
        article = Article(
            source_id=source.id, url=f"https://example.com/is/{slug}", title=slug,
            raw_content="body", published_at=NOW, fetched_at=NOW,
            content_hash=slug, status="enriched",
        )
        db.add(article)
        await db.flush()
        db.add(
            ArticleEnrichment(
                article_id=article.id, headline=slug, summary="s", category=category,
                intelligence_score=intelligence, importance_score=importance,
                rm_impact=0.8 if slug == "critical" else None,
                demand_impact=0.6 if slug == "critical" else None,
                capacity_impact=0.4 if slug == "critical" else None,
                score_detail={"score": intelligence, "components": {}, "weights": {}}
                if intelligence is not None
                else None,
            )
        )
    await db.commit()
    return source


async def test_min_intelligence_filters_on_the_new_column(client, db_session):
    await _seed(db_session)
    response = await client.get("/api/v1/articles", params={"min_intelligence": 0.6})
    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == ["critical"]


async def test_an_unscored_article_is_excluded_rather_than_treated_as_zero(
    client, db_session
):
    """NULL means "never scored", which is not a claim that it is unimportant.

    A filter whose whole purpose is "only the critical stories" must not show a
    row the system has not actually judged -- even one whose old
    importance_score is the highest of the set.
    """
    await _seed(db_session)
    response = await client.get("/api/v1/articles", params={"min_intelligence": 0.0})
    titles = [item["title"] for item in response.json()["items"]]
    assert "unscored" not in titles
    assert set(titles) == {"critical", "middling", "routine"}


async def test_the_old_min_importance_path_is_unchanged(client, db_session):
    """The regression guard. The frontend still sends this parameter.

    `routine` has importance 0.90 in revenue_management (FOCUS_BONUS 0.30) and
    `unscored` has 0.95 in events (bonus 0.08), so both clear a 1.0
    focus-weighted floor while `critical` (importance 0.10) does not -- the
    exact inversion of the intelligence ordering above. If this ever starts
    returning the intelligence answer, the two parameters have been conflated.

    `unscored` passing here is the point rather than an accident: it has no
    intelligence_score at all, so it is invisible to `min_intelligence` and
    fully visible to `min_importance`. The two filters are answering different
    questions, which is exactly why both still exist.
    """
    await _seed(db_session)
    response = await client.get("/api/v1/articles", params={"min_importance": 1.0})
    assert sorted(item["title"] for item in response.json()["items"]) == [
        "routine",
        "unscored",
    ]


async def test_both_floors_may_be_sent_together_and_they_and(client, db_session):
    await _seed(db_session)
    response = await client.get(
        "/api/v1/articles", params={"min_intelligence": 0.6, "min_importance": 1.0}
    )
    # `critical` clears intelligence but not weighted importance; `routine` the
    # reverse. The intersection is empty, and that is the correct answer.
    assert response.json()["items"] == []


async def test_the_enrichment_payload_carries_the_new_fields(client, db_session):
    await _seed(db_session)
    response = await client.get("/api/v1/articles", params={"min_intelligence": 0.6})
    enrichment = response.json()["items"][0]["enrichment"]
    assert enrichment["intelligence_score"] == 0.9
    assert enrichment["rm_impact"] == 0.8
    assert enrichment["demand_impact"] == 0.6
    assert enrichment["capacity_impact"] == 0.4
    assert enrichment["score_detail"]["score"] == 0.9
    # The old column is still on the wire for the frontend that reads it.
    assert enrichment["importance_score"] == 0.1


async def test_null_impact_columns_serialise_as_null_not_zero(client, db_session):
    """A "0" badge on an article nobody scored is a claim the system never made."""
    await _seed(db_session)
    response = await client.get("/api/v1/articles", params={"min_intelligence": 0.4})
    by_title = {item["title"]: item["enrichment"] for item in response.json()["items"]}
    assert by_title["middling"]["rm_impact"] is None
    assert by_title["middling"]["intelligence_score"] == 0.5


async def test_counts_endpoint_mirrors_the_list(client, db_session):
    """A badge counting rows the filtered list would never render is a badge
    that lies."""
    await _seed(db_session)
    counts = (
        await client.get("/api/v1/articles/counts", params={"min_intelligence": 0.6})
    ).json()
    assert counts == {"revenue_management": 1}

    listed = (
        await client.get("/api/v1/articles", params={"min_intelligence": 0.6})
    ).json()
    assert sum(counts.values()) == len(listed["items"])


async def test_source_facets_accept_the_same_floor(client, db_session):
    await _seed(db_session)
    facets = (
        await client.get(
            "/api/v1/articles/source-facets", params={"min_intelligence": 0.6}
        )
    ).json()
    assert [(f["name"], f["count"]) for f in facets] == [("IntelSrc", 1)]


@pytest.mark.parametrize("value", [-0.1, 1.1])
async def test_an_out_of_range_floor_is_rejected(client, db_session, value):
    response = await client.get("/api/v1/articles", params={"min_intelligence": value})
    assert response.status_code == 422


async def test_repository_count_agrees_with_the_list(db_session):
    """`total` drives "load more"; it must count what the list returns."""
    await _seed(db_session)
    repo = ArticleRepository(db_session)
    items = await repo.list_recent(limit=50, min_intelligence=0.4)
    total = await repo.count(min_intelligence=0.4)
    assert total == len(items) == 2
