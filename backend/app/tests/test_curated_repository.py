from datetime import date, datetime, timedelta, timezone

from app.forecast_horizon import forecast_target_date
from app.repositories.curated_repository import CuratedRepository


async def test_upsert_fx_forecast_inserts_then_updates_the_same_natural_key(db_session):
    repo = CuratedRepository(db_session)

    row, was_new = await repo.upsert_fx_forecast(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+12m",
        horizon_months=12,
        value=66.0,
        publication_date=date(2026, 8, 21),
        source_url="https://research.danskebank.com/x.pdf",
    )
    await db_session.commit()
    assert was_new is True
    assert row.value == 66.0

    # The same bank revising its own +12m call -- same natural key, updates
    # in place rather than accumulating a second row for the same claim.
    row2, was_new2 = await repo.upsert_fx_forecast(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+12m",
        horizon_months=12,
        value=64.0,
        publication_date=date(2026, 9, 1),
        source_url="https://research.danskebank.com/y.pdf",
    )
    await db_session.commit()
    assert was_new2 is False
    assert row2.id == row.id
    assert row2.value == 64.0
    assert row2.source_url == "https://research.danskebank.com/y.pdf"

    rows = await repo.fx_forecasts()
    assert len(rows) == 1


async def test_upsert_fx_forecast_treats_different_horizons_as_different_claims(db_session):
    repo = CuratedRepository(db_session)

    await repo.upsert_fx_forecast(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+3m",
        horizon_months=3,
        value=52.0,
        publication_date=date(2026, 8, 21),
        source_url="https://x",
    )
    await repo.upsert_fx_forecast(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+12m",
        horizon_months=12,
        value=66.0,
        publication_date=date(2026, 8, 21),
        source_url="https://x",
    )
    await db_session.commit()

    rows = await repo.fx_forecasts(currency_pair="USD/TRY")
    assert len(rows) == 2


async def test_fx_forecasts_filters_by_pair_and_horizon(db_session):
    repo = CuratedRepository(db_session)

    await repo.upsert_fx_forecast(
        institution="ING",
        currency_pair="EUR/USD",
        horizon_label="Q4 2026",
        horizon_months=None,
        value=1.22,
        publication_date=date(2025, 11, 10),
        source_url="https://ing",
    )
    await repo.upsert_fx_forecast(
        institution="Danske Bank",
        currency_pair="USD/TRY",
        horizon_label="+12m",
        horizon_months=12,
        value=66.0,
        publication_date=date(2026, 8, 21),
        source_url="https://danske",
    )
    await db_session.commit()

    only_try = await repo.fx_forecasts(currency_pair="USD/TRY")
    assert [r.institution for r in only_try] == ["Danske Bank"]

    only_12m = await repo.fx_forecasts(horizon_months=12)
    assert [r.institution for r in only_12m] == ["Danske Bank"]


async def test_upsert_iata_indicator_inserts_then_updates_on_revision(db_session):
    repo = CuratedRepository(db_session)

    row, was_new = await repo.upsert_iata_indicator(
        metric="ebit",
        kind="forecast",
        value=48.0,
        unit="USD milyar",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        period_label_tr="2026",
        publication_date=date(2026, 6, 7),
        source_url="https://iata.org/report-june",
    )
    await db_session.commit()
    assert was_new is True

    # IATA revising the same 2026 forecast in a later outlook -- same period,
    # same metric, same kind: an update, not a second row.
    row2, was_new2 = await repo.upsert_iata_indicator(
        metric="ebit",
        kind="forecast",
        value=52.0,
        unit="USD milyar",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        period_label_tr="2026",
        publication_date=date(2026, 12, 1),
        source_url="https://iata.org/report-december",
    )
    await db_session.commit()
    assert was_new2 is False
    assert row2.id == row.id
    assert row2.value == 52.0

    rows = await repo.iata_indicators()
    assert len(rows) == 1


