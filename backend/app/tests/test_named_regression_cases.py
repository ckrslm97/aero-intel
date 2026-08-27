"""Faz 15's "named regression cases" index.

This project's hardest-won regression protection is not generic
parametrized coverage -- it is specific, real production incidents (a
misclassified film review, a fighter jet named after a storm, a Turkish
country name that failed an English-only lookup) that already broke the
pipeline once in production and are now pinned down as tests, scattered
across the files that own the code they guard. Scattering is correct --
each test lives next to the machinery it exercises -- but it also means
nothing forces someone deleting or renaming one of these to notice they
just removed a specific incident's protection, not just "a test".

This file is that noticing mechanism: a roll call, not a re-implementation.
It imports the real test functions/fixtures by name and asserts they still
exist, so a rename or deletion fails loudly here even if the assertion
logic itself was moved instead of dropped. It does not re-run their
bodies -- that would just be two copies of the same regression to keep in
sync for no added protection.

The golden-set side of "mandatory check" needs no separate index: it
already runs as ordinary regression-locking pytest tests --
test_the_real_golden_set_two_ok_campaigns_both_pass_the_guards and
test_the_real_golden_set_resolves_every_stated_country in
test_golden_eval_service.py -- against the full real golden set, in the
same `pytest` step CI runs on every PR.
"""
import inspect

from app.tests import test_classify, test_news_event_model, test_pipeline_v2_runner, test_risk_radar


def _is_test_function(module, name: str) -> None:
    fn = getattr(module, name, None)
    assert fn is not None, (
        f"{module.__name__}.{name} is gone -- a named regression case was "
        "deleted or renamed without updating this roll call."
    )
    assert inspect.isfunction(fn), f"{module.__name__}.{name} is no longer a test function"


def test_the_pan_am_103_film_review_veto_is_still_guarded():
    # "Film Notlari: The Bombing of Pan Am 103" -- a Turkish review of a
    # documentary about the Lockerbie bombing -- was once classified as a
    # live UK terror attack because a null risk field fell through to a
    # keyword heuristic that scored "bombing" at severity 3. Three layers
    # guard against it recurring, each in the file that owns that layer.
    _is_test_function(test_classify, "test_an_explicit_no_is_recorded_not_treated_as_a_failure")
    _is_test_function(
        test_news_event_model, "test_the_veto_is_durable_and_distinguishable_from_never_looked"
    )
    _is_test_function(test_pipeline_v2_runner, "test_the_veto_is_recorded_and_no_event_is_created")


def test_the_weather_named_aircraft_false_positives_are_still_guarded():
    # RAF Typhoons, a Hawker Hurricane warbird, a Tornado fighter jet, a
    # NOAA "hurricane hunter" research aircraft -- 13 real false positives
    # pulled from a 30-day, 7,670-article production run, all named after
    # weather but none of them weather. Plus the guard's own inverse case:
    # a real typhoon or hurricane must still classify as a storm.
    _is_test_function(test_risk_radar, "test_production_false_positives_stay_unclassified")
    _is_test_function(test_risk_radar, "test_weather_named_aircraft_guard_does_not_suppress_real_weather")
    assert len(test_risk_radar.PRODUCTION_FALSE_POSITIVES) >= 13, (
        "the production-false-positive fixture list shrank -- a named "
        "incident may have been dropped instead of fixed"
    )
