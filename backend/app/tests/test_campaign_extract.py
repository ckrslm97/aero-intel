"""The extraction chain, with the model canned.

Every LLM answer here is a literal dict written into the test, for the same
reason app/tests/test_pipeline_v2_runner.py records its outcomes: CI must not
depend on a model being reachable, and -- more to the point -- the cases worth
testing are the ones where the model is WRONG. A live model cannot be asked to
hallucinate a date on demand; a canned one can, and that is the case the whole
date-validation layer exists for.

The page text is EK-shaped because Emirates is the one carrier a real Chromium
verifiably reaches (app/ingest/carriers.py), so it is the text this chain will
actually be fed. Nothing here assumes TK's page is fetchable.
"""
import json
from datetime import date, datetime, timezone

import pytest

from app.ingest.carriers import CARRIER_MASTER
from app.pipeline.campaign_extract import (
    campaign_url,
    extract_campaigns_from_page,
    named_airlines,
    resolve_route,
    slugify_campaign,
)
from app.schemas.campaign import (
    RawCampaignItem,
    extract_campaign_json,
    parse_campaign_payload,
)

EK = CARRIER_MASTER["EK"]
NOW = datetime(2026, 8, 28, 5, 0, tzinfo=timezone.utc)
TODAY = date(2026, 8, 28)
PAGE_URL = "https://www.emirates.com/tr/english/special-offers/"

EK_PAGE = (
    "Summer fares to Europe. "
    "Save up to 25% on Economy Class fares from DXB to LHR. "
    "Book by 15 September 2026. Travel between 1 October 2026 and 30 November 2026. "
    "Promo code SUMMER25. Book now on emirates.com. "
    "Dubai to Istanbul offer. Return fares from 1200 AED. "
    "Book by 20 September 2026 for travel until 15 December 2026."
)

TR_PAGE = (
    "Sonbahar fırsatı. Yurt dışı uçuşlarda %20 indirim. "
    "Son rezervasyon 30 Kasım'a kadar. Hemen rezervasyon yapın."
)


def _generator(payload):
    """A stand-in for the raw completion coroutine, returning canned JSON."""

    async def generate(_prompt: str) -> str:
        return payload if isinstance(payload, str) else json.dumps(payload)

    return generate


SUMMER = {
    "campaign_name": "Summer fares to Europe",
    "campaign_type": "SUMMER_SALE",
    "is_fare_campaign": True,
    "business_class_hint": "ACTIVE_CAMPAIGN",
    "booking_end": "2026-09-15",
    "travel_start": "2026-10-01",
    "travel_end": "2026-11-30",
    "discount_pct": 25,
    "promo_code": "SUMMER25",
    "cabin": "Economy",
    "origin": "DXB",
    "destination": "LHR",
    "source_text": {
        "booking_end": "Book by 15 September 2026.",
        "travel_start": "Travel between 1 October 2026 and 30 November 2026.",
        "travel_end": "Travel between 1 October 2026 and 30 November 2026.",
        "discount_pct": "Save up to 25% on Economy Class fares",
        "origin": "from DXB to LHR",
        "destination": "from DXB to LHR",
    },
}

ISTANBUL = {
    "campaign_name": "Dubai to Istanbul offer",
    "campaign_type": "DESTINATION_PROMOTION",
    "is_fare_campaign": True,
    "booking_end": "2026-09-20",
    "travel_end": "2026-12-15",
    "price_floor": 1200,
    "currency": "AED",
    "origin": "Dubai",
    "destination": "Istanbul",
    "source_text": {
        "booking_end": "Book by 20 September 2026",
        "travel_end": "for travel until 15 December 2026",
        "price_floor": "Return fares from 1200 AED",
        "origin": "Dubai to Istanbul offer",
        "destination": "Dubai to Istanbul offer",
    },
}


async def _extract(payload, *, text=EK_PAGE, carrier=EK):
    return await extract_campaigns_from_page(
        text,
        carrier=carrier,
        page_url=PAGE_URL,
        source_quality=carrier.source_quality,
        detected_at=NOW,
        today=TODAY,
        content_hash="a" * 64,
        generate=_generator(payload),
    )


# --- the happy path -------------------------------------------------------


