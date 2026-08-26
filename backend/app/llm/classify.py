"""Parsing the consolidated classification response into three-state outcomes.

This module is where the veto is enforced. Everything the prompt asks for comes
back in one JSON object, and the parser's job is to turn it into `Outcome`s
that downstream code cannot misread:

* a valid classification -> CLASSIFIED
* an explicit "not a risk" / "not a campaign" / "not relevant" -> NOT_APPLICABLE
* anything unparseable, off-taxonomy or missing -> FAILED

The distinction the old code could not make is now impossible to lose: a
NOT_APPLICABLE outcome carries no payload, so there is nothing for a caller to
publish from, and a FAILED outcome is never a reason to fall back to a weaker
classifier. See app/pipeline/outcomes.py.

The parser is deliberately strict about the taxonomy and lenient about
everything else. A model inventing "hurricane" as a risk type is a failure --
the slug would render as nothing and the row would be silently wrong. A model
returning a date it could not parse, or an empty market list, is just missing
data, which the confidence score already knows how to handle by capping the
band.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from app.core.logging import get_logger
from app.pipeline.outcomes import Outcome
from app.taxonomy import (
    CATEGORY_SLUGS,
    GENERAL_CATEGORY,
    RISK_SEVERITIES,
    SUBCATEGORY_KEYWORDS,
    is_valid_risk_type,
)

logger = get_logger(__name__)

#: Models wrap JSON in prose or a fenced block however firmly they are asked
#: not to. Rather than failing the call for a formatting habit, pull the first
#: balanced object out and parse that.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


@dataclass(frozen=True)
class Classification:
    """The parts every article gets, when it is relevant at all."""

    category: str
    subcategory: str | None
    title_tr: str | None
    summary_tr: str | None
    confidence: float | None
    airlines: list[dict] = field(default_factory=list)
    airports: list[dict] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)

    @property
    def subject_airline_code(self) -> str | None:
        """The carrier the story is *about*.

        Attribution used to be "whichever tracked carrier is mentioned most",
        computed by ordering on a column that was never written. That is how a
        `Buy Alaska Points` article was attributed to British Airways -- BA
        appeared in a comparison table -- and an LNG pricing story to Emirates.
        """
        for airline in self.airlines:
            if airline.get("role") == "subject" and airline.get("code"):
                return str(airline["code"]).upper()
        return None


@dataclass(frozen=True)
class RiskAssessment:
    type: str
    severity: str
    country: str | None
    city: str | None
    aviation_impact: str | None


@dataclass(frozen=True)
class CampaignExtraction:
    airline_code: str
    discount_pct: int | None
    sale_starts: date | None
    sale_ends: date | None
    travel_starts: date | None
    travel_ends: date | None
    markets: dict


@dataclass(frozen=True)
class ClassificationResult:
    """One model call, three independent verdicts.

    They are separate Outcomes rather than fields on one object because they
    fail independently: a model can be confident an article is aviation news
    and correctly decline to call it a risk, and those two answers must not be
    able to contaminate each other.
    """

    article: Outcome[Classification]
    risk: Outcome[RiskAssessment]
    campaign: Outcome[CampaignExtraction]

    @property
    def is_publishable(self) -> bool:
        return self.article.is_publishable


def _extract_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _clean_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    # Models say "null", "none" and "yok" instead of emitting JSON null.
    if not stripped or stripped.lower() in {"null", "none", "n/a", "yok", "-"}:
        return None
    return stripped


def _clean_confidence(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def _clean_date(value: object) -> date | None:
    text = _clean_str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        # A date the model could not resolve is missing data, not a failed
        # call. Completeness scoring handles it by capping the band.
        return None


def _clean_pct(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    pct = int(value)
    return pct if 0 < pct <= 100 else None


def _clean_entities(value: object, *, code_key: str = "code") -> list[dict]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _clean_str(item.get("name"))
        code = _clean_str(item.get(code_key))
        if not (name or code):
            continue
        entry = {"name": name or code, "code": code.upper() if code else None}
        role = _clean_str(item.get("role"))
        if role:
            entry["role"] = role.lower()
        cleaned.append(entry)
    return cleaned


async def classify_article(
    title: str, content: str, *, topic_fragment: str = ""
) -> ClassificationResult:
    """Run the consolidated call against the configured live model and parse it.

    No live model configured (local dev, no key) is not an error -- it is the
    normal state the heuristic used to paper over. Every outcome comes back
    FAILED with a reason that says so, which means "retried later, never
    published" rather than a silent fall-through to a keyword guess.
    """
    from app.llm.classify_prompt import build_prompt
    from app.llm.factory import get_raw_generator

    generate = get_raw_generator()
    if generate is None:
        failure = Outcome.failed("no_llm_configured")
        return ClassificationResult(failure, failure, failure)

    prompt = build_prompt(title, content, topic_fragment=topic_fragment)
    try:
        raw = await generate(prompt)
    except Exception as exc:  # noqa: BLE001 -- any provider/network failure is a FAILED outcome, not a crash
        logger.warning("classify_call_failed", error=str(exc))
        failure = Outcome.failed("llm_call_error")
        return ClassificationResult(failure, failure, failure)

    return parse(raw)


def parse(raw: str) -> ClassificationResult:
    """Turn one model response into three outcomes.

    Never raises: a malformed response is a FAILED outcome, which means "retry
    later, publish nothing" -- not an exception that a caller might catch and
    paper over with a heuristic.
    """
    payload = _extract_json(raw)
    if payload is None:
        failure = Outcome.failed("json_parse_error")
        logger.info("classify_parse_failed", sample=(raw or "")[:160])
        return ClassificationResult(failure, failure, failure)

    return ClassificationResult(
        article=_parse_article(payload),
        risk=_parse_risk(payload),
        campaign=_parse_campaign(payload),
    )


def _parse_article(payload: dict) -> Outcome[Classification]:
    if payload.get("relevant") is False:
        reason = _clean_str(payload.get("not_relevant_reason")) or "not_relevant"
        return Outcome.not_applicable(
            reason, certainty=_clean_confidence(payload.get("confidence"))
        )

    category = (_clean_str(payload.get("category")) or "").lower()
    if category not in CATEGORY_SLUGS:
        # An off-taxonomy category renders as nothing and files the article
        # under a slug no filter offers. That is a failure, not missing data.
        return Outcome.failed(f"off_taxonomy_category:{category or 'missing'}")

    subcategory = (_clean_str(payload.get("subcategory")) or "").lower() or None
    allowed = SUBCATEGORY_KEYWORDS.get(category, {})
    if subcategory and subcategory not in allowed:
        # A subcategory under the wrong parent is dropped rather than failing
        # the whole call: the category is still usable and is the field the
        # newspaper actually files on.
        logger.info("classify_subcategory_dropped", category=category, subcategory=subcategory)
        subcategory = None

    return Outcome.classified(
        Classification(
            category=category or GENERAL_CATEGORY,
            subcategory=subcategory,
            title_tr=_clean_str(payload.get("title_tr")),
            summary_tr=_clean_str(payload.get("summary_tr")),
            confidence=_clean_confidence(payload.get("confidence")),
            airlines=_clean_entities(payload.get("airlines")),
            airports=_clean_entities(payload.get("airports")),
            countries=[c for c in (_clean_str(x) for x in payload.get("countries") or []) if c],
        ),
        certainty=_clean_confidence(payload.get("confidence")),
    )


def _parse_risk(payload: dict) -> Outcome[RiskAssessment]:
    certainty = _clean_confidence(payload.get("confidence"))

    if payload.get("is_risk") is not True:
        # The veto. An explicit false is a real answer and is recorded so the
        # next run does not re-ask, and so nothing downstream can overturn it.
        reason = _clean_str(payload.get("not_risk_reason")) or "not_a_risk"
        return Outcome.not_applicable(reason, certainty=certainty)

    risk = payload.get("risk")
    if not isinstance(risk, dict):
        # Claimed a risk and then did not describe one. Contradictory, so it is
        # a failed call rather than a silent "no".
        return Outcome.failed("risk_flagged_without_payload")

    risk_type = (_clean_str(risk.get("type")) or "").lower()
    if not is_valid_risk_type(risk_type):
        return Outcome.failed(f"off_taxonomy_risk_type:{risk_type or 'missing'}")

    severity = (_clean_str(risk.get("severity")) or "").lower()
    if severity not in RISK_SEVERITIES:
        return Outcome.failed(f"off_taxonomy_risk_severity:{severity or 'missing'}")

    return Outcome.classified(
        RiskAssessment(
            type=risk_type,
            severity=severity,
            country=_clean_str(risk.get("country")),
            city=_clean_str(risk.get("city")),
            aviation_impact=_clean_str(risk.get("aviation_impact")),
        ),
        certainty=certainty,
    )


def _parse_campaign(payload: dict) -> Outcome[CampaignExtraction]:
    certainty = _clean_confidence(payload.get("confidence"))

    if payload.get("is_campaign") is not True:
        reason = _clean_str(payload.get("not_campaign_reason")) or "not_a_campaign"
        return Outcome.not_applicable(reason, certainty=certainty)

    campaign = payload.get("campaign")
    if not isinstance(campaign, dict):
        return Outcome.failed("campaign_flagged_without_payload")

    airline_code = _clean_str(campaign.get("airline_code"))
    if not airline_code:
        # A campaign nobody is running is not a campaign. This is the field the
        # old extractor guessed at, and guessing is what produced 23% wrong
        # attribution.
        return Outcome.failed("campaign_without_airline")

    markets = campaign.get("markets")
    if not isinstance(markets, dict):
        markets = {}
    normalized_markets = {
        key: [m for m in (_clean_str(x) for x in markets.get(key) or []) if m]
        for key in ("regions", "countries", "cities")
    }

    return Outcome.classified(
        CampaignExtraction(
            airline_code=airline_code.upper(),
            discount_pct=_clean_pct(campaign.get("discount_pct")),
            sale_starts=_clean_date(campaign.get("sale_starts")),
            sale_ends=_clean_date(campaign.get("sale_ends")),
            travel_starts=_clean_date(campaign.get("travel_starts")),
            travel_ends=_clean_date(campaign.get("travel_ends")),
            markets=normalized_markets,
        ),
        certainty=certainty,
    )
