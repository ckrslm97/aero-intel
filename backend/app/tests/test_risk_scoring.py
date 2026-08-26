"""Risk score = severity x probability x aviation impact x recency x source tier.

The heuristic this replaces had an opinion about exactly one of these five
inputs (severity, via which keyword tier matched). It could not say how likely
an event was, how much it actually touched aviation, how fresh it was, or how
reliable the source was -- so a plausible-sounding, severe-sounding keyword
match scored the same whether it was a live war or a six-year-old trial.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.pipeline.risk_scoring import RECENCY_HALF_LIFE_DAYS, score

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def _score(**overrides):
    defaults = dict(
        severity="high", probability=0.9, aviation_impact_score=0.9,
        source_tier="agency", event_time=NOW,
    )
    defaults.update(overrides)
    return score(**defaults, now=NOW)


def test_a_severe_but_improbable_event_scores_near_zero():
    """The shape of the film-review case, if one somehow reached scoring: high
    severity, but the model was not sure it even happened and said so. One
    weak input should be enough to sink the score, not get outvoted by the
    others."""
    result = _score(probability=0.05, aviation_impact_score=0.1)
    assert result.score < 0.02


def test_a_severe_probable_event_with_no_aviation_relevance_also_sinks():
    """Real, severe, certain -- but not an aviation story. A general economic
    crisis with no stated aviation angle should not out-rank an airport
    closure just because 'severity' is high on both."""
    result = _score(aviation_impact_score=0.1)
    low_impact = result.score
    high_impact = _score(aviation_impact_score=0.9).score
    assert low_impact < high_impact / 3


@pytest.mark.parametrize(
    "severity,expect_order",
    [("high", 3), ("medium", 2), ("low", 1)],
)
def test_severity_ordering_is_preserved(severity, expect_order):
    scores = {
        s: _score(severity=s).score for s in ("high", "medium", "low")
    }
    ranked = sorted(scores, key=scores.get, reverse=True)
    assert ranked == ["high", "medium", "low"]


def test_recency_halves_at_the_half_life():
    fresh = _score(event_time=NOW).score
    half_life_old = _score(event_time=NOW - timedelta(days=RECENCY_HALF_LIFE_DAYS)).score
    assert half_life_old == pytest.approx(fresh / 2, rel=0.01)


def test_recency_never_exceeds_one_for_a_future_timestamp():
    """A clock-skew or a published_at that is technically after 'now' must not
    produce a score above what a perfectly fresh event would get."""
    fresh = _score(event_time=NOW).score
    future = _score(event_time=NOW + timedelta(hours=2)).score
    assert future == pytest.approx(fresh)


def test_official_source_outranks_an_aggregator_at_equal_content():
    official = _score(source_tier="official").score
    aggregator = _score(source_tier="aggregator").score
    assert official > aggregator


def test_unknown_source_tier_falls_back_rather_than_crashing():
    result = _score(source_tier="no-such-tier")
    assert result.components["source_tier"] > 0


@pytest.mark.parametrize("value", [-0.5, 1.5])
def test_out_of_range_inputs_are_clamped_not_propagated(value):
    result = _score(probability=value, aviation_impact_score=value)
    assert 0.0 <= result.components["probability"] <= 1.0
    assert 0.0 <= result.components["aviation_impact"] <= 1.0


def test_every_component_is_reported_for_the_audit_trail():
    result = _score()
    assert set(result.components) == {
        "severity", "probability", "aviation_impact", "recency", "source_tier",
    }
