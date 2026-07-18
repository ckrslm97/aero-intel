"""Economist/analyst commentary for the /invest module.

Follows the insights_service.build_daily_digest pattern exactly: numbers are
computed from stored rows only, a bespoke Turkish prompt is handed to the strong
model, and any failure degrades to a deterministic template grounded in the same
numbers. The provider is recorded so the UI never passes a template off as AI
analysis.

Hard rule enforced by both the prompt and the fallback: no number appears in the
commentary that isn't already in the stats dict. There is no market access here
and the repo forbids invented data -- an unpopulated fund gets an honest "veri
bekleniyor" note, not a fabricated outlook.
"""
import hashlib
import json
import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.funds_catalog import MARKET_TR, MARKET_US, specs_for_market
from app.models.fund import DISCREPANCY, Fund
from app.repositories.fund_repository import FundRepository
from app.services.fund_service import weighted_1y_return

logger = get_logger(__name__)

# How many stored daily points a trailing-return window needs before we trust it
# (a "1 yıllık getiri" computed off three weeks of data would lie).
_PERIOD_MIN_DAYS = {"1y": 300, "6m": 150, "3m": 75, "1m": 25}
_PERIOD_LOOKBACK_DAYS = {"1y": 370, "6m": 190, "3m": 100, "1m": 40}


def _period_return(history: list, days_back: int, min_span: int) -> float | None:
    """Trailing return over a window, or None when the stored series doesn't
    actually span it. history is oldest-first FundPrice rows."""
    if len(history) < 2:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    window = [p for p in history if p.as_of >= cutoff]
    if len(window) < 2:
        return None
    first, last = window[0], window[-1]
    if (last.as_of - first.as_of).days < min_span or not first.value:
        return None
    return round((last.value - first.value) / first.value * 100, 2)


def _annualized_volatility(history: list) -> float | None:
    """Stdev of daily percent changes, annualized -- only with enough points to
    be meaningful."""
    if len(history) < 60:
        return None
    changes = []
    for prev, cur in zip(history, history[1:]):
        if prev.value:
            changes.append((cur.value - prev.value) / prev.value)
    if len(changes) < 30:
        return None
    daily = statistics.pstdev(changes)
    return round(daily * (252 ** 0.5) * 100, 2)


async def _fund_stats(repo: FundRepository, fund: Fund) -> dict | None:
    """Only numbers actually stored for this fund. None when there's no price
    data at all (nothing honest to say)."""
    since = datetime.now(timezone.utc) - timedelta(days=400)
    history = await repo.price_history(fund.id, since)
    if not history:
        return None

    latest = history[-1]
    holdings = await repo.latest_holdings(fund.id)
    allocations = await repo.latest_allocations(fund.id)

    return {
        "symbol": fund.symbol,
        "name": fund.name,
        "currency": fund.currency,
        "latest_value": latest.value,
        "as_of": latest.as_of.date().isoformat(),
        "verification_status": latest.verification_status,
        "return_1y_pct": _period_return(history, _PERIOD_LOOKBACK_DAYS["1y"], _PERIOD_MIN_DAYS["1y"]),
        "return_6m_pct": _period_return(history, _PERIOD_LOOKBACK_DAYS["6m"], _PERIOD_MIN_DAYS["6m"]),
        "return_3m_pct": _period_return(history, _PERIOD_LOOKBACK_DAYS["3m"], _PERIOD_MIN_DAYS["3m"]),
        "return_1m_pct": _period_return(history, _PERIOD_LOOKBACK_DAYS["1m"], _PERIOD_MIN_DAYS["1m"]),
        "annualized_volatility_pct": _annualized_volatility(history),
        "expense_ratio": fund.expense_ratio,
        "top_holdings": [
            {"name": h.holding_name, "ticker": h.ticker, "weight_pct": h.weight_pct}
            for h in holdings[:5]
        ],
        "allocations": [{"label": a.label, "weight_pct": a.weight_pct} for a in allocations[:6]],
    }


def _fingerprint(stats: dict) -> str:
    return hashlib.sha256(json.dumps(stats, sort_keys=True, default=str).encode()).hexdigest()


def _outlook_from_return(r1y: float | None, verification_status: str | None) -> str:
    if verification_status == DISCREPANCY:
        return "cautious"
    if r1y is None:
        return "neutral"
    if r1y > 10:
        return "positive"
    if r1y < 0:
        return "cautious"
    return "neutral"


def _pct(value: float | None) -> str:
    return f"%{value:.2f}" if value is not None else "veri yok"


