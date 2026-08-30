import json
from datetime import date

from app.golden import (
    SYNTHETIC_LEAK_SOURCE,
    SYNTHETIC_SOURCES,
    GoldenRecord,
    campaign_records,
    news_records,
    observed_campaign_records,
    risk_records,
    synthetic_campaign_records,
)
from app.services.golden_eval_service import (
    EVALUATION_TODAY,
    _extract_stated_country,
    _parse_campaign_label,
    evaluate_campaign_extraction,
    evaluate_campaign_guards,
    evaluate_full_pipeline,
    evaluate_risk_country_normalisation,
)
from app.taxonomy import (
    CAMPAIGN_BUSINESS_CLASSES,
    CAMPAIGN_STATUSES,
    CAMPAIGN_TYPES,
    ROUTE_SCOPES,
)


def _record(idx=1, title="t", system_label="", verdict="ok", reason="", url=None, **extra) -> GoldenRecord:
    return GoldenRecord(
        idx=idx, title=title, system_label=system_label, verdict=verdict,
        reason=reason, source="", url=url, **extra,
    )


# --- fixture sanity --------------------------------------------------------


def test_golden_set_loads_the_expected_counts():
    """The campaign count moved 131 -> 173 (PR8) -> 187: the 131 observed rows
    are untouched (see the split assertion below), 42 authored records cover
    the dimensions the 2025 snapshot has no examples of, and 14 more pin the
    award/cargo/service-announcement leaks that were still live after the
    backfill."""
    assert len(risk_records()) == 24
    assert len(news_records()) == 100
    assert len(campaign_records()) == 187


def test_the_observed_campaign_snapshot_is_still_exactly_the_original_131():
    """The regression that matters about the expansion: nothing was added to,
    removed from or reclassified inside the production snapshot the earlier
    phases were calibrated on."""
    observed = observed_campaign_records()
    assert len(observed) == 131
    assert [r.verdict for r in observed].count("ok") == 2
    assert [r.verdict for r in observed].count("bad") == 99
    assert [r.verdict for r in observed].count("warn") == 30


def test_observed_records_carry_none_of_the_authored_extensions():
    """The schema grew additively: an observed row loads with every new field
    at its default, so no existing check can accidentally read one."""
    for record in observed_campaign_records():
        assert record.is_synthetic is False
        assert record.text is None
        assert record.expected_business_class is None
        assert record.expected_campaign_type is None
        assert record.expected_route_scope is None
        assert record.expected_dates() == {
            "sale_starts": None, "sale_ends": None,
            "travel_starts": None, "travel_ends": None,
        }


def test_golden_records_are_well_formed():
    for record in risk_records() + news_records() + campaign_records():
        assert record.verdict in ("ok", "bad", "warn")
        assert record.title


def test_synthetic_campaign_records_are_labelled_and_in_taxonomy():
    records = synthetic_campaign_records()
    assert len(records) == 56
    for record in records:
        # Marked as authored on the row itself, and never live-fetchable --
        # `evaluate_full_pipeline` must skip them rather than hit the network.
        assert record.source in SYNTHETIC_SOURCES
        assert record.url is None
        assert record.text
        assert record.reason
        # Every expectation is a taxonomy slug, so a rename in taxonomy.py
        # fails here instead of silently scoring zero forever.
        if record.expected_campaign_type:
            assert record.expected_campaign_type in CAMPAIGN_TYPES
        if record.expected_business_class:
            assert record.expected_business_class in CAMPAIGN_BUSINESS_CLASSES
        if record.expected_route_scope:
            assert record.expected_route_scope in ROUTE_SCOPES
        if record.expected_status:
            assert record.expected_status in CAMPAIGN_STATUSES


def test_synthetic_set_covers_the_dimensions_it_was_written_for():
    records = synthetic_campaign_records()
    types = {r.expected_campaign_type for r in records}
    classes = {r.expected_business_class for r in records}
    assert {
        "FLASH_SALE", "EARLY_BOOKING", "SEASONAL_PROMOTION", "PERCENT_DISCOUNT",
        "FIXED_FARE", "NEW_ROUTE_PROMOTION", "BLACK_FRIDAY", "ROUND_TRIP_PROMOTION",
    } <= types
    assert {
        "ACTIVE_CAMPAIGN", "EXPIRED_CAMPAIGN", "EVERGREEN_OFFER",
        "PRODUCT_PROMOTION", "LOYALTY_PROMOTION", "NEWS_ONLY",
    } <= classes
    assert {r.expected_route_scope for r in records} >= {"OND", "CITY_PAIR", "COUNTRY", "REGION", "NETWORK_WIDE"}
    # The near-duplicate pair: two framings of one campaign.
    groups = [r.dedup_group for r in records if r.dedup_group]
    assert len(groups) == 2 and len(set(groups)) == 1


