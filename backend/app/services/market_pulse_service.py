"""Generates the daily Market Pulse: a short Turkish paragraph over Kokpit's
own already-verified numbers, never a fresh fact of the model's own.

The prompt hands the model a closed list of (label, value, source, source_url)
facts and asks it to synthesize *only those* into a short commercial-desk
read, citing which facts it used. `_parse_and_validate` then rejects the
whole generation if any cited source_url isn't one that was actually in that
list -- the one place a hallucinated citation could slip in and read as real,
so it is checked deterministically rather than trusted from the prompt
instruction alone.

Never raises past this module and never writes a partial row: a missing LLM
key, a network failure, an unparseable response, or a citation that fails
validation all resolve to "write nothing, let the API keep serving the last
good pulse" (see MarketPulseRepository.latest / GET /kokpit/pulse).
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.market_pulse import MarketPulse
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.repositories.market_pulse_repository import MarketPulseRepository
from app.services.kpi_service import FX_PAIR_LABELS, LIVE_FX_PAIRS
from app.taxonomy import PERIOD_KIND_LABELS_TR

logger = get_logger(__name__)


@dataclass(frozen=True)
class GroundingFact:
    label: str
    value_text: str
    source: str
    source_url: str


async def _fx_board_facts(db: AsyncSession) -> list[GroundingFact]:
    repo = KpiRepository(db)
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    facts = []
    for metric_key, *_rest in LIVE_FX_PAIRS:
        latest = await repo.latest(metric_key)
        if latest is None:
            continue
        pair_label = FX_PAIR_LABELS.get(metric_key, metric_key)
        prior = await repo.closest_before(metric_key, day_ago)
        delta_text = ""
        if prior is not None and prior.value:
            delta_pct = round((latest.value - prior.value) / prior.value * 100, 2)
            delta_text = f", günlük değişim %{delta_pct:+.2f}"
        facts.append(
            GroundingFact(
                label=pair_label,
                value_text=f"{latest.value:.4f}{delta_text}",
                source=latest.source,
                source_url=latest.source_url or "",
            )
        )
    return facts


async def _fx_forecast_facts(db: AsyncSession) -> list[GroundingFact]:
    repo = CuratedRepository(db)
    rows = await repo.fx_forecasts()
    # One (the newest) forecast per (institution, pair) -- the prompt should
    # see each bank's current call, not its full revision history.
    seen: set[tuple[str, str]] = set()
    facts = []
    for row in rows:
        key = (row.institution, row.currency_pair)
        if key in seen:
            continue
        seen.add(key)
        facts.append(
            GroundingFact(
                label=f"{row.institution} {row.currency_pair} tahmini ({row.horizon_label})",
                value_text=f"{row.value:.4f}",
                source=row.institution,
                source_url=row.source_url,
            )
        )
    return facts


async def _iata_facts(db: AsyncSession) -> list[GroundingFact]:
    repo = CuratedRepository(db)
    rows = await repo.iata_indicators()
    seen: set[tuple[str, str]] = set()
    facts = []
    for row in rows:
        key = (row.metric, row.kind)
        if key in seen:
            continue
        seen.add(key)
        # The same two words the KPI page and Kokpit's tiles use for these two
        # kinds (app/taxonomy.py). IataIndicator.kind is its own two-value
        # vocabulary (INDICATOR_KINDS), so an unrecognised value stays verbatim
        # rather than being rounded to "tahmin" -- a grounding fact must not
        # tell the model a thing we did not read.
        kind_tr = PERIOD_KIND_LABELS_TR.get(row.kind, row.kind)
        facts.append(
            GroundingFact(
                label=f"IATA {row.metric} ({kind_tr}, {row.period_label_tr})",
                value_text=f"{row.value} {row.unit}",
                source="IATA",
                source_url=row.source_url,
            )
        )
    return facts


async def build_grounding(db: AsyncSession) -> list[GroundingFact]:
    facts = await _fx_board_facts(db)
    facts += await _fx_forecast_facts(db)
    facts += await _iata_facts(db)
    return facts


def _build_prompt(facts: list[GroundingFact]) -> str:
    lines = [f"- {f.label}: {f.value_text} (kaynak: {f.source}, {f.source_url})" for f in facts]
    facts_block = "\n".join(lines)
    return f"""Aşağıda AeroIntel'in Kokpit sayfası için doğrulanmış, güncel veri noktaları var. \
Bunlardan başka HİÇBİR sayı, kurum adı veya iddia kullanma -- sadece bu listedeki verileri \
bir havayolu gelir yönetimi ekibi için 3-5 cümlelik kısa bir Türkçe yorumda sentezle.

VERİLER:
{facts_block}

Her cümlenin dayandığı veriyi, o veriye ait source_url'yi AYNEN kopyalayarak belirt. \
Yalnızca şu JSON şemasıyla cevap ver, başka hiçbir metin ekleme:
{{"summary_tr": "...", "citations": [{{"claim": "...", "source": "...", "source_url": "..."}}]}}"""


def _parse_and_validate(raw: str, allowed_urls: set[str]) -> tuple[str, list[dict]] | None:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("market_pulse_response_not_json")
        return None

    if not isinstance(parsed, dict):
        return None
    summary_tr = parsed.get("summary_tr")
    citations = parsed.get("citations")
    if not isinstance(summary_tr, str) or not summary_tr.strip():
        return None
    if not isinstance(citations, list) or not citations:
        return None

    validated: list[dict] = []
    for citation in citations:
        if not isinstance(citation, dict):
            return None
        claim, source, source_url = (
            citation.get("claim"),
            citation.get("source"),
            citation.get("source_url"),
        )
        if not all(isinstance(v, str) and v.strip() for v in (claim, source, source_url)):
            return None
        if source_url not in allowed_urls:
            # A citation pointing anywhere we didn't supply is exactly the
            # hallucination this whole function exists to catch -- reject the
            # entire generation rather than drop the one bad citation, since a
            # model that invented one source is not trustworthy on the rest.
            logger.warning("market_pulse_citation_url_not_in_grounding", source_url=source_url)
            return None
        validated.append({"claim": claim, "source": source, "source_url": source_url})

    return summary_tr, validated


async def generate_market_pulse(db: AsyncSession) -> MarketPulse | None:
    from app.llm.factory import get_raw_generator

    generate = get_raw_generator()
    if generate is None:
        return None

    facts = await build_grounding(db)
    if not facts:
        return None

    prompt = _build_prompt(facts)
    try:
        raw = await generate(prompt)
    except Exception as exc:  # noqa: BLE001 -- any provider/network failure just skips today's pulse
        logger.warning("market_pulse_generation_failed", error=str(exc))
        return None

    allowed_urls = {f.source_url for f in facts if f.source_url}
    validated = _parse_and_validate(raw, allowed_urls)
    if validated is None:
        return None
    summary_tr, citations = validated

    repo = MarketPulseRepository(db)
    pulse = repo.record(summary_tr, citations, datetime.now(timezone.utc))
    await db.commit()
    logger.info("market_pulse_generated", citation_count=len(citations))
    return pulse
