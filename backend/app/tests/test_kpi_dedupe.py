"""A published estimate and a live reading look identical in the table but mean
different things: re-recording an unchanged IATA figure invents data, while a
market price that happens to be unchanged is a real observation. These pin that
distinction -- it's what made the dashboard sparklines render as flat clones.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.kpi import KPI
from app.repositories.kpi_repository import KpiRepository
from app.services.kpi_service import _record_if_changed, prune_duplicate_estimates

BASE = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _clone_rows(db_session, metric_key: str, value: float, count: int, source="IATA") -> None:
    for i in range(count):
        db_session.add(
            KPI(
                metric_key=metric_key,
                value=value,
                unit="%",
                source=source,
                is_estimate=True,
                is_primary=True,
                as_of=BASE + timedelta(minutes=15 * i),
            )
        )


async def test_unchanged_published_estimate_is_not_recorded_again(db_session):
    repo = KpiRepository(db_session)
    repo.record("load_factor", 82.5, "%", "IATA", True, BASE)
    await db_session.flush()

    wrote = await _record_if_changed(repo, "load_factor", 82.5, "%", "IATA", BASE + timedelta(minutes=15))

    assert wrote is False


async def test_revised_published_estimate_is_recorded(db_session):
    repo = KpiRepository(db_session)
    repo.record("load_factor", 82.5, "%", "IATA", True, BASE)
    await db_session.flush()

    # IATA publishing a new outlook is exactly when a new row should appear.
    wrote = await _record_if_changed(repo, "load_factor", 83.1, "%", "IATA", BASE + timedelta(days=30))

    assert wrote is True


async def test_same_value_from_a_new_source_is_recorded(db_session):
    repo = KpiRepository(db_session)
    repo.record("load_factor", 82.5, "%", "IATA Outlook 2025", True, BASE)
    await db_session.flush()

    wrote = await _record_if_changed(
        repo, "load_factor", 82.5, "%", "IATA Outlook 2026", BASE + timedelta(days=200)
    )

    assert wrote is True


async def test_prune_collapses_clone_runs_to_their_earliest_row(db_session):
    _clone_rows(db_session, "load_factor", 82.5, count=10)
    await db_session.commit()

    deleted = await prune_duplicate_estimates(db_session)

    assert deleted == 9
    rows = (
        await db_session.execute(select(KPI).where(KPI.metric_key == "load_factor"))
    ).scalars().all()
    assert len(rows) == 1
    # The kept row is the earliest -- it records when the figure first appeared.
    assert rows[0].as_of == BASE


async def test_prune_keeps_each_distinct_revision(db_session):
    _clone_rows(db_session, "rask", 8.9, count=5)
    for i in range(5):
        db_session.add(
            KPI(
                metric_key="rask",
                value=9.4,  # a later revision
                unit="¢/ASK",
                source="IATA",
                is_estimate=True,
                is_primary=True,
                as_of=BASE + timedelta(days=1, minutes=15 * i),
            )
        )
    await db_session.commit()

    await prune_duplicate_estimates(db_session)

    values = (
        await db_session.execute(
            select(KPI.value).where(KPI.metric_key == "rask").order_by(KPI.as_of)
        )
    ).scalars().all()
    assert values == [8.9, 9.4]


async def test_prune_leaves_live_market_readings_alone(db_session):
    # Brent closing at the same price twice is a real observation at a real
    # timestamp -- deleting it would be deleting data, not noise.
    for i in range(5):
        db_session.add(
            KPI(
                metric_key="oil_price",
                value=85.4,
                unit="$/bbl",
                source="Yahoo Finance (BZ=F)",
                is_estimate=False,
                is_primary=True,
                as_of=BASE + timedelta(minutes=15 * i),
            )
        )
    await db_session.commit()

    deleted = await prune_duplicate_estimates(db_session)

    assert deleted == 0
    count = await db_session.execute(
        select(func.count()).select_from(KPI).where(KPI.metric_key == "oil_price")
    )
    assert count.scalar_one() == 5
