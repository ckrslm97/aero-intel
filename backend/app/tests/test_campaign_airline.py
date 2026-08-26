"""Campaign validation, against real production failures.

Every rejection case here is a row that was actually published: two of the
Pegasus BolBol partnership rows with multi-year "sale windows", and an Amex
promotion whose title began "[Expired]".
"""
from datetime import date, timedelta

import pytest

from app.agents.campaign_airline import (
    MAX_SALE_WINDOW_DAYS,
    STALE_AFTER_DAYS,
    validate_campaign,
)
from app.llm.classify import CampaignExtraction
from app.pipeline.outcomes import OutcomeState

TODAY = date(2026, 8, 26)


def _campaign(**overrides) -> CampaignExtraction:
    defaults = dict(
        airline_code="PC", discount_pct=50,
        sale_starts=date(2026, 8, 25), sale_ends=date(2026, 8, 27),
        travel_starts=None, travel_ends=None, markets={},
    )
    defaults.update(overrides)
    return CampaignExtraction(**defaults)


def test_a_genuine_short_sale_window_is_accepted():
    """Balkanlar %50'ye Varan İndirimle! -- tarih ve oran birebir doğrulanan
    tek gerçek kayıtlardan biri."""
    result = validate_campaign("Balkanlar %50'ye Varan İndirimle!", _campaign(), today=TODAY)
    assert result.state is OutcomeState.CLASSIFIED
    assert result.payload.airline_code == "PC"


@pytest.mark.parametrize(
    "title",
    [
        "[Expired] Use This Amex Promotion To Fly Etihad First Class From $1,265",
        "[Expired] [Deal Alert] Save up to 30% on Economy and Business Fares",
        "[expired] lowercase variant",
    ],
)
def test_an_expired_title_is_rejected_regardless_of_what_the_model_said(title):
    """The prompt already tells the model not to treat these as live; this is
    the code-level guard for when it does anyway -- the same discipline
    llm/classify.py applies to discount_pct instead of only asking nicely."""
    result = validate_campaign(title, _campaign(), today=TODAY)
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "expired_title"


def test_a_multi_year_window_is_rejected():
    """Pegasus BolBol ve Teknevia İş Birliği: 2024-06-25 -> 2026-12-31 as its
    recorded "sale window" -- a partnership announcement, not a fare sale."""
    result = validate_campaign(
        "Pegasus BolBol ve Teknevia İş Birliği",
        _campaign(sale_starts=date(2024, 6, 25), sale_ends=date(2026, 12, 31), discount_pct=None),
        today=TODAY,
    )
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "implausible_sale_window"


def test_a_window_exactly_at_the_limit_is_accepted():
    starts = TODAY - timedelta(days=1)
    ends = starts + timedelta(days=MAX_SALE_WINDOW_DAYS)
    result = validate_campaign(
        "Uzun ama gerçekçi bir kampanya",
        _campaign(sale_starts=starts, sale_ends=ends),
        today=TODAY,
    )
    assert result.state is OutcomeState.CLASSIFIED


def test_a_window_one_day_past_the_limit_is_rejected():
    starts = TODAY - timedelta(days=1)
    ends = starts + timedelta(days=MAX_SALE_WINDOW_DAYS + 1)
    result = validate_campaign(
        "Sınırın bir gün üstünde",
        _campaign(sale_starts=starts, sale_ends=ends),
        today=TODAY,
    )
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "implausible_sale_window"


def test_a_campaign_with_only_a_start_date_is_not_checked_for_window_length():
    """No end date means no window to measure -- must not crash or reject on
    an absent field."""
    result = validate_campaign(
        "Başlangıcı belli, bitişi belirsiz",
        _campaign(sale_starts=date(2026, 8, 1), sale_ends=None),
        today=TODAY,
    )
    assert result.state is OutcomeState.CLASSIFIED


def test_a_closed_sale_window_beyond_the_grace_period_is_stale():
    stale_end = TODAY - timedelta(days=STALE_AFTER_DAYS + 1)
    result = validate_campaign(
        "Geçen ay kapanmış bir kampanya",
        _campaign(sale_starts=stale_end - timedelta(days=3), sale_ends=stale_end),
        today=TODAY,
    )
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "sale_window_closed"


def test_a_recently_closed_window_within_the_grace_period_still_shows():
    """A sale that ended yesterday is still worth showing -- a revenue desk
    reacting a day late should still see it."""
    recent_end = TODAY - timedelta(days=1)
    result = validate_campaign(
        "Dün kapanmış bir kampanya",
        _campaign(sale_starts=recent_end, sale_ends=recent_end),
        today=TODAY,
    )
    assert result.state is OutcomeState.CLASSIFIED

