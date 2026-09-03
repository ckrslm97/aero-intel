"""The data-quality report: what a sweep discovered, extracted, published and
rejected.

The property worth pinning is that the rejection breakdown accounts for every
row exactly once. A row that is both a loyalty page and low-confidence was
rejected for being a loyalty page; counting it twice would make the column sum
to more than the window contains, and a report whose numbers do not add up is
worse than no report, because it gets quoted.
"""
from datetime import datetime, timedelta, timezone

from app.models.campaign_source import CampaignSource
from app.models.promotion import Promotion
from app.models.scrape_run import ScrapeRun
from app.services.campaign_quality import (
    campaign_quality_report,
    render_report_tr,
)

NOW = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


async def _promo(db, *, slug: str, seen_days_ago: int = 1, **kwargs) -> Promotion:
    seen = NOW - timedelta(days=seen_days_ago)
    row = Promotion(
        airline_code="PC",
        airline_name="Pegasus",
        title_tr=slug,
        summary_tr="",
        url=f"https://example.com/{slug}",
        source_name="test",
        detected_at=seen,
        first_seen_at=seen,
        last_seen_at=seen,
        **kwargs,
    )
    db.add(row)
    await db.flush()
    return row


async def _run(db, *, outcome: str, days_ago: int = 1, changed: bool | None = None):
    db.add(
        ScrapeRun(
            carrier_code="PC",
            url="https://example.com/kampanyalar",
            method="static",
            started_at=NOW - timedelta(days=days_ago),
            finished_at=NOW - timedelta(days=days_ago),
            outcome=outcome,
            changed=changed,
        )
    )
    await db.flush()


async def test_the_scrape_log_is_counted_by_outcome(db_session):
    await _run(db_session, outcome="ok", changed=True)
    await _run(db_session, outcome="ok", changed=False)
    await _run(db_session, outcome="blocked")
    await _run(db_session, outcome="timeout")
    report = await campaign_quality_report(db_session, now=NOW)
    assert report.scrape.attempts == 4
    assert report.scrape.ok == 2
    assert report.scrape.changed == 1
    assert report.scrape.blocked == 1
    assert report.scrape.unreadable == 2


async def test_only_the_window_is_counted(db_session):
    await _promo(db_session, slug="bu-hafta", seen_days_ago=2)
    await _promo(db_session, slug="gecen-ay", seen_days_ago=40)
    await _run(db_session, outcome="ok", days_ago=2)
    await _run(db_session, outcome="ok", days_ago=40)
    report = await campaign_quality_report(db_session, days=7, now=NOW)
    assert report.extracted == 1
    assert report.scrape.attempts == 1


async def test_a_published_campaign_is_not_counted_as_rejected(db_session):
    await _promo(
        db_session,
        slug="canli",
        business_class="ACTIVE_CAMPAIGN",
        campaign_kind="CAMPAIGN",
        confidence_band="high",
        sale_starts=TODAY,
        sale_ends=TODAY + timedelta(days=10),
    )
    report = await campaign_quality_report(db_session, now=NOW)
    assert report.published == 1
    assert report.rejected == {}
    assert report.by_kind == {"CAMPAIGN": 1}


async def test_each_rejection_reason_gets_its_own_line(db_session):
    await _promo(db_session, slug="mil", business_class="LOYALTY_PROMOTION")
    await _promo(db_session, slug="bagaj", business_class="PRODUCT_PROMOTION")
    await _promo(db_session, slug="dusuk", confidence_band="low")
    await _promo(
        db_session,
        slug="bitti",
        sale_starts=TODAY - timedelta(days=40),
        sale_ends=TODAY - timedelta(days=10),
    )
    report = await campaign_quality_report(db_session, now=NOW)
    assert report.rejected == {
        "business_class:LOYALTY_PROMOTION": 1,
        "business_class:PRODUCT_PROMOTION": 1,
        "low_confidence": 1,
        "expired": 1,
    }
    assert report.published == 0


async def test_a_row_is_counted_under_exactly_one_reason(db_session):
    """Loyalty AND low-confidence AND expired: rejected for being a loyalty
    page, which is the rule that would have fired first."""
    await _promo(
        db_session,
        slug="hepsi",
        business_class="LOYALTY_PROMOTION",
        confidence_band="low",
        sale_starts=TODAY - timedelta(days=40),
        sale_ends=TODAY - timedelta(days=10),
    )
    report = await campaign_quality_report(db_session, now=NOW)
    assert report.rejected == {"business_class:LOYALTY_PROMOTION": 1}
    # The other two facts are still reported, as facts rather than as reasons.
    assert report.low_confidence == 1
    assert report.expired == 1


async def test_the_columns_add_up_to_the_rows_in_the_window(db_session):
    await _promo(db_session, slug="canli", business_class="ACTIVE_CAMPAIGN")
    await _promo(db_session, slug="mil", business_class="LOYALTY_PROMOTION")
    await _promo(db_session, slug="dusuk", confidence_band="low")
    report = await campaign_quality_report(db_session, now=NOW)
    # `duplicate` is deliberately not a rejection reason (see the service), so
    # it is excluded from the identity the way the service excludes it.
    rejected = sum(
        count for key, count in report.rejected.items() if key != "duplicate"
    )
    assert report.published + rejected == report.extracted


async def test_a_merged_campaign_is_reported_as_absorbed_not_rejected(db_session):
    row = await _promo(db_session, slug="iki-kaynak", business_class="ACTIVE_CAMPAIGN")
    for tier in ("official", "secondary"):
        db_session.add(
            CampaignSource(
                promotion_id=row.id,
                url=f"{row.url}#{tier}",
                source_name=tier,
                source_tier=tier,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
    await db_session.flush()
    report = await campaign_quality_report(db_session, now=NOW)
    assert report.rejected["duplicate"] == 1
    # ...and the surviving row is still one of the published ones.
    assert report.published == 1


async def test_the_rendered_report_is_turkish_and_names_its_blind_spot(db_session):
    await _promo(db_session, slug="mil", business_class="LOYALTY_PROMOTION")
    await _run(db_session, outcome="blocked")
    text = render_report_tr(await campaign_quality_report(db_session, now=NOW))
    assert "Kampanya veri kalitesi raporu" in text
    assert "İş sınıfı — Sadakat Kampanyası" in text
    # The honesty line: rejections that never became rows cannot be counted,
    # and the unreadable-page count is the upper bound on them.
    assert "okunamayan sayfa" in text
