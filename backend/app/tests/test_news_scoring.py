"""The scoring engine: every sub-score at its boundaries, and the renormalisation.

These are table-driven and database-free on purpose. The weights and the
thresholds in app/services/news_scoring.py are editorial decisions written down
as constants; a test beside them is what makes changing the system's judgement
a reviewable diff rather than an archaeology exercise (the same argument
app/pipeline/confidence.py makes for its own table-driven test).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import news_scoring as ns

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


# --- the invariant everything else rests on ---------------------------------


def test_weights_sum_to_one_and_cover_both_production_paths():
    assert sum(ns.WEIGHTS.values()) == pytest.approx(1.0)
    # Every declared component belongs to exactly one path, or `combine`'s
    # renormalisation would be splitting a weight that has no owner.
    assert set(ns.LLM_COMPONENTS) | set(ns.DETERMINISTIC_COMPONENTS) == set(ns.WEIGHTS)
    assert not set(ns.LLM_COMPONENTS) & set(ns.DETERMINISTIC_COMPONENTS)


def test_source_reliability_is_the_smallest_weight():
    """The whole point of the module, stated as an assertion.

    The old importance_score was ~100% source identity. If a future tuning pass
    ever makes source_reliability the dominant term again, it will have
    rebuilt the bug this file exists to remove, and this fails.
    """
    assert ns.WEIGHT_SOURCE_RELIABILITY == min(ns.WEIGHTS.values())
    assert ns.WEIGHT_SOURCE_RELIABILITY < ns.WEIGHT_RM_IMPACT


# --- freshness ---------------------------------------------------------------


@pytest.mark.parametrize(
    "age_days,expected",
    [
        (0, 1.0),
        (2, 0.5),  # exactly one half-life
        (4, 0.25),
        (8, 0.0625),
    ],
)
def test_freshness_halves_every_half_life(age_days, expected):
    assert ns.freshness(NOW - timedelta(days=age_days), now=NOW) == pytest.approx(
        expected, abs=1e-4
    )


def test_freshness_of_an_undated_article_is_neutral_not_extreme():
    """Feeds that omit dates are a property of the feed, not of the story.

    1.0 would let every undated aggregator item lead the paper; 0.0 would bury
    a genuine wire story for its publisher's RSS habits.
    """
    assert ns.freshness(None, now=NOW) == 0.5


def test_a_future_timestamp_does_not_score_above_one():
    """A clock-skewed feed must not be able to outrank real news."""
    assert ns.freshness(NOW + timedelta(days=3), now=NOW) == 1.0


def test_freshness_accepts_a_naive_timestamp_as_utc():
    """Some feeds store naive datetimes; subtracting one would raise."""
    assert ns.freshness(NOW.replace(tzinfo=None), now=NOW) == 1.0


# --- source reliability ------------------------------------------------------


def test_source_reliability_follows_the_declared_ladder():
    ordered = [
        ns.source_reliability(tier, 0.6)
        for tier in ("official", "regulator", "agency", "trade", "aggregator")
    ]
    assert ordered == sorted(ordered, reverse=True)


def test_an_undeclared_tier_falls_back_to_its_trust_bucket():
    """Never silently "official", and never silently bottom-of-the-ladder.

    A source seeded before the tier column existed resolves through
    taxonomy.effective_source_tier, exactly as every other consumer resolves it.
    """
    # 0.90 buckets to "regulator"; the result must beat an explicit aggregator.
    assert ns.source_reliability(None, 0.90) > ns.source_reliability("aggregator", 0.90)
    assert ns.source_reliability(None, 0.90) == ns.source_reliability("regulator", 0.90)


def test_trust_weight_separates_two_outlets_on_the_same_rung():
    """A pure ladder would flatten a distinction the source list already makes."""
    assert ns.source_reliability("trade", 0.70) > ns.source_reliability("trade", 0.55)


def test_source_reliability_survives_a_null_trust_weight():
    assert 0.0 <= ns.source_reliability("trade", None) <= 1.0


# --- competitive impact ------------------------------------------------------


def test_a_rival_in_the_headline_outranks_one_in_the_body():
    title_hit = ns.competitive_impact("Emirates cuts fares to Bangkok", {"EK"})
    body_only = ns.competitive_impact("Bangkok sees record arrivals", {"EK"})
    assert title_hit == ns.COMPETITIVE_TITLE
    assert body_only == ns.COMPETITIVE_BODY
    assert title_hit > body_only


def test_several_watched_carriers_in_the_body_beat_one():
    """A comparison or fare-war story, even when no carrier made the headline."""
    assert (
        ns.competitive_impact("Gulf capacity report", {"EK", "QR"}) == ns.COMPETITIVE_MULTI_BODY
    )


def test_the_home_carrier_counts_as_competitive_signal():
    """TK is deliberately absent from RIVAL_CODES -- it is what the desk works
    FOR -- but a story about the home carrier is at least as urgent as one
    about a rival, so it must not score zero."""
    assert "TK" not in ns.RIVAL_CODES
    assert ns.competitive_impact("Turkish Airlines adds Lima route", {"TK"}) == (
        ns.COMPETITIVE_TITLE
    )


def test_an_unwatched_carrier_is_not_competitive_signal():
    """"No rival is involved" is a statement about the story, so zero is right
    here in a way it is not for geography."""
    assert ns.competitive_impact("Delta reports Q3 earnings", {"DL"}) == 0.0
    assert ns.competitive_impact("Airport opens new pier", set()) == 0.0


def test_competitive_impact_ignores_diacritics_and_case():
    """The gazetteer's own folding, so "TÜRK HAVA YOLLARI" is not a miss."""
    assert ns.competitive_impact("TÜRK HAVA YOLLARI kapasite artırıyor", {"TK"}) == (
        ns.COMPETITIVE_TITLE
    )


