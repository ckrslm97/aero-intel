"""Singapore Airlines' fare deals, from the endpoint its own homepage calls.

    GET https://www.singaporeair.com/home/getPromotions.form?locale=en_UK&country=GB
      -> {"promos": {...}, "promoVO": [{"city": "MAN-Manchester",
                                        "cityVO": [{...}, ...]}, ...]}

Each entry in `cityVO` is one route-level lead-in fare:

    faredealOriginAirportCode       MAN
    faredealDestinationAirportCode  SIN
    cabin                           Economy
    currency / price                GBP / 750
    shareurl                        /en-gb/flights-from-manchester-to-singapore
    priceSource                     fareCache

No wall of any kind, no JavaScript, no prose. So this is the structured path
(pipeline/campaign_extract.build_structured_campaign) with no LLM call: both
ends are IATA codes, so `resolve_route` returns a real OND scope rather than
guessing at one, and the price is a number in a field named `price`.

**What these are, and what they are not.** `priceSource: fareCache` is the
carrier telling us this is the cheapest fare currently loaded for the route,
not a campaign with a sale window. There is no booking window because there is
no sale; the fare is what it is until it moves. Two consequences, both taken
deliberately rather than papered over:

  * Every row is filed `EVERGREEN_OFFER`, stated from the shape of the feed
    rather than judged from words. `validate_campaign` is not asked, because
    the question it answers -- "does this marketing copy describe a fare
    campaign?" -- has no copy to read here, and inventing one to feed it would
    be asking a rulepack about a sentence we wrote ourselves.
  * With no sale window the confidence scorer's completeness cap holds these at
    the `medium` band at best (pipeline/confidence.py). They are visible, they
    are filterable by `business_class`, and they can never be presented as
    something the system is sure is a live campaign. That is the correct
    outcome: "SQ is selling MAN-SIN from GBP 750 today" is real competitive
    intelligence for a revenue desk, and it is not a sale announcement.

**One row per route, not one per cabin.** The feed lists every route three
times -- Economy, Premium Economy, Business -- and `promo_dedup.is_duplicate`
correctly regards "Manchester-Singapore Economy" and "Manchester-Singapore
Business" as one campaign: same carrier, near-identical titles, overlapping
(absent) windows. Rather than fight a layer that is doing its job, only the
route's lead-in fare is published -- the cheapest cabin, which is what a "from
GBP 750" deal means anyway -- with the cabin recorded on the row. Tracking each
cabin separately would need a documented exemption from the dedup layer, which
is a bigger change than this source is worth today.

**One market for now.** `country=GB` returns 69 deals from a single origin. The
parameter pair (`locale`, `country`) is what selects the market, so iterating
it -- en_UK/GB, en_US/US, and a TR market if SQ publishes one -- would multiply
coverage at one cheap request each. Deliberately not done yet: it also
multiplies the row count on a class of record that is already the least
campaign-like thing in the table, and one market is enough to find out whether
these earn their space at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.logging import get_logger
from app.ingest.fetch import FetchResult, json_get
from app.pipeline.campaign_extract import StructuredCampaign, campaign_url

logger = get_logger(__name__)

SOURCE_NAME = "Singapore Airlines fırsat fiyatları"
SITE_BASE = "https://www.singaporeair.com"

#: Every row from this feed. Stated rather than judged -- see the module
#: docstring.
BUSINESS_CLASS = "EVERGREEN_OFFER"
#: A stated floor price with no rate and no window is a fixed fare, which is
#: the one slug in the taxonomy that describes this without adding anything.
CAMPAIGN_TYPE = "FIXED_FARE"


@dataclass(frozen=True)
class SqHarvest:
    fetch: FetchResult
    entries: tuple[StructuredCampaign, ...] = ()


def _city_label(raw: str | None) -> str | None:
    """"MAN-Manchester" -> "Manchester". The code is already its own field."""
    if not raw:
        return None
    _, _, name = raw.partition("-")
    return (name or raw).strip() or None


def _price(raw) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def map_fare_deals(payload: dict, *, page_url: str) -> list[StructuredCampaign]:
    """The JSON body -> structured campaigns. Never raises on a shape change.

    A deal missing either airport code is skipped: the whole value of this
    source is that its route is stated rather than inferred, and a half-stated
    route would be published as an OND we made up one end of.
    """
    groups = payload.get("promoVO") if isinstance(payload, dict) else None
    if not isinstance(groups, list):
        return []

    # Keyed by route, holding the cheapest cabin seen for it. Insertion order
    # is the feed's own order, which is SQ's own priority ordering.
    lead_in: dict[tuple[str, str], tuple[float, StructuredCampaign]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        origin_city = _city_label(group.get("city"))
        deals = group.get("cityVO")
        if not isinstance(deals, list):
            continue

        for deal in deals:
            if not isinstance(deal, dict):
                continue
            origin = (deal.get("faredealOriginAirportCode") or "").strip().upper()
            destination = (deal.get("faredealDestinationAirportCode") or "").strip().upper()
            if len(origin) != 3 or len(destination) != 3:
                continue

            price = _price(deal.get("price"))
            currency = (deal.get("currency") or "").strip().upper() or None
            cabin = (deal.get("cabinDesc") or deal.get("cabin") or "").strip() or None
            dest_city = (deal.get("destinationCityName") or "").strip() or destination
            from_city = origin_city or origin

            # Route first, and as little boilerplate as the headline can carry.
            # `promo_dedup.is_duplicate` matches on Jaccard over stemmed title
            # tokens at 0.55, and every extra shared word ("Economy",
            # "başlangıç fiyatı") pushes two *different* routes over that line:
            # "Manchester–Singapore Economy: 750 GBP başlangıç fiyatı" and
            # "Manchester–Bangkok Economy: 704 GBP başlangıç fiyatı" score
            # 0.556 and merge. Route plus price scores 0.33 and does not. The
            # cabin still reaches the reader -- through the summary and
            # `attrs_json.cabin` -- and the price is what makes the headline
            # worth reading at all.
            #
            # An en dash rather than a hyphen: `_PAIR_SEPARATOR` in
            # campaign_extract splits on both, and the title is also read by a
            # human, for whom "Manchester–Singapore" is the conventional form.
            name = f"{from_city}–{dest_city}"
            if price is not None and currency:
                name = f"{name}: {price:g} {currency}"

            share = (deal.get("shareurl") or "").strip()
            base = f"{SITE_BASE}{share}" if share.startswith("/") else (share or page_url)
            # A fragment even though `base` is already a real page: SQ serves
            # every route from one share link and `promotions.url` is UNIQUE.
            #
            # Built from the route, NOT from the title -- the title carries the
            # price, and this feed exists precisely because prices move. Keying
            # on the title would make every fare change a new row instead of a
            # version on the existing one, which is the opposite of what a
            # price tracker is for.
            url = campaign_url(base, f"{origin} {destination}")

            entry = StructuredCampaign(
                campaign_name=name[:300],
                url=url[:500],
                body_text=(
                    f"{from_city} ({origin}) - {dest_city} ({destination}) "
                    f"{cabin or ''}".strip()
                ),
                price_floor=price,
                currency=currency,
                cabin=cabin,
                origin=origin,
                destination=destination,
                campaign_type=CAMPAIGN_TYPE,
                business_class=BUSINESS_CLASS,
                summary_prefix=f"{cabin} kabini" if cabin else None,
                extra_attrs={
                    key: value
                    for key, value in {
                        "price_source": deal.get("priceSource"),
                        "destination_country": deal.get("destinationCountry"),
                    }.items()
                    if value
                },
            )

            # A deal with no price cannot be compared, so it only holds the
            # route if nothing priced has claimed it.
            rank = price if price is not None else float("inf")
            held = lead_in.get((origin, destination))
            if held is None or rank < held[0]:
                lead_in[(origin, destination)] = (rank, entry)

    return [entry for _rank, entry in lead_in.values()]


def digest_text(entries: list[StructuredCampaign]) -> str:
    """What gets hashed. Prices are the point, so they are in it: a fare that
    moves is a changed row, and this feed exists to notice that."""
    return "\n".join(
        f"{entry.campaign_name} | {entry.body_text} | {entry.url}" for entry in entries
    )


async def harvest(page_url: str, *, client: httpx.AsyncClient | None = None) -> SqHarvest:
    """Fetch and map. Never raises."""
    result = await json_get(page_url, client=client)
    if not isinstance(result.payload, dict):
        return SqHarvest(fetch=result)

    entries = map_fare_deals(result.payload, page_url=page_url)
    logger.info("sq_fare_deals_harvested", url=page_url, deals=len(entries))
    if not entries:
        return SqHarvest(
            fetch=FetchResult(
                text=None,
                http_status=result.http_status,
                error="Fırsat listesi boş döndü.",
            )
        )
    return SqHarvest(
        fetch=FetchResult(text=digest_text(entries), http_status=result.http_status),
        entries=tuple(entries),
    )
