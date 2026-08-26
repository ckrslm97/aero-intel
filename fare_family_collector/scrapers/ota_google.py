"""Google Flights OTA yedek scraper'ı.

Google Flights sonuçları XHR/RPC (GetShoppingResults / batchexecute) ile döner
ve DOM'da uçuş kartları + "fare options" bulunur. Fiyat/kabin/marka çıkarılır;
istenen taşıyıcıya göre süzülür.

UYARI: Google güçlü anti-bot kullanır; seçiciler ve RPC yanıt yapısı değişebilir.
`playwright codegen https://www.google.com/travel/flights` ile doğrulayın.
"""
from __future__ import annotations

from typing import Any

from core.models import Cabin, FareBrand
from core.ond import OND
from scrapers.ota_base import OTAScraper, register_ota


@register_ota
class GoogleFlightsScraper(OTAScraper):
    ota_name = "google"

    def open_search(self, page: Any, ond: OND, travel_date: str) -> None:
        sel = self.selectors
        # Doğrudan derin bağlantı: OTA'da form doldurmak yerine URL parametreleri
        # daha dayanıklıdır (canlıda gerekiyorsa forma da düşülebilir).
        url = f"{sel['base_url']}?hl=en&curr=USD"
        self._goto(page, url)
        # Google güçlü çerez/consent duvarı kullanır; sağlam onay şart.
        self.accept_cookies(page)
        self.wait_for_ready(page)
        self.human_pause()
        self._fill(page, sel.get("origin_input"), ond.origin)
        self.human_pause()
        self._fill(page, sel.get("destination_input"), ond.destination)
        self.human_pause()
        if page.query_selector(sel.get("date_input", "")):
            page.fill(sel["date_input"], travel_date)
        self.human_pause()
        if page.query_selector(sel.get("search_button", "")):
            page.click(sel["search_button"])

    def parse_api(self, captured: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        fares: list[FareBrand] = []
        for cap in captured:
            for offer in _iter_offers(cap.get("json")):
                carrier = str(offer.get("carrier", offer.get("airlineCode", "")))
                if not self._airline_matches(carrier):
                    continue
                price = offer.get("price", offer.get("amount"))
                name = offer.get("fareName") or offer.get("brandName") or offer.get("cabin") or "Fare"
                fb = FareBrand(
                    airline=self.target_airline or carrier.upper(),
                    cabin=_cabin(offer.get("cabin", "")),
                    fare_brand=str(name),
                    price=self.parse_price(price),
                    currency=str(offer.get("currency", "USD")),
                    package_description="Google Flights",
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
            # Kartta hedef taşıyıcı adı/kodu geçmiyorsa atla (kaba filtre).
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
                package_description="Google Flights",
                source_url=page.url,
            )
            fares.append(fb)
        return fares


def _cabin(raw: str) -> str:
    m = {"ECONOMY": Cabin.ECONOMY.value, "PREMIUM_ECONOMY": Cabin.PREMIUM_ECONOMY.value,
         "PREMIUM": Cabin.PREMIUM_ECONOMY.value, "BUSINESS": Cabin.BUSINESS.value,
         "FIRST": Cabin.FIRST.value}
    return m.get(str(raw).upper(), Cabin.ECONOMY.value)


def _iter_offers(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("offers", "fares", "results", "itineraries", "flights"):
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
