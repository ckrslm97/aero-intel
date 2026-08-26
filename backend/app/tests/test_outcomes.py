"""The three-state result, and the invariant that makes it worth having.

The bug being closed: a classifier answering "not a risk" was indistinguishable
from one that failed, so both fell through to a keyword heuristic. A film review
about the bombing of Pan Am 103 became a high-severity attack in the UK that way.
"""
import pytest

from app.pipeline.outcomes import Outcome, OutcomeState


def test_classified_is_the_only_publishable_state():
    assert Outcome.classified({"risk_type": "flood"}).is_publishable
    assert not Outcome.not_applicable("entertainment_coverage").is_publishable
    assert not Outcome.failed("json_parse_error").is_publishable


def test_saying_no_is_an_assessment_but_failing_is_not():
    """`was_assessed` is the condition for stamping assessed_at. A "no" is a
    real answer and must not be re-asked; a failure must be retried."""
    assert Outcome.not_applicable("historical_commemoration").was_assessed
    assert Outcome.classified({"x": 1}).was_assessed
    assert not Outcome.failed("http_timeout").was_assessed


def test_not_applicable_is_not_a_failure():
    """The distinction the old code could not express."""
    no = Outcome.not_applicable("no_aviation_relevance")
    assert not no.is_failure
    assert no.state is OutcomeState.NOT_APPLICABLE


def test_reason_is_carried_for_the_audit_trail():
    assert Outcome.not_applicable("entertainment_coverage").reason == "entertainment_coverage"
    assert Outcome.failed("off_taxonomy_slug").reason == "off_taxonomy_slug"


def test_classified_requires_a_payload():
    with pytest.raises(ValueError, match="requires a payload"):
        Outcome(OutcomeState.CLASSIFIED)


def test_a_non_answer_cannot_smuggle_a_payload():
    """Guards the shape of the fix: if NOT_APPLICABLE could carry a payload,
    a caller could publish from it and we would be back where we started."""
    with pytest.raises(ValueError, match="must not carry a payload"):
        Outcome(OutcomeState.NOT_APPLICABLE, payload={"risk_type": "war"})
    with pytest.raises(ValueError, match="must not carry a payload"):
        Outcome(OutcomeState.FAILED, payload={"risk_type": "war"})


def test_a_failed_call_cannot_report_certainty():
    with pytest.raises(ValueError, match="cannot report certainty"):
        Outcome(OutcomeState.FAILED, certainty=0.9)


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_certainty_must_be_a_probability(value):
    with pytest.raises(ValueError, match="certainty out of range"):
        Outcome.classified({"x": 1}, certainty=value)
