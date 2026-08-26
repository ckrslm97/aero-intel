"""Zenginleştirme + export roundtrip testleri (uçtan uca, sahte veriyle)."""
from __future__ import annotations

import json
import sqlite3

import pandas as pd

from config import AppConfig
from core.enrich import enrich_all, ond_type_of, region_of, season_of, to_usd
from core.exporter import Exporter
from core.models import Cabin, FareBrand, FeatureState


def _sample_fares():
    f1 = FareBrand(airline="TK", origin="IST", destination="LHR",
                   cabin=Cabin.ECONOMY.value, fare_brand="EcoFly",
                   price=180.0, currency="EUR", package_order=1, source="TK-site")
    f1.set_feature("checked_baggage", FeatureState.INCLUDED, "23kg")
    f2 = FareBrand(airline="AF", origin="CDG", destination="JFK",
                   cabin=Cabin.BUSINESS.value, fare_brand="Business Flex",
                   price=2100.0, currency="USD", package_order=1, source="ota:google")
    return [f1, f2]


def test_enrich_fields():
    fares = enrich_all(_sample_fares(), coll_date="2026-07-01")
    tk = fares[0]
    assert tk.season == season_of("2026-07-01") == "Summer"
    assert tk.ond_type == ond_type_of("IST", "LHR") == "Local"
    assert tk.region == region_of("IST", "LHR") == "Europe"
    assert tk.price_usd == to_usd(180.0, "EUR")
    assert tk.carrier_type == "Legacy"


def test_export_roundtrip(tmp_path):
    cfg = AppConfig()
    cfg.output_dir = tmp_path
    fares = enrich_all(_sample_fares(), coll_date="2026-07-01")
    written = Exporter(cfg).export_all(fares)

    # Tüm biçimler yazıldı mı?
    for fmt in ("excel", "csv", "tsv", "sqlite", "json", "archive"):
        assert fmt in written, f"{fmt} eksik"

    # CSV içeriği + Source sütunu
    df = pd.read_csv(written["csv"])
    assert len(df) == 2
    assert "Source" in df.columns
    assert set(df["Source"]) == {"TK-site", "ota:google"}

    # SQLite
    con = sqlite3.connect(cfg.output_dir / "fares.db")
    n = con.execute("select count(*) from fares").fetchone()[0]
    con.close()
    assert n == 2

    # Kümülatif data.json
    data = json.loads((tmp_path / "data.json").read_text(encoding="utf-8"))
    assert data["count"] == 2
    assert {f["source"] for f in data["fares"]} == {"TK-site", "ota:google"}


def test_data_json_is_cumulative(tmp_path):
    """İkinci çekim data.json'a EKLENMELİ (zaman serisi kaybolmamalı)."""
    cfg = AppConfig()
    cfg.output_dir = tmp_path
    exp = Exporter(cfg)

    run1 = enrich_all([_sample_fares()[0]], coll_date="2026-06-01")
    exp.export_all(run1)
    run2 = enrich_all([_sample_fares()[1]], coll_date="2026-07-01")
    exp.export_all(run2)

    data = json.loads((tmp_path / "data.json").read_text(encoding="utf-8"))
    # Farklı CollDate + farklı kayıt → iki kayıt korunur
    assert data["count"] == 2