# --- geographic relevance ----------------------------------------------------


def test_hub_tiers_are_derived_from_the_hub_table_not_hand_listed():
    """Adding a hub to app/hubs.py must not leave this module behind."""
    assert ns.HOME_HUB_CODES == {"IST", "SAW"}
    assert "DXB" in ns.RIVAL_HUB_CODES and "DOH" in ns.RIVAL_HUB_CODES
    assert "JFK" in ns.OTHER_HUB_CODES
    # The three sets partition the table -- no hub is in two, none is missing.
    assert (
        ns.HOME_HUB_CODES | ns.RIVAL_HUB_CODES | ns.OTHER_HUB_CODES
    ) == {hub.code for hub in __import__("app.hubs", fromlist=["HUBS"]).HUBS}


@pytest.mark.parametrize(
    "region,airports,expected",
    [
        (None, {"IST"}, ns.GEO_HOME_HUB),
        (None, {"SAW"}, ns.GEO_HOME_HUB),
        (None, {"DXB"}, ns.GEO_RIVAL_HUB),
        (None, {"JFK"}, ns.GEO_OTHER_HUB),
        ("middle-east", set(), ns.GEO_HOME_REGION),
        ("north-america", set(), ns.GEO_KNOWN_REGION),
        (None, set(), ns.GEO_UNPLACED),
    ],
)
def test_geographic_relevance_boundaries(region, airports, expected):
    assert ns.geographic_relevance(region, airports) == expected


def test_the_strongest_geography_wins_rather_than_averaging():
    """An article naming both IST and JFK is an IST story with a destination.

    Averaging would score it BELOW an article that named IST alone, which is
    backwards.
    """
    assert ns.geographic_relevance(None, {"IST", "JFK"}) == ns.GEO_HOME_HUB


def test_an_unplaced_story_is_not_scored_zero():
    """Industry-wide news (an IATA forecast, an NDC mandate) names no airport.

    Zero here would let a parochial story about a hub nobody flies to outrank
    a global fare-structure change.
    """
    assert ns.geographic_relevance(None, set()) > 0.0


