"""AJet's campaigns, from the CMS that feeds ajet.com.

www.ajet.com is behind DataDome and stays there. The gateway that supplies its
content is not behind anything at all: two unauthenticated POSTs, no cookies,
no TLS impersonation, no browser.

    POST https://gatewaycmsint.cloud.ajet.com/definition/Integration/getModelData
         {"templateKey": "WEBCURRENTANDPASTCAMPAIGNS"}
      -> 62 campaign records. Every text on them is an i18n KEY, not a string:
         CampaignName, CampaignText, TicketingDates, TravelDates, CampaignPath,
         plus IsCampaignActive and an Id.

    POST https://gatewaycmsint.cloud.ajet.com/definition/Integration/getLangSource
         {"platform": "WEBOUTSIDE", "langCode": "TR", "version": ""}
      -> ~6900 key/value pairs (about 4.8 MB) that resolve them.

Resolved, one active record looks like this -- and this is why AJet is the best
campaign source this product has:

    CampaignName    19 Mayıs'ta Gençlere Özel: Yurt İçi Uçuşlarda %30 İndirim
    TicketingDates  18-19 Mayıs 2026
    TravelDates     1 Eylül 2026 - 10 Kasım 2026
    CampaignPath    https://ajet.com/tr/kesfet/kampanyalar/19-mayista-...

The booking window and the travel window are *separate labelled fields*. That
is the distinction the entire four-column date schema exists to preserve, and
here the carrier states it rather than leaving it to be read out of a sentence.
So AJet takes the structured path (pipeline/campaign_extract.build_structured_campaign):
the deterministic date parser reads both windows, the rulepack still decides
whether each item is a fare campaign, `resolve_route` still refuses to invent a
scope -- and no LLM call is spent at all. A model asked to re-read
"TicketingDates: 18-19 Mayıs 2026" could only agree or be wrong.

Three deliberate omissions
--------------------------
**`WEBSPECIALDISCOUNTCAMPAIGNS` is never requested.** That template carries the
standing student/teacher/veteran discounts. They are evergreen offers, the
rulepack drops them, and the honest place to not ingest them is here rather
than three links later.

**Inactive records are dropped before anything else.** 62 records, ~34 active;
the rest are last year's campaigns kept for their detail pages. Publishing them
would fill the timeline with expired sales that `campaign_status` would then
have to label EXPIRED one by one.

**The 4.8 MB language file is never stored.** It is fetched once per run, read,
and dropped with the function's frame. Caching it across runs would mean
serving campaign names that are one deploy stale, and storing it would put a
5 MB blob in a schema whose largest table is a run log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.ingest.fetch import FetchResult, json_post
from app.pipeline.campaign_extract import StructuredCampaign, campaign_url

logger = get_logger(__name__)

SOURCE_NAME = "AJet kampanya sayfası"

GATEWAY_BASE = "https://gatewaycmsint.cloud.ajet.com/definition/Integration"
MODEL_DATA_URL = f"{GATEWAY_BASE}/getModelData"
LANG_SOURCE_URL = f"{GATEWAY_BASE}/getLangSource"

#: Current + past campaigns. The evergreen-discount template is deliberately
#: absent -- see the module docstring.
CAMPAIGN_TEMPLATE_KEY = "WEBCURRENTANDPASTCAMPAIGNS"
EXCLUDED_TEMPLATE_KEYS: tuple[str, ...] = ("WEBSPECIALDISCOUNTCAMPAIGNS",)

LANG_PLATFORM = "WEBOUTSIDE"
LANG_CODE = "TR"

_PCT = re.compile(r"%\s*(\d{1,3})")
#: "1.449 TL", "29 USD", "699,90 TRY". Turkish writes thousands with a dot and
#: decimals with a comma, which is the inverse of the literal Python reads, so
#: both separators are normalised before float() sees the string.
_PRICE = re.compile(
    r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)\s*(TL|TRY|USD|EUR|₺|\$|€)",
    re.IGNORECASE,
)
_CURRENCY_ALIASES = {"TL": "TRY", "₺": "TRY", "$": "USD", "€": "EUR"}


@dataclass(frozen=True)
class AjetHarvest:
    """What one gateway sweep produced.

    `fetch` is the shape every other carrier hands the scanner -- text to hash,
    a status, an error -- so AJet needs no branch in `deep_scan`'s
    classification. `entries` is the structured half, which only the structured
    persist path reads.
    """

    fetch: FetchResult
    entries: tuple[StructuredCampaign, ...] = ()


def strip_markup(value: str | None) -> str:
    """CMS values arrive with `<p>`/`<strong>`/`&nbsp;` in them. Take the text."""
    if not value:
        return ""
    if "<" not in value:
        return " ".join(value.split())
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return " ".join(text.replace("\xa0", " ").split())


def parse_discount_pct(text: str) -> int | None:
    match = _PCT.search(text or "")
    if match is None:
        return None
    value = int(match.group(1))
    return value if 0 < value <= 100 else None


def parse_price_floor(text: str) -> tuple[float | None, str | None]:
    """"29 USD'den başlayan" -> (29.0, "USD"). (None, None) when unstated."""
    match = _PRICE.search(text or "")
    if match is None:
        return None, None
    raw, symbol = match.groups()
    normalized = raw.replace(".", "").replace(",", ".")
    try:
        amount = float(normalized)
    except ValueError:
        return None, None
    currency = _CURRENCY_ALIASES.get(symbol.upper(), symbol.upper())
    return amount, currency


def _campaign_type_for(discount_pct: int | None, price_floor: float | None) -> str | None:
    """The taxonomy slug the *shape of the offer* forces, or None.

    A rate is a PERCENT_DISCOUNT and a floor price is a FIXED_FARE; anything
    finer (FLASH_SALE, SUMMER_SALE, a calendar peg) would be reading intent
    into a title, which is the kind of guess the closed taxonomy exists to stop.
    Null is a legitimate value for this column and renders as "—".
    """
    if discount_pct is not None:
        return "PERCENT_DISCOUNT"
    if price_floor is not None:
        return "FIXED_FARE"
    return None


def resolve_records(
    records: list[dict], lang_keys: dict[str, str], *, page_url: str
) -> list[StructuredCampaign]:
    """Active CMS records -> structured campaigns, i18n keys already resolved.

    A record whose name key resolves to nothing is skipped rather than filed
    under its own key: "campaigns_hub_active_campaign_title_16_may_2026_dom" on
    an analyst's screen is worse than one campaign missing.
    """
    entries: list[StructuredCampaign] = []
    seen_urls: set[str] = set()

    for record in records:
        if not record.get("IsCampaignActive"):
            continue

        name = strip_markup(lang_keys.get(record.get("CampaignName") or ""))
        if not name:
            logger.info("ajet_campaign_unresolved_name", key=record.get("CampaignName"))
            continue

        body = strip_markup(lang_keys.get(record.get("CampaignText") or ""))
        ticketing = strip_markup(lang_keys.get(record.get("TicketingDates") or "")) or None
        travel = strip_markup(lang_keys.get(record.get("TravelDates") or "")) or None

        detail = (lang_keys.get(record.get("CampaignPath") or "") or "").strip()
        if detail.startswith("https://"):
            url = detail
        else:
            # No detail link resolved: fall back to the hub page plus the
            # campaign's own fragment, which is the same idempotency key the
            # LLM path uses (campaign_extract's module docstring).
            url = campaign_url(page_url, name)
        if url in seen_urls:
            # The CMS reuses a detail path across two records now and then.
            # `promotions.url` is UNIQUE, so the fragment is what separates them.
            url = campaign_url(url, name)
        seen_urls.add(url)

        offer_text = f"{name} {body}"
        discount_pct = parse_discount_pct(offer_text)
        price_floor, currency = parse_price_floor(offer_text)

        entries.append(
            StructuredCampaign(
                campaign_name=name[:300],
                url=url[:500],
                body_text=body,
                booking_text=ticketing,
                travel_text=travel,
                discount_pct=discount_pct,
                price_floor=price_floor,
                currency=currency,
                campaign_type=_campaign_type_for(discount_pct, price_floor),
                extra_attrs={"cms_id": record.get("Id")} if record.get("Id") else {},
            )
        )

    return entries


def digest_text(entries: list[StructuredCampaign]) -> str:
    """The text that gets hashed for change detection.

    Assembled from the resolved fields rather than from the raw JSON, and in
    the CMS's own record order, so it is stable: a re-ordered response, a new
    image URL or a changed `CampaignOrder` must not read as a changed campaign
    and spend a run's work. What it does contain is every field that would
    change a published row.
    """
    blocks: list[str] = []
    for entry in entries:
        lines = [entry.campaign_name]
        if entry.body_text:
            lines.append(entry.body_text)
        if entry.booking_text:
            lines.append(f"Bilet alış tarihleri: {entry.booking_text}")
        if entry.travel_text:
            lines.append(f"Seyahat tarihleri: {entry.travel_text}")
        lines.append(entry.url)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def harvest(page_url: str, *, client: httpx.AsyncClient | None = None) -> AjetHarvest:
    """Both POSTs, resolved and reduced. Never raises.

    Ordered model-data first: it is 54 KB against the language file's 4.8 MB,
    so a gateway that has gone away costs us the small request rather than the
    large one.
    """
    model = await json_post(MODEL_DATA_URL, {"templateKey": CAMPAIGN_TEMPLATE_KEY}, client=client)
    if model.payload is None:
        return AjetHarvest(fetch=model)

    records = model.payload.get("content") if isinstance(model.payload, dict) else None
    if not isinstance(records, list):
        return AjetHarvest(
            fetch=FetchResult(
                text=None,
                http_status=model.http_status,
                error="CMS yanıtında `content` listesi yok.",
            )
        )

    lang = await json_post(
        LANG_SOURCE_URL,
        {"platform": LANG_PLATFORM, "langCode": LANG_CODE, "version": ""},
        client=client,
    )
    lang_keys: dict = {}
    if isinstance(lang.payload, dict):
        content = lang.payload.get("content")
        if isinstance(content, dict) and isinstance(content.get("langKeys"), dict):
            lang_keys = content["langKeys"]
    if not lang_keys:
        # Without the dictionary every name is an i18n key. Publishing keys
        # would be worse than publishing nothing, so this is a failed read.
        return AjetHarvest(
            fetch=FetchResult(
                text=None,
                http_status=lang.http_status,
                error=lang.error or "Dil kaynağı çözümlenemedi; kampanya adları anahtar olarak kalırdı.",
                timed_out=lang.timed_out,
            )
        )

    entries = resolve_records(records, lang_keys, page_url=page_url)
    logger.info(
        "ajet_campaigns_harvested",
        records=len(records),
        active=len(entries),
        lang_keys=len(lang_keys),
    )
    if not entries:
        # 200 with nothing readable on it. Recorded as a failed read rather
        # than as "AJet has no campaigns": the second reading would baseline an
        # empty page and stop asking.
        return AjetHarvest(
            fetch=FetchResult(
                text=None,
                http_status=model.http_status,
                error=f"CMS {len(records)} kayıt döndürdü, aktif kampanya yok.",
            )
        )

    return AjetHarvest(
        fetch=FetchResult(text=digest_text(entries), http_status=model.http_status),
        entries=tuple(entries),
    )
