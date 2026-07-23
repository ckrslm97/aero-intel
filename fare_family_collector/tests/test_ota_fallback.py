"""Runner OTA eskalasyon zinciri testleri (mock scraper'larla)."""
from __future__ import annotations

import pytest

import core.runner as runner_mod
import scrapers.ota_base as ota_mod
from config import AppConfig
from core.models import FareBrand
from core.ond import OND
from core.runner import CollectorRunner
from scrapers.base import ScrapeError


class _FailAirline:
    def run(self, ond, td):
        raise ScrapeError("captcha")


class _OkScraper:
    def __init__(self, source):
        self.source = source

    def run(self, ond, td):
        return [FareBrand(airline=ond.airline, fare_brand="Eco", price=180,
                          currency="USD", source=self.source)]


@pytest.fixture
def runner():
    cfg = AppConfig()
    cfg.demo_mode = False
    cfg.use_ota_fallback = True
    cfg.ota_sources = ["google", "kayak"]
    return CollectorRunner(cfg)


def test_airline_fails_falls_back_to_ota(runner, monkeypatch):
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: True)
    monkeypatch.setattr(runner_mod, "get_scraper", lambda a, c: _FailAirline())
    monkeypatch.setattr(ota_mod, "get_ota_scraper",
                        lambda name, c, al: _OkScraper(f"ota:{name}") if name == "google" else None)
    fares = runner._process_one(OND("TK", "IST", "LHR"), "2026-08-01")
    assert len(fares) == 1
    assert fares[0].source == "ota:google"


def test_no_real_scraper_goes_straight_to_ota(runner, monkeypatch):
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: False)
    monkeypatch.setattr(ota_mod, "get_ota_scraper",
                        lambda name, c, al: _OkScraper(f"ota:{name}"))
    fares = runner._process_one(OND("JL", "CDG", "HND"), "2026-08-01")
    assert fares and fares[0].source == "ota:google"  # ilk kaynak (google)


def test_all_sources_fail_raises(runner, monkeypatch):
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: True)
    monkeypatch.setattr(runner_mod, "get_scraper", lambda a, c: _FailAirline())
    monkeypatch.setattr(ota_mod, "get_ota_scraper", lambda name, c, al: None)
    with pytest.raises(ScrapeError):
        runner._process_one(OND("TK", "IST", "LHR"), "2026-08-01")


def test_ota_disabled_raises_on_airline_failure(monkeypatch):
    cfg = AppConfig()
    cfg.demo_mode = False
    cfg.use_ota_fallback = False
    r = CollectorRunner(cfg)
    monkeypatch.setattr(runner_mod, "has_real_scraper", lambda a: True)
    monkeypatch.setattr(runner_mod, "get_scraper", lambda a, c: _FailAirline())
    with pytest.raises(ScrapeError):
        r._process_one(OND("TK", "IST", "LHR"), "2026-08-01")


def test_demo_mode_never_uses_ota(monkeypatch):
    cfg = AppConfig()
    cfg.demo_mode = True
    r = CollectorRunner(cfg)
    # Demo modda gerçek/ota scraper'lara hiç bakılmamalı; DemoScraper veri üretir.
    fares = r._process_one(OND("TK", "IST", "LHR"), "2026-08-01")
    assert fares and all(f.source == "demo" for f in fares)
