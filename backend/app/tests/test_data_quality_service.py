from datetime import datetime, timedelta, timezone

from app.models.article import Article
from app.models.news_event import NewsEvent
from app.models.promotion import Promotion
from app.models.source import Source
from app.repositories.kpi_repository import KpiRepository
from app.services.data_quality_service import check_data_quality
from app.services.kpi_service import LIVE_FX_PAIRS

NOW = datetime.now(timezone.utc)


async def _source(db, language=None) -> Source:
    source = Source(name="H", url="https://example.com/h", source_type="rss")
    db.add(source)
    await db.flush()
    return source


async def _article(db, source, slug, language="tr"):
    article = Article(
        source_id=source.id, url=f"https://example.com/{slug}", title=slug,
        raw_content="body", published_at=NOW, fetched_at=NOW, content_hash=slug,
        status="enriched", language=language,
    )
    db.add(article)
    await db.flush()
    return article


async def _event(db, *, slug, primary_article_id, **fields):
    event = NewsEvent(
        slug=slug,
        title_tr=fields.pop("title_tr", slug),
        primary_article_id=primary_article_id,
        first_seen=NOW,
        last_seen=NOW,
        is_published=fields.pop("is_published", True),
        confidence_band=fields.pop("confidence_band", "high"),
        **fields,
    )
    db.add(event)
    await db.flush()
    return event


async def _seed_fresh_fx(db):
    repo = KpiRepository(db)
    for metric_key, *_rest in LIVE_FX_PAIRS:
        repo.record(metric_key, 1.0, "X", "test", False, NOW)
    await db.commit()


async def test_a_clean_database_has_no_violations(db_session):
    await _seed_fresh_fx(db_session)
    assert await check_data_quality(db_session) == []


async def test_catches_a_published_event_in_a_disallowed_language(db_session):
    source = await _source(db_session)
    article = await _article(db_session, source, "de-article", language="de")
    await db_session.commit()
    await _event(db_session, slug="de-event", primary_article_id=article.id)
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert any(v.check == "published_language" for v in violations)


async def test_a_published_event_with_no_language_on_its_article_is_caught(db_session):
    """A null language is exactly as unverifiable as a wrong one -- the check
    doesn't give it a pass just because it's absent rather than foreign."""
    source = await _source(db_session)
    article = await _article(db_session, source, "no-lang", language=None)
    await db_session.commit()
    await _event(db_session, slug="no-lang-event", primary_article_id=article.id)
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert any(v.check == "published_language" for v in violations)


async def test_catches_a_low_band_event_marked_published(db_session):
    source = await _source(db_session)
    article = await _article(db_session, source, "low-band")
    await db_session.commit()
    await _event(db_session, slug="low-band-event", primary_article_id=article.id, confidence_band="low")
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert any(v.check == "below_threshold_published" for v in violations)


async def test_catches_a_published_event_with_no_primary_article(db_session):
    await _event(db_session, slug="orphan-event", primary_article_id=None)
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert any(v.check == "sourceless_event" for v in violations)


async def test_catches_a_published_campaign_with_no_sale_window(db_session):
    db_session.add(
        Promotion(
            airline_code="TK",
            airline_name="Turkish Airlines",
            title_tr="Tarihsiz kampanya",
            url="https://example.com/promo",
            source_name="thy.com",
            confidence_band="high",
            detected_at=NOW,
            sale_starts=None,
            sale_ends=None,
        )
    )
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert any(v.check == "dateless_campaign" for v in violations)


async def test_a_campaign_with_only_a_sale_end_is_not_flagged(db_session):
    """sale_starts OR sale_ends is enough -- the same completeness rule
    build_promotion() already uses for `has_sale_window`."""
    db_session.add(
        Promotion(
            airline_code="TK",
            airline_name="Turkish Airlines",
            title_tr="Bitiş tarihli kampanya",
            url="https://example.com/promo-end-only",
            source_name="thy.com",
            confidence_band="high",
            detected_at=NOW,
            sale_starts=None,
            sale_ends=NOW.date(),
        )
    )
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert not any(v.check == "dateless_campaign" for v in violations)


async def test_catches_a_stale_fx_reading(db_session):
    repo = KpiRepository(db_session)
    stale = NOW - timedelta(hours=48)
    for metric_key, *_rest in LIVE_FX_PAIRS:
        repo.record(metric_key, 1.0, "X", "test", False, stale)
    await db_session.commit()

    violations = await check_data_quality(db_session)
    fx_violations = [v for v in violations if v.check == "fx_freshness"]
    assert len(fx_violations) == len(LIVE_FX_PAIRS)


async def test_catches_a_missing_fx_pair_entirely(db_session):
    # No FX rows seeded at all.
    violations = await check_data_quality(db_session)
    fx_violations = [v for v in violations if v.check == "fx_freshness"]
    assert len(fx_violations) == len(LIVE_FX_PAIRS)
    assert all("no observation" in v.detail for v in fx_violations)


async def test_superseded_and_low_confidence_rows_are_ignored_everywhere(db_session):
    """Superseded events/campaigns and low-band events were never meant to be
    live -- the checks must not flag what the pipeline already excluded from
    publication on purpose."""
    source = await _source(db_session)
    article = await _article(db_session, source, "superseded-de", language="de")
    await db_session.commit()
    superseded = await _event(db_session, slug="superseded-event", primary_article_id=article.id)
    superseded.superseded_at = NOW
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert violations == []
