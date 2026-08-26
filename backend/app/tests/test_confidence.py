"""Hand-computed expectations for the confidence score.

If a weight changes, this table has to change with it -- deliberately. The
point of the module is that the system's judgement is reviewable, and a test
that recomputes the implementation would review nothing.
"""
import pytest

from app.pipeline.confidence import (
    ConfidenceInput,
    _WEIGHTS,
    band_for,
    is_publishable,
    score,
)


def test_weights_sum_to_one():
    assert sum(_WEIGHTS.values()) == pytest.approx(1.0)


# name, input, expected score, expected band
CASES = [
    (
        "official announcement, complete, single source",
        # 1.00*.30 + 0.95*.25 + 1.00*.20 + 1.00*.15 + 1.00*.10
        ConfidenceInput("official", 0.95, 3, 3, True, 1),
        0.9875,
        "high",
    ),
    (
        "agency, complete, three sources",
        # 0.75*.30 + 0.85*.25 + 1.00*.20 + 1.00*.15 + 0.93*.10
        ConfidenceInput("agency", 0.85, 3, 3, True, 3),
        0.8800,
        "high",
    ),
    (
        "aggregator, weak certainty, no cross-check",
        # 0.40*.30 + 0.60*.25 + 0.667*.20 + 0.50*.15 + 0.30*.10
        ConfidenceInput("aggregator", 0.60, 2, 3, None, 1),
        0.5083,
        "medium",
    ),
    (
        "classifier reported no certainty at all",
        # 0.60*.30 + 0.00*.25 + 1.00*.20 + 1.00*.15 + 0.87*.10
        ConfidenceInput("trade", None, 3, 3, True, 2),
        0.6000,
        "medium",
    ),
    (
        "deterministic extractor disagrees with the model",
        # 0.75*.30 + 0.90*.25 + 1.00*.20 + 0.00*.15 + 0.70*.10
        # Disagreement zeroes the whole agreement term, which is the point:
        # it costs more than a middling source would.
        ConfidenceInput("agency", 0.90, 3, 3, False, 2),
        0.7197,
        "medium",
    ),
]


@pytest.mark.parametrize("name,data,expected_score,expected_band", CASES)
def test_scores_match_hand_computation(name, data, expected_score, expected_band):
    result = score(data)
    assert result.score == pytest.approx(expected_score, abs=0.005), name
    assert result.band == expected_band, name


# --- the completeness cap ----------------------------------------------------
#
# The property that makes "I don't know" expressible. These are the tests that
# failed the first implementation, where completeness was only a weight.


def test_missing_a_required_field_cannot_be_high_confidence():
    """A campaign missing its sale window, with everything else perfect."""
    result = score(ConfidenceInput("agency", 0.85, 2, 3, True, 3))
    assert result.score > 0.75, "raw score would otherwise qualify for high"
    assert result.band == "medium"


def test_mostly_missing_fields_is_not_publishable_however_good_the_source():
    """An official source is not a substitute for knowing the facts."""
    result = score(ConfidenceInput("official", 0.99, 1, 3, True, 5))
    assert result.score > 0.75
    assert result.band == "low"
    assert not is_publishable(result.band)


def test_complete_record_is_not_capped():
    result = score(ConfidenceInput("official", 0.95, 4, 4, True, 2))
    assert result.band == "high"


def test_no_required_fields_declared_counts_as_complete():
    """Domains without required fields are not punished for having none."""
    result = score(ConfidenceInput("official", 0.95, 0, 0, True, 1))
    assert result.band == "high"


# --- corroboration -----------------------------------------------------------


def test_official_source_needs_no_corroboration():
    """When the airline announces its own campaign, a second outlet repeating
    it adds nothing -- and demanding one would penalise the best input we have."""
    alone = score(ConfidenceInput("official", 0.9, 2, 2, True, 1))
    echoed = score(ConfidenceInput("official", 0.9, 2, 2, True, 4))
    assert alone.components["corroboration"] == 1.0
    assert alone.score == pytest.approx(echoed.score)


def test_corroboration_rises_with_sources_and_saturates():
    values = [
        score(ConfidenceInput("agency", 0.8, 2, 2, True, n)).components["corroboration"]
        for n in (1, 2, 3, 6)
    ]
    assert values == sorted(values), "more sources must never lower confidence"
    assert values[-1] == 1.0


# --- the gate ----------------------------------------------------------------


@pytest.mark.parametrize(
    "band,expected",
    [("high", True), ("medium", True), ("low", False), (None, False), ("", False)],
)
def test_publishable_gate(band, expected):
    assert is_publishable(band) is expected


def test_unscored_record_is_not_publishable():
    """Never scored is not the same as scored badly, and neither reaches the
    reader."""
    assert not is_publishable(None)


@pytest.mark.parametrize(
    "value,band",
    [(1.0, "high"), (0.75, "high"), (0.7499, "medium"), (0.50, "medium"), (0.4999, "low"), (0.0, "low")],
)
def test_band_thresholds_are_inclusive_at_the_bottom(value, band):
    assert band_for(value) == band


def test_unknown_source_tier_falls_back_rather_than_crashing():
    result = score(ConfidenceInput("no-such-tier", 0.8, 2, 2, True, 2))
    assert result.components["source_tier"] == pytest.approx(0.60)
