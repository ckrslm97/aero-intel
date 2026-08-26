"""Canlı gruplu yürütmenin (async motor → OTA yedeği) testleri.

Gerçek tarayıcı/Playwright gerekmez: `async_engine.scrape_group` monkeypatch
edilir; `_run_carrier_group`'un boş/başarısız sonuçları OTA'ya düşürmesi ve
başarı sonuçlarını olduğu gibi geçirmesi doğrulanır.
"""
from __future__ import annotations

import core.async_engine as ae
import core.runner as runner_mod
import scrapers.ota_base as ota_mod
from config import AppConfig
from core.models import FareBrand
from core.ond import OND
from core.runner import CollectorRunner
from scrapers.base import ScrapeError


class _OkScraper:
    def __init__(self, source):
        self.source = source

    def run(self, ond, td):
        return [FareBrand(airline=ond.airline, fare_brand="Eco", price=180,
                          currency="USD", source=self.source)]


def _runner():
    cfg = AppConfig()
    cfg.demo_mode = False
    cfg.use_ota_fallback = True
    cfg.ota_sources = ["google", "kayak"]
    return CollectorRunner(cfg)


def test_engine_success_is_passed_through(monkeypatch):
    r = _runner()
    ond = OND("TK", "IST", "LHR")
    good = [FareBrand(airline="TK", fare_brand="EcoFly", price=180, source="TK-site")]

    async def fake_group(scraper, onds, td, config):
        return {o.key: good for o in onds}

    monkeypatch.setattr(ae, "scrape_group", fake_group)
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: True)
    monkeypatch.setattr(runner_mod, "get_scraper", lambda a, c: object())

    out = r._run_carrier_group("TK", [ond], "2026-08-01")
    assert len(out) == 1
    _, outcome = out[0]
    assert outcome == good


def test_engine_empty_falls_back_to_ota(monkeypatch):
    r = _runner()
    ond = OND("TK", "IST", "LHR")

    async def fake_group(scraper, onds, td, config):
        return {o.key: [] for o in onds}  # boş → OTA denenmeli

    monkeypatch.setattr(ae, "scrape_group", fake_group)
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: True)
    monkeypatch.setattr(runner_mod, "get_scraper", lambda a, c: object())
    monkeypatch.setattr(ota_mod, "get_ota_scraper",
                        lambda name, c, al: _OkScraper(f"ota:{name}") if name == "google" else None)

    out = r._run_carrier_group("TK", [ond], "2026-08-01")
    _, outcome = out[0]
    assert isinstance(outcome, list) and outcome[0].source == "ota:google"


def test_engine_exception_falls_back_to_ota(monkeypatch):
    r = _runner()
    ond = OND("TK", "IST", "LHR")

    async def fake_group(scraper, onds, td, config):
        return {o.key: RuntimeError("captcha") for o in onds}

    monkeypatch.setattr(ae, "scrape_group", fake_group)
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: True)
    monkeypatch.setattr(runner_mod, "get_scraper", lambda a, c: object())
    monkeypatch.setattr(ota_mod, "get_ota_scraper", lambda name, c, al: _OkScraper(f"ota:{name}"))

    out = r._run_carrier_group("TK", [ond], "2026-08-01")
    _, outcome = out[0]
    assert isinstance(outcome, list) and outcome[0].source == "ota:google"


def test_no_real_scraper_goes_to_ota(monkeypatch):
    r = _runner()
    ond = OND("JL", "CDG", "HND")
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: False)
    monkeypatch.setattr(ota_mod, "get_ota_scraper", lambda name, c, al: _OkScraper(f"ota:{name}"))

    out = r._run_carrier_group("JL", [ond], "2026-08-01")
    _, outcome = out[0]
    assert isinstance(outcome, list) and outcome[0].source == "ota:google"


def test_all_sources_fail_yields_scrape_error(monkeypatch):
    r = _runner()
    ond = OND("TK", "IST", "LHR")

    async def fake_group(scraper, onds, td, config):
        return {o.key: [] for o in onds}

    monkeypatch.setattr(ae, "scrape_group", fake_group)
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: True)
    monkeypatch.setattr(runner_mod, "get_scraper", lambda a, c: object())
    monkeypatch.setattr(ota_mod, "get_ota_scraper", lambda name, c, al: None)

    out = r._run_carrier_group("TK", [ond], "2026-08-01")
    _, outcome = out[0]
    assert isinstance(outcome, ScrapeError)
