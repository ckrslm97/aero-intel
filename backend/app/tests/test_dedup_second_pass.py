"""The second dedup pass: the same story filed by two outlets in two languages.

MinHash+LSH compares title and body together, so cross-language coverage of one
story never becomes a candidate. Measured on production, a Spanish and an
English report of the same Arajet announcement scored 0.10 on their original
titles and 0.62 once both had been translated into Turkish -- the newspaper was
listing them as two separate stories.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.source import Source
from app.pipeline.dedup import (
    _mentions_conflict,
    deduplicate_translated_articles,
)

NOW = datetime.now(timezone.utc)


def test_different_orders_are_not_the_same_story():
    """Caught in testing against production: two Riyadh Air orders announced at
    the same show, phrased almost identically, are different events."""
    assert _mentions_conflict(
        "Riyadh Air firms up order for six more Airbus A350-1000s at Farnborough",
        "Riyadh Air firms up order for 28 Boeing 787s, adds 787-10 at Farnborough",
    )


def test_different_counterparties_are_not_the_same_story():
    """Also caught in testing: a CAE training deal merged into a HAVELSAN
    simulator order -- same airline, same week, two different vendors."""
    assert _mentions_conflict(
        "Turkish Airlines Signs Multi-Year Agreement With CAE - TRIPURA STAR NEWS",
        "Turkish Airlines Signs Agreement with HAVELSAN for 12 Flight Simulators",
    )


def test_the_same_story_from_two_outlets_is_not_a_conflict():
    """Publisher credits and shared acronyms must not read as a clash."""
    assert not _mentions_conflict(
        "Turkish Airlines joins SAFFA Fund to accelerate sustainable aviation",
        "Turkish Airlines Joins SAFFA Fund - Business Wire",
    )
    assert not _mentions_conflict(
        "Unison and Lufthansa Technik Sign 15-Year CFM LEAP MRO Agreement - AvWeek",
        "FIA 2026: Unison and Lufthansa Technik agree 15-year CFM LEAP MRO deal",
    )


async def _story(db, source, entity, url, title, headline_tr, published_at=NOW):
    article = Article(
        source_id=source.id, url=url, title=title, raw_content=title,
        published_at=published_at, fetched_at=published_at,
        content_hash=url, status="enriched",
    )
    db.add(article)
    await db.flush()
    db.add(
        ArticleEnrichment(
            article_id=article.id, headline=title, headline_tr=headline_tr,
            category="revenue_management", translated_at=published_at,
        )
    )
    db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    await db.flush()
    return article


async def test_cross_language_duplicates_merge_on_the_turkish_headline(db_session):
    """The production case: Spanish and English coverage of one announcement.
    Original titles overlap 0.10; the Turkish translations overlap 0.62."""
    source = Source(name="S", url="https://example.com/f", source_type="rss")
    db_session.add(source)
    entity = Entity(entity_type="airline", name="Arajet", code="DM")
    db_session.add_all([source, entity])
    await db_session.flush()

    canonical = await _story(
        db_session, source, entity, "https://example.com/es",
        "Arajet incorpora nuevos servicios adicionales con tecnologia Arcube",
        "Arajet, Arcube teknolojisi ile yolcular için yeni ek hizmetler sunmaya başladı",
        NOW - timedelta(hours=2),
    )
    later = await _story(
        db_session, source, entity, "https://example.com/en",
        "Arajet introduces new ancillary services for passengers with Arcube technology",
        "Arajet, Arcube teknolojisi ile yolcular için yeni ek hizmetler tanıtıyor",
    )
    await db_session.commit()

    assert await deduplicate_translated_articles(db_session) == 1

    rows = {
        row.id: row
        for row in (await db_session.execute(select(Article))).scalars()
    }
    # The earlier version stays canonical; the later one points at it.
    assert rows[canonical.id].is_duplicate is False
    assert rows[later.id].is_duplicate is True
    assert rows[later.id].duplicate_of_id == canonical.id


async def test_unrelated_stories_about_one_airline_stay_separate(db_session):
    """Grouping by entity must not merge everything an airline did that day."""
    source = Source(name="S2", url="https://example.com/f2", source_type="rss")
    entity = Entity(entity_type="airline", name="Arajet", code="DM")
    db_session.add_all([source, entity])
    await db_session.flush()

    await _story(
        db_session, source, entity, "https://example.com/a",
        "Arajet introduces new ancillary services for passengers with Arcube technology",
        "Arajet, Arcube teknolojisi ile yolcular için yeni ek hizmetler tanıtıyor",
    )
    await _story(
        db_session, source, entity, "https://example.com/b",
        "Arajet taps StandardAero for LEAP-1B engine MRO on its Boeing 737 MAX fleet",
        "Arajet, Boeing 737 MAX filosunda LEAP-1B motorlarının bakımı için StandardAero ile anlaştı",
    )
    await db_session.commit()

    assert await deduplicate_translated_articles(db_session) == 0


async def test_a_pair_straddling_utc_midnight_still_merges(db_session):
    """The bucket is a bound on the comparison set, not a claim about dates.

    Two outlets covering one announcement two hours apart used to become
    invisible to this pass whenever those two hours crossed UTC midnight --
    permanently, not just on the run that happened to be late. The newspaper
    then listed the same story twice, which is the one outcome this function
    exists to prevent. This fixture pins the times either side of a midnight
    rather than relying on when the suite runs, so it fails for the reason it
    names and not because of the hour.
    """
    source = Source(name="S", url="https://example.com/f2", source_type="rss")
    entity = Entity(entity_type="airline", name="Arajet", code="DM")
    db_session.add_all([source, entity])
    await db_session.flush()

    midnight = datetime.now(timezone.utc).replace(hour=0, minute=30, second=0, microsecond=0)
    await _story(
        db_session, source, entity, "https://example.com/es-mid",
        "Arajet incorpora nuevos servicios adicionales con tecnologia Arcube",
        "Arajet, Arcube teknolojisi ile yolcular için yeni ek hizmetler sunmaya başladı",
        midnight - timedelta(hours=2),
    )
    await _story(
        db_session, source, entity, "https://example.com/en-mid",
        "Arajet introduces new ancillary services for passengers with Arcube technology",
        "Arajet, Arcube teknolojisi ile yolcular için yeni ek hizmetler tanıtıyor",
        midnight,
    )
    await db_session.commit()

    assert await deduplicate_translated_articles(db_session) == 1


async def test_two_days_apart_is_still_two_stories(db_session):
    """The negative half: widening the comparison by ONE day must not widen it
    by two. A story and its re-telling 48 hours later are inside the 3-day
    cutoff but outside the pair this pass is allowed to make."""
    source = Source(name="S", url="https://example.com/f3", source_type="rss")
    entity = Entity(entity_type="airline", name="Arajet", code="DM")
    db_session.add_all([source, entity])
    await db_session.flush()

    anchor = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    await _story(
        db_session, source, entity, "https://example.com/es-far",
        "Arajet incorpora nuevos servicios adicionales con tecnologia Arcube",
        "Arajet, Arcube teknolojisi ile yolcular için yeni ek hizmetler sunmaya başladı",
        anchor - timedelta(days=2),
    )
    await _story(
        db_session, source, entity, "https://example.com/en-far",
        "Arajet introduces new ancillary services for passengers with Arcube technology",
        "Arajet, Arcube teknolojisi ile yolcular için yeni ek hizmetler tanıtıyor",
        anchor,
    )
    await db_session.commit()

    assert await deduplicate_translated_articles(db_session) == 0
