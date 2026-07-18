"""Verification-status semantics of the fund refresh -- the core promise of the
/invest module: agree -> verified, disagree -> discrepancy, no cross-check ->
single_source, TEFAS -> official_single_source. Adapters are monkeypatched at
their source modules (fund_service lazy-imports them per call).
"""
from datetime import date, datetime, timedelta, timezone

import app.ingest.funds.stockanalysis as stockanalysis_mod
import app.ingest.funds.tefas as tefas_mod
import app.ingest.funds.vanguard as vanguard_mod
import app.ingest.funds.yahoo as yahoo_mod
import app.ingest.markets as markets_mod
from app.funds_catalog import get_fund_spec
from app.ingest.funds.base import (
    AllocationSlice,
    FundProfile,
    HoldingRow,
    HoldingsSnapshot,
    TefasInfo,
    TefasPricePoint,
)
from app.models.fund import DISCREPANCY, OFFICIAL_SINGLE_SOURCE, SINGLE_SOURCE, VERIFIED
from app.repositories.fund_repository import FundRepository
from app.services import fund_service

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _history_points(days: int = 400, last: float = 150.0):
    return [(NOW - timedelta(days=days - i), last - (days - i) * 0.01) for i in range(days)]


def _patch_us_adapters(
    monkeypatch,
    history=None,
    cross: float | None = None,
    profile: FundProfile | None = None,
    snapshot: HoldingsSnapshot | None = None,
):
    async def fake_history(base_url, symbol, period):
        return history if history is not None else []

    async def fake_cross(base_url, symbol):
        return cross

    async def fake_profile(base_url, symbol):
        return profile

    async def fake_vanguard():
        return snapshot

    monkeypatch.setattr(markets_mod, "fetch_history", fake_history)
    monkeypatch.setattr(stockanalysis_mod, "fetch_price_cross_check", fake_cross)
    monkeypatch.setattr(yahoo_mod, "fetch_fund_profile", fake_profile)
    monkeypatch.setattr(vanguard_mod, "fetch_vht_holdings", fake_vanguard)


async def test_us_price_verified_when_sources_agree(db_session, monkeypatch):
    points = _history_points()
    _patch_us_adapters(monkeypatch, history=points, cross=points[-1][1] * 1.005)

    spec = get_fund_spec("VHT")
    summary = await fund_service.refresh_us_fund(db_session, spec)
    await db_session.commit()

    assert summary["price_status"] == VERIFIED
    repo = FundRepository(db_session)
    fund = await repo.get_by_symbol("VHT")
    latest = await repo.latest_price(fund.id)
    assert latest.verification_status == VERIFIED
    # History rows never had a live cross-check -- they must not inherit it.
    history = await repo.price_history(fund.id, NOW - timedelta(days=500))
    assert history[0].verification_status == SINGLE_SOURCE
    # The cross-check itself is stored as a secondary row.
    corroborations = await repo.latest_corroborations(fund.id)
    assert len(corroborations) == 1
    assert corroborations[0].source == "stockanalysis.com"


async def test_us_price_discrepancy_when_sources_disagree(db_session, monkeypatch):
    points = _history_points()
    _patch_us_adapters(monkeypatch, history=points, cross=points[-1][1] * 1.05)

    summary = await fund_service.refresh_us_fund(db_session, get_fund_spec("VHT"))
    await db_session.commit()
    assert summary["price_status"] == DISCREPANCY


async def test_us_price_single_source_without_cross_check(db_session, monkeypatch):
    _patch_us_adapters(monkeypatch, history=_history_points(), cross=None)

    summary = await fund_service.refresh_us_fund(db_session, get_fund_spec("VHT"))
    await db_session.commit()
    assert summary["price_status"] == SINGLE_SOURCE


async def test_us_refresh_is_idempotent_for_prices(db_session, monkeypatch):
    points = _history_points(days=10)
    _patch_us_adapters(monkeypatch, history=points, cross=None)
    spec = get_fund_spec("VHT")

    first = await fund_service.refresh_us_fund(db_session, spec)
    await db_session.commit()
    second = await fund_service.refresh_us_fund(db_session, spec)
    await db_session.commit()

    assert first["prices_added"] == 10
    assert second["prices_added"] == 0