async def test_two_campaigns_on_one_page_become_two_validated_records():
    """The shape the article prompt cannot express: one document, N campaigns."""
    result = await _extract({"campaigns": [SUMMER, ISTANBUL]})

    assert result.succeeded is True
    assert result.count == 2
    first, second = result.campaigns

    assert first.campaign_name == "Summer fares to Europe"
    assert first.campaign_type == "SUMMER_SALE"
    assert first.business_class == "ACTIVE_CAMPAIGN"
    assert first.discount_pct == 25
    assert first.sale_ends == date(2026, 9, 15)
    assert (first.travel_starts, first.travel_ends) == (date(2026, 10, 1), date(2026, 11, 30))
    assert first.sale_starts is None, "the page states no booking start; nothing invents one"

    # Route: two airport codes is the only shape that earns an OND.
    assert first.route.scope == "OND"
    assert first.route.ond == "DXB-LHR"
    assert (first.route.origin_code, first.route.dest_code) == ("DXB", "LHR")

    # Cities, not codes: "Dubai to Istanbul" says nothing about which airport.
    assert second.route.scope == "CITY_PAIR"
    assert second.route.ond is None
    assert second.route.origin_code is None


async def test_every_published_field_carries_the_quote_it_came_from():
    result = await _extract({"campaigns": [SUMMER]})
    evidence = result.campaigns[0].evidence_json

    assert evidence["booking_end"]["value"] == "2026-09-15"
    assert evidence["booking_end"]["source_text"] == "Book by 15 September 2026."
    assert evidence["booking_end"]["confidence"] == 1.0
    assert evidence["discount_pct"]["value"] == 25
    assert "25%" in evidence["discount_pct"]["source_text"]


async def test_a_fully_quoted_fully_dated_official_campaign_needs_no_review():
    result = await _extract({"campaigns": [SUMMER]})
    campaign = result.campaigns[0]

    assert campaign.confidence_band == "high"
    assert campaign.review_required is False
    # The dormant weight, awake: three dates checked, three found.
    assert campaign.confidence_detail["components"]["signal_agreement"] == 1.0


async def test_the_classification_reason_says_what_was_verified():
    result = await _extract({"campaigns": [SUMMER]})
    reason = result.campaigns[0].classification_reason

    assert "3/3 tarih" in reason
    assert "OND" in reason


# --- date validation ------------------------------------------------------


async def test_a_date_that_is_nowhere_on_the_page_is_not_published():
    """The hallucination case. The model returns a plausible deadline the page
    never states; the regex layer cannot find it in the quote or anywhere else,
    so it does not reach the column -- but it is recorded, because a rejection
    nobody can see is indistinguishable from a field that was never asked
    about."""
    invented = {**SUMMER, "booking_end": "2026-09-30"}
    invented["source_text"] = {**SUMMER["source_text"], "booking_end": "Book now"}

    result = await _extract({"campaigns": [invented]})
    campaign = result.campaigns[0]

    assert campaign.sale_ends is None
    evidence = campaign.evidence_json["booking_end"]
    assert evidence["value"] is None
    assert evidence["rejected_value"] == "2026-09-30"
    assert evidence["confidence"] == 0.0
    # Two of three dates confirmed drags the score, and the row is queued for
    # a human rather than published as if nothing happened.
    assert campaign.confidence_detail["components"]["signal_agreement"] == pytest.approx(
        2 / 3, abs=1e-4
    )


async def test_a_year_less_date_is_resolved_and_flagged_never_silently_completed():
    yearless = {
        "campaign_name": "Sonbahar fırsatı",
        "campaign_type": "SEASONAL_PROMOTION",
        "is_fare_campaign": True,
        "discount_pct": 20,
        "date_text": {"booking_end": "30 Kasım'a kadar"},
        "destination": "Avrupa",
        "source_text": {
            "discount_pct": "Yurt dışı uçuşlarda %20 indirim",
            "destination": "Yurt dışı uçuşlarda",
        },
    }

    result = await _extract({"campaigns": [yearless]}, text=TR_PAGE)
    campaign = result.campaigns[0]

    assert campaign.sale_ends == date(2026, 11, 30), "completed from the scan year"
    assert campaign.date_flags_json["inferred_year"] is True
    assert campaign.date_flags_json["inferred_year_fields"] == ["booking_end"]
    assert campaign.evidence_json["booking_end"]["inferred_year"] is True
    assert "yıl sayfada yazmadığı" in campaign.classification_reason


