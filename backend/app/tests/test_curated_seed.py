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


def test_ebit_and_net_profit_are_separate_rows_with_separate_values():
    # EBIT and net profit are different figures, and IATA publishes both. The
    # table used to carry only EBIT; it now carries both under the names the
    # report uses, which is only safe as long as they never collapse into each
    # other -- if a transcription error made them equal, this is where it shows.
    by_metric = {
        (e["metric"], e["kind"]): e["value"]
        for e in IATA_INDICATOR_ENTRIES
        if e["metric"] in {"ebit", "net_profit"}
    }
    assert by_metric[("ebit", "forecast")] == 48.0
    assert by_metric[("net_profit", "forecast")] == 23.0
    assert by_metric[("ebit", "actual")] == 76.4
    assert by_metric[("net_profit", "actual")] == 45.0


def test_only_forecast_rows_carry_a_previous_edition_figure():
    # An actual is a measurement, not a restated projection -- see "Revision
    # tracking" in app/models/curated.py.
    for entry in IATA_INDICATOR_ENTRIES:
        if entry["kind"] == "actual":
            assert entry.get("previous_value") is None, entry["metric"]


def test_every_previous_figure_names_the_edition_that_printed_it():
    revised = [e for e in IATA_INDICATOR_ENTRIES if e.get("previous_value") is not None]
    assert revised  # the June 2026 report revises the December 2025 one
    for entry in revised:
        # A prior value without its own citation is an unattributable number.
        assert entry["previous_publication_date"] < entry["publication_date"]
        assert entry["previous_source_url"].startswith("https://www.iata.org/")
        assert entry["previous_source_url"] != entry["source_url"]


def test_the_2026_net_profit_forecast_records_iatas_halving():
    forecast = next(
        e for e in IATA_INDICATOR_ENTRIES if e["metric"] == "net_profit" and e["kind"] == "forecast"
    )
    assert forecast["previous_value"] == 41.0
    assert forecast["value"] == 23.0


async def test_seed_curated_data_is_idempotent(db_session):
    first = await seed_curated_data(db_session)
    assert first["fx_forecasts_new"] == len(FX_FORECAST_ENTRIES)
    assert first["iata_indicators_new"] == len(IATA_INDICATOR_ENTRIES)

    second = await seed_curated_data(db_session)
    assert second == {"fx_forecasts_new": 0, "iata_indicators_new": 0}

    repo = CuratedRepository(db_session)
    assert len(await repo.fx_forecasts()) == len(FX_FORECAST_ENTRIES)
    assert len(await repo.iata_indicators()) == len(IATA_INDICATOR_ENTRIES)