# --- campaign label parsing -------------------------------------------------


def test_parse_campaign_label_reads_carrier_discount_and_dates():
    campaign = _parse_campaign_label("PC (Pegasus Airlines) · 50% · 2026-08-25→2026-08-27")
    assert campaign.airline_code == "PC"
    assert campaign.discount_pct == 50
    assert campaign.sale_starts == date(2026, 8, 25)
    assert campaign.sale_ends == date(2026, 8, 27)


def test_parse_campaign_label_handles_missing_discount_and_dates():
    campaign = _parse_campaign_label("QR (Qatar Airways) · — · tarih yok")
    assert campaign.airline_code == "QR"
    assert campaign.discount_pct is None
    assert campaign.sale_starts is None
    assert campaign.sale_ends is None


def test_parse_campaign_label_returns_none_for_an_unrecognised_shape():
    assert _parse_campaign_label("not a label at all") is None


# --- campaign guard evaluation ----------------------------------------------


def test_guards_catch_an_implausibly_wide_window():
    records = [
        _record(system_label="PC (Pegasus Airlines) · — · 2024-06-25→2026-12-31", verdict="bad"),
    ]
    report = evaluate_campaign_guards(records, today=date(2026, 8, 25))
    assert report.bad_records_parsed == 1
    assert report.bad_records_caught == 1
    assert report.results[0].guard_reason == "implausible_sale_window"


def test_guards_catch_a_stale_closed_window():
    records = [
        _record(system_label="PC (Pegasus Airlines) · 30% · 2026-01-01→2026-01-10", verdict="bad"),
    ]
    report = evaluate_campaign_guards(records, today=date(2026, 8, 25))
    assert report.bad_records_caught == 1
    assert report.results[0].guard_reason == "sale_window_closed"


def test_guards_catch_an_expired_title():
    records = [
        _record(title="[Expired] Save 30%", system_label="PC (Pegasus Airlines) · 30% · tarih yok", verdict="bad"),
    ]
    report = evaluate_campaign_guards(records, today=date(2026, 8, 25))
    assert report.bad_records_caught == 1
    assert report.results[0].guard_reason == "expired_title"


def test_guards_do_not_catch_a_wrong_carrier_attribution():
    """The guards never see who the model picked -- attribution errors are
    the model's job upstream, not something a window/title check can find.
    A record with a plausible window and no expiry marker passes the guards
    even though the golden judge marked it bad for an unrelated reason
    (wrong carrier credited) -- this is the documented limit, not a bug."""
    records = [
        _record(
            system_label="AF (Air France) · 20% · 2026-08-20→2026-08-30",
            verdict="bad",
            reason="Kampanyayı asıl yürüten farklı bir havayolu, AF sadece bahsi geçiyor",
        ),
    ]
    report = evaluate_campaign_guards(records, today=date(2026, 8, 25))
    assert report.bad_records_caught == 0


def test_guards_never_reject_a_genuinely_valid_campaign():
    records = [
        _record(
            system_label="PC (Pegasus Airlines) · 50% · 2026-08-25→2026-08-27", verdict="ok"
        ),
    ]
    report = evaluate_campaign_guards(records, today=date(2026, 8, 25))
    assert report.ok_records_wrongly_rejected == 0


def test_guards_mark_an_unparseable_label_rather_than_crash():
    records = [_record(system_label="not a recognisable shape", verdict="bad")]
    report = evaluate_campaign_guards(records, today=date(2026, 8, 25))
    assert report.results[0].unparseable is True
    assert report.bad_records_parsed == 0


def test_the_real_golden_set_two_ok_campaigns_both_pass_the_guards():
    """Locks in the one thing that must never regress: the two rows the
    owner's own cross-check confirmed as real, correctly-attributed
    campaigns must never be rejected by these guards."""
    report = evaluate_campaign_guards(today=date(2026, 8, 25))
    assert report.ok_records_wrongly_rejected == 0