async def test_upsert_iata_indicator_keeps_forecast_and_actual_separate(db_session):
    repo = CuratedRepository(db_session)

    await repo.upsert_iata_indicator(
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
    await repo.upsert_iata_indicator(
        metric="load_factor",
        kind="forecast",
        value=84.0,
        unit="%",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        period_label_tr="2026",
        publication_date=date(2026, 6, 7),
        source_url="https://iata.org",
    )
    await db_session.commit()

    actuals = await repo.iata_indicators(kind="actual")
    forecasts = await repo.iata_indicators(kind="forecast")
    assert [r.value for r in actuals] == [83.5]
    assert [r.value for r in forecasts] == [84.0]


async def test_only_upcoming_drops_a_forecast_whose_own_horizon_has_elapsed(db_session):
    """A bank's "+3 months" published in March is a claim about June. In
    October it is a claim about the past -- still a true record of what was
    said, which is why the row stays in the table, but no longer a statement
    about where the rate is going.

    Kokpit's Kur Riski tile asks for `only_upcoming` because an elapsed
    horizon was free to be the endpoint it quoted as the outlook.
    """
    repo = CuratedRepository(db_session)
    today = datetime.now(timezone.utc).date()

    await repo.upsert_fx_forecast(
        institution="Elapsed Bank",
        currency_pair="USD/TRY",
        horizon_label="+3m",
        horizon_months=3,
        value=44.0,
        # Published a year ago, so its three-month horizon landed nine months
        # back.
        publication_date=today - timedelta(days=365),
        source_url="https://elapsed.example",
    )
    await repo.upsert_fx_forecast(
        institution="Ahead Bank",
        currency_pair="USD/TRY",
        horizon_label="+12m",
        horizon_months=12,
        value=66.0,
        publication_date=today - timedelta(days=30),
        source_url="https://ahead.example",
    )
    await db_session.commit()

    everything = await repo.fx_forecasts(currency_pair="USD/TRY")
    upcoming = await repo.fx_forecasts(currency_pair="USD/TRY", only_upcoming=True)

    # The table keeps the record; only the tile's view narrows.
    assert {row.institution for row in everything} == {"Elapsed Bank", "Ahead Bank"}
    assert [row.institution for row in upcoming] == ["Ahead Bank"]


async def test_only_upcoming_drops_a_label_horizon_the_resolver_can_date(db_session):
    """A row labelled "end-2024" carries no `horizon_months`, and the
    repository used to read that NULL as "undatable" and keep the row forever.

    It is not undatable: app/forecast_horizon.py resolves the institution's own
    wording, and it is the SAME resolver the FX board uses to stamp such a row
    "· vadesi geçti". Before this, the Kur Riski tile quoted as its
    forward-looking endpoint a forecast the table beside it drew as expired.
    """
    repo = CuratedRepository(db_session)
    await repo.upsert_fx_forecast(
        institution="Elapsed Label Bank",
        currency_pair="USD/TRY",
        horizon_label="end-2024",
        horizon_months=None,
        value=35.0,
        publication_date=date(2024, 3, 4),
        source_url="https://elapsed-label.example",
    )
    # The other half of the rule: a label-only horizon still AHEAD of us stays.
    ahead_year = datetime.now(timezone.utc).year + 2
    await repo.upsert_fx_forecast(
        institution="Ahead Label Bank",
        currency_pair="USD/TRY",
        horizon_label=f"end-{ahead_year}",
        horizon_months=None,
        value=70.0,
        publication_date=datetime.now(timezone.utc).date() - timedelta(days=10),
        source_url="https://ahead-label.example",
    )
    await db_session.commit()

    everything = await repo.fx_forecasts(currency_pair="USD/TRY")
    upcoming = await repo.fx_forecasts(currency_pair="USD/TRY", only_upcoming=True)

    # The table still records what both banks said.
    assert {row.institution for row in everything} == {"Elapsed Label Bank", "Ahead Label Bank"}
    assert [row.institution for row in upcoming] == ["Ahead Label Bank"]


async def test_only_upcoming_keeps_a_forecast_whose_horizon_cannot_be_dated(db_session):
    """A wording the resolver does not recognise ("orta vade") has no target
    date at all -- neither this filter nor the chart can place it.

    Unknown is not elapsed. Dropping it would be acting on an absence of
    evidence, which is the same error as publishing an unmeasured score.
    """
    repo = CuratedRepository(db_session)
    await repo.upsert_fx_forecast(
        institution="Belirsiz Vade Bank",
        currency_pair="USD/TRY",
        horizon_label="orta vade",
        horizon_months=None,
        value=51.4,
        # Old enough that any datable horizon would have elapsed.
        publication_date=datetime.now(timezone.utc).date() - timedelta(days=900),
        source_url="https://belirsiz.example",
    )
    await db_session.commit()

    upcoming = await repo.fx_forecasts(currency_pair="USD/TRY", only_upcoming=True)
    assert [row.institution for row in upcoming] == ["Belirsiz Vade Bank"]


def test_forecast_target_date_adds_calendar_months_and_clamps_the_day():
    """The month-count rungs of the shared resolver, which is what
    `only_upcoming` compares against. The label rungs (end-YYYY, year-end,
    QN YYYY) are pinned in test_kokpit_api.py against the same function."""
    def target(publication_date, horizon_months, label="+Nm"):
        result, _ = forecast_target_date(
            horizon_months=horizon_months,
            horizon_label=label,
            publication_date=publication_date,
        )
        return result

    # Plain case: 21 August + 3 months.
    assert target(date(2026, 8, 21), 3) == date(2026, 11, 21)
    # Across a year boundary.
    assert target(date(2026, 8, 21), 12) == date(2027, 8, 21)
    # 31 August + 6 months lands in a February that has no 31st.
    assert target(date(2026, 8, 31), 6) == date(2027, 2, 28)
    # A wording the resolver does not recognise has no target date at all.
    assert target(date(2026, 8, 21), None, "orta vade") is None
    # ... but a NULL month count is no longer the same thing as undatable.
    assert target(date(2026, 8, 21), None, "end-2026") == date(2026, 12, 31)
