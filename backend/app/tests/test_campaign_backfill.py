"""The retroactive business-class pass over rows the v1 pipeline published.

What is actually being asserted here is the promise the module makes to the
reader of the live page: a loyalty, product, evergreen or news row leaves the
published surface, says in Turkish why, leaves an audit trail, and takes its
unread alerts with it -- while a genuine dated fare campaign is not touched at
all beyond having its class filled in.

The last of those is the one worth the most attention. A cleanup that also
retires real campaigns is not a cleanup, it is an outage, and the only thing
standing between the two is the rulepack. So the surviving row here is
deliberately a realistic one (a dated Pegasus sale with a rate), and the test
asserts field by field that nothing about it moved.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.campaign_alert import CampaignAlert
from app.models.campaign_version import CampaignVersion
from app.models.promotion import Promotion
from app.pipeline.campaign_backfill import backfill_campaign_classes

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


def _promotion(url: str, title: str, summary: str = "", **fields) -> Promotion:
    """A legacy row: every campaign-intelligence column NULL, as the v1
    pipeline left them."""
    base = dict(
        airline_code="TK",
        airline_name="Turkish Airlines",
        title_tr=title,
        summary_tr=summary,
        url=url,
        source_name="example.com",
        detected_at=NOW - timedelta(days=30),
    )
    base.update(fields)
    return Promotion(**base)


def _fare_campaign() -> Promotion:
    """The row that must survive: dated, rated, and unmistakably a ticket sale."""
    return _promotion(
        "https://www.flypgs.com/kampanya/kktc",
        "Pegasus'tan Kuzey Kıbrıs uçuşlarında %40 indirim",
        "Kampanya kapsamındaki uçuşlarda geçerli. Hemen bilet al.",
        airline_code="PC",
        airline_name="Pegasus Airlines",
        discount_pct=40,
        sale_starts=TODAY,
        sale_ends=TODAY + timedelta(days=10),
        travel_starts=TODAY + timedelta(days=20),
        travel_ends=TODAY + timedelta(days=90),
    )


async def _versions(db, promotion: Promotion) -> list[CampaignVersion]:
    return list(
        (
            await db.execute(
                select(CampaignVersion)
                .where(CampaignVersion.promotion_id == promotion.id)
                .order_by(CampaignVersion.version_no)
            )
        ).scalars().all()
    )


async def test_retires_loyalty_product_evergreen_and_news_rows(db_session):
    """The four shapes that made it onto the live page: a credit-card points
    transfer, a baggage promo, a standing student rate and an article about
    someone else's campaign."""
    loyalty = _promotion(
        "https://example.com/citi-thankyou",
        "Citi ThankYou Puanlarınızı Turkish Airlines Miles&Smiles'a Aktarın",
        "Transfer oranı ve kampanya koşulları.",
    )
    product = _promotion(
        "https://example.com/bagaj",
        "THY'de ek bagaj hakkı kampanyası",
        "Uçuşlarınızda ek bagaj hakkı indirimli.",
    )
    evergreen = _promotion(
        "https://example.com/ogrenci",
        "Öğrencilere özel indirimli uçuş fırsatı",
        "Öğrenci belgesi ile her uçuşta geçerli.",
    )
    news = _promotion(
        "https://example.com/haber",
        "Qatar Airways yeni bir kampanya duyurdu",
        "Havayolunun açıklamasına göre kampanya yakında başlayacak.",
    )
    db_session.add_all([loyalty, product, evergreen, news])
    await db_session.commit()

    result = await backfill_campaign_classes(db_session)

    assert result["scanned"] == 4
    assert result["retired_by_class"] == {
        "PRODUCT_PROMOTION": 1,
        "LOYALTY_PROMOTION": 1,
        "EVERGREEN_OFFER": 1,
        "NEWS_ONLY": 1,
    }
    assert result["enriched"] == 0
    assert result["unchanged"] == 0

    expected = {
        loyalty: "LOYALTY_PROMOTION",
        product: "PRODUCT_PROMOTION",
        evergreen: "EVERGREEN_OFFER",
        news: "NEWS_ONLY",
    }
    for row, business_class in expected.items():
        await db_session.refresh(row)
        assert row.business_class == business_class
        assert row.superseded_at is not None
        # The reason is the rulepack's own Turkish sentence, not a generic
        # "backfill" note -- an unexplained retirement is unappealable.
        assert row.classification_reason
        assert "kampanya" in row.classification_reason.lower()


