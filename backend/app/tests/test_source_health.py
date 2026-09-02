"""Round-11 sources and the fetch-health accounting they arrived with.

Three groups, because there are three separate things that can rot.

The seed tests are shape tests, not content tests: they check that the new
entries declare a tier, a language and a trust weight in the band their tier
implies, so a future edit cannot quietly seed a regulator at aggregator trust.
They deliberately do NOT fetch anything -- the live measurements are recorded
in the comments in sources_seed.py, where they can be re-read, rather than
turned into a test that fails whenever a publisher has a slow morning.

The health tests are the important half. They exist because the failure they
guard against has already happened once here: FAA and ICAO sat in the seed
list producing exactly 0 articles from the day they were seeded, every run
logged it, and nothing accumulated it -- so it took a human reading production
to notice. The columns only help if the success path clears the counter and
the failure path advances it, which is what these assert.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.ingest.base import FetchHealth, RawArticle
from app.ingest.rss import RssSourceAdapter
from app.ingest.sources_seed import (
    ALL_SOURCES,
    FREE_RSS_SOURCES,
    PREMIUM_SOURCE_NAMES,
    TIER_DEFAULT_PRIORITY,
    SourceSeed,
)
from app.models.article import Article
from app.models.source import Source
from app.repositories.source_repository import SourceRepository
from app.services import ingestion_service
from app.services.data_quality_service import (
    SOURCE_FAILURE_STREAK_CEILING,
    SOURCE_SILENCE_DAYS,
    check_data_quality,
)
from app.taxonomy import CATEGORY_SLUGS

NOW = datetime.now(timezone.utc)

ROUND_11_NAMES = [
    "SHGM · Mevzuat",
    "SHGM · Duyurular",
    "SHGM · Haberler",
    "Lufthansa Group Newsroom",
    "PROS Blog",
]


def _seed(name: str) -> SourceSeed:
    return next(s for s in ALL_SOURCES if s.name == name)


# --- the new seed entries -------------------------------------------------


@pytest.mark.parametrize("name", ROUND_11_NAMES)
def test_round_11_source_is_seeded_as_a_working_rss_feed(name):
    seed = _seed(name)
    assert seed.source_type == "rss"
    assert not seed.is_premium_stub
    assert seed.url.startswith("https://")


def test_shgm_feeds_are_turkish_regulator_sources():
    """SHGM is the Turkish DGCA. Seeding it at anything below `regulator`
    would put a national authority's own instruction revisions on the same
    footing as the trade press that reports them."""
    for name in ("SHGM · Mevzuat", "SHGM · Duyurular", "SHGM · Haberler"):
        seed = _seed(name)
        assert seed.tier == "regulator"
        assert seed.language == "tr"
        assert seed.category == "org"
        # The band EASA (0.95) and Eurocontrol (0.9) already occupy.
        assert 0.80 <= seed.trust_weight <= 0.95
        assert "regulatory" in (seed.news_categories or "")


def test_shgm_section_feeds_are_seeded_but_the_union_feed_is_not():
    """`rss.php?tr` was measured as the exact union of the three section feeds
    (45 items, all of them present in a section feed, none missing from it).
    Seeding it would double every SHGM fetch AND -- because ingest dedupes on
    URL first-writer-wins -- file Mevzuat items under a generic source, losing
    the per-section weighting the split exists to provide."""
    urls = {s.url for s in ALL_SOURCES}
    assert "https://web.shgm.gov.tr/rss.php?tr/mevzuat" in urls
    assert "https://web.shgm.gov.tr/rss.php?tr/duyurular" in urls
    assert "https://web.shgm.gov.tr/rss.php?tr/haberler" in urls
    assert "https://web.shgm.gov.tr/rss.php?tr" not in urls


def test_mevzuat_outranks_the_other_shgm_sections():
    """The regulatory instruments are the reason this block exists, so they
    must not be flattened into the authority's PR feed by a later edit."""
    mevzuat = _seed("SHGM · Mevzuat")
    haberler = _seed("SHGM · Haberler")
    assert mevzuat.priority == "very_high"
    assert mevzuat.trust_weight > haberler.trust_weight
    assert haberler.priority == "normal"