def _fallback_fund_analysis(stats: dict) -> tuple[str, str]:
    """Deterministic Turkish commentary interpolating only stored numbers.
    Returns (body, outlook)."""
    r1y = stats["return_1y_pct"]
    outlook = _outlook_from_return(r1y, stats["verification_status"])

    perf_bits = []
    if r1y is not None:
        perf_bits.append(f"son 1 yılda {_pct(r1y)}")
    if stats["return_3m_pct"] is not None:
        perf_bits.append(f"son 3 ayda {_pct(stats['return_3m_pct'])}")
    if stats["return_1m_pct"] is not None:
        perf_bits.append(f"son 1 ayda {_pct(stats['return_1m_pct'])}")
    perf = (
        f"{stats['symbol']} ({stats['name']}) " + ", ".join(perf_bits) + " getiri kaydetti."
        if perf_bits
        else f"{stats['symbol']} için henüz yeterli fiyat geçmişi birikmedi; getiri hesaplaması ilk günlük veriler toplandıkça anlam kazanacaktır."
    )
    if stats["annualized_volatility_pct"] is not None:
        perf += f" Yıllıklandırılmış oynaklık yaklaşık {_pct(stats['annualized_volatility_pct'])} seviyesindedir."

    risk_bits = []
    if stats["top_holdings"]:
        top = stats["top_holdings"][0]
        risk_bits.append(
            f"En büyük pozisyon {top['name']} (%{top['weight_pct']:.2f}) olup, ilk beş pozisyonun ağırlığı yoğunlaşma riskini belirler."
        )
    if stats["verification_status"] == DISCREPANCY:
        risk_bits.append(
            "Not: bu fonun son fiyatı kaynaklar arasında uyuşmadığından temkinli değerlendirilmelidir."
        )
    if stats["expense_ratio"] is not None:
        risk_bits.append(f"Fonun gider oranı %{stats['expense_ratio']:.2f} olarak kayıtlıdır.")
    risk = " ".join(risk_bits) or "Pozisyon dağılımı ve makro koşullar başlıca risk unsurlarıdır."

    body = f"{perf}\n\n{risk}\n\nBu metin, saklanan verilerden şablonla üretilmiştir."
    return body, outlook


def _fund_prompt(stats: dict) -> str:
    return (
        "Sen temkinli bir ekonomist ve finansal analistsin. Aşağıdaki fon "
        "istatistiklerine dayanarak Türkçe, iki kısa paragraflık bir değerlendirme yaz. "
        "Kurallar: yalnızca verilen sayıları kullan, kendinden SAYI UYDURMA, kesin "
        "al/sat emri verme, abartılı vaatte bulunma. Birinci paragraf: mevcut görünüm "
        "ve trend değerlendirmesi. İkinci paragraf: riskler ve dikkat edilecek noktalar. "
        "En sona, ayrı bir satırda tek kelimeyle şu formatta genel görünümü ekle: "
        "OUTLOOK: positive|neutral|cautious. İstatistikler (JSON): "
        + json.dumps(stats, ensure_ascii=False, default=str)
    )


def _parse_outlook(text: str, default: str) -> tuple[str, str]:
    """Split a trailing 'OUTLOOK: x' line off the body. Returns (body, outlook)."""
    outlook = default
    lines = text.strip().splitlines()
    kept = []
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("OUTLOOK:"):
            candidate = stripped.split(":", 1)[1].strip().lower()
            if candidate in ("positive", "neutral", "cautious"):
                outlook = candidate
            continue
        kept.append(line)
    return "\n".join(kept).strip(), outlook


