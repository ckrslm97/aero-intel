"""Fixture-based tests for the TEFAS parse helpers (no network, no DB).

tefas.gov.tr could not be probed from the dev sandbox, so these fixtures encode
the community-documented shapes of BOTH API generations: the current JSON API
(camelCase / ISO dates) and the pre-2026 legacy API (UPPERCASE keys /
epoch-millisecond dates).
"""
from datetime import date, datetime, timezone

from app.ingest.funds.tefas import (
    _parse_tefas_date,
    parse_tefas_allocation_rows,
    parse_tefas_info_rows,
)

# ---------------------------------------------------------------------------
# _parse_tefas_date
# ---------------------------------------------------------------------------


def test_date_iso_string():
    parsed = _parse_tefas_date("2026-07-17")
    assert parsed == datetime(2026, 7, 17, tzinfo=timezone.utc)


def test_date_iso_with_time_and_z():
    parsed = _parse_tefas_date("2026-07-17T21:00:00Z")
    assert parsed == datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc)
    assert parsed.tzinfo is not None


def test_date_ddmmyyyy():
    assert _parse_tefas_date("17.07.2026") == datetime(2026, 7, 17, tzinfo=timezone.utc)


def test_date_epoch_ms_number_and_string():
    expected = datetime(2023, 7, 19, tzinfo=timezone.utc)
    assert _parse_tefas_date(1689724800000) == expected
    assert _parse_tefas_date("1689724800000") == expected


def test_date_garbage_returns_none():
    for value in (None, "", "   ", "not-a-date", "32.13.2026", [], {}, True, float("inf")):
        assert _parse_tefas_date(value) is None


# ---------------------------------------------------------------------------
# parse_tefas_info_rows
# ---------------------------------------------------------------------------

NEW_API_INFO_ROWS = [
    {
        "tarih": "2026-07-16",
        "fiyat": 1.512,
        "fonUnvan": "AK PORTFÖY HAVACILIK FONU",
        "portfoyBuyukluk": 950_000_000.0,
        "kisiSayisi": 12100,
    },
    {
        "tarih": "2026-07-17",
        "fiyat": 1.534,
        "fonUnvan": "AK PORTFÖY HAVACILIK FONU",
        "portfoyBuyukluk": 1_000_000_000.0,
        "kisiSayisi": 12345,
    },
    {
        "tarih": "2026-07-15",
        "fiyat": 1.498,
        "fonUnvan": "AK PORTFÖY HAVACILIK FONU",
    },
]


def test_new_api_info_rows_parse():
    info = parse_tefas_info_rows(NEW_API_INFO_ROWS)
    assert info is not None
    assert info.fund_title == "AK PORTFÖY HAVACILIK FONU"
    # sorted ascending regardless of input order
    assert [p.as_of.date() for p in info.points] == [
        date(2026, 7, 15),
        date(2026, 7, 16),
        date(2026, 7, 17),
    ]
    assert info.points[-1].nav == 1.534
    # aum / investor count come from the latest row
    assert info.aum == 1_000_000_000.0
    assert info.investor_count == 12345
    assert all(p.as_of.tzinfo is not None for p in info.points)


LEGACY_INFO_ROWS = {
    "data": [
        {
            "TARIH": "1689724800000",  # 2023-07-19
            "FONKODU": "AFS",
            "FONUNVAN": "LEGACY FON UNVANI",
            "FIYAT": 1.234,
            "PORTFOYBUYUKLUK": "500000000",
            "KISISAYISI": "9001",
        },
        {
            "TARIH": "1689638400000",  # 2023-07-18
            "FONKODU": "AFS",
            "FONUNVAN": "LEGACY FON UNVANI",
            "FIYAT": 1.222,
        },
    ]
}


def test_legacy_info_rows_parse():
    info = parse_tefas_info_rows(LEGACY_INFO_ROWS)
    assert info is not None
    assert info.fund_title == "LEGACY FON UNVANI"
    assert [p.as_of.date() for p in info.points] == [date(2023, 7, 18), date(2023, 7, 19)]
    assert info.points[-1].nav == 1.234
    assert info.aum == 500_000_000.0
    assert info.investor_count == 9001


def test_ddmmyyyy_info_rows_parse():
    info = parse_tefas_info_rows(
        [
            {"date": "16.07.2026", "price": "1.10"},
            {"date": "17.07.2026", "price": "1.20", "fundName": "DD.MM FON"},
        ]
    )
    assert info is not None
    assert info.fund_title == "DD.MM FON"
    assert [p.as_of.date() for p in info.points] == [date(2026, 7, 16), date(2026, 7, 17)]
    assert info.points[-1].nav == 1.20


