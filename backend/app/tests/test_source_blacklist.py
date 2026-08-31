"""The domain blacklist: matcher, ingest-time drop, and the archive purge.

Three separate failure modes, so three groups of tests. The matcher tests are
the ones that matter most -- a blacklist that is one `in` operator away from
banning "notreddit.com" is worse than no blacklist, because the damage is
silent and looks like a source going quiet.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.ingest.blacklist import (
    BLACKLIST_STATUS,
    blacklisted_domain,
    is_blacklisted,
)
from app.ingest.rss import RssSourceAdapter
from app.models.article import Article
from app.models.source import Source
from app.pipeline.blacklist_purge import (
    count_blacklisted_articles,
    purge_blacklisted_articles,
)

# --- the matcher ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://reddit.com/r/awardtravel/comments/abc",
        "https://www.reddit.com/r/aviation/comments/abc/title/",
        "http://old.reddit.com/r/flying/",
        "https://np.reddit.com/r/travel/",
        "https://new.reddit.com/r/Turkey/",
        "https://redd.it/abc123",
        "https://i.redd.it/xyz.jpg",
        "https://v.redd.it/xyz",
        "https://preview.redd.it/xyz.png?width=640",
        "https://out.reddit.com/t3_abc",
        # Case and trailing dot are both legal in a hostname and both have to
        # normalise, or the ban is bypassable by typing it differently.
        "https://WWW.REDDIT.COM/r/aviation/",
        "https://www.reddit.com./r/aviation/",
        # Port, userinfo, query and fragment must not hide the host.
        "https://www.reddit.com:443/r/aviation/",
        "https://user:pass@www.reddit.com/r/aviation/",
        "https://www.reddit.com/search?q=turkish+airlines#top",
    ],
)
def test_reddit_urls_are_blacklisted(url):
    assert blacklisted_domain(url) is not None
    assert is_blacklisted(url)


@pytest.mark.parametrize(
    "url",
    [
        # The whole reason this is host matching and not substring matching:
        # every one of these contains "reddit.com" and every one is innocent.
        "https://notreddit.com/article",
        "https://myreddit.com/r/aviation",
        "https://example.com/reddit.com/story",
        "https://simpleflying.com/what-reddit.com-says-about-turkish-airlines/",
        # A lookalike that merely *ends* the way an attacker would want.
        "https://reddit.com.evil.example/r/aviation",
        # Ordinary sources must be untouched.
        "https://www.airlinehaber.com/feed/",
        "https://news.google.com/rss/articles/CBMiXYZ?oc=5",
        "https://simpleflying.com/feed/",
        # Non-URLs and non-web schemes have no publisher at all.
        "",
        "   ",
        "not a url",
        "mailto:someone@reddit.com",
        "data:text/html,reddit.com",
    ],
)
def test_innocent_urls_are_not_blacklisted(url):
    assert blacklisted_domain(url) is None
    assert not is_blacklisted(url)


def test_none_is_not_blacklisted():
    # Callers pass entry.source["href"], which is absent on most publisher
    # feeds -- "no publisher declared" must never mean "banned".
    assert blacklisted_domain(None) is None
    assert not is_blacklisted(None)


def test_blacklisted_domain_names_the_rule_that_fired():
    # Stored in rejection_reason, so it has to be the registrable domain and
    # not the full host -- "blacklist:reddit.com", not "blacklist:np.reddit.com".
    assert blacklisted_domain("https://old.reddit.com/r/aviation/") == "reddit.com"
    assert blacklisted_domain("https://i.redd.it/x.png") == "redd.it"


def test_is_blacklisted_is_variadic_over_candidates():
    wrapper = "https://news.google.com/rss/articles/CBMiXYZ?oc=5"
    assert not is_blacklisted(wrapper)
    # ...but the same wrapper with Reddit declared as the publisher is banned.
    assert is_blacklisted(wrapper, "https://www.reddit.com")


# --- the ingest-time drop ------------------------------------------------


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.headers = {"content-type": "application/xml"}

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, content: bytes):
        self._content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _FakeResponse(self._content)


def _feed(*items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        "<title>Test</title>" + "".join(items) + "</channel></rss>"
    ).encode()


def _item(title: str, link: str, source_url: str | None = None) -> str:
    source = f'<source url="{source_url}">Publisher</source>' if source_url else ""
    return f"<item><title>{title}</title><link>{link}</link>{source}</item>"


async def _fetch(monkeypatch, feed_bytes: bytes) -> list:
    import app.ingest.rss as rss_module

    monkeypatch.setattr(
        rss_module.httpx, "AsyncClient", lambda **kwargs: _FakeClient(feed_bytes)
    )
    return await RssSourceAdapter("Test Source", "https://example.com/feed").fetch()


async def test_ingest_drops_a_direct_reddit_link(monkeypatch):
    articles = await _fetch(
        monkeypatch,
        _feed(
            _item("Award seat question", "https://www.reddit.com/r/awardtravel/x/"),
            _item("AJet 30% indirim", "https://www.airlinehaber.com/ajet/"),
        ),
    )
    assert [a.url for a in articles] == ["https://www.airlinehaber.com/ajet/"]


async def test_ingest_drops_a_google_news_item_whose_publisher_is_reddit(monkeypatch):
    # The case the seed removal missed: the link is an opaque Google wrapper,
    # so only the <source> element gives Reddit away.
    articles = await _fetch(
        monkeypatch,
        _feed(
            _item(
                "Is this Turkish Airlines sale real? - Reddit",
                "https://news.google.com/rss/articles/CBMiAAA?oc=5",
                source_url="https://www.reddit.com",
            ),
            _item(
                "THY kampanya - AirlineHaber",
                "https://news.google.com/rss/articles/CBMiBBB?oc=5",
                source_url="https://www.airlinehaber.com",
            ),
        ),
    )
    assert [a.title for a in articles] == ["THY kampanya - AirlineHaber"]


class _RecordingLogger:
    """Records structlog calls. pytest's caplog cannot be used here: structlog
    is configured with its own handler and nothing reaches the stdlib logging
    tree, so `assert "x" not in caplog.text` would pass against an empty string
    and prove nothing. Verified -- the positive case below fails without the
    recorder."""

    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def _record(self, level):
        def log(event, **kwargs):
            self.events.append((level, event))

        return log

    def __getattr__(self, name):
        return self._record(name)

    def names(self) -> list[str]:
        return [event for _, event in self.events]


async def _fetch_recording(monkeypatch, feed_bytes: bytes):
    import app.ingest.rss as rss_module

    recorder = _RecordingLogger()
    monkeypatch.setattr(rss_module, "logger", recorder)
    return await _fetch(monkeypatch, feed_bytes), recorder


async def test_a_dead_feed_still_raises_the_alarm(monkeypatch):
    # Positive control for the test below: an HTML shell where the feed used to
    # be is a rotted source and must stay loud.
    articles, recorder = await _fetch_recording(monkeypatch, b"<html><body>x</body></html>")
    assert articles == []
    assert "rss_no_usable_entries" in recorder.names()


async def test_a_feed_emptied_only_by_the_blacklist_is_not_reported_as_broken(monkeypatch):
    # A feed that returned real items and had all of them banned is healthy,
    # not rotted, and must not page anyone -- it reports the drop instead.
    articles, recorder = await _fetch_recording(
        monkeypatch, _feed(_item("Thread", "https://old.reddit.com/r/aviation/x/"))
    )
    assert articles == []
    assert "rss_no_usable_entries" not in recorder.names()
    assert "rss_blacklisted_items_dropped" in recorder.names()


# --- the archive purge ---------------------------------------------------


async def _article(db, source, url: str, status: str = "enriched") -> Article:
    article = Article(
        source_id=source.id,
        url=url,
        title="t",
        raw_content="c",
        word_count=1,
        content_hash=f"hash-{url}",
        status=status,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(article)
    await db.flush()
    return article


async def _seed_articles(db) -> Source:
    source = Source(name="Aggregator", url="https://example.com/feed", source_type="rss")
    db.add(source)
    await db.flush()
    await _article(db, source, "https://www.reddit.com/r/awardtravel/a/")
    await _article(db, source, "https://old.reddit.com/r/aviation/b/")
    await _article(db, source, "https://i.redd.it/c.png")
    await _article(db, source, "https://www.airlinehaber.com/kampanya/")
    # Contains the string, is not the domain -- the pre-filter catches it and
    # the matcher must let it through.
    await _article(db, source, "https://simpleflying.com/what-reddit.com-thinks/")
    return source


async def test_purge_retires_only_blacklisted_articles(db_session):
    await _seed_articles(db_session)

    result = await purge_blacklisted_articles(db_session)

    assert result["purged"] == 3
    assert result["by_domain"] == {"reddit.com": 2, "redd.it": 1}

    rows = (await db_session.execute(select(Article))).scalars().all()
    purged = {a.url: a for a in rows if a.status == BLACKLIST_STATUS}
    assert len(purged) == 3
    assert purged["https://i.redd.it/c.png"].rejection_reason == "blacklist:redd.it"
    survivors = {a.url for a in rows if a.status != BLACKLIST_STATUS}
    assert survivors == {
        "https://www.airlinehaber.com/kampanya/",
        "https://simpleflying.com/what-reddit.com-thinks/",
    }


async def test_purge_is_idempotent(db_session):
    await _seed_articles(db_session)

    first = await purge_blacklisted_articles(db_session)
    second = await purge_blacklisted_articles(db_session)

    assert first["purged"] == 3
    assert second["purged"] == 0
    assert second["already_purged"] == 3
    assert second["scanned"] == first["scanned"]


async def test_dry_run_count_matches_what_the_purge_does(db_session):
    await _seed_articles(db_session)

    before = await count_blacklisted_articles(db_session)
    result = await purge_blacklisted_articles(db_session)
    after = await count_blacklisted_articles(db_session)

    assert before == {"pending": 3, "already_purged": 0}
    assert result["purged"] == before["pending"]
    # The report a second dispatch would print: no work left, and it says so
    # rather than looking like the matcher stopped matching.
    assert after == {"pending": 0, "already_purged": 3}


async def test_purged_articles_disappear_from_listings(db_session):
    # The whole point of the purge: it is not enough that the row is labelled,
    # it has to actually stop being served.
    from app.repositories.article_repository import ArticleRepository

    await _seed_articles(db_session)
    repo = ArticleRepository(db_session)

    assert await repo.count() == 5
    await purge_blacklisted_articles(db_session)

    assert await repo.count() == 2
    listed = await repo.list_recent(limit=50)
    assert {a.url for a in listed} == {
        "https://www.airlinehaber.com/kampanya/",
        "https://simpleflying.com/what-reddit.com-thinks/",
    }
