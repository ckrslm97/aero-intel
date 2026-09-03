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
    is_valid_business_class,
    is_valid_campaign_type,
    is_valid_risk_category,
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
    category: str
    severity: str
    #: The model's own certainty that this event is real, distinct from
    #: `Outcome.certainty` (which is the *classification* confidence -- "I am
    #: sure this is what the article says" -- not "I am sure this happened").
    #: Feeds pipeline/risk_scoring.py.
    probability: float
    #: How directly this touches commercial aviation, 0-1. The second input
    #: risk_scoring.py needs and the keyword heuristic had no way to produce --
    #: it could only say a word matched, never how much the match mattered.
    aviation_impact_score: float
    country: str | None
    city: str | None
    aviation_impact_note: str | None

    # --- the verification fields (spec §7-17) --------------------------------
    #
    # Optional with None defaults, for the same reason CampaignExtraction's
    # intelligence fields are: every existing construction of this dataclass --
    # the tests, the golden-set evaluator, the heuristic path -- keeps working
    # unchanged, and a model that ignores the new prompt lines produces None
    # here rather than a failed parse.
    #
    # None is "the model did not answer" on all of them, and no gate may read
    # it as a low score. See _parse_risk.
    #: 0-1: how sure the model is of `country`, given that the article's
    #: datelines and government quotes name places the event did not happen in.
    location_confidence: float | None = None
    #: Every place named, with the role it played:
    #: [{"name": "Japan", "kind": "country", "role": "event"}]
    mentioned_locations: list[dict] | None = None
    #: The sentence `aviation_impact_score` was read off, quoted verbatim.
    #: Distinct from aviation_impact_note, which is the model's own Turkish
    #: gloss: one is evidence, the other is commentary, and a reader checking
    #: the score needs the first.
    aviation_impact_evidence: str | None = None
    #: "ACTUAL" | "POTENTIAL" -- reported, or forecast.
    aviation_impact_status: str | None = None
    is_current_event: bool | None = None
    is_historical: bool | None = None
    is_analysis: bool | None = None
    is_opinion: bool | None = None
    is_recap: bool | None = None


@dataclass(frozen=True)
class CampaignExtraction:
    airline_code: str
    discount_pct: int | None
    sale_starts: date | None
    sale_ends: date | None
    travel_starts: date | None
    travel_ends: date | None
    markets: dict
    #: The campaign-intelligence fields, asked for only when the runner passes
    #: `classify_prompt.campaign_topic_fragment()` (i.e. CAMPAIGN_V2_ENABLED).
    #: Optional with None defaults so every existing construction of this
    #: dataclass -- the tests, the golden-set evaluator, the heuristic path --
    #: keeps working unchanged, and so a model that ignores the fragment
    #: produces a row with these columns null rather than a failed parse.
    campaign_type: str | None = None
    business_class_hint: str | None = None
    origin: str | None = None
    destination: str | None = None


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


#: The five currency flags (spec §15). `is_developing` / `is_resolved` are
#: absent by design: nothing in this pipeline carries an event lifecycle, only
#: publication times, so no classifier could answer them from what it is shown.
CURRENCY_FLAGS = (
    "is_current_event",
    "is_historical",
    "is_analysis",
    "is_opinion",
    "is_recap",
)

AVIATION_IMPACT_STATUSES = frozenset({"ACTUAL", "POTENTIAL"})


def _clean_tristate(value: object) -> bool | None:
    """True / False / None, where None is "the model did not answer".

    Not `bool(value)`. A missing flag collapsed to False is a row the currency
    gate then deletes, on the strength of a key the model never emitted.
    """
    return value if isinstance(value, bool) else None


