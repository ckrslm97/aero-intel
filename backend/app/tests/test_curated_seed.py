from app.ingest.curated_seed import (
    FX_FORECAST_ENTRIES,
    IATA_INDICATOR_ENTRIES,
    seed_curated_data,
)
from app.repositories.curated_repository import CuratedRepository


def test_every_fx_forecast_entry_has_a_real_source_url():
    assert FX_FORECAST_ENTRIES  # not an empty placeholder list
    for entry in FX_FORECAST_ENTRIES:
        assert entry["source_url"].startswith("https://")
        assert entry["institution"]
        assert entry["horizon_label"]


def test_every_fx_forecast_natural_key_is_unique():
    keys = [(e["institution"], e["currency_pair"], e["horizon_label"]) for e in FX_FORECAST_ENTRIES]
    assert len(keys) == len(set(keys))


def test_iata_indicator_entries_cover_actual_and_forecast_for_every_metric():
    metrics = {e["metric"] for e in IATA_INDICATOR_ENTRIES}
    for metric in metrics:
        kinds = {e["kind"] for e in IATA_INDICATOR_ENTRIES if e["metric"] == metric}
        assert kinds == {"actual", "forecast"}, f"{metric} missing an actual/forecast pair"


def test_iata_ebit_is_not_mislabelled_as_net_profit():
    # See the module docstring: EBIT and net profit are different figures --
    # naming this one "net_profit" would misstate a real number.
    metrics = {e["metric"] for e in IATA_INDICATOR_ENTRIES}
    assert "ebit" in metrics
    assert "net_profit" not in metrics


async def test_seed_curated_data_is_idempotent(db_session):
    first = await seed_curated_data(db_session)
    assert first["fx_forecasts_new"] == len(FX_FORECAST_ENTRIES)
    assert first["iata_indicators_new"] == len(IATA_INDICATOR_ENTRIES)

    second = await seed_curated_data(db_session)
    assert second == {"fx_forecasts_new": 0, "iata_indicators_new": 0}

    repo = CuratedRepository(db_session)
    assert len(await repo.fx_forecasts()) == len(FX_FORECAST_ENTRIES)
    assert len(await repo.iata_indicators()) == len(IATA_INDICATOR_ENTRIES)
