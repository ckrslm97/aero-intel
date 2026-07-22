"""Round-8 remainder: hub facts joined to live coverage, the country/airport
filters underneath them, and the carrier mentions the news cards draw logos from.
"""
from datetime import datetime, timezone

from app.hubs import HUBS, HUBS_BY_CODE
from app.llm.gazetteer import AIRPORTS
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.source import Source
from app.repositories.article_repository import ArticleRepository
from app.schemas.article import ArticleOut
from app.services.hub_service import MIN_ROUTE_MENTIONS, hub_detail, hub_overview

NOW = datetime.now(timezone.utc)


async def _source(db) -> Source:
    source = Source(name="H", url="https://example.com/h", source_type="rss")
    db.add(source)
    await db.flush()
    return source


async def _article(db, source, slug, entities=(), category="network"):
    article = Article(
        source_id=source.id, url=f"https://example.com/{slug}", title=slug,
        raw_content="body", published_at=NOW, fetched_at=NOW, content_hash=slug,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(ArticleEnrichment(article_id=article.id, headline=slug, category=category))
    for entity in entities:
        db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    await db.flush()
    return article


def test_every_hub_is_one_the_gazetteer_can_actually_recognise():
    """A hub whose code no alias produces renders a permanent zero and looks
    like a bug in the counting rather than a gap in the gazetteer."""
    known = {code for _, code in AIRPORTS.values()}
    missing = sorted(hub.code for hub in HUBS if hub.code not in known)
    assert missing == [], f"no gazetteer alias produces: {missing}"


def test_the_home_carriers_own_hub_is_present():
    assert "IST" in HUBS_BY_CODE
    assert "TK" in HUBS_BY_CODE["IST"].carriers


async def test_hub_overview_counts_real_coverage_and_leaves_the_rest_at_zero(db_session):
    source = await _source(db_session)
    ist = Entity(entity_type="airport", name="Istanbul Airport", code="IST")
    db_session.add(ist)
    await db_session.flush()
    for i in range(3):
        await _article(db_session, source, f"ist-{i}", entities=[ist])
    await db_session.commit()

    overview = await hub_overview(db_session, days=30)
    by_code = {h["code"]: h for h in overview["hubs"]}
    assert by_code["IST"]["article_count"] == 3
    # Never invented: a hub with no coverage says zero.
    assert by_code["SYD"]["article_count"] == 0
    # Busiest first, so the map's biggest markers are at the top of the list.
    assert overview["hubs"][0]["code"] == "IST"
    assert by_code["IST"]["lat"] and by_code["IST"]["lon"]  # the map needs these


async def test_a_single_shared_article_is_not_a_route(db_session):
    """A wire story listing six destinations links them all to each other. The
    map would draw fifteen lines out of one article, none of them a route."""
    source = await _source(db_session)
    ist = Entity(entity_type="airport", name="Istanbul Airport", code="IST")
    lhr = Entity(entity_type="airport", name="London Heathrow", code="LHR")
    db_session.add_all([ist, lhr])
    await db_session.flush()

    await _article(db_session, source, "once", entities=[ist, lhr])
    await db_session.commit()
    assert (await hub_overview(db_session, days=30))["routes"] == []

    for i in range(MIN_ROUTE_MENTIONS - 1):
        await _article(db_session, source, f"again-{i}", entities=[ist, lhr])
    await db_session.commit()

    routes = (await hub_overview(db_session, days=30))["routes"]
    assert [(r["from"], r["to"], r["article_count"]) for r in routes] == [
        ("IST", "LHR", MIN_ROUTE_MENTIONS)
    ]
    # Both ends carry coordinates or the arc cannot be drawn.
    assert routes[0]["from_lat"] and routes[0]["to_lon"]


async def test_hub_detail_reports_the_carriers_the_coverage_is_about(db_session):
    source = await _source(db_session)
    ist = Entity(entity_type="airport", name="Istanbul Airport", code="IST")
    tk = Entity(entity_type="airline", name="Turkish Airlines", code="TK")
    ek = Entity(entity_type="airline", name="Emirates", code="EK")
    db_session.add_all([ist, tk, ek])
    await db_session.flush()

    await _article(db_session, source, "d1", entities=[ist, tk], category="network")
    await _article(db_session, source, "d2", entities=[ist, tk], category="network")
    await _article(db_session, source, "d3", entities=[ist, ek], category="fleet")
    await db_session.commit()

    detail = await hub_detail(db_session, "ist")  # case-insensitive
    assert detail["code"] == "IST"
    assert detail["article_count"] == 3
    # The airlines based here, from the reference table...
    assert detail["carriers"] == ["TK"]
    # ...kept separate from the ones this hub's coverage is actually about.
    assert detail["carriers_seen"][0] == {
        "code": "TK", "name": "Turkish Airlines", "article_count": 2
    }
    assert dict((c["slug"], c["count"]) for c in detail["categories"]) == {
        "network": 2, "fleet": 1
    }
    assert await hub_detail(db_session, "ZZZ") is None


async def test_country_filter_is_narrower_than_region(db_session):
    """A region is nine countries wide. "What is happening in Japan" must not
    return all of Asia."""
    source = await _source(db_session)
    japan = Entity(entity_type="country", name="Japan", code=None)
    india = Entity(entity_type="country", name="India", code=None)
    db_session.add_all([japan, india])
    await db_session.flush()

    await _article(db_session, source, "jp-1", entities=[japan])
    await _article(db_session, source, "jp-2", entities=[japan])
    await _article(db_session, source, "in-1", entities=[india])
    await db_session.commit()

    repo = ArticleRepository(db_session)
    assert await repo.count(country="Japan") == 2
    assert await repo.count(country="japan") == 2  # case-insensitive
    assert await repo.count(country="India") == 1
    assert await repo.count() == 3
    assert {a.title for a in await repo.list_recent(country="Japan")} == {"jp-1", "jp-2"}


async def test_an_article_naming_a_country_twice_is_counted_once(db_session):
    """The filter is a semi-join for the same reason the airline one is: a join
    multiplies rows and LIMIT then pages over the duplicates."""
    source = await _source(db_session)
    france = Entity(entity_type="country", name="France", code=None)
    cdg = Entity(entity_type="airport", name="Paris Charles de Gaulle", code="CDG")
    db_session.add_all([france, cdg])
    await db_session.flush()

    for i in range(4):
        await _article(db_session, source, f"fr-{i}", entities=[france, cdg])
    await db_session.commit()

    repo = ArticleRepository(db_session)
    assert await repo.count(country="France", airport="CDG") == 4
    page = await repo.list_recent(country="France", limit=3)
    assert len(page) == 3
    assert len({a.id for a in page}) == 3


async def test_article_json_carries_the_carriers_a_card_draws_logos_from(db_session):
    source = await _source(db_session)
    tk = Entity(entity_type="airline", name="Turkish Airlines", code="TK")
    ist = Entity(entity_type="airport", name="Istanbul Airport", code="IST")
    db_session.add_all([tk, ist])
    await db_session.flush()
    article = await _article(db_session, source, "card", entities=[tk, ist])
    await db_session.commit()

    # Reload the way a request does -- nothing left in the identity map, so a
    # missing eager load raises instead of quietly succeeding.
    db_session.expunge_all()
    fetched = await ArticleRepository(db_session).get_by_id(article.id)
    out = ArticleOut.model_validate(fetched)

    assert [a.code for a in out.airlines] == ["TK"]
    assert [a.code for a in out.airports] == ["IST"]
    payload = out.model_dump()
    assert payload["airlines"] == [{"name": "Turkish Airlines", "code": "TK"}]
    # The association rows themselves stay out of the JSON.
    assert "entity_links" not in payload