async def test_a_quote_the_page_does_not_contain_resolves_to_nothing():
    """A `date_text` is supposed to be verbatim. One that is not is either a
    paraphrase or an invention, and neither is a date."""
    fabricated = {
        "campaign_name": "Sonbahar fırsatı",
        "is_fare_campaign": True,
        "discount_pct": 20,
        "date_text": {"booking_end": "31 Aralık'a kadar"},
        "source_text": {"discount_pct": "%20 indirim"},
    }

    result = await _extract({"campaigns": [fabricated]}, text=TR_PAGE)
    campaign = result.campaigns[0]

    assert campaign.sale_ends is None
    assert campaign.evidence_json["booking_end"]["note"].startswith("Alıntı")


async def test_a_window_that_ends_before_it_starts_loses_both_ends():
    reversed_window = {
        **SUMMER,
        "travel_start": "2026-11-30",
        "travel_end": "2026-10-01",
    }
    result = await _extract({"campaigns": [reversed_window]})
    campaign = result.campaigns[0]

    assert campaign.travel_starts is None
    assert campaign.travel_ends is None
    assert "ters" in campaign.evidence_json["travel_end"]["note"]


# --- entity validation ----------------------------------------------------


async def test_a_partner_carriers_offer_on_our_page_is_not_our_campaign():
    """Attribution is the error this whole rebuild started from: a campaign
    filed under the wrong airline is a competitor's move on the wrong desk."""
    partner = {
        **SUMMER,
        "campaign_name": "Qatar Airways ortak kampanyası",
    }
    result = await _extract({"campaigns": [partner]})

    assert result.count == 0
    assert result.dropped == (("Qatar Airways ortak kampanyası", "airline_mismatch:QR"),)


async def test_a_campaign_naming_both_carriers_stays_with_the_page_it_is_on():
    """A codeshare campaign names the partner AND us. Dropping it would lose a
    real campaign from the carrier whose own site published it."""
    codeshare = {
        **SUMMER,
        "campaign_name": "Emirates ve flydubai ortak kampanyası",
    }
    result = await _extract({"campaigns": [codeshare]})
    assert result.count == 1


def test_named_airlines_reads_the_gazetteer_not_a_substring():
    assert named_airlines("Emirates ve flydubai") == {"EK", "FZ"}
    assert named_airlines("Yaz indirimi") == set()


async def test_a_baggage_promotion_is_dropped_by_the_rule_layer():
    """Layer three. Not a fare campaign, however well-dated and well-quoted --
    this is the single largest category among the 129 wrong rows."""
    baggage = {
        "campaign_name": "Extra baggage offer",
        "campaign_type": "BAGGAGE_PROMOTION",
        "is_fare_campaign": False,
        "booking_end": "2026-09-15",
        "source_text": {"booking_end": "Book by 15 September 2026."},
    }
    result = await _extract({"campaigns": [baggage]})

    assert result.count == 0
    assert result.dropped[0][1] == "business_class:PRODUCT_PROMOTION"


async def test_one_rejected_card_does_not_cost_the_others_theirs():
    result = await _extract(
        {
            "campaigns": [
                SUMMER,
                {
                    "campaign_name": "Skywards miles sale",
                    "is_fare_campaign": False,
                    "source_text": {"booking_end": "Book by 15 September 2026."},
                    "booking_end": "2026-09-15",
                },
                ISTANBUL,
            ]
        }
    )
    assert result.count == 2
    assert len(result.dropped) == 1


# --- route resolution -----------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "destination", "text", "scope", "ond"),
    [
        ("IST", "LHR", "", "OND", "IST-LHR"),
        ("IST-LHR", None, "", "OND", "IST-LHR"),
        ("Istanbul", "London", "", "CITY_PAIR", None),
        ("İstanbul'dan", "Londra'ya", "", "CITY_PAIR", None),
        ("Türkiye", "Almanya", "", "COUNTRY", None),
        ("Türkiye'den", "Avrupa'ya", "", "REGION", None),
        (None, "Avrupa", "", "REGION", None),
        (None, None, "tüm uçuşlarda geçerli", "NETWORK_WIDE", None),
        (None, None, "valid on all destinations", "NETWORK_WIDE", None),
        (None, None, "", None, None),
        ("Nowhereville", "Elsewhereton", "", None, None),
    ],
)
def test_the_route_ladder(origin, destination, text, scope, ond):
    route = resolve_route(origin, destination, text=text)
    assert route.scope == scope
    assert route.ond == ond


