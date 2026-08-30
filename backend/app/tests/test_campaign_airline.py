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
        # The live QR leak: neither headline contains a single term the list
        # knew before -- no miles, no points, no programme the rulepack had
        # heard of. "Privilege Club" and the member-audience dative are what
        # decide it, in whichever language the source wrote it.
        ("Qatar Airways, Privilege Club üyelerine 10% indirim sunuyor", ""),
        ("Qatar Airways Offering 10% Discount To Privilege Club Members", ""),
        ("Etihad Guest ile tanışın", "Programa katılım ücretsiz."),
        ("Üyelere özel %15 indirim", "Programa katılan herkes yararlanır."),
    ],
)
def test_a_loyalty_promotion_is_never_published_as_a_fare_campaign(title, text):
    """The single largest category among the 129 wrong rows. These are about
    the currency, not about the fare."""
    result = validate_campaign(title, _campaign(), today=TODAY, text=text)
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:LOYALTY_PROMOTION"


def test_alliance_membership_prose_is_not_member_discount_vocabulary():
    """"Star Alliance üyesi Lufthansa" is how aviation prose names a carrier,
    and it appears on genuine fare campaigns. The member-audience terms are
    exact dative-plural forms ("üyelerine") rather than a "üye" stem precisely
    so this sentence survives them."""
    result = validate_campaign(
        "Star Alliance üyesi LOT, Varşova hattında %25 indirim başlattı",
        _campaign(),
        today=TODAY,
        text="Kampanya 25-27 Ağustos arasında satışta.",
    )
    assert result.state is OutcomeState.CLASSIFIED
    assert result.details["business_class"] == "ACTIVE_CAMPAIGN"


@pytest.mark.parametrize(
    "title,text",
    [
        # The Turkish "ödül" family, in the inflections the headlines actually
        # use -- none of which contain the bare stem.
        ("Qatar Airways aylık ödül indirimini tanıtıyor", "Ödüllerde %25'e varan azalma."),
        ("Qatar Airways ödül uçuş maliyetlerini %25 azalttı", ""),
        ("Alaska Atmos Rewards Küresel Kaçış Ödül Satışı", "Ödül biletleri daha az mille."),
        ("Her seyahatseverin bilmesi gereken 9 ödül uçuşu rezervasyon taktiği", ""),
        ("Ödüle giden yol", "Ödülü nasıl kullanacağınızı anlatıyoruz."),
        # English, phrase by phrase.
        ("Award Booking Guide", "How to find award space on partner carriers."),
        ("Global Getaways Award Sale", "Book an award flight for fewer miles."),
        ("Redeem your points for a premium cabin", "Redemptions open on Monday."),
        # Points that only ever appear inflected: "puan" is in the rulepack,
        # "puanlarınızı" is what the headline says.
        ("Kredi Kartı Puanlarınızı Cathay Pacific'e Transfer Edin", ""),
        ("Transfer edilebilir kredi kartı puanları neden kazanılmalı", ""),
        ("Bu ay %30 transfer bonusu", "Puan aktarımı yapanlara bonus."),
    ],
)
def test_the_award_and_points_vocabulary_is_never_a_fare_campaign(title, text):
    """The categories PR8 documented as residual and the backfill left live:
    award sales, award-booking guides and credit-card point transfers. All are
    about the currency or about how to spend it, never about a fare."""
    result = validate_campaign(title, _campaign(), today=TODAY, text=text)
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:LOYALTY_PROMOTION"


@pytest.mark.parametrize(
    "title,text",
    [
        ("120.000 + ~500$'lık iş sınıfı üç kişilik aile için uygun mu?", ""),
        ("Is 120,000 + $500 worth it in business?", ""),
        ("Bu fırsat mantıklı mı?", "Kişi başı 60.000 + 250$ ödeyerek geçiş yapabilirsiniz."),
    ],
)
def test_a_points_plus_cash_price_is_award_content_not_a_fare(title, text):
    """"120.000 + ~500$'lık iş sınıfı" was live as a KLM campaign. The pattern
    only survives on the raw text -- fold_text() collapses it to "120 000 500",
    losing the "+" and the "$" that are the whole signal."""
    result = validate_campaign(title, _campaign(), today=TODAY, text=text)
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:LOYALTY_PROMOTION"


