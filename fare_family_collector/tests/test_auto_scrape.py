"""Otomatik (API → HTML) scraping şablonunun sıralama testleri.

Gerçek siteye/Playwright'a ihtiyaç duymaz; sahte page/response nesneleri kullanır.
"""
from __future__ import annotations

import pytest

from config import AppConfig
from core.ond import OND
from scrapers.base import NotFoundError
from scrapers.tk import TKScraper


class _El:
    def __init__(self, text="", children=None, sub=None):
        self._text = text
        self._children = children or []
        self._sub = sub or {}

    def inner_text(self):
        return self._text

    def query_selector(self, sel):
        return self._sub.get("name") if "name" in sel else self._sub.get("price")

    def query_selector_all(self, sel):
        return self._children


class _Page:
    url = "https://airline.test/results"

    def __init__(self, cards=None):
        self._cards = cards or []

    def goto(self, url):
        pass

    def fill(self, sel, val):
        pass

    def click(self, sel):
        pass

    def query_selector(self, sel):
        return None

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_selector(self, *a, **k):
        if not self._cards:
            raise RuntimeError("no cards")

    def query_selector_all(self, sel):
        return self._cards


@pytest.fixture
def scraper():
    return TKScraper(AppConfig())


def test_api_preferred_over_dom(scraper):
    scraper._captured_responses = [{
        "url": "https://api/fare",
        "json": {"fareBrands": [
            {"brandName": "EcoFly", "cabinType": "ECONOMY",
             "price": {"amount": 180, "currency": "EUR"}},
        ]},
    }]
    # DOM'da da kart olsa bile API tercih edilmeli
    fares = scraper.scrape(_Page(cards=[_El("card")]), OND("TK", "IST", "LHR"), "2026-08-01")
    assert len(fares) == 1
    assert fares[0].fare_brand == "EcoFly"
    assert fares[0].price == 180.0


def test_dom_fallback_when_no_api(scraper):
    scraper._captured_responses = []
    card = _El(sub={"name": _El("ExtraFly"), "price": _El("260 EUR")},
               children=[_El("Checked baggage included")])
    fares = scraper.scrape(_Page(cards=[card]), OND("TK", "IST", "LHR"), "2026-08-01")
    assert len(fares) == 1
    assert fares[0].fare_brand == "ExtraFly"
    assert fares[0].price == 260.0


def test_not_found_when_neither(scraper):
    scraper._captured_responses = []
    with pytest.raises(NotFoundError):
        scraper.scrape(_Page(cards=[]), OND("TK", "IST", "LHR"), "2026-08-01")


def test_finalize_sets_source_and_order(scraper):
    scraper._captured_responses = [{
        "url": "u",
        "json": {"fareBrands": [
            {"brandName": "Flex", "price": {"amount": 360, "currency": "EUR"}},
            {"brandName": "Light", "price": {"amount": 180, "currency": "EUR"}},
        ]},
    }]
    ond = OND("TK", "IST", "LHR")
    fares = scraper._finalize(scraper.scrape(_Page(), ond, "2026-08-01"), ond, "2026-08-01")
    # fiyata göre sıralanır ve package_order atanır
    assert [f.fare_brand for f in fares] == ["Light", "Flex"]
    assert fares[0].package_order == 1 and fares[1].package_order == 2
    # kaynak etiketi
    assert all(f.source == "TK-site" for f in fares)