async def test_retirement_is_recorded_as_a_version(db_session):
    loyalty = _promotion(
        "https://example.com/avios",
        "Buy Qatar Airways Avios With 50% Bonus",
        "Bonus mil satın alma kampanyası.",
    )
    db_session.add(loyalty)
    await db_session.commit()

    await backfill_campaign_classes(db_session)

    versions = await _versions(db_session, loyalty)
    assert len(versions) == 1
    changed = versions[0].changed_fields
    assert set(changed) == {"business_class", "classification_reason", "superseded_at"}
    assert changed["business_class"]["previous"] is None
    assert changed["business_class"]["new"] == "LOYALTY_PROMOTION"
    # The transition off the published surface is the part that has to be
    # readable a year from now: it went from null (served) to a timestamp.
    assert changed["superseded_at"]["previous"] is None
    assert changed["superseded_at"]["new"] is not None
    await db_session.refresh(loyalty)
    assert loyalty.last_changed_at is not None


async def test_open_alerts_on_a_retired_row_are_acknowledged(db_session):
    """The EXPIRING/EXPIRED alerts the generator produced for these rows were
    noise. They are marked read rather than deleted -- the alert history is
    evidence of what the old pipeline was announcing."""
    loyalty = _promotion(
        "https://example.com/miles",
        "Miles&Smiles mil satın alma kampanyası",
        "Mil satın alın.",
    )
    survivor = _fare_campaign()
    db_session.add_all([loyalty, survivor])
    await db_session.flush()

    noisy = CampaignAlert(
        promotion_id=loyalty.id,
        alert_type="EXPIRING",
        priority="HIGH",
        title_tr="Mil kampanyası bitmek üzere",
        dedupe_key=f"{loyalty.id}:EXPIRING:2026-01-01",
    )
    already_read = CampaignAlert(
        promotion_id=loyalty.id,
        alert_type="EXPIRED",
        priority="MEDIUM",
        title_tr="Mil kampanyası sona erdi",
        acknowledged_at=NOW - timedelta(days=1),
        dedupe_key=f"{loyalty.id}:EXPIRED:2026-01-01",
    )
    genuine = CampaignAlert(
        promotion_id=survivor.id,
        alert_type="NEW",
        priority="HIGH",
        title_tr="Yeni kampanya — Pegasus",
        dedupe_key=f"{survivor.id}:NEW:2026-01-01",
    )
    db_session.add_all([noisy, already_read, genuine])
    await db_session.commit()

    result = await backfill_campaign_classes(db_session)

    # Only the unread alert on the retired row moved: the count is "noise
    # cleared", not "alerts touched".
    assert result["alerts_acknowledged"] == 1
    await db_session.refresh(noisy)
    await db_session.refresh(genuine)
    assert noisy.acknowledged_at is not None
    # A surviving campaign's alert is still waiting to be read.
    assert genuine.acknowledged_at is None


async def test_a_genuine_fare_campaign_survives_and_is_only_enriched(db_session):
    survivor = _fare_campaign()
    db_session.add(survivor)
    await db_session.commit()
    before = {
        name: getattr(survivor, name)
        for name in (
            "title_tr",
            "summary_tr",
            "discount_pct",
            "sale_starts",
            "sale_ends",
            "travel_starts",
            "travel_ends",
            "detected_at",
            "confidence_band",
            "classification_reason",
        )
    }

    result = await backfill_campaign_classes(db_session)

    assert result["scanned"] == 1
    assert result["enriched"] == 1
    assert result["unchanged"] == 0
    assert sum(result["retired_by_class"].values()) == 0

    await db_session.refresh(survivor)
    assert survivor.superseded_at is None
    assert survivor.business_class == "ACTIVE_CAMPAIGN"
    for name, value in before.items():
        assert getattr(survivor, name) == value, name
    # Pure enrichment matching how the row was already being served: no
    # version row, so the CHANGE alert rule has nothing to announce.
    assert await _versions(db_session, survivor) == []
    assert survivor.last_changed_at is None