def test_lufthansa_is_the_second_official_tier_source():
    """Before this round the `official` tier held exactly one source, which
    made a five-tier authority ladder a four-tier one in practice."""
    official = [s.name for s in ALL_SOURCES if s.tier == "official"]
    assert "Delta News Hub" in official
    assert "Lufthansa Group Newsroom" in official
    assert len(official) >= 2

    seed = _seed("Lufthansa Group Newsroom")
    assert seed.category == "airline"
    assert seed.language == "en"
    assert 0.85 <= seed.trust_weight <= 0.95


def test_pros_is_a_real_feed_and_no_longer_a_premium_stub():
    """PROS was seeded as an unreachable commercial platform. It publishes an
    open RSS feed, so the stub was not merely incomplete -- it was wrong."""
    premium_names = {s.name for s in PREMIUM_SOURCE_NAMES}
    assert "PROS" not in premium_names
    # Amadeus stays a stub: its blog answers 200 with an Imperva interstitial.
    assert "Amadeus" in premium_names

    seed = _seed("PROS Blog")
    assert seed.tier == "trade"
    assert seed.news_categories == "revenue_management"


def test_every_source_declares_a_priority_and_a_crawl_cadence():
    for seed in ALL_SOURCES:
        assert seed.priority in ("very_high", "high", "normal", "low"), seed.name
        assert seed.crawl_frequency_minutes > 0, seed.name


def test_priority_defaults_to_the_tier_but_can_be_overridden():
    """The two fields are different axes -- see the column docstring in
    app/models/source.py -- so the derivation has to be a default rather than
    a rule, or an aggregator radar could never outrank its tier."""
    derived = SourceSeed("X", "https://x.example/feed", "rss", "other", 0.5, tier="aggregator")
    assert derived.priority == TIER_DEFAULT_PRIORITY["aggregator"] == "low"

    override = SourceSeed(
        "Y", "https://y.example/feed", "rss", "other", 0.5,
        tier="aggregator", priority="very_high",
    )
    assert override.priority == "very_high"


def test_declared_news_categories_are_real_taxonomy_slugs():
    """`news_categories` is the NEWS BEAT, and the column beside it called
    `category` is the INSTITUTION TYPE. A slug that is not in the taxonomy is
    the first sign someone confused the two."""
    for seed in ALL_SOURCES:
        if not seed.news_categories:
            continue
        assert len(seed.news_categories) <= 200, seed.name
        for slug in seed.news_categories.split(","):
            assert slug in CATEGORY_SLUGS, f"{seed.name}: {slug!r}"


def test_source_names_are_unique():
    """ensure_seeded() reconciles by name, so a duplicate would make one of
    the two rows unreachable and silently deactivate it every other run."""
    names = [s.name for s in ALL_SOURCES]
    assert len(names) == len(set(names))
    assert len(ALL_SOURCES) == len(FREE_RSS_SOURCES) + len(PREMIUM_SOURCE_NAMES)


# --- the seed reaches the database ---------------------------------------


async def test_ensure_seeded_writes_the_new_config_columns(db_session):
    await SourceRepository(db_session).ensure_seeded()
    row = (
        await db_session.execute(
            select(Source).where(Source.name == "SHGM · Mevzuat")
        )
    ).scalar_one()
    assert row.tier == "regulator"
    assert row.priority == "very_high"
    assert row.news_categories == "regulatory,safety"
    assert row.crawl_frequency_minutes == 720
    assert row.consecutive_failures == 0


async def test_reconcile_does_not_reset_health(db_session):
    """Editorial config is seed-owned; health is run-owned. A reconcile that
    zeroed the failure counter would erase the evidence on every ingestion
    pass -- ensure_seeded() runs at the start of each one."""
    repo = SourceRepository(db_session)
    await repo.ensure_seeded()
    row = (
        await db_session.execute(select(Source).where(Source.name == "PROS Blog"))
    ).scalar_one()
    row.consecutive_failures = 4
    row.last_failure_at = NOW
    row.last_http_status = 503
    await db_session.commit()

    await repo.ensure_seeded()
    await db_session.refresh(row)
    assert row.consecutive_failures == 4
    assert row.last_http_status == 503


# --- health accounting ----------------------------------------------------


def _source(name: str = "Feed") -> Source:
    return Source(name=name, url="https://example.com/feed", source_type="rss")