def test_a_regional_campaign_is_never_fanned_out_into_invented_airport_pairs():
    """The most tempting wrong enrichment available here: "Türkiye'den
    Avrupa'ya" covers hundreds of city pairs and names none of them, and a row
    claiming IST-LHR would be a competitive claim the carrier never made."""
    route = resolve_route("Türkiye'den", "Avrupa'ya")

    assert route.scope == "REGION"
    assert route.ond is None
    assert route.origin_code is None
    assert route.dest_code is None
    assert route.as_json()["dest"] == {"kind": "region", "text": "Avrupa'ya", "region": "europe"}


def test_a_mixed_route_is_read_at_its_coarsest_end():
    """One airport and one region is a regional campaign that happens to state
    where it starts -- not an OND."""
    route = resolve_route("IST", "Avrupa")
    assert route.scope == "REGION"
    assert route.ond is None


def test_an_unresolvable_endpoint_is_recorded_rather_than_guessed():
    route = resolve_route("Zzzz City", "LHR")
    assert route.scope is None
    assert route.as_json()["origin"] == {"kind": "unknown", "text": "Zzzz City"}


def test_a_bare_code_that_is_also_a_word_needs_to_be_written_like_a_code():
    """`Aug` is a month and `AUG` is Augusta, Maine -- the same distinction
    llm/gazetteer.py's AMBIGUOUS_BARE_CODES draws for article bodies."""
    assert resolve_route("Aug", "LHR").as_json()["origin"]["kind"] == "unknown"
    assert resolve_route("AUG", "LHR").as_json()["origin"]["kind"] == "airport"


# --- failure handling -----------------------------------------------------


async def test_unparseable_json_fails_the_page_and_writes_nothing():
    """FAILED never falls back. A whole official page guessed at by keyword
    matching is the failure this rebuild exists to end."""
    result = await _extract("I could not find any campaigns, sorry!")

    assert result.succeeded is False
    assert result.reason.startswith("schema_error")
    assert result.count == 0


async def test_a_campaigns_key_that_is_not_a_container_is_a_failed_page():
    """`{"campaigns": {"campaign_name": ...}}` used to be here too. It is the
    campaigns key holding the one campaign instead of a list of one, which is
    an envelope difference rather than a wrong answer, and it is now read (see
    the schema-layer tests). A value that holds no campaign at all still is
    not one."""
    result = await _extract({"campaigns": "Yaz indirimi"})
    assert result.succeeded is False


# --- the shapes a real model actually answers in --------------------------
#
# The first Azure run of the deep scan got HTTP 200 out of turkishairlines.com
# through the impersonated fetch, called the model, and then threw the whole
# page away with `schema_error:campaign payload must be a JSON object`. The
# campaigns were in the answer; the envelope was not. Each of these is a
# wrapper a model puts around the right answer, and none of them is a reason to
# re-fetch a carrier's page twice a day forever.


async def test_a_bare_list_is_the_same_answer_with_the_envelope_left_off():
    result = await _extract(json.dumps([SUMMER, ISTANBUL]))

    assert result.succeeded is True
    assert [c.campaign_name for c in result.campaigns] == [
        "Summer fares to Europe",
        "Dubai to Istanbul offer",
    ]


async def test_a_fenced_json_block_is_read_not_failed():
    result = await _extract(f"```json\n{json.dumps({'campaigns': [SUMMER]})}\n```")

    assert result.succeeded is True
    assert result.count == 1


async def test_a_fenced_bare_list_is_read_too():
    result = await _extract(f"```\n{json.dumps([SUMMER])}\n```")

    assert result.succeeded is True
    assert result.count == 1


async def test_prose_around_the_json_does_not_cost_the_page():
    result = await _extract(
        "Sayfada iki kampanya buldum, JSON olarak veriyorum:\n"
        f"{json.dumps({'campaigns': [SUMMER, ISTANBUL]})}\n"
        "Başka bir kampanya göremedim."
    )

    assert result.succeeded is True
    assert result.count == 2


async def test_prose_before_a_bare_list_still_finds_the_list():
    """The preamble carries a `{` of its own -- the brace that opens first is
    not the JSON, and picking it would be the failure this test is named for."""
    result = await _extract(
        'Cevap şu biçimde {"kampanya": ...} değil, düz liste olarak:\n'
        f"{json.dumps([SUMMER])}"
    )

    assert result.succeeded is True
    assert result.count == 1


