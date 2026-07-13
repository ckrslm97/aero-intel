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

USER_AGENT = "AeroIntelBot/0.1 (+aviation intelligence newsroom; contact: newsroom@aerointel.local)"
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


class RssSourceAdapter:
    def __init__(self, source_name: str, feed_url: str):
        self.source_name = source_name
        self.feed_url = feed_url

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

        logger.info("rss_fetch_ok", source=self.source_name, count=len(articles))
        return articles