def test_info_mixed_garbage_rows_skipped_without_raising():
    info = parse_tefas_info_rows(
        [
            "not a dict",
            42,
            None,
            {"tarih": "2026-07-17"},  # missing price
            {"fiyat": 1.5},  # missing date
            {"tarih": "garbage", "fiyat": 1.5},  # unparseable date
            {"tarih": "2026-07-16", "fiyat": "not-a-number"},
            {"tarih": "2026-07-16", "fiyat": 1.4, "fonUnvan": "SURVIVOR FON"},
        ]
    )
    assert info is not None
    assert len(info.points) == 1
    assert info.points[0].nav == 1.4
    assert info.fund_title == "SURVIVOR FON"


def test_info_title_absent_is_empty_string():
    info = parse_tefas_info_rows([{"tarih": "2026-07-17", "fiyat": 2.0}])
    assert info is not None
    assert info.fund_title == ""
    assert info.aum is None
    assert info.investor_count is None


def test_info_empty_inputs_return_none():
    assert parse_tefas_info_rows([]) is None
    assert parse_tefas_info_rows(None) is None
    assert parse_tefas_info_rows({}) is None
    assert parse_tefas_info_rows({"data": []}) is None
    assert parse_tefas_info_rows({"data": "oops"}) is None
    assert parse_tefas_info_rows("totally wrong") is None


# ---------------------------------------------------------------------------
# parse_tefas_allocation_rows
# ---------------------------------------------------------------------------


def test_allocation_column_code_rows():
    result = parse_tefas_allocation_rows(
        {
            "data": [
                {
                    "TARIH": "1689638400000",  # 2023-07-18, older -- must be ignored
                    "FONKODU": "AFS",
                    "HS": 90.0,
                    "D": 10.0,
                },
                {
                    "TARIH": "1689724800000",  # 2023-07-19, latest
                    "FONKODU": "AFS",
                    "FONUNVAN": "LEGACY FON UNVANI",
                    "HS": 55.5,
                    "DT": 20.0,
                    "VM": 0,  # zero weight -> dropped
                    "R": None,  # None -> dropped
                    "XYZ": 4.5,  # unknown code -> raw code kept as label
                    "D": 20.0,
                },
            ]
        }
    )
    assert result is not None
    as_of, slices = result
    assert as_of == date(2023, 7, 19)
    assert [(s.label, s.weight_pct) for s in slices] == [
        ("Hisse Senedi", 55.5),
        ("Devlet Tahvili", 20.0),
        ("Diğer", 20.0),
        ("XYZ", 4.5),
    ]


def test_allocation_self_describing_rows():
    result = parse_tefas_allocation_rows(
        [
            {"date": "2026-06-30", "assetType": "Hisse Senedi", "percentage": 80.0},
            {"date": "2026-07-17", "assetType": "Hisse Senedi", "percentage": 60.0},
            {"date": "2026-07-17", "assetType": "Ters Repo", "percentage": 30.0},
            {"date": "2026-07-17", "assetType": "Diğer", "percentage": 10.0},
            {"date": "2026-07-17", "assetType": "Vadeli Mevduat", "percentage": 0},  # dropped
        ]
    )
    assert result is not None
    as_of, slices = result
    assert as_of == date(2026, 7, 17)
    assert [(s.label, s.weight_pct) for s in slices] == [
        ("Hisse Senedi", 60.0),
        ("Ters Repo", 30.0),
        ("Diğer", 10.0),
    ]


def test_allocation_self_describing_uppercase_keys():
    result = parse_tefas_allocation_rows(
        [{"TARIH": "1689724800000", "VARLIKTURU": "Kıymetli Maden", "ORAN": "12,5"}]
    )
    assert result is not None
    as_of, slices = result
    assert as_of == date(2023, 7, 19)
    assert [(s.label, s.weight_pct) for s in slices] == [("Kıymetli Maden", 12.5)]


def test_allocation_garbage_rows_skipped_without_raising():
    result = parse_tefas_allocation_rows(
        [
            "junk",
            None,
            {"HS": 50.0},  # column row without a date -> unusable
            {"TARIH": "17.07.2026", "HS": "not-a-number", "D": 40.0},
        ]
    )
    assert result is not None
    as_of, slices = result
    assert as_of == date(2026, 7, 17)
    assert [(s.label, s.weight_pct) for s in slices] == [("Diğer", 40.0)]


def test_allocation_empty_inputs_return_none():
    assert parse_tefas_allocation_rows([]) is None
    assert parse_tefas_allocation_rows(None) is None
    assert parse_tefas_allocation_rows({"data": []}) is None
    assert parse_tefas_allocation_rows("nope") is None
    # rows exist but every weight is zero/None -> nothing to report
    assert parse_tefas_allocation_rows([{"TARIH": "17.07.2026", "HS": 0, "D": None}]) is None