# --- campaign extraction KPIs (PR8) -----------------------------------------


_GOOD = "PC (Pegasus Airlines) · 30% · 2026-08-24→2026-08-31"


def test_extraction_metrics_count_a_leaking_bad_record_as_a_false_positive():
    records = [
        _record(idx=1, title="Gerçek kampanya", system_label=_GOOD, verdict="ok"),
        # Plausible window, no expiry marker, nothing in the rulepacks: this is
        # the attribution-error shape the guards are documented as blind to.
        _record(idx=2, title="Yanlış havayolu", system_label=_GOOD, verdict="bad"),
    ]
    report = evaluate_campaign_extraction(records, today=date(2026, 8, 25))
    assert (report.true_positives, report.false_positives) == (1, 1)
    assert report.false_negatives == 0 and report.true_negatives == 0
    assert report.precision == 0.5
    assert report.recall == 1.0
    assert report.false_positive_rate == 1.0


def test_extraction_metrics_count_a_rejected_ok_record_as_a_false_negative():
    records = [
        _record(
            idx=1,
            title="[Expired] gerçek kampanya",
            system_label=_GOOD,
            verdict="ok",
        ),
        _record(idx=2, title="Bagaj indirimi", system_label=_GOOD, verdict="bad"),
    ]
    report = evaluate_campaign_extraction(records, today=date(2026, 8, 25))
    assert report.false_negatives == 1
    assert report.true_negatives == 1
    assert report.recall == 0.0
    assert report.false_positive_rate == 0.0


def test_extraction_metrics_exclude_warn_and_unparseable_records():
    records = [
        _record(idx=1, system_label=_GOOD, verdict="ok"),
        _record(idx=2, system_label=_GOOD, verdict="warn"),
        _record(idx=3, system_label="not a label", verdict="bad"),
    ]
    report = evaluate_campaign_extraction(records, today=date(2026, 8, 25))
    assert report.graded == 1
    assert report.warn_excluded == 1
    assert report.unparseable == 1


def test_extraction_metrics_are_none_rather_than_zero_with_nothing_to_divide_by():
    """An empty denominator is "not measured", never 0.0 -- a fabricated zero
    would read as a perfect false-positive rate."""
    report = evaluate_campaign_extraction([], today=date(2026, 8, 25))
    assert report.precision is None
    assert report.recall is None
    assert report.f1 is None
    assert report.false_positive_rate is None
    assert report.route_scope_accuracy is None


def test_extraction_reads_dates_from_the_body_when_the_record_has_one():
    record = _record(
        idx=1,
        title="Kampanya",
        system_label="PC (Pegasus Airlines) · — · tarih yok",
        verdict="ok",
        text=(
            "Satış dönemi 1 Eylül 2026 ile 10 Eylül 2026 tarihleri arasındadır. "
            "Uçuş tarihleri 20 Eylül 2026 ile 30 Ekim 2026 arasındadır."
        ),
        expected_sale_starts="2026-09-01",
        expected_sale_ends="2026-09-10",
        expected_travel_starts="2026-09-20",
        expected_travel_ends="2026-10-30",
        expected_status="UPCOMING",
    )
    report = evaluate_campaign_extraction([record], today=date(2026, 8, 25))
    assert report.date_fields_checked == 4
    assert report.date_fields_correct == 4
    assert report.date_corroboration == 1.0
    assert report.status_correct == 1


def test_extraction_grades_route_scope_through_the_real_resolver():
    records = [
        _record(
            idx=1, system_label=_GOOD, verdict="ok",
            expected_origin="Türkiye", expected_destination="Avrupa",
            expected_route_scope="REGION",
        ),
        _record(
            idx=2, system_label=_GOOD, verdict="ok",
            expected_origin="IST", expected_destination="LHR",
            expected_route_scope="CITY_PAIR",  # deliberately wrong: two airports are OND
        ),
    ]
    report = evaluate_campaign_extraction(records, today=date(2026, 8, 25))
    assert report.route_scope_checked == 2
    assert report.route_scope_correct == 1


