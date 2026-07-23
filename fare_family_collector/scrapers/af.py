"""Air France (AF) scraper — canlı, otomatik (API → HTML).

AF fare family verisi ağırlıklı olarak XHR/JSON ile döner; bu yüzden
`parse_api` birincil, `parse_dom` yedektir. `BaseScraper` şablonu sırayı yönetir.

UYARI: Gerçek JSON şeması ve seçiciler siteye özeldir; canlı yanıt
`playwright codegen https://www.airfrance.com` ile doğrulanmalıdır.
"""
from __future__ import annotations

from typing import Any

from core.models import Cabin, FareBrand, FeatureState
from core.ond import OND
from scrapers.base import BaseScraper
from scrapers.registry import register


# JSON'daki kabin kodlarını standart kabinlere eşle.
_CABIN_MAP = {
    "ECONOMY": Cabin.ECONOMY.value,
    "PREMIUM": Cabin.PREMIUM_ECONOMY.value,
    "PREMIUM_ECONOMY": Cabin.PREMIUM_ECONOMY.value,
    "BUSINESS": Cabin.BUSINESS.value,
    "FIRST": Cabin.FIRST.value,
}

# JSON attribute kodu → standart özellik alanı (API/JSON yolu için, UPPER_SNAKE).
_ATTR_MAP = {
    "CABIN_BAGGAGE": "baggage_cabin",
    "CHECKED_BAGGAGE": "checked_baggage",
    "BAGGAGE": "checked_baggage",
    "SEAT": "seat_selection",
    "SEAT_SELECTION": "seat_selection",
    "MEAL": "meal",
    "REFUND": "refund",
    "CHANGE": "change",
    "MILES": "miles",
    "LOUNGE": "lounge",
    "PRIORITY": "priority_boarding",
    "FAST_TRACK": "fast_track",
    "WIFI": "wifi",
}

# DOM özellik satırı metni → standart alan (HTML yolu için, küçük harf substring).
# Jenerik `BaseScraper.parse_dom` bunu kullanır.
_FEATURE_KEYWORDS = {
    "cabin baggage": "baggage_cabin",
    "carry-on": "baggage_cabin",
    "checked baggage": "checked_baggage",
    "baggage": "checked_baggage",
    "seat": "seat_selection",
    "meal": "meal",
    "refund": "refund",
    "change": "change",
    "miles": "miles",
    "lounge": "lounge",
    "priority": "priority_boarding",
    "fast track": "fast_track",
    "wifi": "wifi",
}


@register
class AFScraper(BaseScraper):
    """Air France fare family scraper (otomatik API→HTML)."""

    airline_code = "AF"
    source_label = "AF-site"
    #: DOM özellik satırı → standart alan (jenerik parse_dom kullanır).
    feature_keywords = _FEATURE_KEYWORDS

    # `open_search` ve `parse_dom` artık `BaseScraper`'ın paylaşımlı şablonundan
    # gelir (çerez onayı + form-hazır bekleme). AF yalnızca API/JSON eşlemesini
    # özelleştirir.

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
        name = offer.get("brandName") or offer.get("name") or offer.get("fareFamilyName")
        if not name:
            return None
        price_block = offer.get("price", {})
        if isinstance(price_block, (int, float, str)):
            price_block = {"amount": price_block}
        fb = FareBrand(
            cabin=_CABIN_MAP.get(str(offer.get("cabin", "")).upper(), Cabin.ECONOMY.value),
            fare_brand=str(name),
            brand_code=str(offer.get("brandCode", "")),
            booking_class=str(offer.get("bookingClass", "")),
            price=self.parse_price(price_block.get("amount", price_block.get("value"))),
            currency=str(price_block.get("currency", "")),
            package_description=str(offer.get("description", "")),
            source_url=url,
        )
        self._map_features(offer.get("attributes", []) or [], fb)
        return fb

    def _map_features(self, attributes: list[dict[str, Any]], fb: FareBrand) -> None:
        for attr in attributes:
            if not isinstance(attr, dict):
                continue
            field_name = _ATTR_MAP.get(str(attr.get("code", "")).upper())
            if not field_name:
                continue
            status = str(attr.get("status", "")).upper()
            state = {
                "INCLUDED": FeatureState.INCLUDED,
                "CHARGEABLE": FeatureState.PAID,
                "PAID": FeatureState.PAID,
                "NOT_OFFERED": FeatureState.NOT_INCLUDED,
            }.get(status, FeatureState.UNKNOWN)
            fb.set_feature(field_name, state, detail=str(attr.get("value", "")))


def _iter_offers(data: Any) -> list[dict[str, Any]]:
    """JSON'da fare/offer dizisini bulur (şema örneği)."""
    if isinstance(data, dict):
        for key in ("fareFamilies", "offers", "recommendations", "products", "brands"):
            val = data.get(key)
            if isinstance(val, list) and val:
                return [x for x in val if isinstance(x, dict)]
        for v in data.values():
            found = _iter_offers(v)
            if found:
                return found
    if isinstance(data, list):
        dicts = [x for x in data if isinstance(x, dict)]
        if any("brandName" in x or "fareFamilyName" in x for x in dicts):
            return dicts
    return []
