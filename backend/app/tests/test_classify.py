"""Parsing the consolidated classification response.

Fixtures are recorded shapes, not live calls -- CI must not depend on a model
being reachable or on it answering the same way twice. Each one corresponds to
a real production row or a real failure mode.
"""
import json
from datetime import date

import pytest

from app.llm.classify import parse
from app.pipeline.outcomes import OutcomeState


def _response(**overrides) -> str:
    payload = {
        "relevant": True,
        "category": "revenue_management",
        "subcategory": "promotion",
        "confidence": 0.9,
        "title_tr": "Pegasus 6 hatta indirim kampanyası başlattı",
        "summary_tr": "Pegasus, altı hatta yüzde 50'ye varan indirim açıkladı.",
        "airlines": [{"code": "PC", "name": "Pegasus Airlines", "role": "subject"}],
        "airports": [],
        "countries": ["Türkiye"],
        "is_risk": False,
        "not_risk_reason": "commercial_announcement",
        "risk": None,
        "is_campaign": True,
        "campaign": {
            "airline_code": "PC",
            "discount_pct": 50,
            "sale_starts": "2026-08-20",
            "sale_ends": "2026-08-31",
            "travel_starts": None,
            "travel_ends": None,
            "markets": {"regions": ["europe"], "countries": [], "cities": ["Roma"]},
        },
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


# --- the veto -----------------------------------------------------------------


def test_an_explicit_no_is_recorded_not_treated_as_a_failure():
    """`Film Notları: The Bombing of Pan Am 103` -- the owner's example.

    The old pipeline could not express this answer: a null risk_type meant
    either "not a risk" or "the call failed", and both fell through to the
    keyword heuristic, which scored `bombing` at 3 from the title alone and
    published a film review as a high-severity attack in the United Kingdom.
    """
    result = parse(
        _response(
            category="general",
            is_risk=False,
            not_risk_reason="entertainment_coverage",
            is_campaign=False,
            campaign=None,
        )
    )
    assert result.risk.state is OutcomeState.NOT_APPLICABLE
    assert result.risk.reason == "entertainment_coverage"
    # The load-bearing distinction: a "no" is an assessment, so it is stamped
    # and never re-asked -- and it is not a failure, so nothing retries it into
    # a different answer.
    assert result.risk.was_assessed
    assert not result.risk.is_failure
    assert not result.risk.is_publishable


def test_a_no_carries_no_payload_so_nothing_can_publish_from_it():
    result = parse(_response(is_risk=False, risk=None))
    assert result.risk.payload is None


def test_irrelevant_articles_are_declined_wholesale():
    """25 of 200 sampled articles had no aviation relevance at all -- pumpkin
    spice, US house prices, a cycling stage win."""
    result = parse(
        json.dumps({"relevant": False, "not_relevant_reason": "not_aviation"})
    )
    assert result.article.state is OutcomeState.NOT_APPLICABLE
    assert result.article.reason == "not_aviation"
    assert not result.is_publishable


# --- failures are not vetoes --------------------------------------------------


def test_unparseable_response_fails_every_verdict():
    result = parse("I'm sorry, I can't help with that.")
    for outcome in (result.article, result.risk, result.campaign):
        assert outcome.state is OutcomeState.FAILED
        assert outcome.reason == "json_parse_error"
        # Not assessed -> stays pending, retried, never published.
        assert not outcome.was_assessed


def test_off_taxonomy_risk_type_is_a_failure_not_a_silent_drop():
    """A model inventing "hurricane" would write a slug nothing renders. The
    row would look classified and be silently wrong."""
    result = parse(
        _response(
            is_risk=True,
            risk={"type": "hurricane", "severity": "high", "country": "United States"},
        )
    )
    assert result.risk.state is OutcomeState.FAILED
    assert result.risk.reason.startswith("off_taxonomy_risk_type")


def test_off_taxonomy_category_is_a_failure():
    result = parse(_response(category="aviation_news"))
    assert result.article.state is OutcomeState.FAILED
    assert result.article.reason.startswith("off_taxonomy_category")


def test_claiming_a_risk_without_describing_one_is_contradictory():
    result = parse(_response(is_risk=True, risk=None))
    assert result.risk.state is OutcomeState.FAILED
    assert result.risk.reason == "risk_flagged_without_payload"


# --- attribution ---------------------------------------------------------------


def test_the_subject_carrier_is_the_one_the_story_is_about():
    """`Buy Alaska Atmos Rewards Points With 100% Bonus` was attributed to
    British Airways because BA appeared in a comparison table. Attribution was
    "whichever tracked carrier is mentioned most", ordered on a column that was
    never written."""
    result = parse(
        _response(
            airlines=[
                {"code": "BA", "name": "British Airways", "role": "mentioned"},
                {"code": "AS", "name": "Alaska Airlines", "role": "subject"},
                {"code": "EK", "name": "Emirates", "role": "mentioned"},
            ]
        )
    )
    assert result.article.payload.subject_airline_code == "AS"


def test_no_subject_carrier_reports_none_rather_than_the_first_mention():
    result = parse(
        _response(airlines=[{"code": "EK", "name": "Emirates", "role": "mentioned"}])
    )
    assert result.article.payload.subject_airline_code is None


def test_a_campaign_nobody_runs_is_a_failure():
    result = parse(_response(campaign={"airline_code": None, "discount_pct": 50}))
    assert result.campaign.state is OutcomeState.FAILED
    assert result.campaign.reason == "campaign_without_airline"


# --- lenient where leniency is right ------------------------------------------


def test_a_fenced_response_is_still_parsed():
    """Models wrap JSON in code fences however firmly they are told not to.
    Failing the call for a formatting habit would waste the budget."""
    result = parse("```json\n" + _response() + "\n```")
    assert result.article.is_classified


def test_prose_around_the_json_is_tolerated():
    result = parse("Here is the analysis:\n" + _response() + "\nHope that helps!")
    assert result.article.is_classified


@pytest.mark.parametrize("value", ["null", "none", "N/A", "yok", "-", "  "])
def test_string_nulls_are_treated_as_missing(value):
    """Models write "null" and "yok" instead of emitting JSON null."""
    result = parse(_response(subcategory=value, title_tr=value))
    assert result.article.payload.subcategory is None
    assert result.article.payload.title_tr is None


def test_an_unparseable_date_is_missing_data_not_a_failed_call():
    """Completeness scoring already knows how to handle a missing date: it caps
    the confidence band. That is the right response, not discarding the row."""
    result = parse(
        _response(campaign={"airline_code": "PC", "sale_starts": "yakında", "markets": {}})
    )
    assert result.campaign.is_classified
    assert result.campaign.payload.sale_starts is None


def test_a_subcategory_under_the_wrong_parent_is_dropped_not_fatal():
    result = parse(_response(category="fleet", subcategory="promotion"))
    assert result.article.is_classified
    assert result.article.payload.category == "fleet"
    assert result.article.payload.subcategory is None


def test_a_revenue_decline_percentage_is_not_a_discount():
    """`IAG Cargo'nun ilk yarı yıl geliri kapasite kesintileri nedeniyle %9,4
    düşüş gösterdi` was published as a Qatar Airways campaign with a 9%
    discount. The prompt forbids it; the parser range-checks what comes back."""
    result = parse(_response(campaign={"airline_code": "QR", "discount_pct": 0, "markets": {}}))
    assert result.campaign.payload.discount_pct is None


@pytest.mark.parametrize("value", [-5, 0, 101, 250, True])
def test_implausible_discount_values_are_dropped(value):
    result = parse(_response(campaign={"airline_code": "PC", "discount_pct": value, "markets": {}}))
    assert result.campaign.payload.discount_pct is None


# --- the happy path ------------------------------------------------------------


def test_a_complete_campaign_parses_end_to_end():
    """`Pegasus'ta 6 hatta yüzde 50'ye varan indirim kampanyası başladı` -- the
    story this product exists to catch, previously filed as `general`."""
    result = parse(_response())

    assert result.article.is_classified
    assert result.article.payload.category == "revenue_management"
    assert result.article.payload.subcategory == "promotion"
    assert result.article.payload.title_tr.startswith("Pegasus")

    assert result.campaign.is_classified
    campaign = result.campaign.payload
    assert campaign.airline_code == "PC"
    assert campaign.discount_pct == 50
    assert campaign.sale_starts == date(2026, 8, 20)
    assert campaign.sale_ends == date(2026, 8, 31)
    assert campaign.markets["cities"] == ["Roma"]

    # Relevant and a campaign, but correctly not a risk.
    assert result.risk.state is OutcomeState.NOT_APPLICABLE


def test_confidence_is_carried_onto_every_outcome():
    """It feeds the confidence score, where a silent classifier is credited
    nothing rather than a middling default."""
    result = parse(_response(confidence=0.42))
    assert result.article.certainty == pytest.approx(0.42)
    assert result.risk.certainty == pytest.approx(0.42)