async def test_second_run_changes_nothing(db_session):
    loyalty = _promotion(
        "https://example.com/avios",
        "Buy Qatar Airways Avios With 50% Bonus",
        "Bonus mil satın alma kampanyası.",
    )
    survivor = _fare_campaign()
    db_session.add_all([loyalty, survivor])
    await db_session.commit()

    first = await backfill_campaign_classes(db_session)
    second = await backfill_campaign_classes(db_session)

    assert first["retired_by_class"]["LOYALTY_PROMOTION"] == 1
    assert first["enriched"] == 1
    # The retired row is superseded and so outside the second scan entirely;
    # the survivor already carries the class the second pass would write.
    assert second == {
        "scanned": 1,
        "retired_by_class": dict.fromkeys(first["retired_by_class"], 0),
        "enriched": 0,
        "unchanged": 1,
        "alerts_acknowledged": 0,
    }
    assert len(await _versions(db_session, loyalty)) == 1


async def test_ignores_superseded_rows(db_session):
    """`mark_legacy_campaigns_superseded` may already have retired a row. It is
    decided; re-examining it would write a second version row for nothing."""
    retired = _promotion(
        "https://example.com/eski",
        "Miles&Smiles mil kampanyası",
        superseded_at=NOW - timedelta(days=5),
    )
    db_session.add(retired)
    await db_session.commit()

    result = await backfill_campaign_classes(db_session)

    assert result["scanned"] == 0
    assert await _versions(db_session, retired) == []


async def test_dated_student_fare_is_a_campaign_not_an_evergreen_offer(db_session):
    """The rulepack's own boundary, asserted here because the backfill is what
    would act on getting it wrong: a student fare with a real sale window is a
    campaign that happens to target students."""
    dated = _promotion(
        "https://example.com/ogrenci-kampanya",
        "Öğrencilere özel 3 gün %30 indirim",
        "Sadece bu hafta sonu geçerli.",
        discount_pct=30,
        sale_starts=TODAY,
        sale_ends=TODAY + timedelta(days=3),
    )
    db_session.add(dated)
    await db_session.commit()

    result = await backfill_campaign_classes(db_session)

    assert sum(result["retired_by_class"].values()) == 0
    await db_session.refresh(dated)
    assert dated.superseded_at is None
    assert dated.business_class == "ACTIVE_CAMPAIGN"


async def test_counts_an_already_classified_survivor_as_unchanged(db_session):
    """A row the new pipeline wrote (business_class already ACTIVE_CAMPAIGN) is
    neither retired nor re-enriched -- it is simply confirmed."""
    survivor = _fare_campaign()
    survivor.business_class = "ACTIVE_CAMPAIGN"
    survivor.classification_reason = "Satış dönemi açıkça belirtilmiş; ücret kampanyası."
    db_session.add(survivor)
    await db_session.commit()

    result = await backfill_campaign_classes(db_session)

    assert result == {
        "scanned": 1,
        "retired_by_class": {
            "PRODUCT_PROMOTION": 0,
            "LOYALTY_PROMOTION": 0,
            "EVERGREEN_OFFER": 0,
            "NEWS_ONLY": 0,
        },
        "enriched": 0,
        "unchanged": 1,
        "alerts_acknowledged": 0,
    }


async def test_retired_rows_leave_the_published_surface(db_session):
    """The end-to-end point of the whole pass, checked against the same filter
    the read endpoints use rather than against the column directly."""
    from app.api.v1.promotions import _publishable_promotions

    loyalty = _promotion(
        "https://example.com/puan",
        "Kredi kartı puanlarınızı Miles&Smiles'a aktarın",
        "Puan transferi kampanyası.",
    )
    survivor = _fare_campaign()
    db_session.add_all([loyalty, survivor])
    await db_session.commit()

    await backfill_campaign_classes(db_session)

    published = (
        await db_session.execute(select(Promotion).where(_publishable_promotions()))
    ).scalars().all()
    assert [row.url for row in published] == [survivor.url]