async def test_holdings_verified_when_issuer_and_yahoo_agree(db_session, monkeypatch):
    issuer_rows = [
        HoldingRow(rank=1, holding_name="Eli Lilly", weight_pct=10.0, ticker="LLY", sector="Health Care"),
        HoldingRow(rank=2, holding_name="UnitedHealth", weight_pct=8.0, ticker="UNH", sector="Health Care"),
    ]
    profile = FundProfile(
        top_holdings=[
            HoldingRow(rank=1, holding_name="Eli Lilly", weight_pct=10.5, ticker="LLY"),
            HoldingRow(rank=2, holding_name="UnitedHealth", weight_pct=7.5, ticker="UNH"),
        ],
        source="yahoo_quote_summary",
    )
    snapshot = HoldingsSnapshot(
        as_of=date(2026, 7, 15), source="vanguard", source_url="https://example.com", rows=issuer_rows
    )
    _patch_us_adapters(
        monkeypatch, history=_history_points(days=5), cross=None, profile=profile, snapshot=snapshot
    )

    summary = await fund_service.refresh_us_fund(db_session, get_fund_spec("VHT"))
    await db_session.commit()

    assert summary["holdings"]["status"] == VERIFIED
    repo = FundRepository(db_session)
    fund = await repo.get_by_symbol("VHT")
    holdings = await repo.latest_holdings(fund.id)
    assert len(holdings) == 2
    assert holdings[0].verification_status == VERIFIED
    # Sector rollup happened from the full issuer file.
    allocations = await repo.latest_allocations(fund.id)
    assert allocations[0].label == "Health Care"
    assert allocations[0].weight_pct == 18.0


async def test_holdings_discrepancy_when_weights_disagree(db_session, monkeypatch):
    issuer_rows = [
        HoldingRow(rank=1, holding_name="Eli Lilly", weight_pct=10.0, ticker="LLY"),
        HoldingRow(rank=2, holding_name="UnitedHealth", weight_pct=8.0, ticker="UNH"),
    ]
    profile = FundProfile(
        top_holdings=[
            HoldingRow(rank=1, holding_name="Eli Lilly", weight_pct=16.0, ticker="LLY"),
            HoldingRow(rank=2, holding_name="UnitedHealth", weight_pct=2.0, ticker="UNH"),
        ],
        source="yahoo_quote_summary",
    )
    snapshot = HoldingsSnapshot(
        as_of=date(2026, 7, 15), source="vanguard", source_url="https://example.com", rows=issuer_rows
    )
    _patch_us_adapters(
        monkeypatch, history=_history_points(days=5), cross=None, profile=profile, snapshot=snapshot
    )

    summary = await fund_service.refresh_us_fund(db_session, get_fund_spec("VHT"))
    await db_session.commit()
    assert summary["holdings"]["status"] == DISCREPANCY


async def test_vht_falls_back_to_yahoo_top10_labeled_single_source(db_session, monkeypatch):
    profile = FundProfile(
        top_holdings=[HoldingRow(rank=1, holding_name="Eli Lilly", weight_pct=10.0, ticker="LLY")],
        sector_weights=[("healthcare", 99.0)],
        source="yahoo_quote_summary",
    )
    _patch_us_adapters(
        monkeypatch, history=_history_points(days=5), cross=None, profile=profile, snapshot=None
    )

    summary = await fund_service.refresh_us_fund(db_session, get_fund_spec("VHT"))
    await db_session.commit()

    assert summary["holdings"]["status"] == SINGLE_SOURCE
    repo = FundRepository(db_session)
    fund = await repo.get_by_symbol("VHT")
    holdings = await repo.latest_holdings(fund.id)
    assert holdings[0].is_top10_only is True
    # Yahoo's fund-level sector weights still populate the allocation chart.
    allocations = await repo.latest_allocations(fund.id)
    assert allocations[0].source == "yahoo_quote_summary"


