"""`detected_at` is OUR clock, and only ours.

The extractor stamped `detected_at` with the ARTICLE's `published_at`, while
`models/promotion.py` documents the column as our first sighting and three
surfaces read it that way -- the "Yeni" badge, the 48-hour banner and
`GET /promotions/new-count`. A campaign extracted this morning out of a
three-week-old trade report was therefore born three weeks old: it could never
be new on the one day anyone needed to see it, and `new-count` -- the number
Kokpit's "Rakip Aktivitesi" tile prints -- silently missed what changed today.

Both directions are pinned here: the sighting is fresh (positive), the
reporter's date is kept but kept OUT of the sighting (negative), and a re-read
does not re-date a row that was already seen.
"""
from datetime import datetime, timedelta, timezone

from fastapi import Response
from sqlalchemy import select

from app.api.v1.promotions import count_new_promotions, list_promotions
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.promotion import NEW_WINDOW_HOURS, Promotion
from app.models.source import Source
from app.pipeline.promotions import extract_promotions

_PAYLOAD = (
    '{"discount_pct": 40, "sale_starts": "2026-09-01", "sale_ends": "2026-09-30",'
    ' "travel_starts": null, "travel_ends": null, "markets": "Avrupa"}'
)


def _generator():
    async def generate(prompt):
        return _PAYLOAD

    return generate


async def _fixture(db):
    source = Source(name="PG", url="https://example.com/pg", source_type="rss")
    airline = Entity(entity_type="airline", name="Pegasus Airlines", code="PC")
    db.add_all([source, airline])
    await db.flush()
    return source, airline


async def _stale_article(db, source, airline, *, published_at, slug="eski-haber"):
    """A campaign article the press filed weeks ago and we are reading now."""
    article = Article(
        source_id=source.id,
        url=f"https://example.com/pg/{slug}",
        title=f"{slug} kampanya %40 indirim",
        raw_content="Kampanya kapsaminda %40 indirim.",
        published_at=published_at,
        fetched_at=published_at,
        content_hash=slug,
        status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id,
            headline=slug,
            summary="s",
            category="revenue_management",
            subcategory="promotion",
        )
    )
    db.add(ArticleEntity(article_id=article.id, entity_id=airline.id))
    await db.flush()
    return article


async def _only_promotion(db) -> Promotion:
    rows = (await db.execute(select(Promotion))).scalars().all()
    assert len(rows) == 1
    return rows[0]


async def test_a_campaign_from_an_old_article_is_detected_now(db_session, monkeypatch):
    """THE bug. Three weeks of reporting age must not age the sighting."""
    monkeypatch.setattr("app.llm.factory.get_raw_generator", _generator)
    source, airline = await _fixture(db_session)
    published = datetime.now(timezone.utc) - timedelta(days=21)
    await _stale_article(db_session, source, airline, published_at=published)
    await db_session.commit()

    before = datetime.now(timezone.utc)
    await extract_promotions(db_session)
    after = datetime.now(timezone.utc)

    row = await _only_promotion(db_session)
    assert before <= row.detected_at <= after, "the sighting is when the run looked"
    assert row.detected_at != published


async def test_the_reporters_date_is_kept_but_kept_out_of_the_sighting(
    db_session, monkeypatch
):
    """The article's date is not thrown away -- it moves to its own column,
    where it answers "how old is the reporting" instead of "how old is this to
    us"."""
    monkeypatch.setattr("app.llm.factory.get_raw_generator", _generator)
    source, airline = await _fixture(db_session)
    published = datetime(2026, 7, 4, 9, 30, tzinfo=timezone.utc)
    await _stale_article(db_session, source, airline, published_at=published)
    await db_session.commit()

    await extract_promotions(db_session)

    row = await _only_promotion(db_session)
    assert row.source_published_at == published
    assert row.detected_at > published


async def test_an_old_article_can_still_produce_a_new_campaign(db_session, monkeypatch):
    """The consequence the badge and the Kokpit tile are made of: a campaign
    found today counts as found today, whatever the article's date said."""
    monkeypatch.setattr("app.llm.factory.get_raw_generator", _generator)
    source, airline = await _fixture(db_session)
    await _stale_article(
        db_session,
        source,
        airline,
        published_at=datetime.now(timezone.utc) - timedelta(hours=NEW_WINDOW_HOURS * 3),
    )
    await db_session.commit()

    await extract_promotions(db_session)

    payload = await count_new_promotions(response=Response(), db=db_session)
    assert payload["count"] == 1, "an old article, a campaign we only just saw"
    assert payload["airline_codes"] == ["PC"]


async def test_a_re_read_does_not_re_date_the_sighting(db_session, monkeypatch):
    """First sight is kept. A rescan re-reads the same article and must not
    hand the row a newer `detected_at` -- 'first seen' would otherwise mean
    'last scanned', and the 48h banner would re-fire on every sweep."""
    monkeypatch.setattr("app.llm.factory.get_raw_generator", _generator)
    source, airline = await _fixture(db_session)
    await _stale_article(
        db_session,
        source,
        airline,
        published_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    await db_session.commit()

    await extract_promotions(db_session)
    first_sighting = (await _only_promotion(db_session)).detected_at

    await extract_promotions(db_session, rescan=True)
    assert (await _only_promotion(db_session)).detected_at == first_sighting


async def test_both_clocks_reach_the_page(db_session, monkeypatch):
    """Serialised, or the drawer cannot tell "found this morning" from "found
    this morning in a three-week-old report"."""
    monkeypatch.setattr("app.llm.factory.get_raw_generator", _generator)
    source, airline = await _fixture(db_session)
    published = datetime(2026, 7, 4, 9, 30, tzinfo=timezone.utc)
    await _stale_article(db_session, source, airline, published_at=published)
    await db_session.commit()
    await extract_promotions(db_session)

    rows = await list_promotions(response=Response(), db=db_session)
    assert len(rows) == 1
    assert rows[0].source_published_at == published
    assert rows[0].detected_at > published


async def test_a_row_from_a_source_with_no_date_says_so(db_session, monkeypatch):
    """NULL means "the source stated no date". It must not fall back to the
    sighting, which would re-create the fused column this split undid."""
    monkeypatch.setattr("app.llm.factory.get_raw_generator", _generator)
    source, airline = await _fixture(db_session)
    article = await _stale_article(
        db_session, source, airline, published_at=datetime.now(timezone.utc)
    )
    article.published_at = None
    await db_session.commit()

    await extract_promotions(db_session)

    row = await _only_promotion(db_session)
    assert row.source_published_at is None
    assert row.detected_at is not None
