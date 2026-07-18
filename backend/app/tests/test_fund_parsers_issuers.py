"""Pure-parser tests for the issuer holdings adapters (ARK / SSGA / Vanguard).

No network, no DB: fixtures are inline CSV text, in-memory openpyxl workbooks,
and literal JSON dicts mirroring the documented file shapes.
"""
from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.ingest.funds.ark import parse_ark_csv
from app.ingest.funds.ssga import parse_ssga_fund_facts, parse_ssga_xlsx
from app.ingest.funds.vanguard import parse_vanguard_json

# ---------------------------------------------------------------- ARK

ARK_CSV = """\
date,fund,company,ticker,cusip,shares,"market value ($)","weight (%)"
07/15/2026,ARKG,TWIST BIOSCIENCE CORP,TWST,90184D100,"3,214,567","$112,345,678.90",7.41%
07/15/2026,ARKG,CRISPR THERAPEUTICS AG,CRSP,H17182108,"2,109,876","$145,678,901.23",9.85%
07/15/2026,ARKG,EXACT SCIENCES CORP,EXAS,30063P105,"1,876,543","$98,765,432.10",6.52%
07/15/2026,ARKG,IONIS PHARMACEUTICALS INC,IONS,462222100,"2,345,678","$123,456,789.01",8.13%
,,,,,,,
"Investors should carefully consider the investment objectives and risks as well as charges and expenses of an ARK ETF before investing.",,,,,,,
"The principal risks of investing in ARKG include equity, market and healthcare sector risk.",,,,,,,
"""


def test_parse_ark_csv_ranks_and_strips_percent():
    snapshot = parse_ark_csv(ARK_CSV, source_url="https://example.test/arkg.csv")
    assert snapshot is not None
    assert snapshot.as_of == date(2026, 7, 15)
    assert snapshot.source == "ark_funds"
    assert snapshot.source_url == "https://example.test/arkg.csv"
    assert snapshot.is_top10_only is False

    # Footer/disclaimer lines skipped; four real holdings survive.
    assert len(snapshot.rows) == 4
    # Ranked by weight desc, "%" stripped to floats.
    assert [(r.rank, r.ticker, r.weight_pct) for r in snapshot.rows] == [
        (1, "CRSP", 9.85),
        (2, "IONS", 8.13),
        (3, "TWST", 7.41),
        (4, "EXAS", 6.52),
    ]
    assert snapshot.rows[0].holding_name == "CRISPR THERAPEUTICS AG"


def test_parse_ark_csv_iso_date_variant():
    csv_text = (
        "date,fund,company,ticker,cusip,shares,market value($),weight(%)\n"
        "2026-07-15,ARKG,TWIST BIOSCIENCE CORP,TWST,90184D100,100,1000,7.41\n"
    )
    snapshot = parse_ark_csv(csv_text)
    assert snapshot is not None
    assert snapshot.as_of == date(2026, 7, 15)
    assert snapshot.rows[0].weight_pct == 7.41


def test_parse_ark_csv_garbage_returns_none():
    assert parse_ark_csv("<html><body>503 Service Unavailable</body></html>") is None
    assert parse_ark_csv("") is None
    # Header only, no data rows.
    assert parse_ark_csv("date,fund,company,ticker,cusip,shares,weight (%)\n") is None


# ---------------------------------------------------------------- SSGA


def _build_ssga_xlsx(
    weights: list[float],
    include_as_of: bool = True,
    as_of_text: str = "As of 15-Jul-2026",
) -> bytes:
    wb = Workbook()
    ws = wb.active
    # Preamble, as in the real files: fund facts before the header row.
    ws.append(["Fund Name:", "Health Care Select Sector SPDR Fund"])
    ws.append(["Ticker Symbol:", "XLV"])
    if include_as_of:
        ws.append([as_of_text])
    ws.append(["Total Net Assets", 41234567890.12])
    ws.append(["Gross Expense Ratio (%)", 0.09])
    ws.append([])
    ws.append(["Name", "Ticker", "Weight", "Sector"])
    holdings = [
        ("ELI LILLY & CO", "LLY", "Pharmaceuticals"),
        ("UNITEDHEALTH GROUP INC", "UNH", "Health Care Providers"),
        ("JOHNSON & JOHNSON", "JNJ", "Pharmaceuticals"),
        ("ABBVIE INC", "ABBV", "Biotechnology"),
    ]
    for (name, ticker, sector), weight in zip(holdings, weights):
        ws.append([name, ticker, weight, sector])
    ws.append([])
    ws.append(["Important Information: this document is not investment advice."])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_parse_ssga_xlsx_basic():
    content = _build_ssga_xlsx(weights=[11.2, 9.8, 8.1, 5.4])
    snapshot = parse_ssga_xlsx(content, source_url="https://example.test/xlv.xlsx")
    assert snapshot is not None
    assert snapshot.as_of == date(2026, 7, 15)
    assert snapshot.source == "ssga"
    assert snapshot.source_url == "https://example.test/xlv.xlsx"
    assert snapshot.is_top10_only is False

    assert len(snapshot.rows) == 4  # footer text excluded
    assert [(r.rank, r.ticker, r.weight_pct) for r in snapshot.rows] == [
        (1, "LLY", 11.2),
        (2, "UNH", 9.8),
        (3, "JNJ", 8.1),
        (4, "ABBV", 5.4),
    ]
    assert snapshot.rows[0].holding_name == "ELI LILLY & CO"
    assert snapshot.rows[0].sector == "Pharmaceuticals"


