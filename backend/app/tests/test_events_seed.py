"""The events calendar is hand-curated rather than scraped, so the risks are
transcription mistakes and duplicate rows on re-run -- not parsing.
"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.ingest.events_seed import EVENTS, format_date_range, seed_events
from app.models.article import Article, ArticleEnrichment
from app.taxonomy import COUNTRY_TO_REGION


def test_every_event_has_a_citable_official_url():
    for event in EVENTS:
        assert event.url.startswith("https://"), event.name


def test_event_regions_are_real_taxonomy_slugs():
    # A typo here would silently hide the event from its region filter.
    valid_regions = set(COUNTRY_TO_REGION.values())
    for event in EVENTS:
        if event.region is not None:
            assert event.region in valid_regions, f"{event.name}: {event.region}"


def test_event_dates_are_coherent():
    for event in EVENTS:
        assert event.starts <= event.ends, event.name


def test_date_range_formatting_reads_naturally_in_turkish():
    assert format_date_range(date(2026, 7, 20), date(2026, 7, 24)) == "20-24 Temmuz 2026"
    # Spanning two months has to spell both out.
    assert format_date_range(date(2027, 5, 30), date(2027, 6, 1)) == "30 Mayıs - 1 Haziran 2027"


async def test_seed_creates_events_in_the_events_category(db_session):
    inserted = await seed_events(db_session)
    assert inserted == len(EVENTS)

    rows = (
        await db_session.execute(select(ArticleEnrichment).where(ArticleEnrichment.category == "events"))
    ).scalars().all()
    assert len(rows) == len(EVENTS)


async def test_curated_events_are_marked_translated_not_machine_translated(db_session):
    await seed_events(db_session)

    row = (
        await db_session.execute(select(ArticleEnrichment).where(ArticleEnrichment.category == "events"))
    ).scalars().first()
    # Written in Turkish by hand, so the UI must not tag them "otomatik çeviri yok".
    assert row.headline_tr
    assert row.translated_at is not None
    assert row.translation_provider == "curated"


async def test_seeding_twice_does_not_duplicate(db_session):
    await seed_events(db_session)
    second = await seed_events(db_session)

    assert second == 0
    count = await db_session.execute(select(func.count()).select_from(Article))
    assert count.scalar_one() == len(EVENTS)


@pytest.mark.parametrize("region", ["europe", "middle-east", "africa", "north-america", "asia"])
def test_calendar_spans_the_major_regions(region):
    # The Etkinlik tab has a region picker; a calendar covering only Europe
    # would leave most of it empty.
    assert any(e.region == region for e in EVENTS), region
