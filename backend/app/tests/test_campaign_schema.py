"""The campaign-intelligence schema, exercised against a real database.

The point is not that SQLAlchemy can insert rows. It is that the three
promises this migration makes actually hold under Postgres:

*Legacy rows keep working.* Every new column is nullable with no server
default, because the ~200 rows already in `promotions` were never classified
and `/promotions` has to keep serving them unchanged. A row with all of these
NULL must still write and read.

*The JSONB payloads survive the round trip.* Evidence quotes, route detail and
campaign attributes are stored as documents rather than columns, so nothing but
a real Postgres write proves they come back the same shape.

*The uniqueness constraints are the idempotency.* Both new child tables are
written by cron jobs that re-run and by workflows that overlap, and in both
cases the constraint -- not the writer's care -- is what stops a second attempt
from forking the history or inflating the corroboration count.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.campaign_source import CampaignSource
from app.models.campaign_version import CampaignVersion
from app.models.promotion import Promotion
from app.models.scrape_run import ScrapeRun

NOW = datetime.now(timezone.utc)


async def _promotion(db, url="https://www.turkishairlines.com/tr-tr/kampanyalar/x") -> Promotion:
    """The legacy shape: only what the pre-existing scraper writes."""
    promotion = Promotion(
        airline_code="TK",
        airline_name="Turkish Airlines",
        title_tr="Yurt dışı uçuşlarda %30 indirim",
        url=url,
        source_name="Turkish Airlines",
        detected_at=NOW,
    )
    db.add(promotion)
    await db.flush()
    return promotion


# --- promotions ----------------------------------------------------------


async def test_a_fully_classified_campaign_round_trips_with_its_json_intact(db_session):
    """Everything the extraction chain will write, written at once. The JSONB
    columns are the risk: they are the only place a shape can degrade
    silently."""
    promotion = Promotion(
        airline_code="TK",
        airline_name="Turkish Airlines",
        title_tr="İstanbul-Londra hattında %40'a varan indirim",
        url="https://www.turkishairlines.com/tr-tr/kampanyalar/londra",
        source_name="Turkish Airlines",
        detected_at=NOW,
        discount_pct=40,
        sale_starts=date(2026, 9, 1),
        sale_ends=date(2026, 9, 30),
        travel_starts=date(2026, 10, 1),
        travel_ends=date(2027, 3, 31),
        campaign_type="FLASH_SALE",
        business_class="ACTIVE_CAMPAIGN",
        route_scope="OND",
        ond="IST-LHR",
        origin_code="IST",
        dest_code="LHR",
        route_json={
            "origin": {"airport": "IST", "city": "İstanbul", "country": "TR", "region": "europe"},
            "dest": {"airport": "LHR", "city": "Londra", "country": "GB", "region": "europe"},
        },
        attrs_json={
            "cabin": "economy",
            "promo_code": "LONDRA40",
            "currency": "TRY",
            "price_floor": 4999,
            "discount_type": "percentage",
            "sales_channel": ["web", "mobile"],
            "eligibility": "Miles&Smiles üyeleri",
            "min_stay_nights": 2,
            "max_stay_nights": 30,
            "blackout_dates": ["2026-12-24", "2026-12-31"],
        },
        evidence_json={
            "sale_ends": {
                "value": "2026-09-30",
                "source_text": "Son satın alma tarihi 30 Eylül 2026'dır.",
                "confidence": 0.95,
            },
            "discount_pct": {
                "value": 40,
                "source_text": "%40'a varan indirim",
                "confidence": 0.9,
            },
        },
        classification_reason="Tarihli satış penceresi ve indirim oranı var; kalıcı teklif işareti yok.",
        review_required=False,
        conflict_detected=False,
        date_flags_json={"inferred_year": False},
        page_published_at=date(2026, 8, 25),
        page_updated_at=date(2026, 8, 27),
        content_hash="a" * 64,
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_changed_at=NOW,
        raw_text="İstanbul-Londra hattında %40'a varan indirim. Son satın alma 30 Eylül 2026.",
    )
    db_session.add(promotion)
    await db_session.commit()

    loaded = (
        await db_session.execute(select(Promotion).where(Promotion.ond == "IST-LHR"))
    ).scalar_one()

    assert loaded.business_class == "ACTIVE_CAMPAIGN"
    assert loaded.route_scope == "OND"
    assert (loaded.origin_code, loaded.dest_code) == ("IST", "LHR")
    # Nested dicts, lists and numbers all come back as themselves -- a JSONB
    # column that quietly stringified the list would still "have data".
    assert loaded.route_json["dest"]["city"] == "Londra"
    assert loaded.attrs_json["sales_channel"] == ["web", "mobile"]
    assert loaded.attrs_json["price_floor"] == 4999
    assert loaded.attrs_json["blackout_dates"] == ["2026-12-24", "2026-12-31"]
    # The quote is the point of evidence_json: the drawer shows the sentence,
    # not just the parsed value.
    assert loaded.evidence_json["sale_ends"]["source_text"].startswith("Son satın alma")
    assert loaded.evidence_json["discount_pct"]["confidence"] == pytest.approx(0.9)
    assert loaded.date_flags_json == {"inferred_year": False}
    assert loaded.review_required is False


async def test_an_unclassified_legacy_row_still_writes_and_reads(db_session):
    """The 200 rows already in the table were written by a scraper that knows
    none of these columns. If this ever fails, the migration was not additive."""
    await _promotion(db_session)
    await db_session.commit()

    loaded = (await db_session.execute(select(Promotion))).scalar_one()

    assert loaded.title_tr == "Yurt dışı uçuşlarda %30 indirim"
    for unclassified in (
        loaded.campaign_type,
        loaded.business_class,
        loaded.route_scope,
        loaded.ond,
        loaded.route_json,
        loaded.attrs_json,
        loaded.evidence_json,
        loaded.classification_reason,
        loaded.content_hash,
        loaded.raw_text,
    ):
        assert unclassified is None


async def test_never_classified_is_distinguishable_from_classified_as_false(db_session):
    """`review_required` has no server default on purpose. A legacy row was
    neither queued for review nor cleared of it, and False would be a claim we
    never made."""
    legacy = await _promotion(db_session, url="https://airline.example/eski")
    cleared = await _promotion(db_session, url="https://airline.example/incelendi")
    cleared.review_required = False
    await db_session.commit()

    pending = (
        await db_session.execute(
            select(Promotion).where(Promotion.review_required.is_(None))
        )
    ).scalars().all()

    assert [row.url for row in pending] == [legacy.url]
    assert cleared.review_required is False


# --- campaign_versions ---------------------------------------------------


async def test_successive_edits_become_numbered_versions_with_both_values(db_session):
    """The discount moving 30 -> 40 is the fact a revenue desk wants, and an
    in-place update on `promotions` is exactly what erases it."""
    promotion = await _promotion(db_session)
    db_session.add_all(
        [
            CampaignVersion(
                promotion_id=promotion.id,
                version_no=1,
                changed_fields={"discount_pct": {"previous": 30, "new": 40}},
                source_url=promotion.url,
            ),
            CampaignVersion(
                promotion_id=promotion.id,
                version_no=2,
                changed_fields={
                    "sale_ends": {"previous": "2026-09-30", "new": "2026-10-15"}
                },
                source_url=promotion.url,
            ),
        ]
    )
    await db_session.commit()

    versions = (
        await db_session.execute(
            select(CampaignVersion)
            .where(CampaignVersion.promotion_id == promotion.id)
            .order_by(CampaignVersion.version_no)
        )
    ).scalars().all()

    assert [version.version_no for version in versions] == [1, 2]
    assert versions[0].changed_fields["discount_pct"] == {"previous": 30, "new": 40}
    assert versions[1].changed_fields["sale_ends"]["new"] == "2026-10-15"
    assert versions[0].created_at is not None


async def test_the_same_version_number_cannot_be_written_twice(db_session):
    """Deep-scan and the article path can both reach the same campaign in one
    cron window. The constraint is what makes the second one fail loudly
    instead of forking the history."""
    promotion = await _promotion(db_session)
    db_session.add(
        CampaignVersion(promotion_id=promotion.id, version_no=1, changed_fields={})
    )
    await db_session.commit()

    db_session.add(
        CampaignVersion(
            promotion_id=promotion.id,
            version_no=1,
            changed_fields={"discount_pct": {"previous": 30, "new": 40}},
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# --- campaign_sources ----------------------------------------------------


async def test_rescanning_a_page_cannot_inflate_the_corroboration_count(db_session):
    """Source count feeds the confidence score, so a page counted twice is a
    campaign that looks better corroborated than it is."""
    promotion = await _promotion(db_session)
    db_session.add(
        CampaignSource(
            promotion_id=promotion.id,
            url="https://www.turkishairlines.com/tr-tr/kampanyalar/x",
            source_name="Turkish Airlines",
            source_tier="official",
            source_quality=1.0,
            page_published_at=date(2026, 8, 25),
            content_hash="b" * 64,
            first_seen_at=NOW,
            last_seen_at=NOW,
            raw_excerpt="Son satın alma tarihi 30 Eylül 2026'dır.",
        )
    )
    await db_session.commit()

    db_session.add(
        CampaignSource(
            promotion_id=promotion.id,
            url="https://www.turkishairlines.com/tr-tr/kampanyalar/x",
            source_tier="official",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_one_newsroom_post_can_be_a_source_for_two_campaigns(db_session):
    """Uniqueness is per (campaign, url), not per url: a single announcement
    routinely covers two sales, and a global unique would drop the second."""
    first = await _promotion(db_session, url="https://airline.example/kampanya-1")
    second = await _promotion(db_session, url="https://airline.example/kampanya-2")
    shared = "https://press.example/iki-kampanya-birden"
    db_session.add_all(
        [
            CampaignSource(promotion_id=first.id, url=shared, source_tier="newsroom"),
            CampaignSource(promotion_id=second.id, url=shared, source_tier="newsroom"),
        ]
    )
    await db_session.commit()

    rows = (
        await db_session.execute(select(CampaignSource).where(CampaignSource.url == shared))
    ).scalars().all()
    assert {row.promotion_id for row in rows} == {first.id, second.id}


async def test_a_source_row_keeps_the_tier_that_decides_conflicts(db_session):
    """"The official page says 40% and a trade outlet says 30%" only reads as a
    resolution if the losing source is still on the record with its tier."""
    promotion = await _promotion(db_session)
    db_session.add_all(
        [
            CampaignSource(
                promotion_id=promotion.id,
                url="https://www.turkishairlines.com/tr-tr/kampanyalar/x",
                source_tier="official",
                source_quality=1.0,
                raw_excerpt="%40'a varan indirim",
            ),
            CampaignSource(
                promotion_id=promotion.id,
                url="https://havayolu101.example/tk-indirim",
                source_tier="secondary",
                source_quality=0.6,
                raw_excerpt="%30 indirim",
            ),
        ]
    )
    promotion.conflict_detected = True
    await db_session.commit()

    sources = (
        await db_session.execute(
            select(CampaignSource)
            .where(CampaignSource.promotion_id == promotion.id)
            .order_by(CampaignSource.source_quality.desc())
        )
    ).scalars().all()

    assert [source.source_tier for source in sources] == ["official", "secondary"]
    assert sources[1].raw_excerpt == "%30 indirim"
    assert promotion.conflict_detected is True


# --- scrape_runs ---------------------------------------------------------


async def test_a_blocked_fetch_is_recorded_as_carefully_as_a_successful_one(db_session):
    """A bot wall answers 200 OK with a body full of JavaScript, so the status
    code alone never says what happened -- `outcome` does, and it is what
    demotes a carrier to its newsroom tier."""
    started = NOW
    db_session.add_all(
        [
            ScrapeRun(
                carrier_code="PC",
                url="https://www.flypgs.com/kampanyalar",
                method="static",
                started_at=started,
                finished_at=started + timedelta(seconds=3),
                outcome="ok",
                http_status=200,
                content_hash="c" * 64,
                changed=True,
            ),
            ScrapeRun(
                carrier_code="TK",
                url="https://www.turkishairlines.com/tr-tr/kampanyalar/",
                method="browser",
                started_at=started,
                finished_at=started + timedelta(seconds=20),
                outcome="blocked",
                http_status=200,
                error="Challenge sayfası döndü, kampanya bloğu bulunamadı.",
            ),
        ]
    )
    await db_session.commit()

    blocked = (
        await db_session.execute(select(ScrapeRun).where(ScrapeRun.outcome == "blocked"))
    ).scalar_one()
    assert blocked.carrier_code == "TK"
    # 200 and still a failure: this is why http_status is not the outcome.
    assert blocked.http_status == 200
    assert blocked.method == "browser"
    assert blocked.content_hash is None
    assert blocked.changed is None


async def test_the_latest_run_per_carrier_is_the_query_this_table_answers(db_session):
    """The (carrier_code, started_at) index exists for exactly this lookup."""
    db_session.add_all(
        [
            ScrapeRun(
                carrier_code="TK",
                url="https://www.turkishairlines.com/tr-tr/kampanyalar/",
                method="browser",
                started_at=NOW - timedelta(days=1),
                outcome="blocked",
            ),
            ScrapeRun(
                carrier_code="TK",
                url="https://www.turkishairlines.com/tr-tr/kampanyalar/",
                method="browser",
                started_at=NOW,
                outcome="ok",
                changed=False,
            ),
        ]
    )
    await db_session.commit()

    latest = (
        await db_session.execute(
            select(ScrapeRun)
            .where(ScrapeRun.carrier_code == "TK")
            .order_by(ScrapeRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one()

    assert latest.outcome == "ok"
    # False, not None: there was a previous hash to compare against.
    assert latest.changed is False


# --- cascade -------------------------------------------------------------


async def test_deleting_a_campaign_takes_its_versions_and_sources_with_it(db_session):
    """Unlike articles/events, which are prunable independently, a version row
    and a source row have no meaning without their campaign -- so the FK
    cascades rather than nulling out."""
    doomed = await _promotion(db_session, url="https://airline.example/silinecek")
    survivor = await _promotion(db_session, url="https://airline.example/kalacak")
    db_session.add_all(
        [
            CampaignVersion(promotion_id=doomed.id, version_no=1, changed_fields={}),
            CampaignSource(promotion_id=doomed.id, url="https://press.example/a"),
            CampaignVersion(promotion_id=survivor.id, version_no=1, changed_fields={}),
            CampaignSource(promotion_id=survivor.id, url="https://press.example/b"),
        ]
    )
    await db_session.commit()

    await db_session.delete(doomed)
    await db_session.commit()

    versions = (await db_session.execute(select(CampaignVersion))).scalars().all()
    sources = (await db_session.execute(select(CampaignSource))).scalars().all()

    assert [version.promotion_id for version in versions] == [survivor.id]
    assert [source.promotion_id for source in sources] == [survivor.id]
