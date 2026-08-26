"""Kayak OTA yedek scraper'ı.

Kayak sonuçları XHR (flights/results / poll) ile döner; DOM'da result kartları
(data-resultid) bulunur. Fiyat/kabin/marka çıkarılır ve istenen taşıyıcıya göre
süzülür.

UYARI: Kayak anti-bot (PerimeterX) kullanır; seçiciler değişebilir.
`playwright codegen https://www.kayak.com/flights` ile doğrulayın.
"""
from __future__ import annotations

from typing import Any

from core.models import Cabin, FareBrand
from core.ond import OND
from scrapers.ota_base import OTAScraper, register_ota


@register_ota
class KayakScraper(OTAScraper):
    ota_name = "kayak"

    def open_search(self, page: Any, ond: OND, travel_date: str) -> None:
        sel = self.selectors
        # Kayak derin bağlantı biçimi: /flights/IST-LHR/2026-08-01
        url = f"{sel['base_url']}/{ond.origin}-{ond.destination}/{travel_date}"
        self._goto(page, url)
        self.accept_cookies(page)
        self.human_pause()

    def parse_api(self, captured: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        fares: list[FareBrand] = []
        for cap in captured:
            for offer in _iter_offers(cap.get("json")):
                carrier = str(offer.get("airlineCode", offer.get("carrier", "")))
                if not self._airline_matches(carrier):
                    continue
                fb = FareBrand(
                    airline=self.target_airline or carrier.upper(),
                    cabin=_cabin(offer.get("cabin", offer.get("cabinClass", ""))),
                    fare_brand=str(offer.get("fareFamily") or offer.get("brand") or "Fare"),
                    price=self.parse_price(offer.get("price", offer.get("amount"))),
                    currency=str(offer.get("currency", "USD")),
                    package_description="Kayak",
                    source_url=cap.get("url", ""),
                )
                fares.append(fb)
        return fares

    def parse_dom(self, page: Any, ond: OND) -> list[FareBrand]:
        sel = self.selectors
        try:
            page.wait_for_selector(sel["fare_card"], timeout=self.config.page_timeout_ms)
        except Exception:  # noqa: BLE001
            return []
        fares: list[FareBrand] = []
        for card in page.query_selector_all(sel["fare_card"]):
            text = (card.inner_text() if hasattr(card, "inner_text") else "") or ""
            if self.target_airline and self.target_airline not in text.upper():
                continue
            name_el = card.query_selector(sel.get("fare_name", ""))
            price_el = card.query_selector(sel.get("fare_price", ""))
            fb = FareBrand(
                airline=self.target_airline,
                cabin=Cabin.ECONOMY.value,
                fare_brand=(name_el.inner_text().strip() if name_el else "Economy"),
                price=self.parse_price(price_el.inner_text() if price_el else text),
                currency="USD",
                package_description="Kayak",
                source_url=page.url,
            )
            fares.append(fb)
        return fares


def _cabin(raw: str) -> str:
    m = {"ECONOMY": Cabin.ECONOMY.value, "PREMIUM": Cabin.PREMIUM_ECONOMY.value,
         "PREMIUM_ECONOMY": Cabin.PREMIUM_ECONOMY.value, "BUSINESS": Cabin.BUSINESS.value,
         "FIRST": Cabin.FIRST.value}
    return m.get(str(raw).upper(), Cabin.ECONOMY.value)


def _iter_offers(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("results", "flights", "offers", "itineraries", "legs"):
            val = data.get(key)
            if isinstance(val, list) and val:
                return [x for x in val if isinstance(x, dict)]
        for v in data.values():
            found = _iter_offers(v)
            if found:
                return found
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict) and ("price" in x or "amount" in x)]
    return []
