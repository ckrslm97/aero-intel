"""The three semantic additions of the campaign v2 backend, and the one rule
that had to be loosened for them.

What is under test here, and why each block exists:

* **`campaign_kind`** -- CAMPAIGN (the offer is a price) vs PROMOTION (the
  offer is a mechanism, a channel or an audience). Derived from
  `campaign_type` through one table, so the exhaustiveness assertion below is
  the real guard: adding a campaign type without deciding its kind fails here
  rather than silently producing NULL in production.
* **The ticketing / campaign windows** -- extractable but never inferred. Both
  directions are asserted: an explicit statement fills the column, and a page
  with one window fills only the sale window.
* **The ancillary rule** -- the one place the false-positive gate was made
  looser, so every test comes in a pair: tied to a flight purchase passes,
  standalone is still rejected.
* **The confidence ceiling** for a campaign no official source confirmed.
"""
from datetime import date, datetime, timezone

from app.agents.campaign_airline import (
    ancillary_tie,
    detect_business_class,
    validate_campaign,
)
from app.llm.classify import CampaignExtraction
from app.llm.heuristic import fold_text
from app.pipeline.campaign_extract import verify_dates
from app.pipeline.confidence import (
    UNVERIFIED_SCORE_CEILING,
    ConfidenceInput,
    score,
)
from app.schemas.campaign import DATE_FIELDS, RawCampaignItem
from app.taxonomy import (
    CAMPAIGN_KINDS,
    CAMPAIGN_TYPE_TO_KIND,
    CAMPAIGN_TYPES,
    campaign_kind_for,
    is_valid_campaign_kind,
)

TODAY = date(2026, 9, 1)
NOW = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)


def _campaign(**kwargs) -> CampaignExtraction:
    return CampaignExtraction(
        airline_code=kwargs.pop("airline_code", "TK"),
        discount_pct=kwargs.pop("discount_pct", 30),
        sale_starts=kwargs.pop("sale_starts", date(2026, 8, 25)),
        sale_ends=kwargs.pop("sale_ends", date(2026, 9, 10)),
        travel_starts=kwargs.pop("travel_starts", None),
        travel_ends=kwargs.pop("travel_ends", None),
        markets=kwargs.pop("markets", {}),
        **kwargs,
    )


# --- campaign_kind ----------------------------------------------------------


def test_every_campaign_type_but_other_has_a_kind():
    """The exhaustiveness guard. A type added to CAMPAIGN_TYPES without a kind
    would produce NULL for every row that used it, and nothing else would
    notice -- a NULL kind is also the legitimate answer for a legacy row."""
    unmapped = set(CAMPAIGN_TYPES) - set(CAMPAIGN_TYPE_TO_KIND)
    assert unmapped == {"OTHER"}


def test_the_mapping_only_ever_produces_a_declared_kind():
    assert set(CAMPAIGN_TYPE_TO_KIND.values()) == set(CAMPAIGN_KINDS)
    for kind in CAMPAIGN_TYPE_TO_KIND.values():
        assert is_valid_campaign_kind(kind)


def test_price_shaped_offers_are_campaigns():
    for slug in (
        "FARE_DISCOUNT", "PERCENT_DISCOUNT", "FIXED_FARE", "FLASH_SALE",
        "EARLY_BOOKING", "LAST_MINUTE", "ROUND_TRIP_PROMOTION",
        "ONE_WAY_PROMOTION", "SUMMER_SALE", "WINTER_SALE", "BLACK_FRIDAY",
        "CYBER_MONDAY",
    ):
        assert campaign_kind_for(slug) == "CAMPAIGN", slug


def test_mechanism_channel_and_audience_offers_are_promotions():
    for slug in (
        "STUDENT_PROMOTION", "FAMILY_PROMOTION", "CORPORATE_PROMOTION",
        "PARTNER_PROMOTION", "LOYALTY_PROMOTION", "MILES_PROMOTION",
        "ANCILLARY_PROMOTION", "BAGGAGE_PROMOTION", "DESTINATION_PROMOTION",
        "NEW_ROUTE_PROMOTION",
    ):
        assert campaign_kind_for(slug) == "PROMOTION", slug


