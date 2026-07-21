"""The source list is hand-curated, so the failure modes are transcription
mistakes -- a duplicated URL that double-ingests a publisher, a duplicated name
(the seeder keys on `name`, so a clash silently drops a source), a category
typo that hides a source from its filter, or a trust weight outside the range
the scoring code assumes.
"""
from app.ingest.sources_seed import ALL_SOURCES, FREE_RSS_SOURCES, PREMIUM_SOURCE_NAMES

VALID_CATEGORIES = {"org", "airline", "airport", "financial", "other"}
VALID_SOURCE_TYPES = {"rss", "premium"}
MIN_LIVE_RSS_SOURCES = 55


def test_urls_are_unique():
    urls = [source.url for source in ALL_SOURCES]
    duplicates = {url for url in urls if urls.count(url) > 1}
    assert not duplicates, f"duplicate source URLs: {sorted(duplicates)}"


def test_names_are_unique():
    # SourceRepository.ensure_seeded() skips a seed whose name already exists,
    # so a duplicate name means one of the two sources never gets created.
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
