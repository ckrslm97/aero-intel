import json
from datetime import date

from app.golden import GoldenRecord, campaign_records, news_records, risk_records
from app.services.golden_eval_service import (
    _extract_stated_country,
    _parse_campaign_label,
    evaluate_campaign_guards,
    evaluate_full_pipeline,
    evaluate_risk_country_normalisation,
)


def _record(idx=1, title="t", system_label="", verdict="ok", reason="", url=None) -> GoldenRecord:
    return GoldenRecord(
        idx=idx, title=title, system_label=system_label, verdict=verdict,
        reason=reason, source="", url=url,
    )


# --- fixture sanity --------------------------------------------------------


def test_golden_set_loads_the_expected_counts():
    assert len(risk_records()) == 24
    assert len(news_records()) == 100
    assert len(campaign_records()) == 131


def test_golden_records_are_well_formed():
    for record in risk_records() + news_records() + campaign_records():
        assert record.verdict in ("ok", "bad", "warn")
        assert record.title


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
