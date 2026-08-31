"""RSS/Atom source adapter -- covers every free aviation feed (news sites, ACI,
Eurocontrol, FAA, ICAO, ...). Network or parse failures are caught and logged so a
single broken feed never blocks the rest of the ingestion run.
"""
import re
from datetime import datetime, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.ingest.base import RawArticle
from app.ingest.blacklist import blacklisted_domain

logger = get_logger(__name__)

# Mozilla-compatible prefix, which is the documented convention for
# well-behaved crawlers (Googlebot and friends all use it) rather than a
# disguise -- the bot still names itself and links back. Measured: the bare
# "AeroIntelBot/0.1" form was 403'd by the FAA and 429'd by Reddit, whose WAFs
# reject user agents they do not recognise, so three otherwise-working public
# feeds were silently producing nothing.
USER_AGENT = (
    "Mozilla/5.0 (compatible; AeroIntelBot/0.1; +https://aero-intel-3qt1.vercel.app)"
)
REQUEST_TIMEOUT = httpx.Timeout(10.0)


# Some feeds escape their HTML twice: the XML carries "&lt;span&gt;", so one
# get_text() pass decodes the entities and hands back a string of literal tags
# instead of prose. Caught in production after the source list grew -- an
# Aviation Week story rendered on the site as
# '<span>Turkey Signs $11 Billion Eurofighter Deal</span> <span lang=""...'.
# Bounded rather than a while-loop: two passes covers double encoding, and an
# unbounded loop on hostile input is a denial-of-service waiting to happen.
_MAX_UNESCAPE_PASSES = 2
_LOOKS_LIKE_MARKUP = re.compile(r"<[a-zA-Z/][^>]*>")


def _strip_html(raw_html: str) -> str:
    text = raw_html
    for _ in range(_MAX_UNESCAPE_PASSES):
        if not text:
            return ""
        text = BeautifulSoup(text, "lxml").get_text(separator=" ", strip=True)
        if not _LOOKS_LIKE_MARKUP.search(text):
            break
    return text


def _entry_content(entry: feedparser.FeedParserDict) -> str:
    if "content" in entry and entry.content:
        return _strip_html(entry.content[0].get("value", ""))
    return _strip_html(entry.get("summary", ""))


def _entry_published_at(entry: feedparser.FeedParserDict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def _entry_publisher_url(entry: feedparser.FeedParserDict) -> str | None:
    """The publisher a Google News item actually came from.

    Google News wraps every `link` in an opaque news.google.com redirect (see
    app/ingest/blacklist.py for why it cannot be decoded), but it also emits
    `<source url="https://www.reddit.com">Reddit</source>` naming the
    publisher. feedparser exposes that as entry.source["href"]. Publisher feeds
    generally have no <source> element at all, which is fine -- their own
    `link` is already the real URL.
    """
    source = entry.get("source")
    if not source:
        return None
    return source.get("href")


# A Google News radar returns ~100 items every run and eight of them drive most
# of the daily volume. Publisher feeds carry maybe 10-30 items of their own
# reporting, so they are worth taking whole; aggregator queries are a firehose
# of the same stories re-listed, and the tail is the least relevant part of it.
AGGREGATOR_ITEM_CAP = 40


class RssSourceAdapter:
    def __init__(self, source_name: str, feed_url: str, item_cap: int | None = None):
        self.source_name = source_name
        self.feed_url = feed_url
        # Cap aggregator queries by default; a publisher feed keeps everything.
        if item_cap is None and "news.google.com" in feed_url:
            item_cap = AGGREGATOR_ITEM_CAP
        self.item_cap = item_cap

    async def fetch(self) -> list[RawArticle]:
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
            ) as client:
                response = await client.get(self.feed_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("rss_fetch_failed", source=self.source_name, error=str(exc))
            return []

        # response.content (bytes), never response.text -- load-bearing, do not
        # "simplify". feedparser sniffs the charset from the XML declaration
        # when handed bytes; hand it a str and the decoding has already
        # happened, badly. Airkule serves `text/xml` with NO charset parameter
        # and an `encoding="windows-1254"` declaration, so httpx falls back to
        # utf-8 and .text returns "THY TEKN?K'TEN YEN? HANGAR" -- while
        # .content parses as "THY TEKNİK'TEN YENİ HANGAR". Verified both ways.
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            logger.warning(
                "rss_parse_failed", source=self.source_name, error=str(parsed.get("bozo_exception"))
            )
            return []

        articles: list[RawArticle] = []
        blocked = 0
        for entry in parsed.entries:
            url = entry.get("link")
            title = entry.get("title")
            if not url or not title:
                continue
            # Blacklisted publishers are dropped here, before an Article row
            # exists -- the cheapest point in the pipeline and the only one
            # where the feed's own <source> metadata is still available. Both
            # candidates are checked because an aggregator item's own link is
            # a news.google.com wrapper that tells us nothing about who wrote
            # the piece; see app/ingest/blacklist.py.
            banned = blacklisted_domain(url) or blacklisted_domain(
                _entry_publisher_url(entry)
            )
            if banned:
                blocked += 1
                continue
            articles.append(
                RawArticle(
                    url=url,
                    title=title.strip(),
                    content=_entry_content(entry),
                    author=entry.get("author"),
                    published_at=_entry_published_at(entry),
                )
            )

        # A fetch that yields nothing usable is a broken source, not a quiet
        # success. Several publishers answer HTTP 200 with an HTML page where
        # the feed used to be -- SHGM and aviationturkey.com both do it today
        # (200 + text/html), and the dropped-candidate list is full of feeds
        # that returned "200 but 0 items". None of them can produce a garbage
        # article: an HTML shell leaves feedparser with no entries, and the
        # loop above already skips any entry missing a link or title. What was
        # missing is the alarm -- a rotted feed logged "rss_fetch_ok count=0"
        # forever and looked healthy on the dashboard. Warn instead, so a
        # source that silently dies is visible in the ingestion error log.
        if blocked:
            # Logged separately from the fetch summary so "how much Reddit is
            # still being offered to us" stays a readable number rather than a
            # silent subtraction -- if this ever drops to zero across every
            # aggregator, the blacklist has stopped earning its keep.
            logger.info(
                "rss_blacklisted_items_dropped",
                source=self.source_name,
                dropped=blocked,
                parsed_entries=len(parsed.entries),
            )

        if not articles:
            # A feed emptied *by the blacklist* is working as designed, not
            # rotted, so it must not raise the dead-source alarm below.
            if blocked:
                return []
            logger.warning(
                "rss_no_usable_entries",
                source=self.source_name,
                url=self.feed_url,
                parsed_entries=len(parsed.entries),
                content_type=response.headers.get("content-type"),
            )
            return []

        if self.item_cap is not None and len(articles) > self.item_cap:
            # Feeds are newest-first, so the cap keeps the freshest items.
            logger.info(
                "rss_item_cap_applied",
                source=self.source_name,
                returned=len(articles),
                kept=self.item_cap,
            )
            articles = articles[: self.item_cap]

        logger.info("rss_fetch_ok", source=self.source_name, count=len(articles))
        return articles