@pytest.mark.parametrize(
    "title,text",
    [
        ("IAG Cargo'nun ilk yarı yıl geliri %9,4 düştü", "Kapasite kesintileri etkiledi."),
        ("Turkish Cargo second quarter revenue rises 12 percent", ""),
        ("Kargo biriminin çeyrek kârı açıklandı", "Bilanço bugün paylaşıldı."),
    ],
)
def test_a_cargo_financial_report_is_news_not_a_passenger_campaign(title, text):
    """A revenue *decline* read as a discount is the exact mistake the module
    docstring opens with, and it was still live: "IAG Cargo'nun ilk yarı yıl
    geliri ... %9,4 düşüş" was published as a Qatar Airways campaign."""
    result = validate_campaign(title, _campaign(), today=TODAY, text=text)
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:NEWS_ONLY"


def test_cargo_alone_is_not_enough_to_reject_a_dated_campaign():
    """Both halves are required. A carrier's own cargo promotion with a real
    window is not a financial results announcement, and the rulepack must not
    treat the word "kargo" as a veto."""
    result = validate_campaign(
        "Kargo taşımalarında %20 indirim",
        _campaign(discount_pct=20),
        today=TODAY,
        text="Kargo gönderilerinde 25-27 Ağustos arası %20 indirim. Hemen rezervasyon yapın.",
    )
    assert result.state is OutcomeState.CLASSIFIED


@pytest.mark.parametrize(
    "title,text",
    [
        ("KLM, Bölgesel Ekonomi Sınıfında Buy On Board Hizmetini Sunuyor", ""),
        ("Lufthansa kısa mesafede yeni kabin hizmetini başlatıyor", ""),
        ("British Airways introduces new service on regional routes", ""),
    ],
)
def test_a_service_launch_announcement_is_a_product_not_a_fare_campaign(title, text):
    result = validate_campaign(title, _campaign(), today=TODAY, text=text)
    assert result.state is OutcomeState.NOT_APPLICABLE
    assert result.reason == "business_class:PRODUCT_PROMOTION"


def test_a_launch_verb_alone_does_not_reject_a_campaign_announcing_itself():
    """"sunuyor", "duyurdu" and "tanıtıyor" are also how a real campaign
    announces itself, which is why every service-launch term is a phrase bound
    to a service noun rather than a bare verb."""
    result = validate_campaign(
        "Pegasus yeni indirim kampanyasını tanıtıyor",
        _campaign(),
        today=TODAY,
        text="Pegasus, 25-27 Ağustos arası geçerli %50 indirimi duyurdu. Hemen rezervasyon yapın.",
    )
    assert result.state is OutcomeState.CLASSIFIED


@pytest.mark.parametrize(
    "title,text",
    [
        ("Ödüllü havayolumuzla Balkanlar'a %45 indirim", "Ödüllü havayolu Pegasus duyurdu."),
        ("Award-winning airline: 40% off fares to London", "Book now."),
        ("Yılın ödüllü kabin ekibiyle uçun", "25-27 Ağustos arası %50 indirim."),
    ],
)
def test_award_winning_marketing_fluff_does_not_block_a_real_campaign(title, text):
    """The morphology trap the "ödül" rule had to be written around: "ödüllü"
    is the adjective "award-winning", one letter from "ödüller". A rulepack
    that rejects a dated campaign for praising itself has overreached, and this
    is the assertion that says so."""
    result = validate_campaign(title, _campaign(), today=TODAY, text=text)
    assert result.state is OutcomeState.CLASSIFIED
    assert result.details["business_class"] == "ACTIVE_CAMPAIGN"


def test_a_million_seats_on_sale_is_not_read_as_a_points_balance():
    """"1 milyon koltuk indirimde" is standard Turkish campaign copy. It is
    also why "mil" is not one of the suffix-tolerant stems -- `\\bmil\\w*`
    swallows "milyon"."""
    result = validate_campaign(
        "1 milyon koltuk indirimde",
        _campaign(),
        today=TODAY,
        text="Kampanya 25-27 Ağustos arası. Hemen bilet alın.",
    )
    assert result.state is OutcomeState.CLASSIFIED


def test_a_fare_price_with_a_thousands_separator_is_not_points_plus_cash():
    result = validate_campaign(
        "İstanbul-Berlin 1.299 TL'den başlayan fiyatlarla",
        _campaign(),
        today=TODAY,
        text="Satış dönemi 25-27 Ağustos. Hemen rezervasyon yapın.",
    )
    assert result.state is OutcomeState.CLASSIFIED


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

