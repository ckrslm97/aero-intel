"""British Airways (BA) scraper — canlı, otomatik (API → HTML).

Arama akışı ve HTML DOM ayrıştırma `BaseScraper`'ın paylaşımlı şablonundan gelir
(sağlam çerez onayı + form-hazır bekleme + jenerik DOM). BA yalnızca API/JSON
eşlemesini özelleştirir; şema bilinmiyorsa DOM yedeği devreye girer.

UYARI: Seçiciler ve JSON şeması canlıda doğrulanmalı:
`playwright codegen https://www.britishairways.com`
"""
from __future__ import annotations

from typing import Any

from core.models import Cabin, FareBrand
from core.ond import OND
from scrapers.base import BaseScraper
from scrapers.registry import register

_FEATURE_KEYWORDS = {
    "hand baggage": "baggage_cabin",
    "cabin bag": "baggage_cabin",
    "checked bag": "checked_baggage",
    "hold bag": "checked_baggage",
    "baggage": "checked_baggage",
    "seat": "seat_selection",
    "meal": "meal",
    "food": "meal",
    "refund": "refund",
    "change": "change",
    "avios": "miles",
    "tier points": "miles",
    "lounge": "lounge",
    "priority": "priority_boarding",
    "fast track": "fast_track",
    "wifi": "wifi",
}


@register
class BAScraper(BaseScraper):
    """British Airways fare family scraper (paylaşımlı şablon; DOM ağırlıklı)."""

    airline_code = "BA"
    source_label = "BA-site"
    feature_keywords = _FEATURE_KEYWORDS
    dom_currency = "GBP"

    def parse_api(self, captured: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        fares: list[FareBrand] = []
        for cap in captured:
            for offer in _iter_offers(cap.get("json")):
                name = offer.get("fareFamilyName") or offer.get("brandName") or offer.get("name")
                if not name:
                    continue
                price_block = offer.get("price") or offer.get("totalPrice") or {}
                if isinstance(price_block, (int, float, str)):
                    price_block = {"amount": price_block}
                fares.append(FareBrand(
                    cabin=_cabin(offer.get("cabin", offer.get("cabinClass", ""))),
                    fare_brand=str(name),
                    brand_code=str(offer.get("brandCode", "")),
                    booking_class=str(offer.get("bookingClass", "")),
                    price=self.parse_price(price_block.get("amount", price_block.get("value"))),
                    currency=str(price_block.get("currency", price_block.get("currencyCode", "GBP"))),
                    package_description=str(offer.get("description", "")),
                    source_url=cap.get("url", ""),
                ))
        return fares


def _cabin(raw: Any) -> str:
    m = {"ECONOMY": Cabin.ECONOMY.value, "M": Cabin.ECONOMY.value,
         "PREMIUM_ECONOMY": Cabin.PREMIUM_ECONOMY.value, "W": Cabin.PREMIUM_ECONOMY.value,
         "BUSINESS": Cabin.BUSINESS.value, "CLUB": Cabin.BUSINESS.value, "J": Cabin.BUSINESS.value,
         "FIRST": Cabin.FIRST.value, "F": Cabin.FIRST.value}
    return m.get(str(raw).upper(), Cabin.ECONOMY.value)


def _iter_offers(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("fareFamilies", "brands", "offers", "recommendations", "products", "fares"):
            val = data.get(key)
            if isinstance(val, list) and val:
                return [x for x in val if isinstance(x, dict)]
        for v in data.values():
            found = _iter_offers(v)
            if found:
                return found
    if isinstance(data, list):
        dicts = [x for x in data if isinstance(x, dict)]
        if any("fareFamilyName" in x or "brandName" in x for x in dicts):
            return dicts
    return []
