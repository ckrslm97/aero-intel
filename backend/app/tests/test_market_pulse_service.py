import json
from datetime import date, datetime, timezone

from app.llm import factory
from app.repositories.curated_repository import CuratedRepository
from app.repositories.kpi_repository import KpiRepository
from app.repositories.market_pulse_repository import MarketPulseRepository
from app.services import market_pulse_service


async def _seed_one_fx_pair(db_session, *, source_url="https://finance.yahoo.com/quote/TRY=X"):
    repo = KpiRepository(db_session)
    repo.record(
        "fx_usd_try", 48.11, "TRY", "Yahoo Finance (TRY=X)", False, datetime.now(timezone.utc), source_url
    )
    await db_session.commit()


async def test_generate_market_pulse_returns_none_when_no_llm_configured(db_session, monkeypatch):
    monkeypatch.setattr(factory, "get_raw_generator", lambda: None)

    await _seed_one_fx_pair(db_session)

    pulse = await market_pulse_service.generate_market_pulse(db_session)
    assert pulse is None
    assert await MarketPulseRepository(db_session).latest() is None


async def test_generate_market_pulse_returns_none_with_no_grounding_data(db_session, monkeypatch):
    async def fake_generate(prompt):
        return json.dumps({"summary_tr": "test", "citations": []})

    monkeypatch.setattr(factory, "get_raw_generator", lambda: fake_generate)

    pulse = await market_pulse_service.generate_market_pulse(db_session)
    assert pulse is None  # empty database -- nothing to summarize yet


async def test_generate_market_pulse_writes_a_row_when_citations_are_grounded(db_session, monkeypatch):
    await _seed_one_fx_pair(db_session, source_url="https://finance.yahoo.com/quote/TRY=X")

    async def fake_generate(prompt):
        assert "USD/TRY" in prompt
        return json.dumps(
            {
                "summary_tr": "USD/TRY bugün 48,11 seviyesinde.",
                "citations": [
                    {
                        "claim": "USD/TRY 48,11",
                        "source": "Yahoo Finance (TRY=X)",
                        "source_url": "https://finance.yahoo.com/quote/TRY=X",
                    }
                ],
            }
        )

    monkeypatch.setattr(factory, "get_raw_generator", lambda: fake_generate)

    pulse = await market_pulse_service.generate_market_pulse(db_session)
    assert pulse is not None
    assert pulse.summary_tr == "USD/TRY bugün 48,11 seviyesinde."
    assert pulse.citations[0]["source_url"] == "https://finance.yahoo.com/quote/TRY=X"

    stored = await MarketPulseRepository(db_session).latest()
    assert stored.id == pulse.id


async def test_generate_market_pulse_rejects_a_citation_pointing_outside_the_grounding_set(
    db_session, monkeypatch
):
    """The one place a hallucinated citation could slip through and read as
    real -- the model naming a URL it was never given. Must reject the whole
    generation, not just drop the bad citation, since a model that invented
    one source is not trustworthy on the rest."""
    await _seed_one_fx_pair(db_session)

    async def fake_generate(prompt):
        return json.dumps(
            {
                "summary_tr": "Uydurma bir iddia.",
                "citations": [
                    {
                        "claim": "Uydurma",
                        "source": "Bir Banka",
                        "source_url": "https://example.com/never-given-to-the-model",
                    }
                ],
            }
        )

    monkeypatch.setattr(factory, "get_raw_generator", lambda: fake_generate)

    pulse = await market_pulse_service.generate_market_pulse(db_session)
    assert pulse is None
    assert await MarketPulseRepository(db_session).latest() is None


async def test_generate_market_pulse_rejects_malformed_json(db_session, monkeypatch):
    await _seed_one_fx_pair(db_session)

    async def fake_generate(prompt):
        return "not json at all"

    monkeypatch.setattr(factory, "get_raw_generator", lambda: fake_generate)

    pulse = await market_pulse_service.generate_market_pulse(db_session)
    assert pulse is None


async def test_generate_market_pulse_rejects_missing_citations(db_session, monkeypatch):
    await _seed_one_fx_pair(db_session)

    async def fake_generate(prompt):
        return json.dumps({"summary_tr": "Yorum var ama kaynak yok.", "citations": []})

    monkeypatch.setattr(factory, "get_raw_generator", lambda: fake_generate)

    pulse = await market_pulse_service.generate_market_pulse(db_session)
    assert pulse is None


async def test_generate_market_pulse_survives_a_provider_exception(db_session, monkeypatch):
    await _seed_one_fx_pair(db_session)

    async def broken_generate(prompt):
        raise RuntimeError("provider down")

    monkeypatch.setattr(factory, "get_raw_generator", lambda: broken_generate)

    pulse = await market_pulse_service.generate_market_pulse(db_session)
    assert pulse is None


async def test_build_grounding_includes_fx_board_forecasts_and_iata(db_session):
    await _seed_one_fx_pair(db_session)

    curated = CuratedRepository(db_session)
    await curated.upsert_fx_forecast(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+12m",
        horizon_months=12,
        value=66.0,
        publication_date=date(2026, 8, 21),
        source_url="https://danske",
    )
    await curated.upsert_iata_indicator(
        metric="load_factor",
        kind="actual",
        value=83.5,
        unit="%",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        period_label_tr="2025",
        publication_date=date(2026, 6, 7),
        source_url="https://iata.org",
    )
    await db_session.commit()

    facts = await market_pulse_service.build_grounding(db_session)
    urls = {f.source_url for f in facts}
    assert "https://danske" in urls
    assert "https://iata.org" in urls
    assert any(f.label == "USD/TRY" for f in facts)


def test_parse_and_validate_rejects_non_dict_citation():
    raw = json.dumps({"summary_tr": "x", "citations": ["not a dict"]})
    assert market_pulse_service._parse_and_validate(raw, {"https://a"}) is None


def test_parse_and_validate_rejects_blank_summary():
    raw = json.dumps({"summary_tr": "   ", "citations": [{"claim": "a", "source": "b", "source_url": "https://a"}]})
    assert market_pulse_service._parse_and_validate(raw, {"https://a"}) is None