def test_success_clears_the_failure_streak_but_keeps_the_failure_history():
    """An intermittently blocked feed is a different problem from a healthy
    one, so a recovery must not erase what the last break was."""
    source = _source()
    source.consecutive_failures = 3
    source.last_failure_at = NOW - timedelta(hours=2)
    source.last_http_status = 403

    SourceRepository.record_health(
        source, FetchHealth(ok=True, http_status=200, article_count=12, at=NOW)
    )

    assert source.last_success_at == NOW
    assert source.consecutive_failures == 0
    assert source.last_article_count == 12
    # Still standing.
    assert source.last_http_status == 403
    assert source.last_failure_at is not None


def test_failures_accumulate_and_keep_the_last_success():
    """The age of the last success is exactly what the silent-death check
    reads, so a failure must not clear it."""
    source = _source()
    last_success = NOW - timedelta(days=3)
    source.last_success_at = last_success
    source.last_article_count = 9

    for expected in (1, 2, 3):
        SourceRepository.record_health(
            source, FetchHealth(ok=False, http_status=403, at=NOW)
        )
        assert source.consecutive_failures == expected

    assert source.last_http_status == 403
    assert source.last_success_at == last_success
    assert source.last_article_count == 9


def test_a_transport_failure_records_no_http_status():
    """"Answered 403" and "never answered" are different diagnoses -- a bot
    wall versus a dead host -- and only the status column can tell them
    apart."""
    source = _source()
    SourceRepository.record_health(source, FetchHealth(ok=False, at=NOW))
    assert source.consecutive_failures == 1
    assert source.last_http_status is None


def test_consecutive_failures_counts_from_zero_when_null():
    """Pre-migration rows arrive with a null counter rather than a 0."""
    source = _source()
    source.consecutive_failures = None
    SourceRepository.record_health(source, FetchHealth(ok=False, at=NOW))
    assert source.consecutive_failures == 1


# --- the adapter reports what happened ------------------------------------


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": "application/xml"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=httpx.Request("GET", "https://example.com/feed"), response=self
            )


class _FakeClient:
    def __init__(self, response=None, raises: Exception | None = None):
        self._response = response
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        if self._raises is not None:
            raise self._raises
        return self._response


def _feed(*items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        "<title>Test</title>" + "".join(items) + "</channel></rss>"
    ).encode()


def _item(title: str, link: str) -> str:
    return f"<item><title>{title}</title><link>{link}</link></item>"


async def _run_adapter(monkeypatch, *, response=None, raises=None) -> RssSourceAdapter:
    import app.ingest.rss as rss_module

    monkeypatch.setattr(
        rss_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(response=response, raises=raises),
    )
    adapter = RssSourceAdapter("Test Source", "https://example.com/feed")
    await adapter.fetch()
    return adapter


async def test_adapter_reports_a_healthy_fetch(monkeypatch):
    adapter = await _run_adapter(
        monkeypatch,
        response=_FakeResponse(
            _feed(
                _item("SHT-66 revizyonu", "https://web.shgm.gov.tr/tr/mevzuat/1"),
                _item("GRF Talimatı", "https://web.shgm.gov.tr/tr/mevzuat/2"),
            )
        ),
    )
    assert adapter.last_health.ok
    assert adapter.last_health.http_status == 200
    assert adapter.last_health.article_count == 2


async def test_adapter_reports_a_200_with_no_usable_entries_as_a_failure(monkeypatch):
    """The FAA/ICAO failure mode exactly: HTTP 200, an HTML page where the feed
    used to be, and a dashboard that says everything is fine."""
    adapter = await _run_adapter(
        monkeypatch, response=_FakeResponse(b"<html><body>404 Page Not Found</body></html>")
    )
    assert adapter.last_health.ok is False
    assert adapter.last_health.http_status == 200


async def test_adapter_reports_an_http_error_with_its_status(monkeypatch):
    adapter = await _run_adapter(monkeypatch, response=_FakeResponse(b"", status_code=403))
    assert adapter.last_health.ok is False
    assert adapter.last_health.http_status == 403


async def test_adapter_reports_a_transport_error_without_a_status(monkeypatch):
    adapter = await _run_adapter(monkeypatch, raises=httpx.ReadTimeout("timed out"))
    assert adapter.last_health.ok is False
    assert adapter.last_health.http_status is None


async def test_a_feed_emptied_by_the_blacklist_is_healthy(monkeypatch):
    """Working as designed, not rotted. Calling it a failure would march a
    perfectly good feed toward the alarm for obeying the blacklist."""
    adapter = await _run_adapter(
        monkeypatch,
        response=_FakeResponse(
            _feed(_item("Award seat question", "https://www.reddit.com/r/awardtravel/x/"))
        ),
    )
    assert adapter.last_health.ok is True
    assert adapter.last_health.article_count == 0