def test_expired_records_are_graded_against_the_status_engine_not_the_class():
    """agents/campaign_airline.py's date guards deliberately return
    business_class=None -- EXPIRED is services/campaign_status.py's answer.
    The breakdown has to grade them there or it fails them for being correct."""
    record = _record(
        idx=1,
        title="Bahar kampanyası",
        system_label="PC (Pegasus Airlines) · 25% · 2026-04-01→2026-04-20",
        verdict="bad",
        expected_business_class="EXPIRED_CAMPAIGN",
    )
    report = evaluate_campaign_extraction([record], today=date(2026, 8, 25))
    row = report.by_business_class["EXPIRED_CAMPAIGN"]
    assert row.published == 0
    assert row.class_agreed == 1
    assert report.results[0].detected_business_class is None
    assert report.results[0].computed_status == "EXPIRED"


def test_the_real_golden_set_produces_a_computable_false_positive_rate():
    report = evaluate_campaign_extraction()
    assert report.today == EVALUATION_TODAY
    assert report.graded == 156
    assert report.false_positive_rate is not None
    assert 0.0 <= report.false_positive_rate <= 1.0
    assert report.precision is not None and report.recall is not None
    # Every non-fare class the rebuild exists to keep out has its own row.
    assert {
        "ACTIVE_CAMPAIGN", "EVERGREEN_OFFER", "EXPIRED_CAMPAIGN",
        "LOYALTY_PROMOTION", "NEWS_ONLY", "PRODUCT_PROMOTION",
    } <= set(report.by_business_class)


def test_the_real_golden_set_never_rejects_a_true_campaign():
    """Recall is the half of the gate that is not allowed to be bought: every
    record the judge called a genuine campaign must still reach the timeline."""
    report = evaluate_campaign_extraction()
    assert report.false_negatives == 0
    assert report.recall == 1.0


def test_no_authored_non_campaign_leaks_through():
    """The rulepacks' own regression lock. Every authored `bad` record --
    evergreen, product, loyalty, news-only, expired -- must be rejected; the
    observed snapshot's residual false positives are tracked separately and
    are what the gate is currently failing on."""
    report = evaluate_campaign_extraction(synthetic_campaign_records())
    assert report.false_positives == 0
    assert report.false_negatives == 0


def _leak_records():
    return [r for r in campaign_records() if r.source == SYNTHETIC_LEAK_SOURCE]


def test_the_leak_batch_pins_every_pattern_that_was_still_live():
    """Each of these is a paraphrase of a row the site was still publishing
    after the backfill: award sales and award-booking guides, a cargo
    division's half-year revenue, an onboard-service launch. Rejected is not
    enough -- each must be rejected as the *right kind* of wrong, or the
    business_class column on the analyst view is decoration."""
    records = _leak_records()
    assert len(records) == 14

    report = evaluate_campaign_extraction(records)
    assert report.false_positives == 0
    assert report.false_negatives == 0
    for row in report.by_business_class.values():
        assert row.class_agreed == row.total


def test_the_leak_batch_still_publishes_a_campaign_that_calls_itself_award_winning():
    """The over-blocking half. "Ödüllü havayolu" is Turkish for
    "award-winning airline" -- marketing fluff on a genuinely dated campaign,
    and one letter away from the "ödül" (award/redemption) vocabulary the
    LOYALTY rulepack now keys on."""
    published = [
        r for r in evaluate_campaign_extraction(_leak_records()).results if r.would_publish
    ]
    assert len(published) == 2
    assert all("dül" in r.title or "ward-Winning" in r.title for r in published)


def test_the_campaign_gate_passes_so_the_article_path_flag_may_be_on():
    """The gate and the flag are one decision, asserted together so they cannot
    drift: `.github/workflows/jobs-news.yml` turns CAMPAIGN_V2_ENABLED on for
    the article path, and it is only allowed to be on while this holds."""
    from pathlib import Path

    from app.cli import CAMPAIGN_FP_RATE_GATE

    report = evaluate_campaign_extraction()
    assert report.false_positive_rate < CAMPAIGN_FP_RATE_GATE
    assert report.recall == 1.0

    workflow = (
        Path(__file__).resolve().parents[3] / ".github" / "workflows" / "jobs-news.yml"
    ).read_text(encoding="utf-8")
    assert 'CAMPAIGN_V2_ENABLED: "true"' in workflow


def test_the_real_golden_set_keeps_every_expected_campaign_type_in_the_taxonomy():
    """Taxonomy-drift lock, not a model-accuracy number -- see the evaluator's
    docstring. Goes red when a slug the golden set expects is renamed."""
    report = evaluate_campaign_extraction()
    assert report.campaign_type_checked > 0
    assert report.campaign_type_valid == report.campaign_type_checked