def test_geographic_relevance_is_case_insensitive_on_codes():
    assert ns.geographic_relevance(None, {"ist"}) == ns.GEO_HOME_HUB


# --- relevance normalisation -------------------------------------------------


def test_relevance_is_monotone_and_never_saturates():
    """The reason the curve is exponential rather than `min(1, raw/N)`.

    A hard clip ties every article above the cut-off -- and those are exactly
    the articles the shortlist is chosen from, so the ordering would be
    destroyed precisely where it is load-bearing.
    """
    weak = ns.relevance("Airport cat adopted by ground crew", "A nice story.")
    strong = ns.relevance(
        "Emirates cuts fares in price war as capacity and yield collapse",
        "fare pricing yield revenue capacity demand load factor",
    )
    # Raw scores 3 and 88 on the real scorer -- weak is well inside the range,
    # strong is past the measured p99 (61) and still short of 1.0, so two
    # genuinely strong articles remain orderable against each other.
    assert 0.0 <= weak < strong < 1.0


def test_relevance_of_empty_text_is_zero():
    assert ns.relevance("", "") == 0.0


def test_relevance_half_score_lands_where_documented():
    """The calibration constant, pinned to the value its docstring claims."""
    assert ns.RELEVANCE_HALF_SCORE == 12.0


# --- combine: the renormalisation -------------------------------------------


def test_a_deterministic_only_score_is_a_real_number_not_a_penalty():
    """The single most consequential decision in the module.

    Only the shortlist is scored by the model, so ~95% of articles carry no LLM
    components -- by construction, not by failure. If absent components were
    scored as 0.0, a perfect deterministic article would cap at the
    deterministic weight share (0.56) and could never be compared with an
    LLM-scored one -- including by the selection pass, which runs before any
    LLM call exists.
    """
    perfect = {name: 1.0 for name in ns.DETERMINISTIC_COMPONENTS}
    assert ns.combine(perfect).intelligence_score == pytest.approx(1.0)
    assert ns.DETERMINISTIC_WEIGHT_SHARE < 1.0


def test_llm_components_shift_the_score_in_both_directions():
    """Adding the model's read must be able to demote as well as promote."""
    deterministic = {name: 0.5 for name in ns.DETERMINISTIC_COMPONENTS}
    base = ns.combine(deterministic).intelligence_score
    promoted = ns.combine({**deterministic, **{n: 1.0 for n in ns.LLM_COMPONENTS}})
    demoted = ns.combine({**deterministic, **{n: 0.0 for n in ns.LLM_COMPONENTS}})
    assert demoted.intelligence_score < base < promoted.intelligence_score


def test_zero_and_missing_are_different_answers():
    """0.0 means the model found no impact; absent means nobody asked.

    Collapsing them is the failure app/pipeline/outcomes.py exists to prevent,
    applied to scoring.
    """
    deterministic = {name: 0.8 for name in ns.DETERMINISTIC_COMPONENTS}
    scored_zero = ns.combine({**deterministic, "rm_impact": 0.0})
    never_asked = ns.combine(deterministic)
    assert scored_zero.intelligence_score < never_asked.intelligence_score


def test_applied_weights_are_stored_and_sum_to_one():
    """`score_detail` has to be enough to reconstruct the number by itself."""
    result = ns.combine({name: 0.5 for name in ns.DETERMINISTIC_COMPONENTS})
    assert sum(result.applied_weights.values()) == pytest.approx(1.0)
    detail = result.as_detail()
    assert set(detail["weights"]) == set(detail["components"])
    assert detail["llm_scored"] is False
    recomputed = sum(
        detail["components"][k] * detail["weights"][k] for k in detail["components"]
    )
    assert recomputed == pytest.approx(detail["score"], abs=1e-3)


