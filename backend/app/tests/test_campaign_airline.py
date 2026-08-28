"""Campaign validation, against real production failures.

Every rejection case here is a row that was actually published: two of the
Pegasus BolBol partnership rows with multi-year "sale windows", an Amex
promotion whose title began "[Expired]", and -- for the business-class half
below -- the Avios bonus sales, Flying Blue devaluation write-ups and baggage
promos that made up most of the 129 wrong rows out of 131.

The date guards and the business-class rulepacks answer different questions.
The guards ask "is this campaign live and plausible" and cannot reject a page
with no dates on it at all; most of the wrong rows had no dates. The rulepacks
ask the prior question -- "is this a fare campaign" -- and are what stops a
mileage sale from ever being published as one.
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


# --- business class: is this a fare campaign at all? -------------------------


@pytest.mark.parametrize(
    "title,text",
    [
        ("BolBol Extralılara özel: %50 Bagaj İndirimi", ""),
        ("Ekstra bagaj hakkınızda indirim", "Bagaj hakkı satın alırken %30 indirim."),
        ("Lounge erişiminde kampanya", "İç hatlarda CIP salonu kullanımı yarı fiyatına."),
        ("Koltuk seçimi kampanyası", "Seçili uçuşlarda yer seçimi ücretsiz."),
        ("Extra baggage promotion", "Save 30% when you buy extra baggage online."),
        ("Lounge access offer", "Half-price lounge access for economy passengers."),
        ("Otel rezervasyonlarında indirim", "Anlaşmalı otellerde konaklama indirimi."),
        ("Car rental discount", "Save on rent a car bookings made with your ticket."),
    ],
)
def test_a_product_promotion_is_never_published_as_a_fare_campaign(title, text):
    """Ancillary revenue is legitimate aviation news and never a fare sale.
    The old pipeline published "%50 Bagaj İndirimi" as a Pegasus fare
    campaign."""
    result = validate_campaign(title, _campaign(), today=TODAY, text=text)
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:PRODUCT_PROMOTION"
    assert result.details["business_class"] == "PRODUCT_PROMOTION"


@pytest.mark.parametrize(
    "title,text",
    [
        ("Buy Qatar Airways Avios With 50% Bonus", ""),
        ("Buy JetBlue TrueBlue Points With Up To 120% Bonus", ""),
        ("Flying Blue Award Pricing Changes", "A devaluation of the award chart."),
        ("Miles&Smiles üyelerine mil kampanyası", "Uçuşlarınızda 2 kat mil kazanın."),
        ("Skywards statü eşitleme", "Status match başvuruları başladı."),
        ("Puan transferi kampanyası", "Kredi kartı puanlarınızı mil'e çevirin."),
        ("Double miles this autumn", "Earn bonus miles on every flight."),
    ],
)
def test_a_loyalty_promotion_is_never_published_as_a_fare_campaign(title, text):
    """The single largest category among the 129 wrong rows. These are about
    the currency, not about the fare."""
    result = validate_campaign(title, _campaign(), today=TODAY, text=text)
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:LOYALTY_PROMOTION"


@pytest.mark.parametrize(
    "title,text",
    [
        ("Öğrencilere özel indirim", "Öğrenci belgesi ile her zaman geçerli indirim."),
        ("Student discount", "Students always save on selected routes."),
        ("Kurumsal seyahat avantajları", "Şirketler için sürekli geçerli kurumsal anlaşma."),
        ("65 yaş üstü yolcularımıza", "Senior yolcular için yıl boyu indirim."),
        ("KKTC mukim indirimi", "Resident tarifesi ikamet belgesi ile uygulanır."),
    ],
)
def test_an_evergreen_offer_with_no_sale_window_is_not_a_campaign(title, text):
    """A "campaign" that never starts and never ends is noise on a timeline
    whose entire purpose is when-does-this-close."""
    result = validate_campaign(
        title, _campaign(sale_starts=None, sale_ends=None), today=TODAY, text=text
    )
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:EVERGREEN_OFFER"


def test_a_dated_student_campaign_is_a_real_campaign_not_an_evergreen_offer():
    """The rulepack needs BOTH the vocabulary and the absence of a window.
    "Öğrencilere özel 3 gün %30" is a real campaign that happens to target
    students, and rejecting it would be the rulepack overreaching."""
    result = validate_campaign(
        "Öğrencilere özel 3 günlük indirim",
        _campaign(sale_starts=date(2026, 8, 25), sale_ends=date(2026, 8, 27)),
        today=TODAY,
        text="Öğrenci biletlerinde %30 indirim, 25-27 Ağustos arası.",
    )
    assert result.state is OutcomeState.CLASSIFIED
    assert result.details["business_class"] == "ACTIVE_CAMPAIGN"


@pytest.mark.parametrize(
    "title,text",
    [
        ("Havayolu yaz döneminde kampanya yapacağını duyurdu", "Ayrıntılar paylaşılmadı."),
        ("Airline hints at autumn promotions", "No details were given."),
        ("Rekabet kurumu kampanya duyurularını inceliyor", "İnceleme sürüyor."),
    ],
)
def test_a_page_with_no_dates_no_rate_and_no_call_to_action_is_news_only(title, text):
    """An article *about* the campaign surface rather than a campaign. Neither
    date guard can catch these -- they have no dates to be implausible."""
    result = validate_campaign(
        title,
        _campaign(discount_pct=None, sale_starts=None, sale_ends=None),
        today=TODAY,
        text=text,
    )
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:NEWS_ONLY"


def test_a_dateless_page_with_a_booking_call_to_action_is_not_news_only():
    """The CTA vocabulary is deliberately loose, because every term in it makes
    NEWS_ONLY less likely: a false match costs a row that survives to the next
    guard, a missing term costs a real campaign."""
    result = validate_campaign(
        "Fırsat biletleri",
        _campaign(discount_pct=None, sale_starts=None, sale_ends=None),
        today=TODAY,
        text="Hemen rezervasyon yapın, biletinizi alın.",
    )
    assert result.state is OutcomeState.CLASSIFIED


def test_a_dateless_page_with_a_stated_discount_is_not_news_only():
    result = validate_campaign(
        "Yurt dışı uçuşlarında %35 indirim",
        _campaign(discount_pct=35, sale_starts=None, sale_ends=None),
        today=TODAY,
    )
    assert result.state is OutcomeState.CLASSIFIED


def test_a_genuine_fare_campaign_still_passes_every_rulepack():
    """The golden set's own "ok" record, run through the new layer with a body
    attached. Precision work that rejects this is precision work that has gone
    too far."""
    result = validate_campaign(
        "Balkanlar %50'ye Varan İndirimle!",
        _campaign(),
        today=TODAY,
        text="Balkan hatlarında %50'ye varan indirim, 25-27 Ağustos arası satışta.",
    )
    assert result.state is OutcomeState.CLASSIFIED
    assert result.details["business_class"] == "ACTIVE_CAMPAIGN"


def test_the_body_is_optional_so_title_only_callers_still_grade():
    """services/golden_eval_service.py grades labelled titles with no body
    available; a rulepack that required one would silently stop grading."""
    result = validate_campaign("Avios satışında %50 bonus", _campaign(), today=TODAY)
    assert result.reason == "business_class:LOYALTY_PROMOTION"


# --- classification_reason ---------------------------------------------------


def test_an_accepted_campaign_states_what_it_was_accepted_on():
    result = validate_campaign("Balkanlar %50'ye Varan İndirimle!", _campaign(), today=TODAY)
    reason = result.details["classification_reason"]
    assert "Satış dönemi" in reason
    assert "%50 indirim" in reason
    assert reason.endswith(".")


def test_an_accepted_campaign_with_no_dates_says_so_rather_than_inventing_them():
    result = validate_campaign(
        "Fırsat biletleri",
        _campaign(discount_pct=None, sale_starts=None, sale_ends=None),
        today=TODAY,
        text="Hemen rezervasyon yapın.",
    )
    assert "belirtilmemiş" in result.details["classification_reason"]


def test_a_rejection_quotes_the_phrase_that_decided_it():
    """A verdict the analyst cannot check is a verdict they cannot trust."""
    result = validate_campaign("Buy Qatar Airways Avios With 50% Bonus", _campaign(), today=TODAY)
    assert "avios" in result.details["classification_reason"]


@pytest.mark.parametrize(
    "title,campaign_kwargs",
    [
        ("[Expired] Save up to 30% on Economy Fares", {}),
        (
            "Pegasus BolBol ve Teknevia İş Birliği",
            dict(sale_starts=date(2024, 6, 25), sale_ends=date(2026, 12, 31)),
        ),
        (
            "Geçen ay kapanmış bir kampanya",
            dict(sale_starts=date(2026, 7, 1), sale_ends=date(2026, 7, 15)),
        ),
        ("Buy Qatar Airways Avios With 50% Bonus", {}),
        ("Ekstra bagaj indirimi", {}),
    ],
)
def test_every_rejection_carries_a_turkish_sentence_explaining_itself(title, campaign_kwargs):
    result = validate_campaign(title, _campaign(**campaign_kwargs), today=TODAY)
    assert result.state is OutcomeState.NOT_APPLICABLE
    reason = result.details["classification_reason"]
    assert reason and reason.endswith(".")
    # A sentence, not a slug: slugs live in `reason`, prose lives here.
    assert " " in reason.strip()


def test_the_date_guards_do_not_claim_a_business_class():
    """"This window is a partnership, not a sale" is a statement about the
    extraction, not about what kind of page this is -- and EXPIRED is
    services/campaign_status.py's question, computed from dates rather than
    detected here."""
    result = validate_campaign(
        "Pegasus BolBol ve Teknevia İş Birliği",
        _campaign(sale_starts=date(2024, 6, 25), sale_ends=date(2026, 12, 31)),
        today=TODAY,
    )
    assert result.details["business_class"] is None


def test_every_business_class_this_layer_emits_is_a_declared_slug():
    from app.taxonomy import CAMPAIGN_BUSINESS_CLASSES

    emitted = set()
    for title, text in [
        ("Balkanlar %50'ye Varan İndirimle!", ""),
        ("Ekstra bagaj indirimi", ""),
        ("Avios bonus", ""),
        ("Öğrencilere özel indirim", "her zaman geçerli"),
        ("Havayolu kampanya yapacağını duyurdu", ""),
    ]:
        outcome = validate_campaign(
            title,
            _campaign(discount_pct=None, sale_starts=None, sale_ends=None),
            today=TODAY,
            text=text,
        )
        emitted.add(outcome.details["business_class"])
    assert emitted <= set(CAMPAIGN_BUSINESS_CLASSES)

