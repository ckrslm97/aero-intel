"""Lufthansa (LH) scraper — canlı, otomatik (API → HTML).

LH "Choose your fare" ekranı fare family verisini hem XHR/JSON (offers/
fare-families) hem de görünür kartlar olarak sunar. `BaseScraper` şablonu
önce API, sonra DOM dener.

UYARI: Seçiciler ve JSON şeması canlı sitede doğrulanmalıdır:
`playwright codegen https://www.lufthansa.com`
"""
from __future__ import annotations

from typing import Any

from core.models import Cabin, FareBrand, FeatureState
from core.ond import OND
from scrapers.base import BaseScraper
from scrapers.registry import register


_FEATURE_KEYWORDS: dict[str, str] = {
    "carry-on": "baggage_cabin",
    "hand baggage": "baggage_cabin",
    "checked bag": "checked_baggage",
    "baggage": "checked_baggage",
    "seat": "seat_selection",
    "meal": "meal",
    "rebooking": "change",
    "change": "change",
    "refund": "refund",
    "cancellation": "refund",
    "miles": "miles",
    "award miles": "miles",
    "lounge": "lounge",
    "priority": "priority_boarding",
    "fast lane": "fast_track",
    "wi-fi": "wifi",
    "wifi": "wifi",
}

_CABIN_MAP = {
    "ECONOMY": Cabin.ECONOMY.value,
    "PREMIUM_ECONOMY": Cabin.PREMIUM_ECONOMY.value,
    "PREMIUM": Cabin.PREMIUM_ECONOMY.value,
    "BUSINESS": Cabin.BUSINESS.value,
    "FIRST": Cabin.FIRST.value,
}


@register
class LHScraper(BaseScraper):
    """Lufthansa fare family scraper (otomatik API→HTML)."""

    airline_code = "LH"
    source_label = "LH-site"
    #: DOM özellik satırı → standart alan (jenerik parse_dom kullanır).
    feature_keywords = _FEATURE_KEYWORDS

    # `open_search` ve `parse_dom` `BaseScraper`'ın paylaşımlı şablonundan gelir
    # (çerez onayı + form-hazır bekleme). LH yalnızca API/JSON eşlemesini özelleştirir.

    # ---- 1) API ---- #
    def parse_api(self, captured: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        fares: list[FareBrand] = []
        for cap in captured:
            for offer in _iter_offers(cap.get("json")):
                fb = self._offer_to_fare(offer, cap.get("url", ""))
                if fb:
                    fares.append(fb)
        return fares

    def _offer_to_fare(self, offer: dict[str, Any], url: str) -> FareBrand | None:
        name = offer.get("fareFamilyName") or offer.get("brandName") or offer.get("name")
        if not name:
            return None
        price_block = offer.get("price") or offer.get("totalPrice") or {}
        if isinstance(price_block, (int, float, str)):
            price_block = {"amount": price_block}
        fb = FareBrand(
            cabin=_CABIN_MAP.get(str(offer.get("cabinClass", offer.get("cabin", ""))).upper(),
                                 Cabin.ECONOMY.value),
            fare_brand=str(name),
            brand_code=str(offer.get("fareFamilyCode", offer.get("brandCode", ""))),
            booking_class=str(offer.get("bookingClass", "")),
            price=self.parse_price(price_block.get("amount", price_block.get("total"))),
            currency=str(price_block.get("currency", price_block.get("currencyCode", ""))),
            package_description=str(offer.get("description", "")),
            source_url=url,
        )
        for attr in offer.get("services", offer.get("attributes", []) or []):
            self._map_json_feature(attr, fb)
        return fb

    def _map_json_feature(self, attr: Any, fb: FareBrand) -> None:
        if not isinstance(attr, dict):
            return
        label = str(attr.get("name", attr.get("code", ""))).lower()
        field_name = next((v for k, v in _FEATURE_KEYWORDS.items() if k in label), None)
        if not field_name:
            return
        status = str(attr.get("status", attr.get("availability", ""))).upper()
        state = {
            "INCLUDED": FeatureState.INCLUDED, "FREE": FeatureState.INCLUDED,
            "CHARGEABLE": FeatureState.PAID, "PAID": FeatureState.PAID,
            "NOT_AVAILABLE": FeatureState.NOT_INCLUDED, "NOT_OFFERED": FeatureState.NOT_INCLUDED,
        }.get(status, FeatureState.UNKNOWN)
        fb.set_feature(field_name, state, detail=str(attr.get("value", "")))


def _iter_offers(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("fareFamilies", "fares", "offers", "recommendations", "products"):
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