# --- the run wires it together -------------------------------------------


async def _noop_seed(self) -> None:
    """ensure_seeded() would insert all ~100 curated sources and fetch them.

    These tests are about what happens to ONE row, so the seeder is stubbed
    out rather than worked around -- otherwise every assertion would be made
    against a database with a hundred other sources in it.
    """
    return None


class _FakeAdapter:
    def __init__(self, articles, health=None, crash=False):
        self.source_name = "Fake"
        self._articles = articles
        self._crash = crash
        if health is not None:
            self.last_health = health

    async def fetch(self):
        if self._crash:
            raise RuntimeError("adapter exploded")
        return self._articles


def _raw(url: str) -> RawArticle:
    return RawArticle(url=url, title="T", content="body", author=None, published_at=None)


async def test_run_ingestion_writes_health_to_the_source_row(db_session, monkeypatch):
    source = _source("Healthy Feed")
    db_session.add(source)
    await db_session.flush()

    monkeypatch.setattr(
        ingestion_service,
        "_adapter_for",
        lambda src: _FakeAdapter(
            [_raw("https://example.com/a")],
            health=FetchHealth(ok=True, http_status=200, article_count=1),
        ),
    )
    monkeypatch.setattr(SourceRepository, "ensure_seeded", _noop_seed)

    await ingestion_service.run_ingestion(db_session)

    await db_session.refresh(source)
    assert source.last_success_at is not None
    assert source.last_article_count == 1
    assert source.consecutive_failures == 0


async def test_run_ingestion_records_a_failure_without_stopping(db_session, monkeypatch):
    source = _source("Broken Feed")
    db_session.add(source)
    await db_session.flush()

    monkeypatch.setattr(
        ingestion_service,
        "_adapter_for",
        lambda src: _FakeAdapter([], health=FetchHealth(ok=False, http_status=403)),
    )
    monkeypatch.setattr(SourceRepository, "ensure_seeded", _noop_seed)

    inserted = await ingestion_service.run_ingestion(db_session)

    assert inserted == 0
    await db_session.refresh(source)
    assert source.consecutive_failures == 1
    assert source.last_http_status == 403
    assert source.last_success_at is None


async def test_one_crashing_source_does_not_stop_the_others(db_session, monkeypatch):
    """The behaviour this whole module is built around, asserted as a
    regression: adding health accounting must not turn a broken feed into a
    broken run."""
    good = _source("Good Feed")
    bad = _source("Crashing Feed")
    db_session.add_all([good, bad])
    await db_session.flush()

    def adapter_for(src):
        if src.name == "Crashing Feed":
            return _FakeAdapter([], crash=True)
        return _FakeAdapter(
            [_raw("https://example.com/good-1"), _raw("https://example.com/good-2")],
            health=FetchHealth(ok=True, http_status=200, article_count=2),
        )

    monkeypatch.setattr(ingestion_service, "_adapter_for", adapter_for)
    monkeypatch.setattr(SourceRepository, "ensure_seeded", _noop_seed)

    inserted = await ingestion_service.run_ingestion(db_session)

    assert inserted == 2
    stored = (await db_session.execute(select(Article))).scalars().all()
    assert {a.url for a in stored} == {
        "https://example.com/good-1",
        "https://example.com/good-2",
    }
    await db_session.refresh(good)
    await db_session.refresh(bad)
    assert good.last_success_at is not None
    # The crash is a failure even though the adapter never got far enough to
    # report one itself.
    assert bad.consecutive_failures == 1
    assert bad.last_http_status is None


async def test_an_adapterless_source_leaves_health_untouched(db_session, monkeypatch):
    """Premium stubs are seeded to be visible, not fetched. Calling them
    failed would march every one of them past the alarm on the first run."""
    stub = Source(
        name="IATA stub", url="https://www.iata.org", source_type="premium",
        is_premium_stub=True,
    )
    db_session.add(stub)
    await db_session.flush()

    monkeypatch.setattr(ingestion_service, "_adapter_for", lambda src: None)
    monkeypatch.setattr(SourceRepository, "ensure_seeded", _noop_seed)

    await ingestion_service.run_ingestion(db_session)

    await db_session.refresh(stub)
    assert stub.last_success_at is None
    assert stub.last_failure_at is None
    assert stub.consecutive_failures == 0


