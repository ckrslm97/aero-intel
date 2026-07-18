"""Pure-function tests for the fund-data parsers (no network, no DB).

The fetch functions are exercised only through their parse steps -- live
endpoints are unreachable from CI/sandbox, so fixtures mirror the documented
response shapes.
"""
from app.ingest.funds.stockanalysis import parse_stockanalysis_quote
from app.ingest.funds.yahoo import parse_quote_summary


def _quote_summary_fixture() -> dict:
    """Realistic (trimmed) quoteSummary payload for an airline ETF."""
    return {
        "quoteSummary": {
            "result": [
                {
                    "topHoldings": {
                        "holdings": [
                            {
                                "symbol": "DAL",
                                "holdingName": "Delta Air Lines Inc",
                                "holdingPercent": {"raw": 0.1023, "fmt": "10.23%"},
                            },
                            {
                                "symbol": "UAL",
                                "holdingName": "United Airlines Holdings Inc",
                                "holdingPercent": {"raw": 0.0987, "fmt": "9.87%"},
                            },
                            {
                                # no "symbol" key -- ticker must default to None
                                "holdingName": "Ryanair Holdings PLC ADR",
                                "holdingPercent": {"raw": 0.0421, "fmt": "4.21%"},
                            },
                        ],
                        "sectorWeightings": [
                            {"industrials": {"raw": 0.9412, "fmt": "94.12%"}},
                            {"consumer_cyclical": {"raw": 0.0588, "fmt": "5.88%"}},
                        ],
                    },
                    "fundProfile": {
                        "feesExpensesInvestment": {
                            "annualReportExpenseRatio": {"raw": 0.006, "fmt": "0.60%"}
                        }
                    },
                }
            ],
            "error": None,
        }
    }


def test_parse_quote_summary_full_fixture():
    profile = parse_quote_summary(_quote_summary_fixture())
    assert profile is not None
    assert profile.source == "yahoo_quote_summary"
    assert profile.aum is None  # topHoldings carries no AUM

    assert [h.rank for h in profile.top_holdings] == [1, 2, 3]
    assert profile.top_holdings[0].holding_name == "Delta Air Lines Inc"
    assert profile.top_holdings[0].ticker == "DAL"
    assert profile.top_holdings[0].weight_pct == 10.23
    assert profile.top_holdings[2].ticker is None
    assert abs(profile.top_holdings[2].weight_pct - 4.21) < 1e-9

    assert profile.sector_weights[0] == ("industrials", 94.12)
    assert profile.sector_weights[1][0] == "consumer_cyclical"
    assert abs(profile.sector_weights[1][1] - 5.88) < 1e-9

    assert profile.expense_ratio is not None
    assert abs(profile.expense_ratio - 0.6) < 1e-9


def test_parse_quote_summary_missing_fund_profile_module():
    data = _quote_summary_fixture()
    del data["quoteSummary"]["result"][0]["fundProfile"]
    profile = parse_quote_summary(data)
    assert profile is not None
    assert profile.expense_ratio is None
    assert len(profile.top_holdings) == 3  # holdings survive the missing module
    assert len(profile.sector_weights) == 2


def test_parse_quote_summary_missing_top_holdings_module():
    data = _quote_summary_fixture()
    del data["quoteSummary"]["result"][0]["topHoldings"]
    profile = parse_quote_summary(data)
    assert profile is not None
    assert profile.top_holdings == []
    assert profile.sector_weights == []
    assert profile.expense_ratio is not None


def test_parse_quote_summary_empty_and_garbage_return_none():
    assert parse_quote_summary({}) is None
    assert parse_quote_summary({"quoteSummary": {"result": []}}) is None
    assert parse_quote_summary({"quoteSummary": {"result": None}}) is None
    assert parse_quote_summary({"quoteSummary": {"result": [{}]}}) is None
    assert parse_quote_summary({"chart": {"result": [{}]}}) is None
    assert parse_quote_summary({"quoteSummary": "nope"}) is None


def test_parse_quote_summary_malformed_holdings_do_not_raise():
    data = {
        "quoteSummary": {
            "result": [
                {
                    "topHoldings": {"holdings": [{"holdingName": "X"}]},  # no percent
                    "fundProfile": {
                        "feesExpensesInvestment": {
                            "annualReportExpenseRatio": {"raw": 0.004}
                        }
                    },
                }
            ]
        }
    }
    profile = parse_quote_summary(data)
    assert profile is not None
    assert profile.top_holdings == []  # bad holdings dropped, not raised
    assert abs(profile.expense_ratio - 0.4) < 1e-9


def test_stockanalysis_price_key():
    assert parse_stockanalysis_quote({"data": {"price": 152.3}}) == 152.3


def test_stockanalysis_alternate_keys():
    assert parse_stockanalysis_quote({"data": {"cl": "152.3"}}) == 152.3
    assert parse_stockanalysis_quote({"data": {"last": 99}}) == 99.0
    assert parse_stockanalysis_quote({"close": 12.5}) == 12.5  # no "data" wrapper


def test_stockanalysis_rejects_non_numeric_and_negative():
    assert parse_stockanalysis_quote({"data": {"price": "n/a"}}) is None
    assert parse_stockanalysis_quote({"data": {"price": -5}}) is None
    assert parse_stockanalysis_quote({"data": {"price": 0}}) is None
    assert parse_stockanalysis_quote({"data": {"price": True}}) is None
    assert parse_stockanalysis_quote({"data": {"price": None}}) is None
    assert parse_stockanalysis_quote({"data": {"volume": 123456}}) is None


def test_stockanalysis_garbage_shapes_return_none():
    assert parse_stockanalysis_quote(None) is None
    assert parse_stockanalysis_quote("152.3") is None
    assert parse_stockanalysis_quote([{"price": 152.3}]) is None
    assert parse_stockanalysis_quote({"data": [152.3]}) is None
    assert parse_stockanalysis_quote({}) is None