def _clean_mentioned_locations(value: object) -> list[dict] | None:
    """Places and their roles, rebuilt field by field.

    Never the model's own object: this reaches a JSONB column, and a response
    that answers with strings, nested lists or extra keys must not be able to
    write its shape into the database for a later reader to trip over.
    """
    if not isinstance(value, list):
        return None
    cleaned: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _clean_str(item.get("name"))
        if not name:
            continue
        kind = (_clean_str(item.get("kind")) or "").lower()
        role = (_clean_str(item.get("role")) or "").lower()
        cleaned.append(
            {
                "name": name,
                "kind": kind if kind in {"country", "city"} else "unknown",
                # Default to "event": "source" is the label that REMOVES a
                # place from consideration as the event location, so it has to
                # be asserted rather than assumed.
                "role": "source" if role == "source" else "event",
            }
        )
    return cleaned or None


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

    risk_category = (_clean_str(risk.get("category")) or "").lower()
    if not is_valid_risk_category(risk_category):
        return Outcome.failed(f"off_taxonomy_risk_category:{risk_category or 'missing'}")

    severity = (_clean_str(risk.get("severity")) or "").lower()
    if severity not in RISK_SEVERITIES:
        return Outcome.failed(f"off_taxonomy_risk_severity:{severity or 'missing'}")

    probability = _clean_confidence(risk.get("probability"))
    aviation_impact_score = _clean_confidence(risk.get("aviation_impact_score"))
    # Both are load-bearing inputs to the risk score, not optional colour --
    # a model that flags a risk but won't estimate how likely or how relevant
    # it is has not really answered the question.
    if probability is None or aviation_impact_score is None:
        return Outcome.failed("risk_missing_scoring_inputs")

    # The verification fields are NOT required the way probability and
    # aviation_impact_score above are. Those two are load-bearing inputs to the
    # risk score, so a model that skips them has not answered the question;
    # these describe how much to TRUST the answer, and a model that skips them
    # has produced a less verifiable classification, not an invalid one.
    # Failing the call over them would delete good rows to punish a model for
    # ignoring a prompt line.
    status = _clean_str(risk.get("aviation_impact_status"))
    status = status.upper() if status else None
    if status not in AVIATION_IMPACT_STATUSES:
        status = None

    return Outcome.classified(
        RiskAssessment(
            category=risk_category,
            severity=severity,
            probability=probability,
            aviation_impact_score=aviation_impact_score,
            country=_clean_str(risk.get("country")),
            city=_clean_str(risk.get("city")),
            aviation_impact_note=_clean_str(risk.get("aviation_impact_note")),
            location_confidence=_clean_confidence(risk.get("location_confidence")),
            mentioned_locations=_clean_mentioned_locations(risk.get("mentioned_locations")),
            aviation_impact_evidence=_clean_str(risk.get("aviation_impact_evidence")),
            aviation_impact_status=status,
            **{flag: _clean_tristate(risk.get(flag)) for flag in CURRENCY_FLAGS},
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

    # Off-taxonomy campaign_type/business_class_hint are dropped rather than
    # failing the call, the same way an off-parent subcategory is above: the
    # campaign itself is still usable, and the alternative is losing a correct
    # extraction over a vocabulary slip in a field the row can carry as null.
    campaign_type = (_clean_str(campaign.get("campaign_type")) or "").upper() or None
    if campaign_type and not is_valid_campaign_type(campaign_type):
        logger.info("classify_campaign_type_dropped", campaign_type=campaign_type)
        campaign_type = None
    business_class = (_clean_str(campaign.get("business_class_hint")) or "").upper() or None
    if business_class and not is_valid_business_class(business_class):
        logger.info("classify_business_class_dropped", business_class=business_class)
        business_class = None

    return Outcome.classified(
        CampaignExtraction(
            airline_code=airline_code.upper(),
            discount_pct=_clean_pct(campaign.get("discount_pct")),
            sale_starts=_clean_date(campaign.get("sale_starts")),
            sale_ends=_clean_date(campaign.get("sale_ends")),
            travel_starts=_clean_date(campaign.get("travel_starts")),
            travel_ends=_clean_date(campaign.get("travel_ends")),
            markets=normalized_markets,
            campaign_type=campaign_type,
            business_class_hint=business_class,
            origin=_clean_str(campaign.get("origin")),
            destination=_clean_str(campaign.get("destination")),
        ),
        certainty=certainty,
    )


@dataclass(frozen=True)
class NewsImpact:
    """The three revenue-management impact scores from one consolidated call.

    Every field is required and in [0, 1]. A partial answer is not accepted:
    `app/services/news_scoring.py` renormalises its weights over whichever
    components are present, so a payload carrying only `rm_impact` would
    silently produce a score weighted quite differently from its neighbours --
    two articles ranked against each other on different rubrics. Either the
    model answered the question it was asked, or the article keeps its
    deterministic-only score, which is a real number and not a degraded one.
    """

    rm_impact: float
    demand_impact: float
    capacity_impact: float
    #: One short Turkish sentence, or None. Colour for the audit trail; nothing
    #: ranks on it.
    rationale_tr: str | None = None


#: How long a stored rationale may be. The prompt asks for one short sentence;
#: this is the backstop for a model that writes an essay, and it truncates
#: rather than rejecting because the three scores -- the part that matters --
#: are already valid by the time this applies.
MAX_RATIONALE_CHARS = 400


def parse_news_impact(raw: str) -> Outcome[NewsImpact]:
    """Parse one `news_impact_prompt` response.

    Never raises, and never writes the model's raw text anywhere: the payload
    is rebuilt field by field from validated values, so a response that is
    prose, truncated JSON or a JSON array cannot reach the database in any
    form. Same contract as `parse()` above.

    Three states, and the middle one is load-bearing:

      CLASSIFIED  three numbers in range -> the article gets LLM components
      FAILED      unparseable, missing or out-of-range -> the article keeps its
                  deterministic score and the columns stay NULL

    There is deliberately no NOT_APPLICABLE. Unlike risk and campaign
    classification, "this article has no RM impact" is not a refusal to answer
    -- it is the answer 0.0, which is a real, orderable score and must be
    stored as one. Collapsing it into NULL would make "the model read this and
    found nothing" indistinguishable from "nobody looked", which is the exact
    distinction app/services/news_scoring.py is built around.
    """
    payload = _extract_json(raw)
    if payload is None:
        logger.info("news_impact_parse_failed", sample=(raw or "")[:160])
        return Outcome.failed("json_parse_error")

    scores: dict[str, float] = {}
    for field_name in ("rm_impact", "demand_impact", "capacity_impact"):
        value = _clean_confidence(payload.get(field_name))
        if value is None:
            # _clean_confidence returns None for a missing key, a string, a
            # bool, or anything non-numeric -- all of which mean the model did
            # not score this axis. It CLAMPS out-of-range numbers rather than
            # rejecting them, which is right here: a model answering 1.2 has
            # expressed "as high as it goes", not garbage.
            return Outcome.failed(f"news_impact_missing:{field_name}")
        scores[field_name] = value

    rationale = _clean_str(payload.get("rationale_tr"))
    return Outcome.classified(
        NewsImpact(**scores, rationale_tr=rationale[:MAX_RATIONALE_CHARS] if rationale else None)
    )


async def score_news_impact(title: str, content: str, category: str) -> Outcome[NewsImpact]:
    """Run the impact call against the configured live model and parse it.

    No live model configured is a FAILED outcome rather than an error, exactly
    as `classify_article` treats it: the caller keeps the article's
    deterministic score and leaves the three columns NULL.
    """
    from app.llm.factory import get_raw_generator
    from app.llm.prompts import news_impact_prompt

    generate = get_raw_generator()
    if generate is None:
        return Outcome.failed("no_llm_configured")

    try:
        raw = await generate(news_impact_prompt(title, content, category))
    except Exception as exc:  # noqa: BLE001 -- a provider failure is FAILED, not a crash
        logger.warning("news_impact_call_failed", error=str(exc)[:200])
        return Outcome.failed("llm_call_error")

    return parse_news_impact(raw)