async def test_an_empty_bare_list_is_an_empty_page_not_a_failure():
    """`[]` says exactly what `{"campaigns": []}` says. Failing it would keep
    the page queued and re-ask a settled question on every scan."""
    result = await _extract("[]")

    assert result.succeeded is True
    assert result.count == 0


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "Bu sayfada kampanya yok.",
        "```json\n{\"campaigns\": [\n```",  # fenced and truncated mid-answer
        "<html><body>Access denied</body></html>",
    ],
)
def test_text_with_no_json_in_it_is_still_nothing(raw):
    """The leniency is about wrappers, not about guessing. Anything that is not
    JSON comes back None and fails the page."""
    assert extract_campaign_json(raw) is None


def test_a_clean_object_is_read_whole_rather_than_out_of_a_slice():
    payload = extract_campaign_json(json.dumps({"campaigns": [], "note": "yok"}))
    assert payload == {"campaigns": [], "note": "yok"}


async def test_no_model_configured_is_a_failed_page_not_a_heuristic_pass(monkeypatch):
    monkeypatch.setattr("app.llm.factory.get_raw_generator", lambda **_: None)
    result = await extract_campaigns_from_page(
        EK_PAGE,
        carrier=EK,
        page_url=PAGE_URL,
        detected_at=NOW,
        today=TODAY,
    )
    assert result.succeeded is False
    assert result.reason == "no_llm_configured"
    assert result.llm_calls == 0


async def test_a_provider_error_is_a_failed_page():
    async def explode(_prompt):
        raise RuntimeError("groq is down")

    result = await extract_campaigns_from_page(
        EK_PAGE,
        carrier=EK,
        page_url=PAGE_URL,
        detected_at=NOW,
        today=TODAY,
        generate=explode,
    )
    assert result.succeeded is False
    assert result.reason == "llm_call_error"


async def test_an_empty_page_is_a_successful_answer_not_a_failure():
    """A carrier between campaigns must not be retried twice a day forever."""
    result = await _extract({"campaigns": []})
    assert result.succeeded is True
    assert result.count == 0


# --- the idempotency key --------------------------------------------------


async def test_each_campaign_on_a_shared_page_gets_its_own_stable_url():
    result = await _extract({"campaigns": [SUMMER, ISTANBUL]})
    urls = [c.url for c in result.campaigns]

    assert len(set(urls)) == 2, "promotions.url is UNIQUE; one page is not one campaign"
    assert all(url.startswith(PAGE_URL + "#") for url in urls)
    # Stable across runs: the same campaign name is the same row, not a new one
    # on every scan.
    assert campaign_url(PAGE_URL, SUMMER["campaign_name"]) == urls[0]


def test_the_fragment_survives_turkish_and_punctuation():
    assert slugify_campaign("Yaz İndirimi %40'a varan!") == "yaz-indirimi-40-a-varan"
    assert slugify_campaign("") == "kampanya"


# --- schema layer ---------------------------------------------------------


def test_an_off_taxonomy_slug_is_dropped_and_recorded_not_raised():
    item = RawCampaignItem.model_validate(
        {"campaign_name": "Mega sale", "campaign_type": "MEGA_SALE"}
    )
    assert item.campaign_type is None
    assert item.dropped_fields == ["campaign_type:MEGA_SALE"]


@pytest.mark.parametrize("value", [0, 130, "çok", None, True])
def test_an_out_of_range_discount_is_missing_data(value):
    item = RawCampaignItem.model_validate({"campaign_name": "X", "discount_pct": value})
    assert item.discount_pct is None


def test_a_price_floor_without_a_currency_is_not_a_price():
    item = RawCampaignItem.model_validate(
        {"campaign_name": "X", "price_floor": 199, "currency": None}
    )
    assert item.price_floor is None
    assert item.dropped_fields == ["price_floor:no_currency"]


def test_a_date_that_is_not_iso_becomes_date_text_for_the_regex_layer():
    item = RawCampaignItem.model_validate(
        {"campaign_name": "X", "booking_end": "30 Kasım"}
    )
    assert item.booking_end is None
    assert item.date_text["booking_end"] == "30 Kasım"


def test_the_model_writing_the_word_null_is_still_null():
    item = RawCampaignItem.model_validate(
        {"campaign_name": "X", "promo_code": "yok", "cabin": "null"}
    )
    assert item.promo_code is None
    assert item.cabin is None


