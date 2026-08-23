"""Direct scraping of airline campaign pages.

Scrapeability was verified with curl before a line of this was written, and
only the carrier that actually serves campaign data is scraped:

  * Pegasus (PC) -- https://www.flypgs.com/kampanyali-ucak-biletleri/aktif-kampanyalar
    WORKS. Plain server-rendered HTML, HTTP 200 in ~0.3s, ~160KB. Every
    campaign is a `.current-cmps-list__item` carrying its title, a description,
    a canonical detail link, and -- the part that makes this worth doing -- a
    `<time data-time="02 Mayıs 2026 / 30 Kasım 2026">` validity range. That is
    an airline stating its own sale window, which is strictly better than
    anything an extractor can recover from a news report about it.

Deliberately NOT scraped, because they cannot be:

  * Turkish Airlines (TK) -- https://www.turkishairlines.com/tr-tr/ucus-firsatlari/
    BOT-WALLED. Over HTTP/2 the connection is reset mid-stream
    (`INTERNAL_ERROR`, 0 bytes); forced to HTTP/1.1 with full browser headers
    it accepts the connection and then never responds (20s timeout, 0 bytes).
    That is TLS/behavioural fingerprinting, not a missing header -- no
    combination of User-Agent, Accept or Accept-Language gets past it. Same
    result on the alternate /tr-tr/promosyonlar/ path.
  * AJet (VF) -- https://www.ajet.com/tr/kampanyalar (and /tr/firsatlar)
    BOT-WALLED, identically: HTTP/2 stream reset, HTTP/1.1 hang.

Both would need a real headless browser. Shipping a requests-based scraper for
them would produce a module that returns zero rows forever while looking like
working coverage, which is worse than not having one -- so TK and AJet reach
the campaign timeline through the article-derived path
(app/pipeline/promotions.py), which is the backbone for exactly this reason.

Also checked and skipped: Pegasus's press room
(https://www.flypgs.com/basin-odasi/duyurular) is equally server-rendered, but
its `.proclamation__item` list is operational notices -- cancelled flights,
airspace closures -- not campaigns. Scraping it would fill the campaign table
with disruption announcements.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.promotion import Promotion
from app.pipeline.promo_dedup import PromoCandidate, find_duplicate, merge_candidate
from app.pipeline.promotions import TR_MONTHS, find_dates

logger = get_logger(__name__)

PEGASUS_BASE = "https://www.flypgs.com"
PEGASUS_CAMPAIGNS = f"{PEGASUS_BASE}/kampanyali-ucak-biletleri/aktif-kampanyalar"

SOURCE_NAME = "Pegasus kampanya sayfası"

# flypgs serves the campaign list to a default httpx UA too, but the rest of
# the site is behind Dynatrace and a browser UA costs nothing.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = httpx.Timeout(25.0)

_PCT = re.compile(r"%\s*(\d{1,3})")
_MONTHS_RE = "|".join(TR_MONTHS)


@dataclass(frozen=True)
class ScrapedPromo:
    airline_code: str
    airline_name: str
    title_tr: str
    summary_tr: str
    url: str
    sale_starts: date | None
    sale_ends: date | None
    discount_pct: int | None


def parse_validity(raw: str | None) -> tuple[date | None, date | None]:
    """"02 Mayıs 2026 / 30 Kasım 2026" -> (date, date).

    Pegasus writes this range with a slash, but has also used a dash, so the
    separator is not what is matched on -- the two dates are simply read in
    order. One date alone is treated as the END of an open-ended run, which is
    how the page uses it ("30 Kasım 2026'ya kadar"); guessing a start would put
    the bar somewhere the airline never said it was.
    """
    if not raw:
        return None, None
    dates = [value for _, value in find_dates(raw)]
    if len(dates) >= 2:
        first, second = dates[0], dates[1]
        return (first, second) if second >= first else (second, first)
    if len(dates) == 1:
        return None, dates[0]
    return None, None


def parse_pegasus(html: str) -> list[ScrapedPromo]:
    """Read the campaign cards out of the Aktif Kampanyalar page.

    Every field is looked up defensively and a card missing a title is skipped
    rather than inserted blank: this is someone else's markup and it will
    change without warning. A class rename costs us the run's rows and logs it,
    it never raises.
    """
    soup = BeautifulSoup(html, "html.parser")
    promos: list[ScrapedPromo] = []

    for item in soup.select(".current-cmps-list__item"):
        title_el = item.select_one(".current-cmps-list__title")
        if title_el is None:
            continue
        title = " ".join(title_el.get_text(" ", strip=True).split())
        if not title:
            continue

        desc_el = item.select_one(".current-cmps-list__description")
        # The description node also wraps the date block; take only its own
        # text so "GEÇERLİLİK TARİHİ" doesn't end up inside the summary.
        summary = ""
        if desc_el is not None:
            parts = [
                str(node).strip()
                for node in desc_el.contents
                if isinstance(node, str) and node.strip()
            ]
            summary = " ".join(" ".join(parts).split())

        time_el = item.select_one(".current-cmps-list__date")
        raw_range = None
        if time_el is not None:
            raw_range = time_el.get("data-time") or time_el.get_text(" ", strip=True)
        sale_starts, sale_ends = parse_validity(raw_range)

        link_el = item.select_one(".current-cmps-list__detail__link")
        href = link_el.get("href") if link_el is not None else None
        if not href:
            continue
        url = href if href.startswith("http") else f"{PEGASUS_BASE}{href}"

        pct_match = _PCT.search(f"{title} {summary}")
        discount = None
        if pct_match:
            value = int(pct_match.group(1))
            if 0 < value <= 100:
                discount = value

        promos.append(
            ScrapedPromo(
                airline_code="PC",
                airline_name="Pegasus Airlines",
                title_tr=title[:300],
                summary_tr=summary,
                url=url[:500],
                sale_starts=sale_starts,
                sale_ends=sale_ends,
                discount_pct=discount,
            )
        )

    return promos


async def fetch_pegasus(client: httpx.AsyncClient) -> list[ScrapedPromo]:
    response = await client.get(PEGASUS_CAMPAIGNS)
    response.raise_for_status()
    return parse_pegasus(response.text)


async def scrape_promotions(
    db: AsyncSession, client: httpx.AsyncClient | None = None
) -> dict:
    """Fetch every scrapeable carrier's campaign page and upsert the rows.

    Idempotent by campaign URL. A refresh updates dates in place -- Pegasus
    extends campaigns without changing their URL, and a timeline showing last
    month's end date for a live campaign is worse than one showing none.

    A campaign that has no row under this URL may still be in the table under
    another one: the article-derived path (app/pipeline/promotions.py) files the
    same campaign under the URL of the news report about it. So a URL miss is
    checked against app/pipeline/promo_dedup before it becomes an insert, and a
    match is merged -- the airline's dates and canonical link win, the article's
    summary and the earlier sighting survive.
    """
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": BROWSER_UA, "Accept-Language": "tr-TR,tr;q=0.9"},
            follow_redirects=True,
        )

    result = {"fetched": 0, "inserted": 0, "updated": 0, "merged": 0, "errors": {}}
    try:
        try:
            scraped = await fetch_pegasus(client)
        except (httpx.HTTPError, ValueError) as exc:
            # One carrier's site being down costs that carrier's rows, never
            # the run -- and the existing rows stay exactly as they were.
            logger.warning("promo_scrape_source_failed", source="pegasus", error=str(exc))
            result["errors"]["pegasus"] = str(exc)
            scraped = []

        result["fetched"] = len(scraped)
        now = datetime.now(timezone.utc)

        for promo in scraped:
            existing = (
                await db.execute(select(Promotion).where(Promotion.url == promo.url))
            ).scalar_one_or_none()
            if existing is None:
                candidate = PromoCandidate(
                    airline_code=promo.airline_code,
                    airline_name=promo.airline_name,
                    title_tr=promo.title_tr,
                    summary_tr=promo.summary_tr,
                    url=promo.url,
                    source_name=SOURCE_NAME,
                    detected_at=now,
                    discount_pct=promo.discount_pct,
                    sale_starts=promo.sale_starts,
                    sale_ends=promo.sale_ends,
                )
                twin = await find_duplicate(db, candidate)
                if twin is not None:
                    # Same campaign, already on the timeline under the news
                    # report's URL. Take it over rather than drawing it twice.
                    merge_candidate(twin, candidate)
                    await db.flush()
                    result["merged"] += 1
                    continue
                db.add(
                    Promotion(
                        airline_code=promo.airline_code,
                        airline_name=promo.airline_name,
                        title_tr=promo.title_tr,
                        summary_tr=promo.summary_tr,
                        discount_pct=promo.discount_pct,
                        markets=None,
                        sale_starts=promo.sale_starts,
                        sale_ends=promo.sale_ends,
                        travel_starts=None,
                        travel_ends=None,
                        url=promo.url,
                        source_name=SOURCE_NAME,
                        region=None,
                        # First sighting: this is a scrape, so "when we saw it"
                        # is genuinely now. That is what makes the 48h banner
                        # fire the first run after a campaign goes live.
                        detected_at=now,
                    )
                )
                # Flushed as we go so the duplicate check above sees rows this
                # same run inserted: one page can list a campaign twice.
                await db.flush()
                result["inserted"] += 1
            else:
                existing.title_tr = promo.title_tr
                existing.summary_tr = promo.summary_tr
                existing.discount_pct = promo.discount_pct
                existing.sale_starts = promo.sale_starts
                existing.sale_ends = promo.sale_ends
                # detected_at is deliberately NOT touched: re-seeing a campaign
                # is not detecting it, and refreshing it would keep an
                # eight-month-old campaign permanently badged "Yeni".
                result["updated"] += 1

        await db.commit()
    finally:
        if owns_client:
            await client.aclose()

    logger.info("promotions_scraped", **{k: v for k, v in result.items() if k != "errors"})
    return result
