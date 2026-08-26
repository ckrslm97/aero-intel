"""The source list is hand-curated, so the failure modes are transcription
mistakes -- a duplicated URL that double-ingests a publisher, a duplicated name
(the seeder keys on `name`, so a clash silently drops a source), a category
typo that hides a source from its filter, or a trust weight outside the range
the scoring code assumes.

The reconcile tests at the bottom cover the other half: that editing this file
actually changes a database that has already been seeded.
"""
from dataclasses import replace

from sqlalchemy import select

from app.ingest.sources_seed import ALL_SOURCES, FREE_RSS_SOURCES, PREMIUM_SOURCE_NAMES, SourceSeed
from app.models.source import Source
from app.repositories.source_repository import SourceRepository

VALID_CATEGORIES = {"org", "airline", "airport", "financial", "other"}
VALID_SOURCE_TYPES = {"rss", "premium"}
MIN_LIVE_RSS_SOURCES = 55


def test_urls_are_unique():
    urls = [source.url for source in ALL_SOURCES]
    duplicates = {url for url in urls if urls.count(url) > 1}
    assert not duplicates, f"duplicate source URLs: {sorted(duplicates)}"


def test_names_are_unique():
    # ensure_seeded() keys on `name`, so a duplicate means the second seed
    # overwrites the first instead of both existing.
    names = [source.name for source in ALL_SOURCES]
    duplicates = {name for name in names if names.count(name) > 1}
    assert not duplicates, f"duplicate source names: {sorted(duplicates)}"


def test_categories_are_valid():
    for source in ALL_SOURCES:
        assert source.category in VALID_CATEGORIES, f"{source.name}: {source.category}"


def test_source_types_are_valid():
    for source in ALL_SOURCES:
        assert source.source_type in VALID_SOURCE_TYPES, f"{source.name}: {source.source_type}"


def test_trust_weight_within_range():
    for source in ALL_SOURCES:
        assert 0.0 <= source.trust_weight <= 1.0, f"{source.name}: {source.trust_weight}"


def test_urls_are_https():
    for source in ALL_SOURCES:
        assert source.url.startswith("https://"), f"{source.name}: {source.url}"


def test_live_rss_coverage():
    # Guards against a future edit quietly shrinking the feed list back down.
    live = [source for source in FREE_RSS_SOURCES if not source.is_premium_stub]
    assert len(live) >= MIN_LIVE_RSS_SOURCES, f"only {len(live)} live RSS sources"


def test_free_sources_are_rss_and_premium_stubs_are_flagged():
    for source in FREE_RSS_SOURCES:
        assert source.source_type == "rss", source.name
        assert not source.is_premium_stub, source.name
    for source in PREMIUM_SOURCE_NAMES:
        assert source.source_type == "premium", source.name
        assert source.is_premium_stub, source.name


# --- reconcile behaviour -------------------------------------------------
#
# These need a database because the bug they guard against was invisible in a
# unit test: the old seeder read only the set of existing *names*, so every
# assertion about the seed file passed while production kept serving the old
# URLs and the retired feeds.


async def _seed(db, seeds: list[SourceSeed]) -> None:
    repo = SourceRepository(db)
    import app.repositories.source_repository as module

    original = module.ALL_SOURCES
    module.ALL_SOURCES = seeds
    try:
        await repo.ensure_seeded()
    finally:
        module.ALL_SOURCES = original


async def _get(db, name: str) -> Source:
    result = await db.execute(select(Source).where(Source.name == name))
    return result.scalar_one()


async def test_reseeding_applies_a_corrected_url(db_session):
    seed = SourceSeed("Havayolu 101", "https://old.example/feed", "rss", "other", 0.5)
    await _seed(db_session, [seed])

    corrected = replace(seed, url="https://new.example/feed", trust_weight=0.75)
    await _seed(db_session, [corrected])

    source = await _get(db_session, "Havayolu 101")
    assert source.url == "https://new.example/feed"
    assert source.trust_weight == 0.75


async def test_source_dropped_from_the_seed_list_is_deactivated(db_session):
    keep = SourceSeed("Havayolu 101", "https://a.example/feed", "rss", "other", 0.7)
    retire = SourceSeed("Reddit r/aviation", "https://b.example/.rss", "rss", "other", 0.35)
    await _seed(db_session, [keep, retire])

    await _seed(db_session, [keep])

    # Deactivated, not deleted -- articles carry a foreign key to their source.
    retired = await _get(db_session, "Reddit r/aviation")
    assert retired.is_active is False
    assert (await _get(db_session, "Havayolu 101")).is_active is True


async def test_deactivated_source_is_excluded_from_the_fetch_list(db_session):
    keep = SourceSeed("Havayolu 101", "https://a.example/feed", "rss", "other", 0.7)
    retire = SourceSeed("Reddit r/aviation", "https://b.example/.rss", "rss", "other", 0.35)
    await _seed(db_session, [keep, retire])
    await _seed(db_session, [keep])

    active = await SourceRepository(db_session).list_active()
    assert [source.name for source in active] == ["Havayolu 101"]