async def _generate_via_llm(prompt: str) -> str | None:
    settings = get_settings()
    if settings.llm_provider != "openai_compat" or not settings.llm_base_url:
        return None
    from app.llm.openai_compat import OpenAICompatProvider

    try:
        live = OpenAICompatProvider(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
        return (await live._generate(prompt)).strip()  # noqa: SLF001 -- bespoke prompt, not a pipeline task
    except Exception as exc:  # noqa: BLE001 -- analysis must never crash the refresh job
        logger.warning("fund_analysis_llm_failed_falling_back", error=str(exc))
        return None


async def build_fund_analysis(db: AsyncSession, fund: Fund) -> str | None:
    """Regenerate one fund's analysis unless the inputs are unchanged. Returns
    "generated" | "skipped" | None (no data)."""
    repo = FundRepository(db)
    stats = await _fund_stats(repo, fund)
    if stats is None:
        return None

    fingerprint = _fingerprint(stats)
    existing = await repo.latest_analysis("fund", fund.id)
    today = datetime.now(timezone.utc).date()
    if existing is not None and existing.input_fingerprint == fingerprint and existing.analysis_date == today:
        return "skipped"

    provider = "heuristic"
    body, outlook = _fallback_fund_analysis(stats)
    llm_text = await _generate_via_llm(_fund_prompt(stats))
    if llm_text:
        body, outlook = _parse_outlook(
            llm_text, _outlook_from_return(stats["return_1y_pct"], stats["verification_status"])
        )
        provider = "openai_compat"

    await repo.upsert_analysis("fund", fund.id, today, body, outlook, provider, fingerprint)
    return "generated"


def _portfolio_prompt(stats: dict) -> str:
    return (
        "Sen temkinli bir ekonomist ve portföy analistisin. Aşağıda, KULLANICININ "
        "BELİRLEDİĞİ örnek bir varlık dağılımı ve fonların getirileri var. Türkçe, iki "
        "kısa paragraflık bir portföy değerlendirmesi yaz. Kurallar: yalnızca verilen "
        "sayıları kullan, sayı uydurma, kesin al/sat tavsiyesi verme; bunun bir örnek "
        "dağılım olduğunu ve yatırım tavsiyesi olmadığını vurgula. En sona ayrı satırda "
        "OUTLOOK: positive|neutral|cautious ekle. İstatistikler (JSON): "
        + json.dumps(stats, ensure_ascii=False, default=str)
    )


def _fallback_portfolio_analysis(stats: dict) -> tuple[str, str]:
    market_label = "ABD ETF" if stats["market"] == MARKET_US else "TEFAS fon"
    weighted = stats["weighted_return_1y_pct"]
    if weighted is not None:
        lead = (
            f"Kullanıcının belirlediği örnek {market_label} dağılımı, saklanan verilere göre "
            f"son 1 yılda ağırlıklı {_pct(weighted)} getiri göstermektedir."
        )
        outlook = "positive" if weighted > 10 else "cautious" if weighted < 0 else "neutral"
    else:
        lead = (
            f"Kullanıcının belirlediği örnek {market_label} dağılımının ağırlıklı getirisi, tüm "
            "fonların 1 yıllık verisi tamamlandığında hesaplanacaktır."
        )
        outlook = "neutral"

    members = ", ".join(
        f"{m['symbol']} %{m['target_weight'] * 100:.0f} ({_pct(m['return_1y_pct'])})"
        for m in stats["members"]
    )
    unverified = [m["symbol"] for m in stats["members"] if m["verification_status"] in (None, DISCREPANCY)]
    risk = f"Dağılım: {members}."
    if unverified:
        risk += (
            " Şu fonların son verisi henüz iki kaynaktan doğrulanmadığından temkinli "
            f"değerlendirilmelidir: {', '.join(unverified)}."
        )
    risk += " Sektör/coğrafya yoğunlaşması ve döviz kuru başlıca risk unsurlarıdır."

    body = f"{lead}\n\n{risk}\n\nBu metin, saklanan verilerden şablonla üretilmiştir ve yatırım tavsiyesi değildir."
    return body, outlook


async def build_portfolio_analysis(db: AsyncSession, market: str) -> str:
    """Regenerate one market portfolio's analysis. Returns "generated" | "skipped"."""
    repo = FundRepository(db)
    weighted, per_fund = await weighted_1y_return(db, market)

    members = []
    for spec in specs_for_market(market):
        fund = await repo.get_by_symbol(spec.symbol)
        latest = await repo.latest_price(fund.id) if fund else None
        members.append(
            {
                "symbol": spec.symbol,
                "target_weight": spec.target_weight,
                "return_1y_pct": per_fund.get(spec.symbol),
                "verification_status": latest.verification_status if latest else None,
            }
        )

    stats = {"market": market, "weighted_return_1y_pct": weighted, "members": members}
    fingerprint = _fingerprint(stats)
    scope = "portfolio_us" if market == MARKET_US else "portfolio_tr"
    existing = await repo.latest_analysis(scope)
    today = datetime.now(timezone.utc).date()
    if existing is not None and existing.input_fingerprint == fingerprint and existing.analysis_date == today:
        return "skipped"

    provider = "heuristic"
    body, outlook = _fallback_portfolio_analysis(stats)
    llm_text = await _generate_via_llm(_portfolio_prompt(stats))
    if llm_text:
        body, outlook = _parse_outlook(llm_text, outlook)
        provider = "openai_compat"

    await repo.upsert_analysis(scope, None, today, body, outlook, provider, fingerprint)
    return "generated"


async def regenerate_fund_analyses(db: AsyncSession) -> dict:
    """Regenerate every fund + both portfolio analyses, isolating failures.
    Called by the scheduler job and the admin refresh endpoint."""
    repo = FundRepository(db)
    result = {"generated": 0, "skipped": 0, "failed": []}

    for fund in await repo.list_all():
        try:
            outcome = await build_fund_analysis(db, fund)
            if outcome == "generated":
                result["generated"] += 1
            elif outcome == "skipped":
                result["skipped"] += 1
            await db.commit()
        except Exception as exc:  # noqa: BLE001 -- one fund must not block the rest
            await db.rollback()
            logger.warning("fund_analysis_failed", symbol=fund.symbol, error=str(exc))
            result["failed"].append(fund.symbol)

    for market in (MARKET_US, MARKET_TR):
        try:
            outcome = await build_portfolio_analysis(db, market)
            if outcome == "generated":
                result["generated"] += 1
            else:
                result["skipped"] += 1
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.warning("portfolio_analysis_failed", market=market, error=str(exc))
            result["failed"].append(f"portfolio_{market}")

    logger.info("fund_analyses_regenerated", **result)
    return result