def test_a_nameless_card_is_dropped_without_costing_the_page():
    page = parse_campaign_payload(
        {"campaigns": [{"campaign_name": "Yaz"}, {"discount_pct": 40}, "not an object"]}
    )
    assert [c.campaign_name for c in page.campaigns] == ["Yaz"]
    assert page.invalid_items == 2


@pytest.mark.parametrize(
    "payload", [None, "Yaz", 42, {"items": []}, {"campaigns": "Yaz"}]
)
def test_a_malformed_payload_raises_rather_than_being_half_believed(payload):
    with pytest.raises(ValueError):
        parse_campaign_payload(payload)


def test_a_bare_list_is_wrapped_rather_than_refused():
    """`[]` used to be in the list above. It is not malformed -- it is the
    campaigns, unwrapped -- and the parser now says so; the prompt still asks
    for the object shape."""
    assert parse_campaign_payload([]).campaigns == []
    page = parse_campaign_payload([{"campaign_name": "Yaz"}, {"discount_pct": 40}])
    assert [c.campaign_name for c in page.campaigns] == ["Yaz"]
    assert page.invalid_items == 1


def test_a_single_campaign_written_without_the_envelope_is_read_as_one():
    """Same leniency as the bare list, one campaign further in: the model
    answered the question and skipped the wrapper."""
    page = parse_campaign_payload({**SUMMER})

    assert [c.campaign_name for c in page.campaigns] == ["Summer fares to Europe"]


def test_campaigns_written_as_a_map_is_read_as_the_list_in_its_own_order():
    page = parse_campaign_payload({"campaigns": {"1": SUMMER, "2": ISTANBUL}})

    assert [c.campaign_name for c in page.campaigns] == [
        "Summer fares to Europe",
        "Dubai to Istanbul offer",
    ]
    # And the single-campaign-as-the-value shape.
    assert parse_campaign_payload({"campaigns": SUMMER}).campaigns[0].discount_pct == 25


@pytest.mark.parametrize("payload", [{"campaigns": {}}, {"campaigns": {"a": "Yaz"}}])
def test_a_map_with_no_campaigns_in_it_still_fails_the_page(payload):
    """The envelope is forgiven; the answer is not. An object that carries no
    campaign object is not a page with no campaigns on it."""
    with pytest.raises(ValueError):
        parse_campaign_payload(payload)


# --- the cut-off answer ---------------------------------------------------


def _truncated(*items) -> str:
    """The shape a cut-off answer actually has: a valid opening, whole cards,
    and a last one that stops mid-field with nothing closed after it."""
    body = ",\n".join(json.dumps(item, ensure_ascii=False) for item in items)
    return '{\n"campaigns": [\n' + body + ',\n  {\n    "campaign_name": "Kış fırs'


def test_a_cut_off_answer_keeps_the_cards_that_were_finished():
    payload = extract_campaign_json(_truncated(SUMMER, ISTANBUL))

    assert isinstance(payload, dict)
    page = parse_campaign_payload(payload)
    assert [c.campaign_name for c in page.campaigns] == [
        "Summer fares to Europe",
        "Dubai to Istanbul offer",
    ]
    assert page.truncated is True, "the caller has to be able to log why this happened"
    # The half-written card is dropped, never completed: it is not counted as
    # an item that failed validation either, because it was never an item.
    assert page.invalid_items == 0


async def test_a_cut_off_page_publishes_the_campaigns_that_survived():
    """The production failure, end to end: a fetched page, a spent call and
    two real campaigns used to be lost to a missing closing brace."""
    result = await _extract(_truncated(SUMMER, ISTANBUL))

    assert result.succeeded is True
    assert result.count == 2


def test_a_truncation_that_finished_nothing_is_still_a_failed_page():
    """The opposite fact from an empty page. `{"campaigns": [` says the model
    was interrupted before it said anything, and reading that as "no campaigns"
    would baseline the page and stop asking."""
    assert extract_campaign_json('{\n"campaigns": [\n  {\n    "campaign_name": "Kış') is None


async def test_a_page_with_no_json_in_the_answer_says_so_in_its_reason():
    result = await _extract("Bu sayfada kampanya bulunmuyor, yardımcı olabildiysem ne mutlu.")

    assert result.succeeded is False
    assert result.reason == "schema_error:no_json_in_response"