async def test_tr_fund_rows_are_official_single_source(db_session, monkeypatch):
    points = [
        TefasPricePoint(as_of=NOW - timedelta(days=i), nav=1.0 + i * 0.001) for i in range(30, 0, -1)
    ]

    async def fake_info(base_url, fon_kod, months=12):
        return TefasInfo(fund_title="Resmî Fon Unvanı A.Ş.", points=points, aum=1_000_000.0)

    async def fake_allocation(base_url, fon_kod):
        return (date(2026, 7, 15), [AllocationSlice("Hisse Senedi", 80.0), AllocationSlice("Repo", 20.0)])

    monkeypatch.setattr(tefas_mod, "fetch_tefas_info", fake_info)
    monkeypatch.setattr(tefas_mod, "fetch_tefas_allocation", fake_allocation)
    monkeypatch.setattr(fund_service, "TEFAS_REQUEST_GAP_SECONDS", 0)

    spec = get_fund_spec("AFS")
    summary = await fund_service.refresh_tr_fund(db_session, spec)
    await db_session.commit()

    assert summary["prices_added"] == 30
    repo = FundRepository(db_session)
    fund = await repo.get_by_symbol("AFS")
    latest = await repo.latest_price(fund.id)
    assert latest.verification_status == OFFICIAL_SINGLE_SOURCE
    # The official title replaced the catalog placeholder.
    assert fund.name == "Resmî Fon Unvanı A.Ş."
    assert fund.metadata_verified is True
    allocations = await repo.latest_allocations(fund.id)
    assert [a.label for a in allocations] == ["Hisse Senedi", "Repo"]
    assert allocations[0].kind == "asset_class"


async def test_refresh_all_funds_isolates_failures(db_session, monkeypatch):
    async def exploding_history(base_url, symbol, period):
        if symbol == "XLV":
            raise RuntimeError("boom")
        return _history_points(days=5)

    async def fake_none(*args, **kwargs):
        return None

    monkeypatch.setattr(markets_mod, "fetch_history", exploding_history)
    monkeypatch.setattr(stockanalysis_mod, "fetch_price_cross_check", fake_none)
    monkeypatch.setattr(yahoo_mod, "fetch_fund_profile", fake_none)
    monkeypatch.setattr(vanguard_mod, "fetch_vht_holdings", fake_none)

    async def fake_ssga(base_url, symbol):
        return None

    async def fake_ark(base_url):
        return None

    import app.ingest.funds.ark as ark_mod
    import app.ingest.funds.ssga as ssga_mod

    monkeypatch.setattr(ssga_mod, "fetch_ssga_holdings", fake_ssga)
    monkeypatch.setattr(ark_mod, "fetch_arkg_holdings", fake_ark)
    monkeypatch.setattr(tefas_mod, "fetch_tefas_info", fake_none)

    async def fake_tefas_allocation(base_url, fon_kod):
        return None

    monkeypatch.setattr(tefas_mod, "fetch_tefas_allocation", fake_tefas_allocation)
    monkeypatch.setattr(fund_service, "TEFAS_REQUEST_GAP_SECONDS", 0)

    results = await fund_service.refresh_all_funds(db_session)

    assert "XLV" in results["failed"]
    refreshed_symbols = {r["symbol"] for r in results["refreshed"]}
    # Every other fund still refreshed despite XLV's source exploding.
    assert {"VHT", "XLF", "XBI", "ARKG", "AFS", "TBE", "TI2", "MAC"} <= refreshed_symbols


async def test_weighted_return_requires_complete_data(db_session, monkeypatch):
    _patch_us_adapters(monkeypatch, history=_history_points(), cross=None)
    # Only VHT gets data -- the US portfolio figure must stay None, per-fund
    # returns still reported where they exist.
    await fund_service.refresh_us_fund(db_session, get_fund_spec("VHT"))
    await db_session.commit()

    weighted, per_fund = await fund_service.weighted_1y_return(db_session, "us")
    assert weighted is None
    assert per_fund["VHT"] is not None
    assert per_fund["XLV"] is None
