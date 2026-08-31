"""SİNYALLER composition: every stream contributes, ordering holds, and an
empty stream is stated rather than swallowed.

The builders are pure by design (see app/services/signals_service.py) -- each
takes an already-computed stream and maps it -- so most of this file asserts
against hand-built streams with no database at all. The one orchestration test
patches the seven fetches, which is what proves the composition wires each
stream to its own builder rather than that any particular query works; those
queries are covered by the suites that own them.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.risks import (
    RiskCountryOut,
    RiskItemOut,
    RiskRadarOut,
    SeverityCountsOut,
)
from app.schemas.kokpit import CockpitSignalOut
from app.services import signals_service as svc

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


# --- kinds and severities ---------------------------------------------------


def test_every_kind_has_a_turkish_label_and_a_place_in_the_chip_row():
    assert set(svc.KIND_ORDER) == set(svc.KIND_LABELS_TR)
    assert len(svc.KIND_ORDER) == len(svc.KIND_LABELS_TR) == 4


def test_every_severity_has_a_label_and_the_order_is_worst_first():
    assert set(svc.SEVERITY_ORDER) == set(svc.SEVERITY_LABELS_TR)
    assert svc.SEVERITY_ORDER[0] == svc.CRITICAL
    # `unknown` sorts last but is a distinct value: it must never be able to
    # render as an all-clear, which is why it is not folded into `low`.
    assert svc.SEVERITY_ORDER[-1] == svc.UNKNOWN
    assert svc.UNKNOWN != svc.LOW


def test_a_kokpit_tile_never_reaches_critical():
    # `critical` belongs to the campaign alert ladder -- a banded FX move must
    # not outrank "a named rival's sale ends tomorrow".
    assert svc.CRITICAL not in svc.COCKPIT_LEVEL_SEVERITY.values()
    assert svc.COCKPIT_LEVEL_SEVERITY["critical"] == svc.HIGH
    assert svc.COCKPIT_LEVEL_SEVERITY["unknown"] == svc.UNKNOWN


# --- builders ---------------------------------------------------------------


def _tile(key="fx", level="warning") -> CockpitSignalOut:
    return CockpitSignalOut(
        key=key,
        label_tr="Kur Riski",
        level=level,
        level_label_tr="Dikkat",
        value_label="+%3,4",
        reason_tr="USD/TRY 41,20 · 30 günde +%3,4.",
        method_tr="Bantlama yöntemi.",
        source="Yahoo Finance",
        source_url=None,
        href="/kpi/fx_usd_try",
        as_of=NOW,
    )


def test_cockpit_tiles_carry_their_own_method_note_as_the_severity_basis():
    [row] = svc.from_cockpit([_tile()])

    assert row.kind == svc.MARKET
    assert row.severity == svc.MEDIUM
    # Verbatim: restating the threshold table here would be a second copy of a
    # number nobody would keep in step with the tile.
    assert row.severity_basis_tr == "Bantlama yöntemi."
    assert row.href == "/kpi/fx_usd_try"
    assert row.detected_at == NOW


def test_the_risk_tile_is_filed_under_risk_and_the_rival_tile_under_competitor():
    rows = svc.from_cockpit([_tile(key="risk"), _tile(key="competitor"), _tile(key="fuel")])
    assert [row.kind for row in rows] == [svc.RISK, svc.COMPETITOR, svc.MARKET]


def test_campaign_alerts_keep_their_priority_and_their_composed_sentence():
    alert = SimpleNamespace(
        id="a1",
        priority="CRITICAL",
        alert_type="EXPIRING",
        title_tr="Emirates kampanyası yarın bitiyor: Avrupa indirimi",
        detail_json={"airline_code": "EK"},
        created_at=NOW,
    )

    [row] = svc.from_campaign_alerts([alert])

    assert row.severity == svc.CRITICAL
    assert row.kind == svc.COMPETITOR
    assert row.type_label_tr == "Bitmek üzere"
    assert row.title_tr == alert.title_tr
    assert row.airline_codes == ["EK"]
    assert row.href == "/kampanyalar"


def test_a_campaign_alert_with_no_carrier_in_its_detail_carries_no_chips():
    alert = SimpleNamespace(
        id="a2",
        priority="INFO",
        alert_type="NEW",
        title_tr="Yeni kampanya",
        detail_json=None,
        created_at=NOW,
    )

    [row] = svc.from_campaign_alerts([alert])

    assert row.airline_codes == []
    assert row.severity == svc.LOW


def _risk_item(item_id="r1", severity="high", *, fresh=True, published=NOW) -> RiskItemOut:
    return RiskItemOut(
        id=item_id,
        headline="Etna'da kül bulutu",
        url="https://example.com/etna",
        source_name="Reuters",
        published_at=published,
        risk_type="volcano",
        risk_family="natural",
        risk_type_label_tr="Volkanik faaliyet",
        severity=severity,
        country="Italy",
        city="Catania",
        region="europe",
        is_fresh=fresh,
        confidence_score=0.61,
        summary_tr="Kül bulutu hava sahasını etkiledi.",
    )


def _radar(items) -> RiskRadarOut:
    return RiskRadarOut(
        days=14,
        total=len(items),
        countries=[
            RiskCountryOut(
                country="Italy",
                region="europe",
                count=len(items),
                score=3 * len(items),
                severity_counts=SeverityCountsOut(high=len(items), medium=0, low=0),
                items=items,
            )
        ],
        type_counts={},
        family_counts={},
        generated_at=NOW,
    )


def test_only_high_severity_risk_clusters_reach_the_feed():
    radar = _radar([_risk_item("r1", "high"), _risk_item("r2", "medium")])

    rows = svc.from_risk_radar(radar)

    assert [row.id for row in rows] == ["risk:r1"]
    assert rows[0].kind == svc.RISK
    assert rows[0].severity == svc.HIGH
    # The confidence the risk rollup actually carries, never synthesised.
    assert rows[0].confidence_score == 0.61
    assert rows[0].region == "europe"


def test_fresh_risk_clusters_lead_the_stale_ones():
    stale = _risk_item("old", fresh=False, published=NOW - timedelta(days=10))
    fresh = _risk_item("new", fresh=True, published=NOW - timedelta(days=12))

    rows = svc.from_risk_radar(_radar([stale, fresh]))

    # Freshness wins over the raw timestamp: an early-warning list that led
    # with a ten-day-old cluster would be sorting by nothing a reader cares
    # about.
    assert [row.id for row in rows] == ["risk:new", "risk:old"]


def test_rival_events_are_one_card_per_rival_and_declare_they_have_no_severity():
    groups = [
        {
            "airline_code": "EK",
            "airline_name": "Emirates",
            "count": 4,
            "events": [
                {"headline": "Emirates yeni kabin", "region": "middle-east",
                 "last_seen": (NOW - timedelta(hours=2)).isoformat()},
                {"headline": "İkincisi", "region": "europe",
                 "last_seen": (NOW - timedelta(days=3)).isoformat()},
            ],
        }
    ]

    [row] = svc.from_rival_events(groups)

    assert row.title_tr == "Emirates: 4 yayımlanmış olay"
    assert row.severity == svc.LOW
    assert row.severity_basis_tr == svc.NO_SEVERITY_BASIS_TR
    assert row.airline_codes == ["EK"]
    # The newest telling in the group, so the recency sort is not driven by
    # whichever event happened to be listed first.
    assert row.detected_at == NOW - timedelta(hours=2)
    assert row.href == "/newspaper?airline=EK"


def test_strategic_developments_use_the_shared_category_labels_and_link_nowhere():
    events = [{"id": "e1", "headline": "Hisse satışı", "category": "finance",
               "region": "europe", "last_seen": NOW.isoformat()}]

    [row] = svc.from_strategic(events)

    assert row.kind == svc.FINANCIAL
    assert row.type_label_tr == "Finans"
    # BİZ was this stream's page and no longer renders it; there is nowhere
    # deeper to send the reader, and a Gazete tab would be wrong for two of the
    # four categories the paper excludes.
    assert row.href is None


def test_network_signals_are_flattened_per_announcement_and_capped():
    groups = [
        {
            "region": "asia",
            "count": 2,
            "articles": [
                {"id": "n1", "headline": "Yeni hat A", "airlines": ["TK"],
                 "published_at": NOW.isoformat(), "source_name": "Wire"},
                {"id": "n2", "headline": "Yeni hat B", "airlines": [],
                 "published_at": None, "source_name": "Wire"},
            ],
        }
    ]

    rows = svc.from_network(groups, limit=1)

    assert [row.id for row in rows] == ["network:n1"]
    assert rows[0].kind == svc.MARKET
    assert rows[0].region == "asia"
    assert rows[0].airline_codes == ["TK"]


def test_momentum_keeps_rivals_that_actually_moved():
    movers = [
        {"code": "TK", "name": "Turkish Airlines", "current": 30, "previous": 10, "delta": 20},
        {"code": "EK", "name": "Emirates", "current": 9, "previous": 2, "delta": 7},
        {"code": "QR", "name": "Qatar Airways", "current": 4, "previous": 4, "delta": 0},
    ]

    rows = svc.from_momentum(movers)

    # The home carrier is not a rival, and a delta of zero is not a mover.
    assert [row.airline_codes for row in rows] == [["EK"]]
    assert "+7" in rows[0].title_tr
    # A rolling window has no point reading, so no timestamp is claimed.
    assert rows[0].detected_at is None


# --- ordering ---------------------------------------------------------------


def _row(severity, detected_at, row_id="x"):
    return svc.SignalOut(
        id=row_id,
        stream="test",
        kind=svc.RISK,
        kind_label_tr="Risk",
        type_label_tr="t",
        severity=severity,
        severity_label_tr=svc.SEVERITY_LABELS_TR[severity],
        severity_basis_tr="b",
        title_tr="t",
        detected_at=detected_at,
        source_label="s",
    )


def test_severity_outranks_recency():
    rows = svc.sort_signals(
        [
            _row(svc.LOW, NOW, "low-now"),
            _row(svc.CRITICAL, NOW - timedelta(days=1), "critical-yesterday"),
            _row(svc.MEDIUM, NOW, "medium-now"),
        ]
    )

    assert [row.id for row in rows] == ["critical-yesterday", "medium-now", "low-now"]


def test_undated_rows_sort_last_within_their_band():
    rows = svc.sort_signals([_row(svc.HIGH, None, "undated"), _row(svc.HIGH, NOW, "dated")])

    assert [row.id for row in rows] == ["dated", "undated"]


# --- orchestration ----------------------------------------------------------


@pytest.fixture
def stubbed_streams(monkeypatch):
    """Every fetch the composition makes, replaced with a returnable value.

    Written as one fixture so a test can override exactly the stream it is
    about and leave the other six empty -- which is also how the "empty streams
    are tolerated" case is expressed.
    """
    state = {
        "radar": _radar([]),
        "tiles": [],
        "alerts": [],
        "rivals": [],
        "strategic": [],
        "network": [],
        "movers": [],
    }

    async def _radar_fn(db, days=14):
        return state["radar"]

    async def _tiles(db, radar=None):
        # The composition must hand its own rollup down rather than letting the
        # tiles fetch a second one -- otherwise the tile's count and the cards
        # under it could be two different numbers.
        state["radar_passed_to_tiles"] = radar
        return state["tiles"]

    async def _alerts(db, limit=20):
        return state["alerts"]

    async def _rivals(db, days=30):
        return state["rivals"]

    async def _strategic(db, days=30):
        return state["strategic"]

    async def _network(db, days=30):
        return state["network"]

    async def _momentum(db, window_days=7, limit=10):
        return state["movers"]

    monkeypatch.setattr(svc, "aggregate_risks", _radar_fn)
    monkeypatch.setattr(svc, "cockpit_signals", _tiles)
    monkeypatch.setattr(svc, "open_alerts", _alerts)
    monkeypatch.setattr(svc, "competitor_signals", _rivals)
    monkeypatch.setattr(svc, "strategic_developments", _strategic)
    monkeypatch.setattr(svc, "network_signals", _network)
    monkeypatch.setattr(svc, "airline_momentum", _momentum)
    return state


async def test_every_stream_is_listed_even_when_it_produced_nothing(stubbed_streams):
    out = await svc.unified_signals(None)

    assert out.total == 0
    assert out.signals == []
    assert [stream.key for stream in out.streams] == [key for key, _, _ in svc.STREAMS]
    # Honest empty states, not a silently omitted stream: a reader has to be
    # able to tell "nothing happened" from "it broke".
    assert all(stream.available is False for stream in out.streams)
    assert all(stream.empty_message == svc.EMPTY_MESSAGE for stream in out.streams)


async def test_each_stream_contributes_its_own_rows(stubbed_streams):
    stubbed_streams["tiles"] = [_tile(key="fuel", level="critical")]
    stubbed_streams["radar"] = _radar([_risk_item("r1")])
    stubbed_streams["alerts"] = [
        SimpleNamespace(
            id="a1", priority="HIGH", alert_type="NEW", title_tr="Yeni kampanya",
            detail_json={"airline_code": "QR"}, created_at=NOW,
        )
    ]
    stubbed_streams["rivals"] = [
        {"airline_code": "EK", "airline_name": "Emirates", "count": 2, "events": []}
    ]
    stubbed_streams["strategic"] = [
        {"id": "e1", "headline": "Filo siparişi", "category": "fleet",
         "region": None, "last_seen": NOW.isoformat()}
    ]
    stubbed_streams["network"] = [
        {"region": "asia", "count": 1, "articles": [
            {"id": "n1", "headline": "Yeni hat", "airlines": [],
             "published_at": NOW.isoformat(), "source_name": "Wire"}]}
    ]
    stubbed_streams["movers"] = [
        {"code": "EK", "name": "Emirates", "current": 9, "previous": 2, "delta": 7}
    ]

    out = await svc.unified_signals(None)

    counted = {stream.key: stream.count for stream in out.streams}
    assert counted == {
        "kokpit": 1,
        "campaign_alerts": 1,
        "risk": 1,
        "rival_events": 1,
        "strategic": 1,
        "network": 1,
        "momentum": 1,
    }
    assert out.total == 7
    assert len(out.signals) == 7
    # Sorted worst-first across streams, not grouped by stream.
    assert [row.id for row in out.signals] == [row.id for row in svc.sort_signals(out.signals)]
    assert out.signals[0].severity == svc.HIGH


async def test_the_risk_rollup_is_computed_once_and_handed_to_the_tiles(stubbed_streams):
    stubbed_streams["radar"] = _radar([_risk_item("r1")])

    await svc.unified_signals(None)

    assert stubbed_streams["radar_passed_to_tiles"] is stubbed_streams["radar"]
