"""RSS/Atom source adapter -- covers every free aviation feed (news sites, ACI,
Eurocontrol, FAA, ICAO, ...). Network or parse failures are caught and logged so a
single broken feed never blocks the rest of the ingestion run.
"""
from datetime import datetime, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.ingest.base import RawArticle

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


def _strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    return BeautifulSoup(raw_html, "lxml").get_text(separator=" ", strip=True)


def _entry_content(entry: feedparser.FeedParserDict) -> str:
    if "content" in entry and entry.content:
        return _strip_html(entry.content[0].get("value", ""))
    return _strip_html(entry.get("summary", ""))


def _entry_published_at(entry: feedparser.FeedParserDict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


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

        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            logger.warning(
                "rss_parse_failed", source=self.source_name, error=str(parsed.get("bozo_exception"))
            )
            return []

        articles: list[RawArticle] = []
        for entry in parsed.entries:
            url = entry.get("link")
            title = entry.get("title")
            if not url or not title:
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
