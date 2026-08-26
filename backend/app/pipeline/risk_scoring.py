"""Risk score: severity x probability x aviation impact x recency x source tier.

Five inputs, matching the owner's own list for what should decide how hot a
risk reads on the radar. The heuristic this replaces had no way to produce
four of the five: `classify_risk_heuristic` could only say a keyword matched,
never how likely the event was, how much it actually touched aviation, how
fresh it was, or how reliable the source was -- severity was the only
dimension it had an opinion on, and that opinion came from which keyword tier
matched, not from the event itself.

`probability` and `aviation_impact_score` now come from the model
(RiskAssessment, see llm/classify.py) -- both load-bearing inputs the parser
requires before it will call a risk CLASSIFIED at all. Severity reuses the
app's existing high/medium/low convention. Recency and source tier are
computed here, outside the model call, because both are facts about the
record, not judgements about the event.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.pipeline.confidence import SOURCE_TIER_SCORES
from app.taxonomy import RISK_SEVERITY_WEIGHT

#: Exponential half-life for the recency term: a risk event is "as hot as it
#: will ever be" the moment it is reported, and a revenue desk's reaction
#: window for this kind of news is days, not weeks. Three days was picked to
#: match the same lookback window pipeline/clustering.py and pipeline/dedup.py
#: already use for "how long is a story still live" -- one number, one meaning,
#: reused rather than re-guessed here.
RECENCY_HALF_LIFE_DAYS = 3.0

#: Highest value RISK_SEVERITY_WEIGHT can produce, for normalising it onto the
#: same 0-1 scale as the other four inputs. Computed rather than hardcoded so
#: a future severity tier does not silently throw the normalisation off.
_MAX_SEVERITY_WEIGHT = max(RISK_SEVERITY_WEIGHT.values())


@dataclass(frozen=True)
class RiskScoreResult:
    score: float
    components: dict


def _recency_weight(event_time: datetime, *, now: datetime | None = None) -> float:
    """1.0 at the moment of the event, halving every RECENCY_HALF_LIFE_DAYS.

    A risk from six hours ago and one from six days ago are not the same
    "how hot is this right now" answer, even at identical severity -- the
    old system had no notion of this at all; risk rows never aged.
    """
    reference = now or datetime.now(timezone.utc)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    days_elapsed = max(0.0, (reference - event_time).total_seconds() / 86400)
    return math.pow(0.5, days_elapsed / RECENCY_HALF_LIFE_DAYS)


def score(
    *,
    severity: str,
    probability: float,
    aviation_impact_score: float,
    source_tier: str,
    event_time: datetime,
    now: datetime | None = None,
) -> RiskScoreResult:
    """Every component already lives in [0, 1]; the result is their product,
    which is deliberate -- a risk score should collapse to near-zero if any
    single input is near-zero (an event nobody is sure happened, or one with
    no real aviation relevance, should not rank as hot regardless of how
    severe its label is)."""
    severity_component = RISK_SEVERITY_WEIGHT.get(severity, 0) / _MAX_SEVERITY_WEIGHT
    probability_component = max(0.0, min(1.0, probability))
    impact_component = max(0.0, min(1.0, aviation_impact_score))
    recency_component = _recency_weight(event_time, now=now)
    source_component = SOURCE_TIER_SCORES.get(source_tier, SOURCE_TIER_SCORES["trade"])

    total = (
        severity_component
        * probability_component
        * impact_component
        * recency_component
        * source_component
    )

    return RiskScoreResult(
        score=round(total, 4),
        components={
            "severity": round(severity_component, 4),
            "probability": round(probability_component, 4),
            "aviation_impact": round(impact_component, 4),
            "recency": round(recency_component, 4),
            "source_tier": round(source_component, 4),
        },
    )
