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


def test_event_types_are_valid():
    from app.models.event import EVENT_TYPES

    for event in EVENTS:
        assert event.event_type in EVENT_TYPES, f"{event.name}: {event.event_type}"


def test_calendar_covers_the_year_ahead_with_varied_types():
    # The user asked for holidays/sports/festivals, not just trade shows.
    types = {e.event_type for e in EVENTS}
    assert {"airshow", "conference", "sports", "holiday", "festival"} <= types


async def test_seed_writes_structured_calendar_rows(db_session):
    from sqlalchemy import select as sa_select

    from app.models.event import AviationEvent as Row

    await seed_events(db_session)
    rows = (await db_session.execute(sa_select(Row))).scalars().all()
    assert len(rows) == len(EVENTS)

    # Re-run: no duplicates, and a corrected date propagates in place.
    await seed_events(db_session)
    rows = (await db_session.execute(sa_select(Row))).scalars().all()
    assert len(rows) == len(EVENTS)
    by_url = {r.url: r for r in rows}
    farnborough = by_url["https://www.farnboroughairshow.com/"]
    assert farnborough.starts == date(2026, 7, 20)
    assert farnborough.event_type == "airshow"


# --- Round-8 remainder: the calendar carries demand judgement, not just dates ---

def test_every_event_says_what_it_does_to_demand():
    """A calendar that only says "Farnborough is in July" is a search engine.
    The reason this one exists is the line underneath."""
    from app.ingest.events_seed import EVENTS
    from app.models.event import IMPACT_LEVELS

    for event in EVENTS:
        assert event.impact_level in IMPACT_LEVELS, event.name
        assert event.demand_effect.strip(), event.name
        # Attendance is optional on purpose -- most holidays have no headcount,
        # and inventing one would look exactly like a published figure.
        assert event.attendance is None or event.attendance > 0, event.name


async def test_seed_writes_and_refreshes_the_demand_fields(db_session):
    from sqlalchemy import select

    from app.ingest.events_seed import EVENTS, seed_events
    from app.models.event import AviationEvent as AviationEventRow

    await seed_events(db_session)
    rows = {
        row.url: row
        for row in (await db_session.execute(select(AviationEventRow))).scalars()
    }
    assert len(rows) == len(EVENTS)
    for event in EVENTS:
        row = rows[event.url]
        assert row.impact_level == event.impact_level
        assert row.demand_effect_tr == event.demand_effect
        assert row.attendance == event.attendance

    # Re-running refreshes in place rather than duplicating.
    await seed_events(db_session)
    again = (await db_session.execute(select(AviationEventRow))).scalars().all()
    assert len(again) == len(EVENTS)
