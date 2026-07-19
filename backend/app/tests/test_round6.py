"""Round-6 surface: RIVALS/ALL airline filters, day-scoped article queries for
the archive, the TK review aggregates behind the BİZ page, the promotion
subcategory, and seed idempotency.
"""
from datetime import date, datetime, timedelta, timezone

from app.llm.heuristic import HeuristicProvider
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.source import Source
from app.models.tk_review import TkReview
from app.repositories.article_repository import ArticleRepository
from app.services.tk_service import review_stats

NOW = datetime.now(timezone.utc)


async def _source(db) -> Source:
    source = Source(name="R6", url="https://example.com/r6", source_type="rss")
    db.add(source)
    await db.flush()
    return source


async def _article(db, source, url, published_at=NOW, airline: Entity | None = None):
    article = Article(
        source_id=source.id, url=url, title="t", raw_content="body",
        published_at=published_at, fetched_at=published_at or NOW,
        content_hash=url, status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(ArticleEnrichment(article_id=article.id, headline="h", category="fleet"))
    if airline is not None:
        db.add(ArticleEntity(article_id=article.id, entity_id=airline.id))
    await db.flush()
    return article


async def test_airline_filter_rivals_all_and_single(db_session):
    source = await _source(db_session)
    ek = Entity(entity_type="airline", name="Emirates", code="EK")
    tk = Entity(entity_type="airline", name="Turkish Airlines", code="TK")
    fr = Entity(entity_type="airline", name="Ryanair", code="FR")
    db_session.add_all([ek, tk, fr])
    await db_session.flush()

    await _article(db_session, source, "https://example.com/a-ek", airline=ek)
    await _article(db_session, source, "https://example.com/a-tk", airline=tk)
    await _article(db_session, source, "https://example.com/a-fr", airline=fr)
    await _article(db_session, source, "https://example.com/a-none")
    await db_session.commit()

    repo = ArticleRepository(db_session)
    # RIVALS = the 9 named rivals only; TK (home carrier) and Ryanair are not rivals.
    assert await repo.count(airline="RIVALS") == 1
    # ALL = any airline mention at all ("Tüm Taşıyıcılar").
    assert await repo.count(airline="ALL") == 3
    assert await repo.count(airline="TK") == 1
    assert await repo.count() == 4


async def test_on_date_filter_uses_fetched_at_when_published_missing(db_session):
    source = await _source(db_session)
    today = NOW.date()
    await _article(db_session, source, "https://example.com/d-today", published_at=NOW)
    await _article(
        db_session, source, "https://example.com/d-old", published_at=NOW - timedelta(days=3)
    )
    # No published_at at all -- must fall back to fetched_at and still count today.
    orphan = Article(
        source_id=source.id, url="https://example.com/d-nodate", title="t",
        raw_content="body", published_at=None, fetched_at=NOW,
        content_hash="nodate", status="enriched",
    )
    db_session.add(orphan)
    await db_session.commit()

    repo = ArticleRepository(db_session)
    assert await repo.count(on_date=today) == 2
    assert await repo.count(on_date=today - timedelta(days=3)) == 1
    listed = await repo.list_recent(on_date=today)
    assert {a.url for a in listed} == {
        "https://example.com/d-today", "https://example.com/d-nodate"
    }

    by_day = await repo.count_by_day(days=7)
    assert by_day[today.isoformat()] == 2
    assert by_day[(today - timedelta(days=3)).isoformat()] == 1


async def test_tk_review_stats_aggregates_themes_and_quotes(db_session):
    db_session.add_all(
        [
            TkReview(
                source_name="Skytrax", url="https://example.com/r1", dedupe_key="k1",
                review_date=date(2026, 7, 1), rating=9, excerpt="Great crew",
                excerpt_tr="Harika ekip", sentiment="positive", themes=["cabin_crew", "food"],
            ),
            TkReview(
                source_name="Skytrax", url="https://example.com/r2", dedupe_key="k2",
                review_date=date(2026, 6, 1), rating=2, excerpt="Lost my bag",
                excerpt_tr="Bagajım kayboldu", sentiment="negative", themes=["baggage"],
            ),
            TkReview(
                source_name="Reddit", url="https://example.com/r3", dedupe_key="k3",
                review_date=None, rating=None, excerpt="Crew was distant",
                excerpt_tr="Ekip mesafeliydi", sentiment="negative", themes=["cabin_crew"],
            ),
        ]
    )
    await db_session.commit()

    stats = await review_stats(db_session)
    assert stats["review_count"] == 3
    # Average over the two rated reviews only: (9 + 2) / 2.
    assert stats["rating"] == {"average": 5.5, "count": 2}
    assert stats["sentiment"] == {"positive": 1, "neutral": 0, "negative": 2}

    themes = {t["slug"]: t for t in stats["themes"]}
    assert themes["cabin_crew"]["count"] == 2
    assert themes["cabin_crew"]["positive"] == 1
    assert themes["cabin_crew"]["negative"] == 1
    # Newest dated review wins the sample-quote slot, in Turkish.
    assert themes["cabin_crew"]["quote"]["excerpt"] == "Harika ekip"
    assert themes["baggage"]["quote"]["excerpt"] == "Bagajım kayboldu"
    assert len(stats["quotes"]) == 3
    assert {s["name"] for s in stats["sources"]} == {"Skytrax", "Reddit"}


async def test_promotion_subcategory_wins_for_campaign_stories():
    heuristic = HeuristicProvider()
    sub = await heuristic.subcategorize(
        "Emirates launches flash sale with promo code for summer",
        "The promotional fare covers selected routes until August.",
        "revenue_management",
    )
    assert sub == "promotion"


async def test_tk_reviews_seed_idempotent(db_session):
    from app.ingest.tk_reviews_seed import REVIEWS, seed_tk_reviews

    first = await seed_tk_reviews(db_session)
    assert first == len(REVIEWS)
    second = await seed_tk_reviews(db_session)
    assert second == 0  # re-run refreshes in place, inserts nothing


async def test_promos_seed_idempotent_and_links_airline(db_session):
    from app.ingest.promos_seed import PROMOS, seed_promos

    pc = Entity(entity_type="airline", name="Pegasus Airlines", code="PC")
    db_session.add(pc)
    await db_session.flush()

    first = await seed_promos(db_session)
    assert first == len(PROMOS)
    assert await seed_promos(db_session) == 0

    repo = ArticleRepository(db_session)
    pc_promos = [p for p in PROMOS if p.airline_code == "PC"]
    # The entity link is what makes the Ana Rakipler chip find these.
    assert await repo.count(airline="PC") == len(pc_promos)


async def test_front_page_prefers_focus_beats_over_generic_aviation(db_session):
    """A mid-scoring revenue-management story must outrank a high-scoring
    general-interest one -- the front page is an RM desk's, not a hobbyist's."""
    from app.services.edition_service import assemble_edition

    source = await _source(db_session)
    today = NOW.date()

    async def _scored(url, category, importance):
        article = Article(
            source_id=source.id, url=url, title="t", raw_content="body",
            published_at=NOW, fetched_at=NOW, content_hash=url, status="enriched",
        )
        db_session.add(article)
        await db_session.flush()
        db_session.add(
            ArticleEnrichment(
                article_id=article.id, headline=url, category=category,
                importance_score=importance,
            )
        )
        await db_session.flush()
        return article

    generic = await _scored("https://example.com/bomber", "general", 0.90)
    rm = await _scored("https://example.com/yield", "revenue_management", 0.70)
    await db_session.commit()

    edition = await assemble_edition(db_session, today)
    top = sorted(
        [ea for ea in edition.articles if ea.section == "top_story"], key=lambda ea: ea.rank
    )
    assert top[0].article_id == rm.id
    assert top[1].article_id == generic.id
