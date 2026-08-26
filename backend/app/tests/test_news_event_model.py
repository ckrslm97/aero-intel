"""The v2 schema, exercised against a real database.

The point of these is not that SQLAlchemy can insert rows. It is that the two
things the schema exists to express -- a durable veto, and a cluster whose
classification lives on the event rather than on each article -- actually
survive a write and a read.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.article import Article
from app.models.curated import IataIndicator
from app.models.news_event import NewsEvent
from app.models.source import Source
from app.pipeline.confidence import ConfidenceInput, score


async def _source(db, name="Havayolu 101", trust=0.75) -> Source:
    source = Source(name=name, url=f"https://{name}.example/feed", source_type="rss", trust_weight=trust)
    db.add(source)
    await db.flush()
    return source


async def _article(db, source, url, title) -> Article:
    article = Article(
        source_id=source.id,
        url=url,
        title=title,
        fetched_at=datetime.now(timezone.utc),
        content_hash=url[-16:],
        status="enriched",
    )
    db.add(article)
    await db.flush()
    return article


async def test_one_event_holds_many_articles_and_carries_the_classification(db_session):
    """The Jin Air case: one merger reported by two outlets used to be two rows
    classified twice, landing in `finance/equity` and `general`."""
    source = await _source(db_session)
    now = datetime.now(timezone.utc)

    event = NewsEvent(
        slug="jin-air-air-busan-air-seoul-merger",
        title_tr="Jin Air, Air Busan ve Air Seoul birleşiyor",
        category="finance",
        subcategory="equity",
        first_seen=now,
        last_seen=now,
        article_count=2,
    )
    db_session.add(event)
    await db_session.flush()

    english = await _article(db_session, source, "https://a.example/1", "Jin Air ... to merge")
    german = await _article(db_session, source, "https://a.example/2", "Jin Air ... fusionieren")
    event.primary_article_id = english.id
    for article in (english, german):
        article.event_id = event.id
    await db_session.commit()

    loaded = (
        await db_session.execute(select(NewsEvent).where(NewsEvent.slug == event.slug))
    ).scalar_one()
    articles = (
        await db_session.execute(select(Article).where(Article.event_id == loaded.id))
    ).scalars().all()

    assert len(articles) == 2
    # One classification, on the event -- not one per article.
    assert (loaded.category, loaded.subcategory) == ("finance", "equity")
    assert loaded.primary_article_id == english.id


async def test_the_veto_is_durable_and_distinguishable_from_never_looked(db_session):
    """`risk_assessed_at` with a null risk_type is the classifier saying "no".

    The old pipeline could not express this: a null risk_type meant either "not
    a risk" or "the call failed", and both fell through to a keyword heuristic.
    That is how `Film Notları: The Bombing of Pan Am 103` became a high-severity
    attack in the United Kingdom.
    """
    now = datetime.now(timezone.utc)
    vetoed = NewsEvent(
        slug="film-notlari-pan-am-103",
        title_tr="Film Notları: The Bombing of Pan Am 103",
        first_seen=now,
        last_seen=now,
        risk_assessed_at=now,
        not_applicable_reasons={"risk": "entertainment_coverage"},
    )
    never_looked = NewsEvent(
        slug="henuz-degerlendirilmedi", first_seen=now, last_seen=now
    )
    db_session.add_all([vetoed, never_looked])
    await db_session.commit()

    # Both have no risk_type. Only one of them has been answered.
    assert vetoed.risk_type is None and never_looked.risk_type is None
    assert vetoed.risk_assessed_at is not None
    assert never_looked.risk_assessed_at is None
    assert vetoed.not_applicable_reasons["risk"] == "entertainment_coverage"

    # The query the pipeline runs to find work: unassessed only. A vetoed event
    # is never re-asked, so nothing can overturn the "no".
    pending = (
        await db_session.execute(
            select(NewsEvent).where(NewsEvent.risk_assessed_at.is_(None))
        )
    ).scalars().all()
    assert [event.slug for event in pending] == ["henuz-degerlendirilmedi"]


async def test_confidence_detail_round_trips_as_jsonb(db_session):
    """The breakdown is stored, not recomputed, so a judgement stays explicable
    after the weights move on."""
    now = datetime.now(timezone.utc)
    result = score(ConfidenceInput("agency", 0.85, 3, 3, True, 3))
    event = NewsEvent(
        slug="guven-kirilimi",
        first_seen=now,
        last_seen=now,
        confidence_score=result.score,
        confidence_band=result.band,
        confidence_detail=result.as_detail(),
    )
    db_session.add(event)
    await db_session.commit()

    loaded = (
        await db_session.execute(select(NewsEvent).where(NewsEvent.slug == "guven-kirilimi"))
    ).scalar_one()
    assert loaded.confidence_band == "high"
    assert loaded.confidence_detail["components"]["source_tier"] == pytest.approx(0.75)
    # The weights are captured with the score, which is the point.
    assert loaded.confidence_detail["weights"]["source_tier"] == pytest.approx(0.30)


async def test_deleting_an_article_does_not_delete_its_event(db_session):
    """ON DELETE SET NULL both ways: raw articles are prunable, the event and
    its history are not collateral."""
    source = await _source(db_session)
    now = datetime.now(timezone.utc)
    event = NewsEvent(slug="kalici-olay", first_seen=now, last_seen=now)
    db_session.add(event)
    await db_session.flush()

    article = await _article(db_session, source, "https://a.example/9", "Bir haber")
    article.event_id = event.id
    event.primary_article_id = article.id
    await db_session.commit()

    await db_session.delete(article)
    await db_session.commit()
    await db_session.refresh(event)

    assert event.slug == "kalici-olay"
    assert event.primary_article_id is None


async def test_forecast_and_actual_cannot_be_confused(db_session):
    """`kind` is the column that stops a projection being read as a
    measurement. The owner asked for both on Kokpit; they must never share a
    card."""
    db_session.add_all(
        [
            IataIndicator(
                metric="net_profit",
                value=23.0,
                unit="USD bn",
                kind="forecast",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 12, 31),
                period_label_tr="2026",
                publication_date=date(2026, 6, 7),
                source_url="https://www.iata.org/en/pressroom/2026-releases/06-07-...",
                interpretation_tr="Önceki 41 milyar dolarlık projeksiyonun yaklaşık yarısı.",
            ),
            IataIndicator(
                metric="rpk_growth",
                value=2.1,
                unit="%",
                kind="actual",
                period_start=date(2026, 6, 1),
                period_end=date(2026, 6, 30),
                period_label_tr="Haziran 2026",
                publication_date=date(2026, 7, 30),
                source_url="https://www.iata.org/en/pressroom/2026-releases/07-30-...",
            ),
        ]
    )
    await db_session.commit()

    forecasts = (
        await db_session.execute(
            select(IataIndicator).where(IataIndicator.kind == "forecast")
        )
    ).scalars().all()
    assert [row.metric for row in forecasts] == ["net_profit"]
    # Every published figure carries the link the reader checks it against.
    for row in forecasts:
        assert row.source_url.startswith("https://")


async def test_superseded_event_is_marked_not_deleted(db_session):
    """A re-cluster merges events; a shared link must still resolve."""
    now = datetime.now(timezone.utc)
    event = NewsEvent(slug="yerini-aldi", first_seen=now, last_seen=now)
    db_session.add(event)
    await db_session.commit()

    event.superseded_at = now + timedelta(hours=1)
    await db_session.commit()

    still_there = (
        await db_session.execute(select(NewsEvent).where(NewsEvent.slug == "yerini-aldi"))
    ).scalar_one()
    assert still_there.superseded_at is not None
