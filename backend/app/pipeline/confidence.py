"""How sure the pipeline is about a record, and whether the reader sees it.

The product rule is "do not show the reader anything you are not sure of", so
something has to hold the uncertainty. This does.

Five components, each in [0, 1], combined by fixed weights into a score and a
band. Nothing here is learned or tuned at runtime: the weights are constants in
this file with a table-driven test beside them, so changing the system's
judgement is a reviewable diff rather than an archaeology exercise.

The band is what the API filters on. `low` rows are written to the database --
they are the audit trail, and the record of what the pipeline chose not to show
-- but no production endpoint serves them.

Deliberate property: **a record with missing required fields cannot reach the
high band, whatever else it has going for it.** This is a cap, not a weight.
Weighting completeness at 0.20 was the first attempt and it did not hold: an
agency-sourced, three-times-corroborated campaign missing only its sale date
still scored 0.81 and landed in `high`. But "we are very sure about a campaign
whose dates we do not know" is not a coherent thing to say, and no choice of
weight makes it one -- enough good signals will always outvote one missing
field. Incompleteness is categorical, so the rule is too: see `_cap_for()`.

This is why a campaign with no sale window stays invisible rather than
appearing with a blank date, which is what the reader was being shown before.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Literal

Band = Literal["high", "medium", "low"]

# --- weights -----------------------------------------------------------------
#
# Ordered by how much they deserve to move the answer. Source reliability leads
# because the owner's priority ladder is a statement about exactly this: an
# official airline announcement and an aggregator's rewrite of it are not
# equally trustworthy even when they say the same words.

WEIGHT_SOURCE_TIER = 0.30
WEIGHT_CLASSIFIER_CERTAINTY = 0.25
WEIGHT_FIELD_COMPLETENESS = 0.20
WEIGHT_SIGNAL_AGREEMENT = 0.15
WEIGHT_CORROBORATION = 0.10

_WEIGHTS = {
    "source_tier": WEIGHT_SOURCE_TIER,
    "classifier_certainty": WEIGHT_CLASSIFIER_CERTAINTY,
    "field_completeness": WEIGHT_FIELD_COMPLETENESS,
    "signal_agreement": WEIGHT_SIGNAL_AGREEMENT,
    "corroboration": WEIGHT_CORROBORATION,
}

assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9, "confidence weights must sum to 1"

HIGH_THRESHOLD = 0.75
MEDIUM_THRESHOLD = 0.50

# --- source tiers -------------------------------------------------------------
#
# The owner's ladder, as numbers. An airline announcing its own campaign is the
# top of it; a Google News query that found someone quoting that announcement is
# the bottom.

SOURCE_TIER_SCORES: dict[str, float] = {
    "official": 1.00,  # the airline's or airport's own announcement
    "regulator": 0.90,  # IATA, ICAO, EASA, national authorities
    "agency": 0.75,  # Reuters, AA, major wires
    "trade": 0.60,  # aviation and financial trade press
    "aggregator": 0.40,  # Google News queries and similar
}
DEFAULT_SOURCE_TIER = "trade"


@dataclass(frozen=True)
class ConfidenceInput:
    """Everything the score is allowed to depend on."""

    source_tier: str
    #: The classifier's own certainty. None means it did not report one, which
    #: is treated as "no evidence of confidence", not as confidence.
    classifier_certainty: float | None
    required_fields_present: int
    required_fields_total: int
    #: Does the deterministic extractor agree with the model's answer? None when
    #: there is nothing to cross-check against.
    #:
    #: A float in [0, 1] is also accepted, and is what the campaign extraction
    #: chain passes: it cross-checks up to four dates per campaign against the
    #: regex layer, and "three of four" is a real answer that a boolean would
    #: have to round to yes or no. `score()` reads it numerically either way --
    #: `float(True)` is 1.0 -- so the two spellings agree by construction.
    signal_agreement: bool | float | None
    #: How many distinct sources reported this event.
    source_count: int


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    band: Band
    components: dict[str, float]

    def as_detail(self) -> dict:
        """The JSON written to `confidence_detail`, and shown in the UI drawer.

        Stored per record rather than recomputed, so a score can be explained
        months later even after the weights have moved on.
        """
        return {
            "score": round(self.score, 4),
            "band": self.band,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "weights": dict(_WEIGHTS),
        }


def _corroboration_score(source_count: int, source_tier: str) -> float:
    """Independent reports raise confidence, with diminishing returns.

    An official source needs no corroboration: when the airline itself
    announces a campaign, a second outlet repeating it adds nothing. Demanding
    corroboration there would penalise the most reliable input we have.
    """
    if SOURCE_TIER_SCORES.get(source_tier, 0.0) >= SOURCE_TIER_SCORES["official"]:
        return 1.0
    if source_count <= 0:
        return 0.0
    # 1 -> 0.30, 2 -> 0.68, 3 -> 0.90, 4+ -> 1.00
    return min(1.0, 0.30 + 0.63 * math.log(source_count, 3))


def score(data: ConfidenceInput) -> ConfidenceResult:
    tier = SOURCE_TIER_SCORES.get(data.source_tier, SOURCE_TIER_SCORES[DEFAULT_SOURCE_TIER])

    if data.required_fields_total <= 0:
        completeness = 1.0
    else:
        completeness = max(
            0.0, min(1.0, data.required_fields_present / data.required_fields_total)
        )

    # A model that reports no certainty gets none credited. Defaulting to a
    # middling value would let a silent classifier look as good as a confident
    # one, which is the failure this whole module exists to prevent.
    certainty = data.classifier_certainty if data.classifier_certainty is not None else 0.0

    # Nothing to cross-check reads as neutral, not as disagreement: absence of a
    # second opinion is not evidence against the first.
    agreement = 0.5 if data.signal_agreement is None else float(data.signal_agreement)

    components = {
        "source_tier": tier,
        "classifier_certainty": max(0.0, min(1.0, certainty)),
        "field_completeness": completeness,
        "signal_agreement": agreement,
        "corroboration": _corroboration_score(data.source_count, data.source_tier),
    }

    total = sum(components[name] * weight for name, weight in _WEIGHTS.items())
    band = _apply_cap(band_for(total), _cap_for(completeness))
    return ConfidenceResult(score=total, band=band, components=components)


def band_for(value: float) -> Band:
    if value >= HIGH_THRESHOLD:
        return "high"
    if value >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


_BAND_ORDER: tuple[Band, ...] = ("low", "medium", "high")


def _cap_for(completeness: float) -> Band:
    """The best band a record with this much of its required data may occupy.

    Full data caps at `high` (i.e. no cap). Anything missing caps at `medium` --
    the record can still be shown, but never as something we are sure of. Below
    half, the record is mostly holes and is capped at `low`, which means it is
    not shown at all.
    """
    if completeness >= 1.0:
        return "high"
    if completeness >= 0.5:
        return "medium"
    return "low"


def _apply_cap(band: Band, cap: Band) -> Band:
    return band if _BAND_ORDER.index(band) <= _BAND_ORDER.index(cap) else cap


def is_publishable(band: str | None) -> bool:
    """The single gate every read endpoint applies.

    A record with no band has not been scored, which is not the same as scoring
    badly -- and is equally not something to put in front of a reader.
    """
    return band in ("high", "medium")


#: Denominator used when a stored completeness ratio is turned back into the
#: (present, total) pair `ConfidenceInput` is written in. Nothing downstream
#: reads the pair -- `score()` divides it immediately and `_cap_for` reads only
#: the ratio -- so any denominator that preserves the ratio reproduces the
#: original score exactly; 1000 keeps three decimals of it.
_COMPLETENESS_SCALE = 1000

_TIER_BY_SCORE = {value: name for name, value in SOURCE_TIER_SCORES.items()}


def rescore_with_corroboration(
    detail: dict | None, *, source_count: int
) -> ConfidenceResult | None:
    """Re-run `score()` for a stored record whose source count has changed.

    The one input that can legitimately change after a record is written is how
    many independent pages reported it: a second source turning up is new
    evidence that the campaign is real, and a score that cannot move for it
    would make the `corroboration` weight decorative. Everything else is
    reconstructed from `confidence_detail` exactly as it was scored -- this is
    a re-score of one input, not a re-judgement of the record.

    None when the stored detail predates component storage or is unreadable,
    which the caller must treat as "leave the score alone".
    """
    components = (detail or {}).get("components") or {}
    if not components:
        return None
    try:
        completeness = float(components.get("field_completeness", 0.0))
        return score(
            ConfidenceInput(
                source_tier=_TIER_BY_SCORE.get(
                    round(float(components.get("source_tier", 0.0)), 4), DEFAULT_SOURCE_TIER
                ),
                classifier_certainty=float(components.get("classifier_certainty", 0.0)),
                required_fields_present=round(completeness * _COMPLETENESS_SCALE),
                required_fields_total=_COMPLETENESS_SCALE,
                signal_agreement=float(components.get("signal_agreement", 0.5)),
                source_count=source_count,
            )
        )
    except (TypeError, ValueError):
        return None


def explain(data: ConfidenceInput) -> dict:
    """Score plus the inputs that produced it, for the audit trail."""
    result = score(data)
    return {**result.as_detail(), "inputs": asdict(data)}