async def test_an_unreadable_but_json_shaped_answer_is_named_as_a_truncation():
    """The reason the log used to give -- "payload must be a JSON object" --
    about a response whose first character is `{`. It is now named for what it
    is, so the next occurrence points at the output ceiling."""
    result = await _extract('{"campaigns": [{"campaign_name": "Kış fırs')

    assert result.succeeded is False
    assert result.reason == "schema_error:truncated_response"


async def test_the_campaign_call_raises_its_own_output_ceiling(monkeypatch):
    """A one-argument coroutine either way -- the whole chain injects
    `generate` -- but the campaign call's is bound to a ceiling, because its
    answer is a document and the provider default cut one off in production."""
    from app.llm import factory
    from app.pipeline.campaign_extract import CAMPAIGN_MAX_OUTPUT_TOKENS

    seen: dict = {}

    class _Provider:
        name = "fake"

        async def _generate(self, prompt: str, *, max_tokens: int | None = None) -> str:
            seen["max_tokens"] = max_tokens
            return "{}"

    monkeypatch.setattr(factory, "get_llm_provider", lambda: _Provider())

    assert CAMPAIGN_MAX_OUTPUT_TOKENS > 3072, "the ceiling the production answer hit"
    generate = factory.get_raw_generator(max_output_tokens=CAMPAIGN_MAX_OUTPUT_TOKENS)

    assert await generate("selam") == "{}"
    assert seen["max_tokens"] == CAMPAIGN_MAX_OUTPUT_TOKENS


def test_a_generator_that_cannot_take_a_ceiling_is_returned_unchanged(monkeypatch):
    """Ollama's completion call has no such parameter; wrapping it in one would
    turn a working local model into a TypeError on every campaign page."""
    from app.llm import factory

    class _Provider:
        name = "ollama"

        async def _generate(self, prompt: str) -> str:
            return "{}"

    provider = _Provider()
    monkeypatch.setattr(factory, "get_llm_provider", lambda: provider)

    assert factory.get_raw_generator(max_output_tokens=5000) == provider._generate


# --- the prompt -----------------------------------------------------------


def test_the_page_prompt_states_the_taxonomy_it_will_be_graded_against():
    """A model cannot answer inside a closed set it was never shown -- and the
    schema layer drops anything outside it, so an un-interpolated prompt would
    lose every campaign_type silently."""
    from app.llm.campaign_prompt import build_campaign_page_prompt
    from app.taxonomy import CAMPAIGN_TYPES, ROUTE_SCOPES

    prompt = build_campaign_page_prompt("EK", "Emirates", PAGE_URL, EK_PAGE)

    assert "Emirates (EK)" in prompt
    assert PAGE_URL in prompt
    assert all(slug in prompt for slug in CAMPAIGN_TYPES)
    assert all(slug in prompt for slug in ROUTE_SCOPES)
    assert "campaigns" in prompt and "source_text" in prompt
    # The two rules the whole chain depends on the model following.
    assert "date_text" in prompt
    assert "Yıl TAHMİN ETME" in prompt


def test_a_long_page_is_cut_with_a_marker_rather_than_silently():
    """A truncated last card reads as a campaign with missing fields; saying
    the text was cut is what stops half a card being extracted as a whole one."""
    from app.llm.campaign_prompt import MAX_PAGE_CHARS, TRUNCATION_MARKER, build_campaign_page_prompt

    prompt = build_campaign_page_prompt("EK", "Emirates", PAGE_URL, "kampanya " * 5000)

    assert TRUNCATION_MARKER in prompt
    body = prompt[prompt.index("SAYFA METNİ:") :]
    assert len(body) <= MAX_PAGE_CHARS + len(TRUNCATION_MARKER) + 40, (
        "the cap is on the page text, whatever the rules above it cost"
    )


def test_the_article_prompt_is_unchanged_until_the_fragment_is_passed():
    """The golden set grades the current article prompt; a silently widened
    one would change every answer it grades."""
    from app.llm.classify_prompt import build_prompt, campaign_topic_fragment

    plain = build_prompt("Başlık", "Metin")
    assert "business_class_hint" not in plain

    widened = build_prompt("Başlık", "Metin", topic_fragment=campaign_topic_fragment())
    assert "business_class_hint" in widened
    assert "KONUYA ÖZEL KURALLAR" in widened
