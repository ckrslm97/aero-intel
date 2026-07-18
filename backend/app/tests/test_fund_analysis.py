"""Fund analysis pipeline: the fallback must be grounded in stored numbers only,
fingerprints must be stable, and provider labeling must be honest. Pure-function
tests need no DB; the regeneration/skip tests use the Postgres fixture.
"""
import re
from datetime import date, datetime, timedelta, timezone

from app.funds_catalog import get_fund_spec
from app.models.fund import DISCREPANCY, OFFICIAL_SINGLE_SOURCE, SINGLE_SOURCE, VERIFIED
from app.repositories.fund_repository import FundRepository
from app.services import fund_analysis_service as fas

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _stats(**overrides) -> dict:
    base = {
        "symbol": "XLV",
        "name": "Health Care Select Sector SPDR",
        "currency": "USD",
        "latest_value": 150.0,
        "as_of": "2026-07-18",
        "verification_status": VERIFIED,
        "return_1y_pct": 12.34,
        "return_6m_pct": 5.5,
        "return_3m_pct": 2.1,
        "return_1m_pct": 1.0,
        "annualized_volatility_pct": 14.2,
        "expense_ratio": 0.09,
        "top_holdings": [{"name": "Eli Lilly", "ticker": "LLY", "weight_pct": 10.5}],
        "allocations": [{"label": "Health Care", "weight_pct": 99.0}],
    }
    base.update(overrides)
    return base


def _numbers_in(text: str) -> set[float]:
    # Numeric values (formatting-insensitive: "10.50" == "10.5") to assert
    # nothing was invented that isn't in the stats.
    return {float(n) for n in re.findall(r"\d+\.\d+|\d+", text)}


def test_fallback_uses_only_provided_numbers():
    stats = _stats()
    body, outlook = fas._fallback_fund_analysis(stats)

    allowed = {
        stats["return_1y_pct"],
        stats["return_3m_pct"],
        stats["return_1m_pct"],
        stats["annualized_volatility_pct"],
        stats["expense_ratio"],
        stats["top_holdings"][0]["weight_pct"],
        5.0,  # "ilk beş pozisyon"
        1.0,  # "1 yıl/ay" period words
        3.0,  # "3 ay"
    }
    for token in _numbers_in(body):
        assert token in allowed, f"invented number {token} in fallback body: {body}"
    assert outlook == "positive"  # r1y 12.34 > 10
    assert "şablonla üretilmiştir" in body


def test_fallback_handles_missing_returns_without_inventing():
    stats = _stats(
        return_1y_pct=None,
        return_6m_pct=None,
        return_3m_pct=None,
        return_1m_pct=None,
        annualized_volatility_pct=None,
        expense_ratio=None,
        top_holdings=[],
    )
    body, outlook = fas._fallback_fund_analysis(stats)
    assert "yeterli fiyat geçmişi birikmedi" in body
    assert outlook == "neutral"


def test_fallback_flags_discrepancy_as_cautious():
    body, outlook = fas._fallback_fund_analysis(_stats(verification_status=DISCREPANCY, return_1y_pct=20.0))
    assert outlook == "cautious"
    assert "kaynaklar arasında uyuşmadığından" in body


def test_fingerprint_is_stable_and_sensitive():
    a = _stats()
    b = _stats()
    c = _stats(return_1y_pct=99.9)
    assert fas._fingerprint(a) == fas._fingerprint(b)
    assert fas._fingerprint(a) != fas._fingerprint(c)


def test_parse_outlook_strips_trailing_line():
    text = "Paragraf bir.\n\nParagraf iki.\nOUTLOOK: cautious"
    body, outlook = fas._parse_outlook(text, "neutral")
    assert outlook == "cautious"
    assert "OUTLOOK" not in body
    assert body.endswith("Paragraf iki.")


def test_parse_outlook_defaults_when_absent():
    body, outlook = fas._parse_outlook("Sadece metin.", "positive")
    assert outlook == "positive"
    assert body == "Sadece metin."


def test_period_return_requires_real_span():
    class P:
        def __init__(self, as_of, value):
            self.as_of = as_of
            self.value = value

    # Two weeks of data can't yield a "1y" return.
    short = [P(NOW - timedelta(days=14), 100.0), P(NOW, 110.0)]
    assert fas._period_return(short, 370, 300) is None
    # A full year does.
    full = [P(NOW - timedelta(days=360), 100.0), P(NOW, 112.0)]
    assert fas._period_return(full, 370, 300) == 12.0


# --- DB-backed regeneration / provider-labeling -----------------------------


async def _seed_us_fund_with_history(db, symbol="XLV", days=360, status=VERIFIED):
    repo = FundRepository(db)
    fund = await repo.upsert_fund(get_fund_spec(symbol))
    for i in range(days):
        repo.record_price(
            fund.id, 100.0 + i * 0.05, NOW - timedelta(days=days - i), "Yahoo Finance", status
        )
    await db.commit()
    return fund


async def test_build_fund_analysis_generates_then_skips(db_session, monkeypatch):
    # No LLM configured -> heuristic provider, deterministic.
    monkeypatch.setattr(fas, "_generate_via_llm", lambda prompt: _async_none())
    fund = await _seed_us_fund_with_history(db_session)

    first = await fas.build_fund_analysis(db_session, fund)
    await db_session.commit()
    assert first == "generated"

    repo = FundRepository(db_session)
    analysis = await repo.latest_analysis("fund", fund.id)
    assert analysis.provider == "heuristic"
    assert analysis.body_tr

    # Same inputs, same day -> skipped (protects the token budget).
    second = await fas.build_fund_analysis(db_session, fund)
    assert second == "skipped"


async def test_build_fund_analysis_none_without_data(db_session):
    repo = FundRepository(db_session)
    fund = await repo.upsert_fund(get_fund_spec("XBI"))
    await db_session.commit()
    assert await fas.build_fund_analysis(db_session, fund) is None


async def test_llm_provider_labeled_when_available(db_session, monkeypatch):
    async def fake_llm(prompt):
        return "Yapay zekâ paragrafı bir.\n\nParagraf iki.\nOUTLOOK: positive"

    monkeypatch.setattr(fas, "_generate_via_llm", fake_llm)
    fund = await _seed_us_fund_with_history(db_session, symbol="XLF")

    await fas.build_fund_analysis(db_session, fund)
    await db_session.commit()

    repo = FundRepository(db_session)
    analysis = await repo.latest_analysis("fund", fund.id)
    assert analysis.provider == "openai_compat"
    assert analysis.outlook == "positive"
    assert "OUTLOOK" not in analysis.body_tr


async def test_regenerate_all_reports_counts(db_session, monkeypatch):
    monkeypatch.setattr(fas, "_generate_via_llm", lambda prompt: _async_none())
    await _seed_us_fund_with_history(db_session, symbol="XLV")

    result = await fas.regenerate_fund_analyses(db_session)
    # One fund with data + two portfolio scopes attempted; funds without price
    # data return None (neither generated nor skipped), portfolios always write.
    assert result["generated"] >= 1
    assert result["failed"] == []


def _async_none():
    async def _n():
        return None

    return _n()
