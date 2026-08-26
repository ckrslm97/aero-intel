"""Pegasus (PC) scraper — canlı, otomatik (API → HTML).

Düşük maliyetli taşıyıcı; "Essentials / Advantage / Extra" paketleri. Arama akışı
ve DOM ayrıştırma `BaseScraper`'ın paylaşımlı şablonundan gelir.

UYARI: Seçiciler ve JSON şeması canlıda doğrulanmalı:
`playwright codegen https://www.flypgs.com/en`
"""
from __future__ import annotations

from typing import Any

from core.models import Cabin, FareBrand
from core.ond import OND
from scrapers.base import BaseScraper
from scrapers.registry import register

_FEATURE_KEYWORDS = {
    "cabin bag": "baggage_cabin",
    "hand baggage": "baggage_cabin",
    "carry-on": "baggage_cabin",
    "checked": "checked_baggage",
    "baggage": "checked_baggage",
    "seat": "seat_selection",
    "meal": "meal",
    "bolbol": "miles",
    "refund": "refund",
    "change": "change",
    "flexibility": "change",
    "priority": "priority_boarding",
    "fast track": "fast_track",
    "wifi": "wifi",
    "pet": "pet",
    "sport": "sport_equipment",
}


@register
class PegasusScraper(BaseScraper):
    """Pegasus fare package scraper (paylaşımlı şablon; DOM ağırlıklı)."""

    airline_code = "PC"
    source_label = "PC-site"
    feature_keywords = _FEATURE_KEYWORDS
    dom_currency = "TRY"

    def parse_api(self, captured: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        fares: list[FareBrand] = []
        for cap in captured:
            for offer in _iter_offers(cap.get("json")):
                name = offer.get("packageName") or offer.get("brandName") or offer.get("name")
                if not name:
                    continue
                price_block = offer.get("price") or offer.get("totalPrice") or {}
                if isinstance(price_block, (int, float, str)):
                    price_block = {"amount": price_block}
                fares.append(FareBrand(
                    cabin=Cabin.ECONOMY.value,
                    fare_brand=str(name),
                    brand_code=str(offer.get("packageCode", offer.get("brandCode", ""))),
                    booking_class=str(offer.get("bookingClass", "")),
                    price=self.parse_price(price_block.get("amount", price_block.get("value"))),
                    currency=str(price_block.get("currency", price_block.get("currencyCode", "TRY"))),
                    package_description=str(offer.get("description", "")),
                    source_url=cap.get("url", ""),
                ))
        return fares


def _iter_offers(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("packages", "fareFamilies", "brands", "offers", "products", "bundles"):
            val = data.get(key)
            if isinstance(val, list) and val:
                return [x for x in val if isinstance(x, dict)]
        for v in data.values():
            found = _iter_offers(v)
            if found:
                return found
    if isinstance(data, list):
        dicts = [x for x in data if isinstance(x, dict)]
        if any("packageName" in x or "brandName" in x for x in dicts):
            return dicts
    return []