# --- the maintenance dispatch entry ------------------------------------------
#
# maintenance.yml has two lists that must agree: the dropdown a human picks
# from, and the shell `case` that decides what actually runs. A task in the
# dropdown but not the case block dispatches, prints "Unknown task" and exits
# 1 -- a failure that only shows up when somebody tries to use it. Asserted as
# text rather than parsed YAML so the check needs no new dependency.


def test_evaluate_campaigns_is_dispatchable_from_the_maintenance_workflow():
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[3] / ".github" / "workflows" / "maintenance.yml"
    ).read_text(encoding="utf-8")

    assert "          - evaluate-campaigns\n" in workflow
    assert "            evaluate-campaigns)\n" in workflow
    assert "python -m app.cli evaluate-campaigns ;;" in workflow


def test_evaluate_campaigns_is_a_real_cli_command():
    import app.cli as cli

    assert hasattr(cli, "_evaluate_campaigns")
    source = (
        __import__("pathlib").Path(cli.__file__).read_text(encoding="utf-8")
    )
    assert '"evaluate-campaigns",' in source


# --- risk country normalisation ---------------------------------------------


def test_extract_stated_country_reads_the_second_field():
    assert _extract_stated_country("attack (high) · Ukraine") == "Ukraine"


def test_extract_stated_country_ignores_a_trailing_city():
    assert _extract_stated_country("war (high) · India · Mumbai") == "India"


def test_extract_stated_country_returns_none_when_unspecified():
    assert _extract_stated_country("war (medium) · Belirtilmemiş") is None


def test_country_normalisation_resolves_turkish_and_english_names():
    records = [
        _record(idx=1, system_label="attack (high) · Ukraine"),
        _record(idx=2, system_label="volcano (high) · Turkey"),
    ]
    report = evaluate_risk_country_normalisation(records)
    assert report.checked == 2
    assert report.resolved == 2


def test_country_normalisation_skips_records_with_no_stated_country():
    records = [_record(system_label="war (medium) · Belirtilmemiş")]
    report = evaluate_risk_country_normalisation(records)
    assert report.checked == 0


def test_the_real_golden_set_resolves_every_stated_country():
    """Real regression lock: every country name actually named in the golden
    risk set's own labels must resolve through the alias table -- this is
    the exact Faz 6 bug (Turkish country names silently failing an
    English-only lookup)."""
    report = evaluate_risk_country_normalisation()
    assert report.checked > 0
    assert report.resolved == report.checked


# --- full pipeline evaluator -------------------------------------------------


async def test_evaluate_full_pipeline_returns_none_without_an_llm(monkeypatch):
    import app.llm.factory as factory

    monkeypatch.setattr(factory, "get_raw_generator", lambda: None)
    assert await evaluate_full_pipeline([_record()], surface="news") is None


async def test_evaluate_full_pipeline_skips_records_with_no_url(monkeypatch):
    async def fake_generate(prompt):
        return "irrelevant"

    import app.llm.factory as factory

    monkeypatch.setattr(factory, "get_raw_generator", lambda: fake_generate)

    report = await evaluate_full_pipeline([_record(url=None)], surface="news")
    assert report.skipped_no_url == 1
    assert report.results == []


async def test_evaluate_full_pipeline_grades_a_classified_result(monkeypatch):
    import app.llm.factory as factory
    from app.services import golden_eval_service

    async def fake_generate(prompt):
        return json.dumps(
            {
                "relevant": True,
                "category": "network",
                "subcategory": "new_route",
                "title_tr": "Başlık",
                "summary_tr": "Özet",
                "confidence": 0.8,
                "airlines": [],
                "airports": [],
                "countries": [],
                "is_risk": False,
                "is_campaign": False,
            }
        )

    monkeypatch.setattr(factory, "get_raw_generator", lambda: fake_generate)

    async def fake_fetch(url):
        return "<html>body</html>"

    monkeypatch.setattr(golden_eval_service, "_fetch_content", fake_fetch)

    report = await evaluate_full_pipeline(
        [_record(url="https://example.com/a", verdict="ok")], surface="news"
    )
    assert len(report.results) == 1
    assert report.results[0].golden_verdict == "ok"
