from datetime import date, datetime, timedelta, timezone

from app.funds_catalog import get_fund_spec
from app.models.fund import SINGLE_SOURCE, VERIFIED, FundHolding
from app.repositories.fund_repository import FundRepository


async def test_upsert_fund_preserves_runtime_enriched_name(db_session):
    repo = FundRepository(db_session)
    spec = get_fund_spec("AFS")

    fund = await repo.upsert_fund(spec)
    fund.name = "Resmî TEFAS Unvanı"
    fund.metadata_verified = True
    await db_session.commit()

    again = await repo.upsert_fund(spec)
    # A later catalog sync must not clobber the official title fetched from TEFAS.
    assert again.name == "Resmî TEFAS Unvanı"
    assert again.metadata_verified is True
    assert again.target_weight == spec.target_weight


async def test_price_backfill_is_idempotent(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("XLV"))
    ts = datetime.now(timezone.utc).replace(microsecond=0)

    repo.record_price(fund.id, 150.0, ts, "Yahoo Finance", SINGLE_SOURCE)
    await db_session.commit()

    assert await repo.exists_price_at(fund.id, ts) is True
    assert await repo.exists_price_at(fund.id, ts + timedelta(days=1)) is False


async def test_trend_excludes_secondary_rows(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("XLV"))
    base = datetime.now(timezone.utc)

    for i, value in enumerate([10.0, 20.0, 30.0]):
        repo.record_price(fund.id, value, base + timedelta(days=i), "Yahoo Finance", SINGLE_SOURCE)
    repo.record_price(fund.id, 999.0, base, "stockanalysis.com", VERIFIED, is_primary=False)
    await db_session.commit()

    trend = await repo.trend(fund.id)
    assert [t.value for t in trend] == [10.0, 20.0, 30.0]

    corroborations = await repo.latest_corroborations(fund.id)
    assert len(corroborations) == 1
    assert corroborations[0].value == 999.0


async def test_replace_holdings_snapshot_semantics(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("XLV"))
    as_of = date(2026, 7, 15)

    def rows(weights: list[float]) -> list[FundHolding]:
        return [
            FundHolding(
                fund_id=fund.id,
                as_of=as_of,
                rank=i + 1,
                ticker=f"T{i}",
                holding_name=f"Holding {i}",
                weight_pct=w,
                source="ssga",
                verification_status=SINGLE_SOURCE,
            )
            for i, w in enumerate(weights)
        ]

    await repo.replace_holdings(fund.id, as_of, rows([10.0, 9.0]))
    await db_session.commit()
    # Re-running the same file date replaces, never duplicates.
    await repo.replace_holdings(fund.id, as_of, rows([11.0, 8.0, 7.0]))
    await db_session.commit()

    holdings = await repo.latest_holdings(fund.id)
    assert [h.weight_pct for h in holdings] == [11.0, 8.0, 7.0]


async def test_latest_holdings_returns_newest_snapshot_only(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("ARKG"))

    old = FundHolding(
        fund_id=fund.id, as_of=date(2026, 7, 1), rank=1, ticker="OLD",
        holding_name="Old Co", weight_pct=5.0, source="ark_funds",
        verification_status=SINGLE_SOURCE,
    )
    new = FundHolding(
        fund_id=fund.id, as_of=date(2026, 7, 15), rank=1, ticker="NEW",
        holding_name="New Co", weight_pct=6.0, source="ark_funds",
        verification_status=SINGLE_SOURCE,
    )
    db_session.add_all([old, new])
    await db_session.commit()

    holdings = await repo.latest_holdings(fund.id)
    assert [h.ticker for h in holdings] == ["NEW"]


async def test_upsert_analysis_updates_in_place(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("XLV"))
    today = date(2026, 7, 18)

    await repo.upsert_analysis("fund", fund.id, today, "ilk metin", "neutral", "heuristic", "fp1")
    await db_session.commit()
    await repo.upsert_analysis("fund", fund.id, today, "güncel metin", "positive", "openai_compat", "fp2")
    await db_session.commit()

    analysis = await repo.latest_analysis("fund", fund.id)
    assert analysis.body_tr == "güncel metin"
    assert analysis.provider == "openai_compat"
    assert analysis.input_fingerprint == "fp2"
