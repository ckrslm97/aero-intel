"""Çerez/onay ve jenerik DOM ayrıştırma testleri (tarayıcısız, sahte page ile)."""
from __future__ import annotations

from config import AppConfig
from core.models import FeatureState
from core.ond import OND
from core.selectors import COMMON_CONSENT_FALLBACKS, consent_candidates, get_selectors
from scrapers.tk import TKScraper


def test_consent_candidates_site_first_then_fallbacks():
    sel = get_selectors("TK")
    cands = consent_candidates(sel)
    # Site-özel seçiciler, ortak yedeklerden önce gelmeli.
    assert cands.index("#cookie-accept") < cands.index("button.cookie-accept, button.accept-cookies, button#accept, #accept-cookies")
    # Tüm ortak yedekler listede bulunmalı.
    for fb in COMMON_CONSENT_FALLBACKS:
        assert fb in cands


def test_consent_candidates_deduplicated():
    sel = get_selectors("TK")
    cands = consent_candidates(sel)
    # OneTrust seçicisi hem TK listesinde hem ortak yedeklerde var; bir kez görünmeli.
    assert cands.count("#onetrust-accept-btn-handler") == 1
    assert len(cands) == len(set(cands))


def test_consent_candidates_template_uses_common_fallbacks():
    # Bilinmeyen taşıyıcı → _TEMPLATE; yine de ortak CMP yedekleri denenir.
    sel = get_selectors("ZZ")
    cands = consent_candidates(sel)
    assert "#onetrust-accept-btn-handler" in cands
    assert "#didomi-notice-agree-button" in cands


# ---- Jenerik DOM ayrıştırma (feature_keywords ile) ---- #
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

    def __init__(self, cards):
        self._cards = cards

    def wait_for_selector(self, *a, **k):
        if not self._cards:
            raise RuntimeError("no cards")

    def query_selector_all(self, sel):
        return self._cards


def test_generic_parse_dom_maps_features():
    scraper = TKScraper(AppConfig())
    card = _El(
        sub={"name": _El("ExtraFly"), "price": _El("260 EUR")},
        children=[_El("Checked baggage included"), _El("Seat selection € 12")],
    )
    fares = scraper.parse_dom(_Page([card]), OND("TK", "IST", "LHR"))
    assert len(fares) == 1
    fb = fares[0]
    assert fb.fare_brand == "ExtraFly"
    # "checked baggage" → checked_baggage, "included" → INCLUDED
    assert fb.features["checked_baggage"].state == FeatureState.INCLUDED
    # "seat" → seat_selection, "€" → PAID
    assert fb.features["seat_selection"].state == FeatureState.PAID


def test_accept_cookies_simple_page_clicks_known_selector():
    """Locator'ı olmayan basit page'de query_selector yoluyla çerez tıklanır."""
    clicked: list[str] = []

    class _SimplePage:
        def query_selector(self, sel):
            return object() if sel == "#onetrust-accept-btn-handler" else None

        def click(self, sel):
            clicked.append(sel)

    scraper = TKScraper(AppConfig())
    assert scraper.accept_cookies(_SimplePage()) is True
    assert clicked == ["#onetrust-accept-btn-handler"]
