"""OND yükleme, dinamik giriş ve Excel taşıyıcı çaprazlama testleri."""
from __future__ import annotations

import pandas as pd
import pytest

from core.ond import (
    OND, load_ond_file, ond_from_fields, parse_inline_routes,
)


def test_ond_from_fields_multi_carrier():
    onds = ond_from_fields("TK,AF/LH", "ist", "lhr")
    assert [str(o) for o in onds] == ["TK IST-LHR", "AF IST-LHR", "LH IST-LHR"]
    # origin/dest büyük harfe normalize edilir
    assert onds[0].origin == "IST" and onds[0].destination == "LHR"


def test_ond_from_fields_validation():
    with pytest.raises(ValueError):
        ond_from_fields("", "IST", "LHR")
    with pytest.raises(ValueError):
        ond_from_fields("TK", "IST", "")


def test_parse_inline_routes():
    onds = parse_inline_routes("TK:IST-LHR, AF:CDG-JFK, TK/AF:IST-CDG")
    keys = {o.key for o in onds}
    assert "TK_IST_LHR" in keys and "AF_CDG_JFK" in keys
    assert "TK_IST_CDG" in keys and "AF_IST_CDG" in keys
    with pytest.raises(ValueError):
        parse_inline_routes("bad-format")


def test_load_csv_multi_carrier(tmp_path):
    p = tmp_path / "ond.csv"
    p.write_text("AIRLINE,ORIGIN,DESTINATION\n\"AF,JL,NH\",CDG,HND\nTK,IST,LHR\n", encoding="utf-8")
    onds = load_ond_file(p)
    assert len(onds) == 4  # 3 taşıyıcı + 1
    assert OND("JL", "CDG", "HND").key in {o.key for o in onds}


def test_load_excel_two_sheet_cross_join(tmp_path):
    """Routes (taşıyıcısız) × Carriers sayfası çaprazlanmalı."""
    p = tmp_path / "ond.xlsx"
    routes = pd.DataFrame({"ORIGIN": ["IST", "CDG"], "DESTINATION": ["LHR", "JFK"]})
    carriers = pd.DataFrame({"CARRIER": ["TK", "AF", "LH"]})
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        routes.to_excel(w, index=False, sheet_name="Routes")
        carriers.to_excel(w, index=False, sheet_name="Carriers")
    onds = load_ond_file(p)
    assert len(onds) == 6  # 2 rota × 3 taşıyıcı
    assert {o.airline for o in onds} == {"TK", "AF", "LH"}
    assert {(o.origin, o.destination) for o in onds} == {("IST", "LHR"), ("CDG", "JFK")}


def test_load_excel_row_carrier_takes_precedence(tmp_path):
    """Rota satırında taşıyıcı varsa, genel liste ile çaprazlama yapılmaz."""
    p = tmp_path / "ond.xlsx"
    routes = pd.DataFrame({"AIRLINE": ["TK", ""], "ORIGIN": ["IST", "CDG"],
                           "DESTINATION": ["LHR", "JFK"]})
    carriers = pd.DataFrame({"CARRIER": ["AF", "LH"]})
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        routes.to_excel(w, index=False, sheet_name="Routes")
        carriers.to_excel(w, index=False, sheet_name="Carriers")
    onds = load_ond_file(p)
    keys = {o.key for o in onds}
    # IST-LHR yalnızca TK (satır taşıyıcısı); CDG-JFK boş → AF,LH ile çaprazlanır
    assert "TK_IST_LHR" in keys
    assert "AF_CDG_JFK" in keys and "LH_CDG_JFK" in keys
    assert "AF_IST_LHR" not in keys


def test_load_missing_route_columns_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("FOO,BAR\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_ond_file(p)
