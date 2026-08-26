"""Turkish Airlines (TK) scraper — canlı, otomatik (API → HTML).

`BaseScraper`'ın şablon `scrape()` metodu şu sırayı yönetir:
1. `open_search`  — siteyi aç, çerez onayı, arama formunu doldur, aramayı tetikle.
2. `parse_api`    — arama sonrası yakalanan XHR/JSON yanıtlarından fare üret.
3. `parse_dom`    — API boşsa görünür fare kartlarını DOM'dan oku.

Seçiciler `core/selectors.py` içindeki "TK" bloğundan gelir; site tasarımı
değişince yalnızca orası güncellenir.

UYARI: Havayolu siteleri anti-bot koruması, dinamik yükleme ve sık tasarım
değişimi içerir. Aşağıdaki akış çalışan bir iskelettir; canlı sitede seçicilerin
`playwright codegen https://www.turkishairlines.com` ile doğrulanması gerekir.
"""
from __future__ import annotations

from typing import Any

from core.models import Cabin, FareBrand, FeatureState
from core.ond import OND
from scrapers.base import BaseScraper
from scrapers.registry import register


# Site metnini / JSON kodlarını standart özelliklere eşleyen sözlük.
_FEATURE_KEYWORDS: dict[str, str] = {
    "cabin baggage": "baggage_cabin",
    "carry-on": "baggage_cabin",
    "checked baggage": "checked_baggage",
    "baggage allowance": "checked_baggage",
    "seat selection": "seat_selection",
    "seat": "seat_selection",
    "meal": "meal",
    "refund": "refund",
    "reissue": "change",
    "change": "change",
    "miles": "miles",
    "lounge": "lounge",
    "priority": "priority_boarding",
    "fast track": "fast_track",
    "wifi": "wifi",
}

# JSON kabin kodlarını standart kabinlere eşle.
_CABIN_MAP = {
    "ECONOMY": Cabin.ECONOMY.value,
    "ECO": Cabin.ECONOMY.value,
    "PREMIUM": Cabin.PREMIUM_ECONOMY.value,
    "BUSINESS": Cabin.BUSINESS.value,
    "BUS": Cabin.BUSINESS.value,
    "FIRST": Cabin.FIRST.value,
}


@register
class TKScraper(BaseScraper):
    """Turkish Airlines fare family scraper (otomatik API→HTML)."""

    airline_code = "TK"
    source_label = "TK-site"
    #: DOM özellik satırı metnini standart alanlara eşler (jenerik parse_dom kullanır).
    feature_keywords = _FEATURE_KEYWORDS

    # Arama akışı (`open_search`) ve HTML DOM ayrıştırma (`parse_dom`) artık
    # `BaseScraper`'ın paylaşımlı, sağlamlaştırılmış şablonundan gelir (çerez
    # onayı + form-hazır bekleme tek yerde). TK yalnızca API/JSON eşlemesini
    # (aşağıda) özelleştirir.

    # ------------------------------------------------------------------ #
    # API (network/JSON) — tercih edilen kaynak
    # ------------------------------------------------------------------ #
    def parse_api(self, captured: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        fares: list[FareBrand] = []
        for cap in captured:
            for offer in _iter_offers(cap.get("json")):
                fb = self._offer_to_fare(offer, cap.get("url", ""))
                if fb:
                    fares.append(fb)
        return fares

    def _offer_to_fare(self, offer: dict[str, Any], url: str) -> FareBrand | None:
        name = offer.get("brandName") or offer.get("fareBrandName") or offer.get("name")
        if not name:
            return None
        price_block = offer.get("price") or offer.get("totalPrice") or {}
        if isinstance(price_block, (int, float, str)):
            price_block = {"amount": price_block}
        fb = FareBrand(
            cabin=_CABIN_MAP.get(str(offer.get("cabinType", offer.get("cabin", ""))).upper(),
                                 Cabin.ECONOMY.value),
            fare_brand=str(name),
            brand_code=str(offer.get("brandCode", offer.get("fareBasisCode", ""))),
            booking_class=str(offer.get("bookingClass", offer.get("bookingCode", ""))),
            price=self.parse_price(price_block.get("amount", price_block.get("value"))),
            currency=str(price_block.get("currency", price_block.get("currencyCode", ""))),
            package_description=str(offer.get("description", "")),
            source_url=url,
        )
        for attr in offer.get("brandFeatures", offer.get("attributes", []) or []):
            self._map_json_feature(attr, fb)
        return fb

    def _map_json_feature(self, attr: Any, fb: FareBrand) -> None:
        if not isinstance(attr, dict):
            return
        label = str(attr.get("code", attr.get("name", ""))).lower()
        field_name = next((v for k, v in _FEATURE_KEYWORDS.items() if k in label), None)
        if not field_name:
            return
        status = str(attr.get("status", attr.get("value", ""))).upper()
        state = {
            "INCLUDED": FeatureState.INCLUDED, "TRUE": FeatureState.INCLUDED,
            "CHARGEABLE": FeatureState.PAID, "PAID": FeatureState.PAID,
            "NOT_OFFERED": FeatureState.NOT_INCLUDED, "FALSE": FeatureState.NOT_INCLUDED,
        }.get(status, FeatureState.UNKNOWN)
        fb.set_feature(field_name, state, detail=str(attr.get("value", "")))


def _iter_offers(data: Any) -> list[dict[str, Any]]:
    """JSON'da fare/offer dizisini bulur (şema örneği; canlıda doğrulayın)."""
    if isinstance(data, dict):
        for key in ("fareBrands", "brands", "fareFamilies", "offers",
                    "recommendations", "products", "pricingOptions"):
            val = data.get(key)
            if isinstance(val, list) and val:
                return [x for x in val if isinstance(x, dict)]
        # Bir kademe derine bak (ör. data["data"]["fareBrands"])
        for v in data.values():
            found = _iter_offers(v)
            if found:
                return found
    if isinstance(data, list):
        dicts = [x for x in data if isinstance(x, dict)]
        if any("brandName" in x or "fareBrandName" in x for x in dicts):
            return dicts
    return []