def test_combine_clamps_out_of_range_components():
    assert ns.combine({"freshness": 5.0}).intelligence_score == pytest.approx(1.0)
    assert ns.combine({"freshness": -3.0}).intelligence_score == pytest.approx(0.0)


def test_combine_ignores_unknown_components():
    """A score_detail written by a future version must stay readable."""
    result = ns.combine({"freshness": 1.0, "some_future_axis": 1.0})
    assert set(result.components) == {"freshness"}


def test_combine_of_nothing_is_zero_rather_than_a_crash():
    assert ns.combine({}).intelligence_score == 0.0
    assert ns.combine({"freshness": None}).intelligence_score == 0.0


def test_as_detail_reports_whether_the_model_was_involved():
    scored = ns.combine({"freshness": 1.0, "rm_impact": 1.0})
    assert scored.as_detail()["llm_scored"] is True


# --- score(): the two paths together ----------------------------------------


def _signals(**overrides) -> ns.ArticleSignals:
    base = dict(
        title="Emirates cuts fares to Bangkok",
        content="fare pricing yield capacity demand",
        published_at=NOW,
        source_tier="agency",
        trust_weight=0.75,
        region="middle-east",
        airline_codes=frozenset({"EK"}),
        airport_codes=frozenset({"IST"}),
    )
    base.update(overrides)
    return ns.ArticleSignals(**base)


def test_score_without_impact_uses_only_the_free_components():
    result = ns.score(_signals(), now=NOW)
    assert set(result.components) == set(ns.DETERMINISTIC_COMPONENTS)
    assert not result.has_llm_components
    assert 0.0 < result.intelligence_score <= 1.0


def test_score_with_impact_adds_exactly_three_components():
    result = ns.score(
        _signals(),
        ns.ImpactScores(rm_impact=0.9, demand_impact=0.4, capacity_impact=0.1),
        now=NOW,
    )
    assert set(result.components) == set(ns.WEIGHTS)
    assert result.has_llm_components


def test_a_partial_impact_object_contributes_only_what_it_has():
    """ImpactScores defaults to all-None; a half-filled one must not imply zeros."""
    partial = ns.ImpactScores(rm_impact=0.9)
    assert partial.as_components() == {"rm_impact": 0.9}
    assert ns.ImpactScores().is_empty


def test_the_same_story_from_a_weaker_outlet_barely_moves():
    """The regression guard for the original bug.

    Source identity used to be the ENTIRE score. Here it is one input of eight
    at the lowest weight, so swapping the best possible publisher for the worst
    must move the score by far less than the gap between a relevant story and
    an irrelevant one.
    """
    best = ns.score(_signals(source_tier="official", trust_weight=1.0), now=NOW)
    worst = ns.score(_signals(source_tier="aggregator", trust_weight=0.3), now=NOW)
    publisher_gap = best.intelligence_score - worst.intelligence_score

    irrelevant = ns.score(
        _signals(
            title="Airport cat adopted by ground crew",
            content="A nice story about a cat.",
            airline_codes=frozenset(),
            airport_codes=frozenset(),
            region=None,
            source_tier="official",
            trust_weight=1.0,
        ),
        now=NOW,
    )
    story_gap = best.intelligence_score - irrelevant.intelligence_score
    assert story_gap > publisher_gap


def test_two_articles_from_one_source_can_differ():
    """The precise thing importance_score could not do.

    Every production source produced exactly ONE distinct importance_score --
    eighteen sources, eight distinct values, 484 articles. Same source, same
    day, different story: these must not tie.
    """
    fare_war = ns.score(_signals(), now=NOW)
    cat = ns.score(
        _signals(
            title="Airport cat adopted by ground crew",
            content="A nice story.",
            airline_codes=frozenset(),
            airport_codes=frozenset(),
        ),
        now=NOW,
    )
    assert fare_war.intelligence_score != cat.intelligence_score