# --- the data-quality checks ---------------------------------------------


async def _quality_source(db, **fields) -> Source:
    source = Source(
        name=fields.pop("name", "Quality Feed"),
        url="https://example.com/feed",
        source_type=fields.pop("source_type", "rss"),
        **fields,
    )
    db.add(source)
    await db.flush()
    return source


def _checks(violations, name: str) -> list:
    return [v for v in violations if v.check == name]


async def test_a_long_failure_streak_is_a_violation(db_session):
    await _quality_source(
        db_session,
        name="Dead Feed",
        consecutive_failures=SOURCE_FAILURE_STREAK_CEILING,
        last_failure_at=NOW,
        last_http_status=403,
        last_success_at=NOW - timedelta(hours=12),
    )
    found = _checks(await check_data_quality(db_session), "source_failure_streak")
    assert len(found) == 1
    assert "Dead Feed" in found[0].detail
    assert "403" in found[0].detail


async def test_a_short_failure_streak_is_not_a_violation(db_session):
    """A publisher deploy or an expired certificate fixes itself well inside
    ten hours; the check must not fire on a bad afternoon."""
    await _quality_source(
        db_session,
        name="Flaky Feed",
        consecutive_failures=SOURCE_FAILURE_STREAK_CEILING - 1,
        last_failure_at=NOW,
        last_http_status=500,
        last_success_at=NOW - timedelta(hours=8),
    )
    assert _checks(await check_data_quality(db_session), "source_failure_streak") == []


async def test_a_source_that_has_never_succeeded_is_a_violation(db_session):
    """The FAA/ICAO case: seeded, fetched every run, zero articles ever, and
    invisible until someone read production by hand."""
    await _quality_source(
        db_session,
        name="ICAO",
        last_failure_at=NOW,
        last_http_status=200,
        consecutive_failures=2,
    )
    found = _checks(await check_data_quality(db_session), "silently_dead_source")
    assert len(found) == 1
    assert "no successful fetch on record" in found[0].detail


async def test_a_stale_last_success_is_a_violation(db_session):
    await _quality_source(
        db_session,
        name="Gone Quiet",
        last_success_at=NOW - timedelta(days=SOURCE_SILENCE_DAYS + 1),
        last_failure_at=NOW,
        consecutive_failures=1,
    )
    found = _checks(await check_data_quality(db_session), "silently_dead_source")
    assert len(found) == 1
    assert "Gone Quiet" in found[0].detail


async def test_a_recently_successful_source_is_clean(db_session):
    await _quality_source(
        db_session,
        name="Working Feed",
        last_success_at=NOW - timedelta(hours=3),
        last_article_count=25,
    )
    violations = await check_data_quality(db_session)
    assert _checks(violations, "silently_dead_source") == []
    assert _checks(violations, "source_failure_streak") == []


async def test_an_unobserved_source_is_not_reported_as_dead(db_session):
    """Every row is in this state between the migration landing and the first
    ingestion run after it -- about two hours on a `0 */2 * * *` schedule.
    Reporting the whole source list then would be reporting the deploy."""
    await _quality_source(db_session, name="Just Migrated")
    assert _checks(await check_data_quality(db_session), "silently_dead_source") == []


async def test_premium_stubs_are_exempt_from_both_checks(db_session):
    """A stub is seeded to be visible until credentials exist. It is never
    fetched, so it would otherwise fail forever for doing its job."""
    await _quality_source(
        db_session,
        name="Cirium",
        is_premium_stub=True,
        source_type="premium",
        last_failure_at=NOW,
        consecutive_failures=SOURCE_FAILURE_STREAK_CEILING + 3,
    )
    violations = await check_data_quality(db_session)
    assert _checks(violations, "source_failure_streak") == []
    assert _checks(violations, "silently_dead_source") == []


async def test_an_inactive_source_is_exempt_from_both_checks(db_session):
    """Retirement is done by removing a source from the seed list, which
    deactivates the row rather than deleting it (articles reference it). A
    retired source must stop being an alarm."""
    await _quality_source(
        db_session,
        name="Retired Feed",
        is_active=False,
        last_failure_at=NOW,
        consecutive_failures=SOURCE_FAILURE_STREAK_CEILING + 1,
    )
    violations = await check_data_quality(db_session)
    assert _checks(violations, "source_failure_streak") == []
    assert _checks(violations, "silently_dead_source") == []