def test_parse_ssga_xlsx_fraction_weights_converted_to_percent():
    content = _build_ssga_xlsx(weights=[0.30, 0.28, 0.22, 0.20])  # sums to 1.0
    snapshot = parse_ssga_xlsx(content)
    assert snapshot is not None
    weights = [r.weight_pct for r in snapshot.rows]
    assert weights == pytest.approx([30.0, 28.0, 22.0, 20.0])


def test_parse_ssga_xlsx_missing_as_of_uses_today_without_raising():
    content = _build_ssga_xlsx(weights=[11.2, 9.8, 8.1, 5.4], include_as_of=False)
    snapshot = parse_ssga_xlsx(content)
    assert snapshot is not None
    assert snapshot.as_of == date.today()
    assert len(snapshot.rows) == 4


def test_parse_ssga_xlsx_garbage_returns_none():
    assert parse_ssga_xlsx(b"definitely not a zip/xlsx payload") is None
    assert parse_ssga_xlsx(b"") is None


def test_parse_ssga_fund_facts():
    content = _build_ssga_xlsx(weights=[11.2, 9.8, 8.1, 5.4])
    facts = parse_ssga_fund_facts(content)
    assert facts["aum"] == 41234567890.12
    assert facts["expense_ratio"] == 0.09


def test_parse_ssga_fund_facts_garbage_is_empty_not_raising():
    facts = parse_ssga_fund_facts(b"not an xlsx")
    assert facts == {"aum": None, "expense_ratio": None}


# ---------------------------------------------------------------- Vanguard

VANGUARD_INVESTOR_SHAPE = {
    "fund": {
        "asOfDate": "2026-07-15",
        "entity": [
            {"longName": "Eli Lilly & Co.", "ticker": "LLY", "percentWeight": "10.93"},
            {"longName": "UnitedHealth Group Inc.", "ticker": "UNH", "percentWeight": "6.21"},
            {"longName": "Johnson & Johnson", "ticker": "JNJ", "percentWeight": "7.48"},
        ],
    }
}

VANGUARD_API_SHAPE = {
    "effectiveDate": "07/15/2026",
    "entity": [
        {"shortName": "Eli Lilly", "ticker": "LLY", "percentWeight": 10.93},
        {"shortName": "Johnson & Johnson", "ticker": "JNJ", "percentWeight": 7.48},
    ],
}


def test_parse_vanguard_investor_shape_with_string_weights():
    snapshot = parse_vanguard_json(VANGUARD_INVESTOR_SHAPE, source_url="https://example.test/vht")
    assert snapshot is not None
    assert snapshot.as_of == date(2026, 7, 15)
    assert snapshot.source == "vanguard"
    assert snapshot.is_top10_only is False
    assert [(r.rank, r.ticker, r.weight_pct) for r in snapshot.rows] == [
        (1, "LLY", 10.93),
        (2, "JNJ", 7.48),
        (3, "UNH", 6.21),
    ]
    assert snapshot.rows[0].holding_name == "Eli Lilly & Co."


def test_parse_vanguard_api_shape():
    snapshot = parse_vanguard_json(VANGUARD_API_SHAPE)
    assert snapshot is not None
    assert snapshot.as_of == date(2026, 7, 15)
    assert len(snapshot.rows) == 2
    assert snapshot.rows[0].ticker == "LLY"
    assert snapshot.rows[0].weight_pct == 10.93


def test_parse_vanguard_empty_or_garbage_returns_none():
    assert parse_vanguard_json({}) is None
    assert parse_vanguard_json(None) is None
    assert parse_vanguard_json([]) is None
    assert parse_vanguard_json({"fund": {"entity": []}}) is None
    assert parse_vanguard_json({"fund": {"entity": [{"percentWeight": "n/a"}]}}) is None
