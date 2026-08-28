from datetime import date, datetime, timedelta, timezone

from app.models.article import Article
from app.models.news_event import NewsEvent
from app.models.promotion import Promotion
from app.models.source import Source
from app.repositories.kpi_repository import KpiRepository
from app.services.data_quality_service import (
    NON_FARE_BUSINESS_CLASSES,
    REVIEW_QUEUE_CEILING,
    STALE_EXPIRED_AFTER_DAYS,
    check_data_quality,
)
from app.services.kpi_service import LIVE_FX_PAIRS

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


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


# --- PR8 campaign invariants -------------------------------------------------


def _promo(slug: str, **fields) -> Promotion:
    defaults = dict(
        airline_code="TK",
        airline_name="Turkish Airlines",
        title_tr=slug,
        url=f"https://example.com/{slug}",
        source_name="thy.com",
        confidence_band="high",
        detected_at=NOW,
        sale_starts=TODAY - timedelta(days=2),
        sale_ends=TODAY + timedelta(days=5),
    )
    defaults.update(fields)
    return Promotion(**defaults)


async def test_catches_every_non_fare_business_class_reaching_the_timeline(db_session):
    """One seeded row per non-fare class -- the check is derived from the
    taxonomy, so a class added there must be caught without editing it."""
    for slug in NON_FARE_BUSINESS_CLASSES:
        db_session.add(_promo(f"non-fare-{slug.lower()}", business_class=slug))
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    leaked = [v for v in violations if v.check == "non_fare_campaign_published"]
    assert len(leaked) == len(NON_FARE_BUSINESS_CLASSES)


async def test_an_active_campaign_class_is_not_flagged_as_non_fare(db_session):
    db_session.add(_promo("real-campaign", business_class="ACTIVE_CAMPAIGN"))
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert not any(v.check == "non_fare_campaign_published" for v in violations)


async def test_a_superseded_non_fare_row_is_not_flagged(db_session):
    """`superseded_at` is the retirement mechanism; a retired row is already
    off every read path and must not keep the daily job red."""
    row = _promo("retired-product-promo", business_class="PRODUCT_PROMOTION")
    row.superseded_at = NOW
    db_session.add(row)
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert not any(v.check == "non_fare_campaign_published" for v in violations)


async def test_catches_an_ancient_expired_campaign_still_publishable(db_session):
    closed = TODAY - timedelta(days=STALE_EXPIRED_AFTER_DAYS + 10)
    db_session.add(
        _promo(
            "ancient",
            sale_starts=closed - timedelta(days=7),
            sale_ends=closed,
        )
    )
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    stale = [v for v in violations if v.check == "stale_expired_campaign"]
    assert len(stale) == 1
    assert "still publishable" in stale[0].detail


async def test_a_recently_expired_campaign_is_not_a_violation(db_session):
    """A campaign that closed last week is shown as "Süresi doldu" on purpose
    -- what a rival just stopped selling is intelligence, not a leak."""
    closed = TODAY - timedelta(days=STALE_EXPIRED_AFTER_DAYS - 1)
    db_session.add(
        _promo("recent", sale_starts=closed - timedelta(days=7), sale_ends=closed)
    )
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert not any(v.check == "stale_expired_campaign" for v in violations)


async def test_a_long_closed_sale_whose_travel_window_is_still_open_is_not_stale(db_session):
    """BOOKING_CLOSED_TRAVEL_ACTIVE, not EXPIRED: booking is over but the
    competitor's capacity is still committed, so the row belongs on the
    timeline. The check recomputes status rather than filtering on sale_ends
    in SQL exactly so this case can't be mistaken for a stale row."""
    db_session.add(
        _promo(
            "booking-closed",
            sale_starts=TODAY - timedelta(days=120),
            sale_ends=TODAY - timedelta(days=90),
            travel_starts=TODAY - timedelta(days=10),
            travel_ends=TODAY + timedelta(days=30),
        )
    )
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert not any(v.check == "stale_expired_campaign" for v in violations)


async def test_a_fixed_today_makes_the_stale_check_deterministic(db_session):
    db_session.add(
        _promo("fixed-clock", sale_starts=date(2026, 1, 1), sale_ends=date(2026, 1, 10))
    )
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    # Five days after the close: still legitimately on the timeline.
    early = await check_data_quality(db_session, today=date(2026, 1, 15))
    assert not any(v.check == "stale_expired_campaign" for v in early)

    # A year later: nothing retired it.
    late = await check_data_quality(db_session, today=date(2027, 1, 15))
    assert any(v.check == "stale_expired_campaign" for v in late)


async def test_catches_a_typed_campaign_with_no_classification_reason(db_session):
    db_session.add(
        _promo("unexplained", campaign_type="FLASH_SALE", classification_reason=None)
    )
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert any(v.check == "unexplained_campaign_classification" for v in violations)


async def test_a_typed_campaign_that_states_its_reason_is_not_flagged(db_session):
    db_session.add(
        _promo(
            "explained",
            campaign_type="FLASH_SALE",
            classification_reason="Satış dönemi ve indirim açıkça belirtilmiş.",
        )
    )
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert not any(v.check == "unexplained_campaign_classification" for v in violations)


async def test_an_untyped_legacy_row_needs_no_classification_reason(db_session):
    """Legacy rows predate the v2 columns entirely -- demanding a reason from
    them would flag every row written before PR1."""
    db_session.add(_promo("legacy", campaign_type=None, classification_reason=None))
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert not any(v.check == "unexplained_campaign_classification" for v in violations)


async def test_catches_a_review_queue_past_the_ceiling(db_session):
    for i in range(REVIEW_QUEUE_CEILING + 1):
        db_session.add(_promo(f"review-{i}", review_required=True))
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    backlog = [v for v in violations if v.check == "review_queue_backlog"]
    # The size is the finding, so it is one violation and not one per row.
    assert len(backlog) == 1
    assert str(REVIEW_QUEUE_CEILING + 1) in backlog[0].detail


async def test_a_review_queue_at_the_ceiling_is_not_a_violation(db_session):
    for i in range(REVIEW_QUEUE_CEILING):
        db_session.add(_promo(f"review-ok-{i}", review_required=True))
    await db_session.commit()
    await _seed_fresh_fx(db_session)

    violations = await check_data_quality(db_session)
    assert not any(v.check == "review_queue_backlog" for v in violations)


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