def test_an_unnameable_offer_gets_no_kind_rather_than_a_guess():
    # OTHER and null both mean "we could not name this offer", which is not
    # evidence for either bucket.
    assert campaign_kind_for("OTHER") is None
    assert campaign_kind_for(None) is None
    assert campaign_kind_for("MEGA_SALE") is None


def test_a_promo_code_only_decides_the_kind_when_the_type_did_not():
    # A code you have to type is a mechanism...
    assert campaign_kind_for(None, promo_code="FLY30") == "PROMOTION"
    assert campaign_kind_for("OTHER", sales_channel="mobil uygulama") == "PROMOTION"
    # ...but a flash sale with a code on it is still a price move.
    assert campaign_kind_for("FLASH_SALE", promo_code="FLY30") == "CAMPAIGN"


def test_the_migrations_frozen_snapshot_matches_the_live_table_today():
    """History is frozen on purpose, so this is not a "must never differ"
    assertion -- it is a note to whoever changes the mapping that the rows
    already in the database were written from the snapshot, and that
    `backfill-campaign-kind` is what reconciles them."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "c4f18a2b7d31_campaign_kind_and_explicit_date_windows.py"
    )
    spec = importlib.util.spec_from_file_location("_kind_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    frozen = {
        slug: kind
        for kind, slugs in migration._CAMPAIGN_TYPES.items()
        for slug in slugs
    }
    assert frozen == CAMPAIGN_TYPE_TO_KIND


# --- the ticketing and campaign windows -------------------------------------


def _item(**kwargs) -> RawCampaignItem:
    return RawCampaignItem.model_validate({"campaign_name": "Test", **kwargs})


def test_the_schema_accepts_all_eight_date_edges():
    assert DATE_FIELDS == (
        "booking_start", "booking_end", "travel_start", "travel_end",
        "ticketing_start", "ticketing_end", "campaign_start", "campaign_end",
    )


def test_an_explicitly_stated_ticketing_window_is_kept():
    page = (
        "Kampanya dönemi 1 Eylül 2026 - 15 Eylül 2026. "
        "Biletlemenin 20 Eylül 2026 tarihine kadar tamamlanması gerekmektedir. "
        "Seyahat 1 Ekim 2026 - 31 Aralık 2026."
    )
    item = _item(
        booking_start="2026-09-01",
        booking_end="2026-09-15",
        ticketing_end="2026-09-20",
        campaign_start="2026-09-01",
        campaign_end="2026-09-15",
        source_text={
            "booking_end": "Kampanya dönemi 1 Eylül 2026 - 15 Eylül 2026",
            "ticketing_end": "Biletlemenin 20 Eylül 2026 tarihine kadar",
        },
    )
    verdict = verify_dates(item, page, default_year=2026)
    assert verdict.values["ticketing_end"] == date(2026, 9, 20)
    assert verdict.values["campaign_end"] == date(2026, 9, 15)
    assert verdict.values["booking_end"] == date(2026, 9, 15)


def test_a_page_with_one_window_fills_only_the_sale_window():
    """The rule the whole four-column addition rests on: nothing is copied
    across. A ticketing deadline nobody stated must stay NULL rather than
    inheriting the booking deadline."""
    page = "Son rezervasyon 15 Eylül 2026. Hemen alın."
    item = _item(booking_end="2026-09-15", source_text={"booking_end": "Son rezervasyon 15 Eylül 2026"})
    verdict = verify_dates(item, page, default_year=2026)
    assert verdict.values["booking_end"] == date(2026, 9, 15)
    for name in ("ticketing_start", "ticketing_end", "campaign_start", "campaign_end"):
        assert verdict.values.get(name) is None


def test_an_uncorroborated_ticketing_date_is_dropped_like_any_other():
    # The new columns get no special trust: a date the page does not carry is
    # rejected and recorded as rejected.
    page = "Son rezervasyon 15 Eylül 2026."
    item = _item(booking_end="2026-09-15", ticketing_end="2026-10-30")
    verdict = verify_dates(item, page, default_year=2026)
    assert verdict.values["ticketing_end"] is None
    assert verdict.evidence["ticketing_end"]["rejected_value"] == "2026-10-30"


def test_a_reversed_ticketing_window_loses_both_ends():
    page = "Biletleme 20 Eylül 2026 ile 10 Eylül 2026 arasında."
    item = _item(ticketing_start="2026-09-20", ticketing_end="2026-09-10")
    verdict = verify_dates(item, page, default_year=2026)
    assert verdict.values["ticketing_start"] is None
    assert verdict.values["ticketing_end"] is None


def test_date_flags_record_which_edges_the_page_actually_stated():
    page = "Son rezervasyon 15 Eylül 2026. Biletleme 20 Eylül 2026 tarihine kadar."
    item = _item(booking_end="2026-09-15", ticketing_end="2026-09-20")
    verdict = verify_dates(item, page, default_year=2026)
    assert verdict.flags["explicit_dates"] == ["booking_end", "ticketing_end"]


def test_a_page_that_states_nothing_gets_no_explicit_flag():
    verdict = verify_dates(_item(), "Fırsatı kaçırma!", default_year=2026)
    assert "explicit_dates" not in verdict.flags


# --- the ancillary rule, in both directions ---------------------------------


def test_an_ancillary_offer_tied_to_a_flight_purchase_is_published():
    outcome = validate_campaign(
        "Bilet Alana 10 kg Ekstra Bagaj",
        _campaign(),
        today=TODAY,
        text="Yurt dışı hatlarında bilet alana 10 kg ekstra bagaj ücretsiz.",
    )
    assert outcome.is_classified
    assert outcome.details["business_class"] == "ACTIVE_CAMPAIGN"
    assert outcome.details["campaign_type_override"] == "ANCILLARY_PROMOTION"


def test_the_english_wording_of_the_same_tie_also_passes():
    outcome = validate_campaign(
        "Complimentary Lounge Access",
        _campaign(),
        today=TODAY,
        text="Complimentary lounge access when you book a flight in Economy.",
    )
    assert outcome.is_classified
    assert outcome.details["campaign_type_override"] == "ANCILLARY_PROMOTION"


def test_a_standalone_lounge_campaign_is_still_rejected():
    outcome = validate_campaign(
        "Annual Lounge Membership 30% Off",
        _campaign(),
        today=TODAY,
        text="30 percent off the annual lounge membership fee.",
    )
    assert not outcome.is_classified
    assert outcome.details["business_class"] == "PRODUCT_PROMOTION"


def test_a_standalone_hotel_campaign_is_still_rejected():
    outcome = validate_campaign(
        "Otel Rezervasyonlarında %20 İndirim",
        _campaign(),
        today=TODAY,
        text="Konaklama platformunda yapılan otel rezervasyonlarında yüzde 20 indirim.",
    )
    assert not outcome.is_classified
    assert outcome.details["business_class"] == "PRODUCT_PROMOTION"


def test_a_car_rental_campaign_with_no_flight_condition_is_still_rejected():
    detected = detect_business_class(
        "Araç Kiralamada %25 İndirim",
        "Anlaşmalı araç kiralama firmalarında yüzde 25 indirim.",
        sale_starts=date(2026, 8, 25),
        sale_ends=date(2026, 9, 10),
    )
    assert detected is not None
    assert detected[0] == "PRODUCT_PROMOTION"


def test_the_tie_waives_the_product_rule_and_nothing_else():
    """A tied offer that is also about miles is still a loyalty promo. The
    exception was cut for ancillary revenue, not for the whole gate."""
    detected = detect_business_class(
        "Bilet Alana 5.000 Bonus Mil ve Ekstra Bagaj",
        "Bilet alana 5.000 bonus mil ve 10 kg ekstra bagaj.",
        sale_starts=date(2026, 8, 25),
        sale_ends=date(2026, 9, 10),
    )
    assert detected is not None
    assert detected[0] == "LOYALTY_PROMOTION"


def test_the_tie_needs_a_flight_word_not_just_a_purchase_word():
    # "rezervasyon yapana" is a purchase condition with no flight in it, which
    # is exactly how a hotel campaign words itself.
    assert ancillary_tie(fold_text("Otel rezervasyonu yapana ücretsiz kahvaltı")) is None
    assert ancillary_tie(fold_text("Bilet alana ücretsiz ekstra bagaj")) is not None


def test_a_plain_fare_campaign_is_never_relabelled_as_ancillary():
    """The gate on the override: there has to be an ancillary product in the
    copy for the question to arise at all, so a fare campaign that happens to
    say "bilet alana %30" keeps its own type."""
    outcome = validate_campaign(
        "Bilet Alana %30 İndirim",
        _campaign(),
        today=TODAY,
        text="Yurt dışı uçuşlarında bilet alana yüzde 30 indirim.",
    )
    assert outcome.is_classified
    assert outcome.details["campaign_type_override"] is None


def test_the_acceptance_reason_quotes_the_phrase_that_waived_the_rule():
    outcome = validate_campaign(
        "Bilet Alana Ücretsiz Koltuk Seçimi",
        _campaign(),
        today=TODAY,
        text="Bilet alana ücretsiz koltuk seçimi hakkı.",
    )
    reason = outcome.details["classification_reason"]
    assert "bilet alana" in reason
    assert "uçuş satın alımına bağlı" in reason


def test_an_expired_title_still_beats_the_tie():
    # Guard order is unchanged: the date guards run before the rulepacks, so a
    # tied ancillary offer with an [Expired] title is still not published.
    outcome = validate_campaign(
        "[Expired] Bilet Alana Ekstra Bagaj",
        _campaign(),
        today=TODAY,
        text="Bilet alana 10 kg ekstra bagaj.",
    )
    assert not outcome.is_classified
    assert outcome.reason == "expired_title"


# --- the official-verification ceiling --------------------------------------


def _input(**kwargs) -> ConfidenceInput:
    return ConfidenceInput(
        source_tier=kwargs.pop("source_tier", "official"),
        classifier_certainty=kwargs.pop("classifier_certainty", 1.0),
        required_fields_present=kwargs.pop("required_fields_present", 3),
        required_fields_total=kwargs.pop("required_fields_total", 3),
        signal_agreement=kwargs.pop("signal_agreement", 1.0),
        source_count=kwargs.pop("source_count", 1),
        **kwargs,
    )


def test_an_official_campaign_with_full_data_reaches_the_high_band():
    result = score(_input(official_verified=True))
    assert result.band == "high"
    assert result.official_verified is True


def test_an_unverified_campaign_is_capped_below_high_however_good_it_looks():
    result = score(
        _input(source_tier="agency", source_count=4, official_verified=False)
    )
    assert result.score <= UNVERIFIED_SCORE_CEILING
    assert result.band == "medium"


def test_corroboration_cannot_buy_a_way_past_the_ceiling():
    """Four aggregators agreeing is still four aggregators."""
    one = score(_input(source_tier="aggregator", source_count=1, official_verified=False))
    many = score(_input(source_tier="aggregator", source_count=9, official_verified=False))
    assert many.score <= UNVERIFIED_SCORE_CEILING
    assert many.band != "high"
    assert many.score >= one.score


def test_a_caller_that_never_asked_the_question_gets_no_ceiling():
    """Every caller outside the campaign surface passes None, and nothing that
    scored 0.90 before may silently drop to 0.74 because a field defaulted."""
    assert score(_input()).band == "high"
    assert score(_input()).official_verified is None
    assert "official_verified" not in score(_input()).as_detail()


def test_the_ceiling_survives_a_rescore():
    from app.pipeline.confidence import rescore_with_corroboration

    capped = score(_input(source_tier="agency", official_verified=False))
    again = rescore_with_corroboration(capped.as_detail(), source_count=4)
    assert again is not None
    assert again.score <= UNVERIFIED_SCORE_CEILING


def test_a_rescore_can_lift_the_ceiling_when_the_carrier_turns_up():
    from app.pipeline.confidence import rescore_with_corroboration

    capped = score(_input(source_tier="agency", official_verified=False))
    lifted = rescore_with_corroboration(
        capped.as_detail(), source_count=2, official_verified=True
    )
    assert lifted is not None
    assert lifted.score > UNVERIFIED_SCORE_CEILING
