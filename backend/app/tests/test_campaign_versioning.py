"""What a merge leaves behind: a diff, a version row, and every source URL.

The failure these guard against is the quiet one. Before this, a merge was an
in-place overwrite: the rival moved its booking deadline from the 23rd to the
30th, the row changed, and nothing anywhere recorded that it had -- the single
fact a revenue desk most wants was destroyed by the write that carried it. And
when two sources disagreed, whichever path ran last won, silently.

So three properties are asserted here over and over, from different angles:

* a change is written down (`campaign_versions`), and a non-change is not --
  version numbers count edits, not sightings;
* a disagreement is resolved by source tier and BOTH values survive, so
  "official beats the trade press" is auditable rather than merely true;
* every page that contributed to a row is on file (`campaign_sources`), which
  is what makes the corroboration input of the confidence score a count of
  sources rather than a guess.

The per-writer wiring lives with each writer's own tests -- the deep-scan hook
in test_campaign_deep_scan.py, the article path in test_pipeline_v2_runner.py,
the Pegasus scraper in test_promotions.py -- because what has to be checked
there is that the path calls this machinery at all, which is a different
question from whether the machinery is right.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models.campaign_source import CampaignSource
from app.models.campaign_version import CampaignVersion
from app.models.promotion import Promotion
from app.pipeline.confidence import ConfidenceInput, score
from app.pipeline.promo_dedup import (
    PromoCandidate,
    apply_updates,
    campaign_tier_for_article,
    count_sources,
    ensure_source_row,
    merge_candidate,
    record_version,
    rescore_for_corroboration,
    tier_for_source_name,
)

NOW = datetime.now(timezone.utc)
AIRLINE_PAGE = "Pegasus kampanya sayfası"
NEWS_URL = "https://havayolu101.example/pegasus-kktc"
PAGE_URL = "https://www.flypgs.com/kampanyali-ucak-biletleri/kktc-2026"


def _news_row(**fields) -> Promotion:
    base = dict(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Pegasus'tan Kuzey Kıbrıs uçuşlarında %40 indirim",
        summary_tr="Haberin ayrıntılı özeti.",
        url=NEWS_URL,
        source_name="Havayolu 101",
        detected_at=NOW - timedelta(days=2),
    )
    base.update(fields)
    return Promotion(**base)


def _page_candidate(**fields) -> PromoCandidate:
    base = dict(
        airline_code="PC",
        airline_name="Pegasus Airlines",
        title_tr="Kuzey Kıbrıs Uçuşları Salı'dan Perşembe'ye %40 indirimli!",
        summary_tr="Kısa açıklama.",
        url=PAGE_URL,
        source_name=AIRLINE_PAGE,
        detected_at=NOW,
    )
    base.update(fields)
    return PromoCandidate(**base)


async def _stored_news_row(db, **fields) -> Promotion:
    row = _news_row(**fields)
    db.add(row)
    await db.flush()
    return row


async def _versions(db, promotion) -> list[CampaignVersion]:
    rows = (
        await db.execute(
            select(CampaignVersion)
            .where(CampaignVersion.promotion_id == promotion.id)
            .order_by(CampaignVersion.version_no)
        )
    ).scalars().all()
    return list(rows)


async def _sources(db, promotion) -> list[CampaignSource]:
    rows = (
        await db.execute(
            select(CampaignSource)
            .where(CampaignSource.promotion_id == promotion.id)
            .order_by(CampaignSource.url)
        )
    ).scalars().all()
    return list(rows)


# --- the diff -------------------------------------------------------------


def test_a_merge_reports_every_field_it_moved_and_nothing_else():
    row = _news_row(discount_pct=None, sale_starts=None, sale_ends=None)
    changed = merge_candidate(
        row,
        _page_candidate(discount_pct=40, sale_starts=date(2026, 8, 21), sale_ends=date(2026, 8, 23)),
    )

    assert changed["discount_pct"] == {"previous": None, "new": 40}
    assert changed["sale_starts"] == {"previous": None, "new": "2026-08-21"}
    assert changed["url"] == {"previous": NEWS_URL, "new": PAGE_URL}
    # The summary the news wrote is longer and survives, so it never moved.
    assert "summary_tr" not in changed
    # detected_at did not move either: the row already held the earlier sighting.
    assert "detected_at" not in changed


def test_dates_are_iso_strings_so_the_diff_is_json():
    changed = merge_candidate(
        _news_row(),
        _page_candidate(sale_ends=date(2026, 8, 23), detected_at=NOW - timedelta(days=9)),
    )

    assert changed["sale_ends"]["new"] == "2026-08-23"
    assert date.fromisoformat(changed["sale_ends"]["new"]) == date(2026, 8, 23)
    # Datetimes too, and tz-aware: two spellings of one instant must not read
    # as a change.
    assert datetime.fromisoformat(changed["detected_at"]["new"]) == NOW - timedelta(days=9)


def test_a_re_sight_that_changes_nothing_reports_nothing():
    row = _news_row(discount_pct=40, sale_ends=date(2026, 8, 23))
    merge_candidate(row, _page_candidate(discount_pct=40, sale_ends=date(2026, 8, 23)))
    # Second pass over the same reading: the row already says all of it.
    assert merge_candidate(
        row, _page_candidate(discount_pct=40, sale_ends=date(2026, 8, 23))
    ) == {}


def test_apply_updates_diffs_a_plain_overwrite():
    row = _news_row(discount_pct=30, sale_ends=date(2026, 8, 23))
    changed = apply_updates(
        row, {"discount_pct": 40, "sale_ends": date(2026, 8, 23), "title_tr": row.title_tr}
    )

    assert changed == {"discount_pct": {"previous": 30, "new": 40}}
    assert row.discount_pct == 40


# --- conflict resolution --------------------------------------------------


def test_the_carriers_own_page_wins_a_disagreement_and_the_loser_stays_on_record():
    row = _news_row(sale_ends=date(2026, 8, 23))
    changed = merge_candidate(row, _page_candidate(sale_ends=date(2026, 8, 30)))

    assert row.sale_ends == date(2026, 8, 30), "official wins the field it sells on"
    assert row.conflict_detected is True
    entry = changed["sale_ends"]
    assert entry["previous"] == "2026-08-23"
    assert entry["new"] == "2026-08-30"
    # ...and the rejected reading is still readable, with who said it.
    assert entry["conflict"] is True
    assert entry["rejected"] == "2026-08-23"
    assert entry["rejected_source"] == NEWS_URL
    assert entry["rejected_source_tier"] == "secondary"


def test_a_news_report_does_not_overturn_the_page_it_is_reporting_on():
    """The same rule from the other side. The incumbent wins, and the version
    row still records that it was contradicted -- an entry whose previous and
    new agree is not a no-op when it carries a rejection."""
    row = _news_row(
        url=PAGE_URL, source_name=AIRLINE_PAGE, discount_pct=40, sale_ends=date(2026, 8, 30)
    )
    changed = merge_candidate(
        row,
        PromoCandidate(
            airline_code="PC",
            airline_name="Pegasus Airlines",
            title_tr="Pegasus'tan Kuzey Kıbrıs uçuşlarında indirim",
            summary_tr="",
            url=NEWS_URL,
            source_name="Havayolu 101",
            detected_at=NOW,
            discount_pct=30,
            sale_ends=date(2026, 8, 23),
        ),
    )

    assert (row.discount_pct, row.sale_ends) == (40, date(2026, 8, 30))
    assert row.conflict_detected is True
    for name, rejected in (("discount_pct", 30), ("sale_ends", "2026-08-23")):
        entry = changed[name]
        assert entry["previous"] == entry["new"], "the incumbent value did not move"
        assert entry["rejected"] == rejected
        assert entry["rejected_source"] == NEWS_URL
        assert entry["rejected_source_tier"] == "secondary"


def test_campaign_type_disagreement_is_material_too():
    row = _news_row(campaign_type="SEASONAL_PROMOTION")
    changed = merge_candidate(row, _page_candidate(campaign_type="FLASH_SALE"))

    assert row.campaign_type == "FLASH_SALE"
    assert changed["campaign_type"]["rejected"] == "SEASONAL_PROMOTION"
    assert row.conflict_detected is True


def test_one_source_revising_itself_is_a_change_not_a_conflict():
    """The carrier extended its own deadline on its own page. That is the
    campaign moving, which is what a version row is for -- and flagging it as a
    conflict would fill the column with every carrier that ever did it."""
    row = _news_row(url=PAGE_URL, source_name=AIRLINE_PAGE, sale_ends=date(2026, 8, 23))
    changed = merge_candidate(
        row, _page_candidate(sale_ends=date(2026, 8, 30)), prefer_candidate=True
    )

    assert row.sale_ends == date(2026, 8, 30)
    assert row.conflict_detected is None
    assert changed["sale_ends"] == {"previous": "2026-08-23", "new": "2026-08-30"}
    assert "rejected" not in changed["sale_ends"]


def test_the_tier_ladder_reads_official_off_the_source_name():
    assert tier_for_source_name(AIRLINE_PAGE) == "official"
    assert tier_for_source_name("Emirates kampanya sayfası") == "official"
    assert tier_for_source_name("Havayolu 101") == "secondary"
    assert tier_for_source_name(None) == "secondary"


def test_an_article_is_secondary_unless_the_source_is_the_carrier():
    # "official" on a `sources` row means the carrier's own channel; as a
    # campaign source that is its newsroom, never the page selling the fare.
    assert campaign_tier_for_article("official") == "newsroom"
    for tier in ("regulator", "agency", "trade", "aggregator", None):
        assert campaign_tier_for_article(tier) == "secondary"


# --- version rows ---------------------------------------------------------


async def test_creation_writes_no_version_row(db_session):
    """Version 1 means the first time a campaign MOVED. When we first saw it is
    already on the row, in first_seen_at."""
    row = await _stored_news_row(db_session, first_seen_at=NOW, last_seen_at=NOW)

    assert await record_version(db_session, row, {}, source_url=NEWS_URL) is None
    assert await _versions(db_session, row) == []
    assert row.last_changed_at is None


async def test_version_numbers_count_edits_not_sightings(db_session):
    row = await _stored_news_row(db_session, discount_pct=20)

    for pct in (30, 40, 50):
        changed = merge_candidate(row, _page_candidate(discount_pct=pct), prefer_candidate=True)
        await record_version(db_session, row, changed, source_url=PAGE_URL)
    # A fourth scan finding the same 50% writes nothing at all.
    unchanged = merge_candidate(row, _page_candidate(discount_pct=50), prefer_candidate=True)
    seen_again = NOW + timedelta(hours=6)
    row.last_seen_at = seen_again
    await record_version(db_session, row, unchanged, source_url=PAGE_URL)
    await db_session.commit()

    versions = await _versions(db_session, row)
    assert [v.version_no for v in versions] == [1, 2, 3]
    assert [v.changed_fields["discount_pct"] for v in versions] == [
        {"previous": 20, "new": 30},
        {"previous": 30, "new": 40},
        {"previous": 40, "new": 50},
    ]
    assert all(v.source_url == PAGE_URL for v in versions)
    assert row.last_seen_at == seen_again, "the sighting still moved"
    assert row.last_changed_at is not None


async def test_a_date_change_survives_the_round_trip_through_jsonb(db_session):
    row = await _stored_news_row(db_session, sale_ends=date(2026, 8, 23))
    changed = merge_candidate(row, _page_candidate(sale_ends=date(2026, 8, 30)))
    await record_version(db_session, row, changed, source_url=PAGE_URL)
    await db_session.commit()

    stored = (await _versions(db_session, row))[0].changed_fields["sale_ends"]
    assert date.fromisoformat(stored["previous"]) == date(2026, 8, 23)
    assert date.fromisoformat(stored["new"]) == date(2026, 8, 30)
    assert date.fromisoformat(stored["rejected"]) == date(2026, 8, 23)


# --- source rows and corroboration ---------------------------------------


async def test_a_second_url_is_a_second_source_and_a_re_sight_is_not(db_session):
    row = await _stored_news_row(db_session)

    _, created = await ensure_source_row(
        db_session, row, url=NEWS_URL, source_name="Havayolu 101", seen_at=NOW - timedelta(days=2)
    )
    assert created is True

    _, created = await ensure_source_row(
        db_session, row, url=PAGE_URL, source_name=AIRLINE_PAGE, seen_at=NOW, content_hash="a" * 64
    )
    assert created is True
    assert await count_sources(db_session, row) == 2

    later = NOW + timedelta(hours=12)
    again, created = await ensure_source_row(
        db_session, row, url=PAGE_URL, source_name=AIRLINE_PAGE, seen_at=later, content_hash="b" * 64
    )
    await db_session.commit()

    assert created is False, "looking twice is not two sources"
    assert await count_sources(db_session, row) == 2
    assert again.last_seen_at == later
    assert again.first_seen_at == NOW, "the first sighting is not rewritten"
    assert again.content_hash == "b" * 64

    news, page = await _sources(db_session, row)
    assert (news.url, news.source_tier) == (NEWS_URL, "secondary")
    assert (page.url, page.source_tier) == (PAGE_URL, "official")


async def test_a_second_independent_source_raises_the_confidence_score(db_session):
    scored = score(
        ConfidenceInput(
            source_tier="trade",
            classifier_certainty=0.8,
            required_fields_present=1,
            required_fields_total=1,
            signal_agreement=None,
            source_count=1,
        )
    )
    row = await _stored_news_row(
        db_session,
        confidence_score=scored.score,
        confidence_band=scored.band,
        confidence_detail=scored.as_detail(),
        review_required=True,
    )
    await ensure_source_row(db_session, row, url=NEWS_URL, source_name="Havayolu 101")

    assert await rescore_for_corroboration(db_session, row) is False, "one source, nothing new"
    assert row.confidence_score == scored.score

    await ensure_source_row(db_session, row, url=PAGE_URL, source_name=AIRLINE_PAGE)
    assert await rescore_for_corroboration(db_session, row) is True
    await db_session.commit()

    assert row.confidence_score > scored.score
    assert row.confidence_detail["components"]["corroboration"] > (
        scored.as_detail()["components"]["corroboration"]
    )
    # Only the corroboration input moved; the reading itself was not re-judged.
    for component in ("source_tier", "classifier_certainty", "field_completeness"):
        assert row.confidence_detail["components"][component] == (
            scored.as_detail()["components"][component]
        )


async def test_an_unscored_row_is_left_alone(db_session):
    """A legacy row has no components to re-score from, and inventing them
    would be putting a number on a record nobody ever judged."""
    row = await _stored_news_row(db_session)
    await ensure_source_row(db_session, row, url=NEWS_URL)
    await ensure_source_row(db_session, row, url=PAGE_URL)

    assert await rescore_for_corroboration(db_session, row) is False
    assert row.confidence_score is None
