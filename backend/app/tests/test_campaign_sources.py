"""The three browserless carrier sources, tested without touching a network.

Same contract as test_deep_scan.py: CI has no route to any of these origins --
that is the whole reason the modules exist -- so every fixture here is a
trimmed copy of a real response captured on 2026-08-30, and every fetch is
either injected or mocked. What is testable, and what actually decides whether
a row gets published, is the half between the bytes and the campaign:

  * `fetch.impersonated_get` -- that a failure becomes a result rather than an
    exception, and that a missing curl_cffi degrades instead of crashing.
  * TK -- the card parse (and that the obvious selector finds eight empty
    divs), plus the pre-chain filter that keeps Holidays packages out of a
    prompt that would only drop them later anyway.
  * AJet -- i18n key resolution, the active-only filter, and the fact that the
    evergreen-discount template is never even requested.
  * SQ -- the fare-deal mapping, including the two ends being real IATA codes,
    which is what makes `resolve_route` return OND instead of guessing, and the
    title shape that keeps two different routes from deduping into one row.
  * The structured builder both feed into, including the two-day ticketing
    window that the general date parser reads as one day.
"""
import json
from datetime import date, datetime, timezone

import pytest

from app.ingest import ajet_campaigns, sq_campaigns, tk_campaigns
from app.ingest.carriers import CARRIER_MASTER
from app.ingest.fetch import FetchResult, impersonated_get
from app.pipeline.campaign_extract import (
    StructuredCampaign,
    build_structured_campaign,
    parse_window,
)

NOW = datetime(2026, 8, 30, 5, 0, tzinfo=timezone.utc)
TODAY = date(2026, 8, 30)


# --- the impersonating fetch layer -------------------------------------------


class _FakeResponse:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status


class _FakeSession:
    """Stands in for curl_cffi.requests.AsyncSession. Records what it was asked."""

    def __init__(self, response=None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._error is not None:
            raise self._error
        return self._response


async def test_an_impersonated_get_asks_for_chromes_fingerprint():
    """The single reason this dependency exists. A GET that forgets to
    impersonate is an httpx GET with extra steps, and TK answers it with a
    stream reset."""
    session = _FakeSession(_FakeResponse("<html>kampanyalar</html>"))
    result = await impersonated_get(
        "https://www.turkishairlines.com/tr-tr/kampanyalar/", session_factory=lambda: session
    )

    assert result.http_status == 200
    assert result.text == "<html>kampanyalar</html>"
    (url, kwargs), = session.calls
    assert url.endswith("/kampanyalar/")
    assert kwargs["impersonate"] == "chrome"
    assert kwargs["allow_redirects"] is True


async def test_a_403_comes_back_as_a_result_not_an_exception():
    """`classify_outcome` is the only place that decides what a status means,
    so the fetch layer must hand it the status rather than raising on it."""
    session = _FakeSession(_FakeResponse("Access Denied", status=403))
    result = await impersonated_get("https://www.etihad.com/en/offers", session_factory=lambda: session)

    assert result.http_status == 403
    assert result.error is None


async def test_a_transport_failure_becomes_a_recordable_row():
    session = _FakeSession(error=ConnectionResetError("Connection reset by peer"))
    result = await impersonated_get("https://tk.example", session_factory=lambda: session)

    assert result.text is None
    assert "ConnectionResetError" in result.error
    assert result.timed_out is False


async def test_a_hang_is_flagged_as_a_timeout_by_name_not_by_type():
    """curl_cffi may not be installed, so its exception classes cannot be named
    in an isinstance check -- the same reason deep_scan matches Playwright's
    TimeoutError by name."""

    class RequestsTimeout(Exception):
        pass

    session = _FakeSession(error=RequestsTimeout("Operation timed out after 25000 ms"))
    result = await impersonated_get("https://tk.example", session_factory=lambda: session)

    assert result.timed_out is True


async def test_a_missing_curl_cffi_degrades_instead_of_crashing(monkeypatch):
    """Same contract as playwright in deep_scan: no binary here is a logged
    no-op, never an ImportError at module import time."""
    import builtins

    real_import = builtins.__import__

    def _refuse(name, *args, **kwargs):
        if name.startswith("curl_cffi"):
            raise ImportError("no wheel for this platform")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _refuse)
    result = await impersonated_get("https://tk.example")

    assert result.text is None
    assert "curl_cffi" in result.error


# --- Turkish Airlines: the campaign cards ------------------------------------

# Trimmed from the live response on 2026-08-30, structure preserved exactly --
# including the empty `div.promotions` sub-block that makes the obvious
# selector return eight matches and zero campaigns.
TK_HTML = """
<html><body>
  <section class="hero"><h1>Uçuş Fırsatları</h1></section>
  <div class="row">
    <div class="col-12 dtable dinlinetable">
      <div class="promotions">
        <img class="img-fluid block" src="https://cdn.turkishairlines.com/asset/a.webp"/>
        <a class="btn btn-danger" href="https://www.turkishairlines.com/tr-tr/ucus-firsatlari-yurtici-ucak-bileti-kampanyasi">Detaylı bilgi</a>
      </div>
      <h3>Zafer Bayramı’nda yurt içi uçuşlar 1.449 TL’den başlayan fiyatlarla!</h3>
      <p>Biletinizi 30-31 Ağustos tarihlerinde alın, 24 Kasım 2026-20 Ocak 2027
         tarihleri arasında Türkiye’nin dört bir yanına uçun.</p>
    </div>
    <div class="col-12 dtable dinlinetable">
      <div class="promotions">
        <a class="btn btn-danger" href="https://www.turkishairlinesholidays.com/tr-tr/tatil-firsatlari">Detaylı bilgi</a>
      </div>
      <h3>Turkish Airlines Holidays ile Termal Tatil Paketlerine Özel 3 Kat Mil</h3>
    </div>
    <div class="col-12 dtable dinlinetable">
      <div class="promotions"><img src="https://cdn.turkishairlines.com/asset/b.webp"/></div>
    </div>
    <div class="col-12 dtable dinlinetable">
      <div class="promotions">
        <a class="btn btn-danger" href="https://www.turkishairlines.com/tr-tr/uygun-avrupa-ucak-bileti">Detaylı bilgi</a>
      </div>
      <h3>Avrupa’ya %25 indirim</h3>
      <p>Satış dönemi 1 Eylül 2026 - 10 Eylül 2026.</p>
      <p>Seyahat dönemi 1 Ekim 2026 - 30 Kasım 2026.</p>
    </div>
  </div>
</body></html>
"""


def test_the_campaign_blocks_are_read_title_and_all_paragraphs():
    blocks = tk_campaigns.parse_campaign_blocks(TK_HTML)

    assert [b.title for b in blocks] == [
        "Zafer Bayramı’nda yurt içi uçuşlar 1.449 TL’den başlayan fiyatlarla!",
        "Turkish Airlines Holidays ile Termal Tatil Paketlerine Özel 3 Kat Mil",
        "Avrupa’ya %25 indirim",
    ]
    # Both paragraphs, not just the first: TK splits the two windows across
    # them often enough that taking one would publish half the campaign.
    assert "Satış dönemi" in blocks[2].body
    assert "Seyahat dönemi" in blocks[2].body


def test_the_empty_promotions_subblock_is_not_mistaken_for_the_card():
    """Selecting `div.promotions` finds the image wrapper, which has no text at
    all -- eight matches and zero campaigns, which reads as "TK has no
    campaigns" rather than as a bug. The card is `div.dinlinetable`."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(TK_HTML, "html.parser")
    assert len(soup.select("div.promotions")) == 4
    assert not any(node.find("h3") for node in soup.select("div.promotions"))
    assert tk_campaigns.BLOCK_SELECTOR == "div.dinlinetable"


def test_the_detail_link_is_parsed_even_though_it_is_not_published_yet():
    blocks = tk_campaigns.parse_campaign_blocks(TK_HTML)

    assert blocks[0].detail_url.endswith("/tr-tr/ucus-firsatlari-yurtici-ucak-bileti-kampanyasi")


def test_a_block_with_no_heading_is_skipped_rather_than_filed_blank():
    assert len(tk_campaigns.parse_campaign_blocks(TK_HTML)) == 3


def test_holiday_and_loyalty_cards_are_dropped_before_the_prompt_sees_them():
    """The rulepack would drop them anyway. This is about what the page costs:
    every card that reaches the prompt is budget spent on a row that cannot
    survive two links later. TK's live hub mixes two Holidays package cards in
    with six fare campaigns, which is a quarter of the prompt."""
    text, found, kept = tk_campaigns.campaign_text(TK_HTML)

    assert (found, kept) == (3, 2)
    assert "Holidays" not in text
    assert "Zafer Bayramı" in text
    assert "Avrupa’ya %25 indirim" in text


def test_a_renamed_css_class_falls_back_to_the_body_not_to_silence():
    """The fallback is what lets classify_outcome tell a markup change
    (parse_error) from a challenge page (blocked). Returning "" for both would
    erase the distinction the carrier registry is maintained from."""
    text, found, kept = tk_campaigns.campaign_text(
        "<html><body><div class='campaigns'>Yurt içi uçuşlarda %30 indirim.</div></body></html>"
    )

    assert (found, kept) == (0, 0)
    assert "%30 indirim" in text


async def test_the_tk_fetch_hands_downstream_text_not_markup(monkeypatch):
    """Adding a fetch method must not add a branch to the scanner, so what
    comes back has to be the same shape the browser path produces."""

    async def _fake_get(url, **kwargs):
        return FetchResult(text=TK_HTML, http_status=200)

    monkeypatch.setattr(tk_campaigns, "impersonated_get", _fake_get)
    result = await tk_campaigns.fetch_campaign_page(
        "https://www.turkishairlines.com/tr-tr/kampanyalar/"
    )

    assert result.http_status == 200
    assert "<div" not in result.text
    assert "Zafer Bayramı" in result.text


# --- AJet: the CMS gateway ---------------------------------------------------

AJET_RECORDS = [
    {
        "Id": "aaa",
        "CampaignName": "campaigns_hub_active_campaign_title_16_may_2026_dom",
        "CampaignText": "campaigns_hub_active_campaign_description_16_may_2026_dom",
        "TicketingDates": "campaigns_details_ticketing_date_16_may_2026_dom",
        "TravelDates": "campaigns_details_travel_date_16_may_2026_dom",
        "CampaignPath": "campaigns_hub_active_campaign_button_link_16_may_2026_dom",
        "IsCampaignActive": True,
    },
    {
        "Id": "bbb",
        "CampaignName": "campaigns_hub_active_campaign_title_19_august_2026_int",
        "CampaignText": "campaigns_hub_active_campaign_description_19_august_2026_int",
        "TicketingDates": "campaigns_details_ticketing_date_19_august_2026_int",
        "TravelDates": "campaigns_details_travel_date_19_august_2026_int",
        "CampaignPath": "campaigns_hub_active_campaign_button_link_19_august_2026_int",
        "IsCampaignActive": True,
    },
    {
        # Last year's campaign, kept by the CMS for its detail page.
        "Id": "ccc",
        "CampaignName": "campaigns_hub_active_campaign_title_16_18_september_dom",
        "TicketingDates": "campaigns_details_ticketing_date_16_18_september_dom",
        "IsCampaignActive": False,
    },
    {
        # A record whose name key is not in the dictionary at all.
        "Id": "ddd",
        "CampaignName": "campaigns_hub_active_campaign_title_missing",
        "IsCampaignActive": True,
    },
]

AJET_LANG = {
    "campaigns_hub_active_campaign_title_16_may_2026_dom":
        "19 Mayıs'ta Gençlere Özel: Yurt İçi Uçuşlarda %30 İndirim✈️",
    "campaigns_hub_active_campaign_description_16_may_2026_dom":
        "<p>Yeni hikâyeler bazen tek bir biletle başlar.&nbsp;AJet Mobil'e özel avantaj!</p>",
    "campaigns_details_ticketing_date_16_may_2026_dom": "18-19 Mayıs 2026",
    "campaigns_details_travel_date_16_may_2026_dom": "1 Eylül 2026 – 10 Kasım 2026 ",
    "campaigns_hub_active_campaign_button_link_16_may_2026_dom":
        "https://ajet.com/tr/kesfet/kampanyalar/19-mayista-genclere-ozel",
    "campaigns_hub_active_campaign_title_19_august_2026_int":
        "Yurt Dışına Uç: 29 USD'den Başlayan Fiyatlarla Sonbahar Fırsatları ✈️",
    "campaigns_hub_active_campaign_description_19_august_2026_int":
        "Avrupa'nın popüler şehirlerinden Orta Doğu'ya avantajlı fiyatlarla çık!",
    "campaigns_details_ticketing_date_19_august_2026_int": "19-20 Ağustos 2026 ",
    "campaigns_details_travel_date_19_august_2026_int": "1 Eylül – 24 Ekim 2026 ",
    "campaigns_hub_active_campaign_button_link_19_august_2026_int":
        "https://ajet.com/tr/kesfet/kampanyalar/yurt-disina-uc-29-usd",
    "campaigns_hub_active_campaign_title_16_18_september_dom": "Geçen yılın kampanyası",
    "campaigns_details_ticketing_date_16_18_september_dom": "16-18 Eylül 2025",
}

AJET_PAGE = "https://www.ajet.com/tr/kesfet/kampanyalar/guncel-kampanyalar"


def test_only_active_campaigns_are_resolved():
    entries = ajet_campaigns.resolve_records(AJET_RECORDS, AJET_LANG, page_url=AJET_PAGE)

    names = [e.campaign_name for e in entries]
    assert len(entries) == 2
    assert "Geçen yılın kampanyası" not in names


def test_a_name_that_does_not_resolve_is_dropped_not_published_as_a_key():
    """"campaigns_hub_active_campaign_title_missing" on an analyst's screen is
    worse than one campaign missing."""
    entries = ajet_campaigns.resolve_records(AJET_RECORDS, AJET_LANG, page_url=AJET_PAGE)

    assert not any(e.campaign_name.startswith("campaigns_") for e in entries)


def test_the_two_windows_stay_separate_because_the_cms_states_them_separately():
    """The distinction the whole four-column date schema exists to preserve.
    Here it costs nothing: the carrier labels both."""
    first, second = ajet_campaigns.resolve_records(
        AJET_RECORDS, AJET_LANG, page_url=AJET_PAGE
    )

    assert first.booking_text == "18-19 Mayıs 2026"
    assert first.travel_text == "1 Eylül 2026 – 10 Kasım 2026"
    assert second.booking_text == "19-20 Ağustos 2026"


def test_markup_and_nbsp_are_stripped_out_of_cms_prose():
    first, _second = ajet_campaigns.resolve_records(
        AJET_RECORDS, AJET_LANG, page_url=AJET_PAGE
    )

    assert "<p>" not in first.body_text
    assert "\xa0" not in first.body_text
    assert first.body_text.startswith("Yeni hikâyeler")


def test_the_rate_and_the_floor_price_are_read_off_the_title():
    first, second = ajet_campaigns.resolve_records(
        AJET_RECORDS, AJET_LANG, page_url=AJET_PAGE
    )

    assert (first.discount_pct, first.campaign_type) == (30, "PERCENT_DISCOUNT")
    assert (second.price_floor, second.currency) == (29.0, "USD")
    assert second.campaign_type == "FIXED_FARE"


def test_turkish_thousands_separators_are_not_read_as_decimals():
    """"1.449 TL" is one thousand four hundred and forty-nine, not 1.449."""
    assert ajet_campaigns.parse_price_floor("1.449 TL'den başlayan") == (1449.0, "TRY")
    assert ajet_campaigns.parse_price_floor("hiç fiyat yok") == (None, None)


def test_each_campaign_links_to_its_own_detail_page():
    first, _second = ajet_campaigns.resolve_records(
        AJET_RECORDS, AJET_LANG, page_url=AJET_PAGE
    )

    assert first.url.startswith("https://ajet.com/tr/kesfet/kampanyalar/19-mayista")


def test_a_campaign_with_no_detail_link_falls_back_to_the_hub_fragment():
    records = [
        {
            "Id": "eee",
            "CampaignName": "n",
            "TicketingDates": "t",
            "IsCampaignActive": True,
        }
    ]
    lang = {"n": "Sonbahar Fırsatı", "t": "1-2 Eylül 2026"}

    (entry,) = ajet_campaigns.resolve_records(records, lang, page_url=AJET_PAGE)

    # The fragment is `slugify_campaign`'s, ASCII-folded the way every other
    # campaign URL in the product is -- stable for a stable campaign name,
    # which is the only property the idempotency key needs.
    assert entry.url == f"{AJET_PAGE}#sonbahar-frsat"


def test_the_evergreen_discount_template_is_never_requested():
    """Standing student/veteran discounts. The rulepack drops them; the honest
    place not to ingest them is before the request, not three links later."""
    assert ajet_campaigns.CAMPAIGN_TEMPLATE_KEY == "WEBCURRENTANDPASTCAMPAIGNS"
    assert "WEBSPECIALDISCOUNTCAMPAIGNS" in ajet_campaigns.EXCLUDED_TEMPLATE_KEYS
    assert ajet_campaigns.CAMPAIGN_TEMPLATE_KEY not in ajet_campaigns.EXCLUDED_TEMPLATE_KEYS


def test_the_hash_ignores_everything_that_is_not_a_published_field():
    """Image URLs and CampaignOrder move on every CMS deploy. Hashing the raw
    JSON would report a change twice a day and spend the run on nothing."""
    entries = ajet_campaigns.resolve_records(AJET_RECORDS, AJET_LANG, page_url=AJET_PAGE)
    reordered = [dict(r, CampaignOrder=99, Image="file_manager_new") for r in AJET_RECORDS]
    same = ajet_campaigns.resolve_records(reordered, AJET_LANG, page_url=AJET_PAGE)

    assert ajet_campaigns.digest_text(entries) == ajet_campaigns.digest_text(same)


async def test_a_harvest_with_no_language_file_is_a_failed_read(monkeypatch):
    """Without the dictionary every name is an i18n key, so this has to record
    as a failure and stay queued -- not baseline an unreadable page."""

    async def _fake_post(url, payload, **kwargs):
        if url == ajet_campaigns.MODEL_DATA_URL:
            return FetchResult(text="{}", http_status=200, payload={"content": AJET_RECORDS})
        return FetchResult(text="{}", http_status=200, payload={"content": {}})

    monkeypatch.setattr(ajet_campaigns, "json_post", _fake_post)
    harvest = await ajet_campaigns.harvest(AJET_PAGE)

    assert harvest.entries == ()
    assert harvest.fetch.text is None
    assert "Dil kaynağı" in harvest.fetch.error


async def test_a_full_harvest_returns_both_halves(monkeypatch):
    async def _fake_post(url, payload, **kwargs):
        if url == ajet_campaigns.MODEL_DATA_URL:
            assert payload == {"templateKey": "WEBCURRENTANDPASTCAMPAIGNS"}
            return FetchResult(text="{}", http_status=200, payload={"content": AJET_RECORDS})
        return FetchResult(
            text="{}", http_status=200, payload={"content": {"langKeys": AJET_LANG}}
        )

    monkeypatch.setattr(ajet_campaigns, "json_post", _fake_post)
    harvest = await ajet_campaigns.harvest(AJET_PAGE)

    assert len(harvest.entries) == 2
    assert harvest.fetch.http_status == 200
    assert "Bilet alış tarihleri: 18-19 Mayıs 2026" in harvest.fetch.text


# --- Singapore Airlines: the fare-deal feed ----------------------------------

SQ_PAYLOAD = json.loads(
    """
{
  "promos": {"country": "GB", "countryDescription": "United Kingdom"},
  "promoVO": [
    {"city": "MAN-Manchester", "cityVO": [
      {"shareurl": "/en-gb/flights-from-manchester-to-singapore",
       "destinationCityName": "Singapore", "currency": "GBP", "price": "750",
       "cabin": "Economy", "cabinDesc": "Economy",
       "faredealOriginAirportCode": "MAN", "faredealDestinationAirportCode": "SIN",
       "priceSource": "fareCache", "destinationCountry": "Singapore"},
      {"shareurl": "/en-gb/flights-from-manchester-to-singapore",
       "destinationCityName": "Singapore", "currency": "GBP", "price": "2450",
       "cabin": "Business", "cabinDesc": "Business",
       "faredealOriginAirportCode": "MAN", "faredealDestinationAirportCode": "SIN",
       "priceSource": "fareCache", "destinationCountry": "Singapore"},
      {"shareurl": "/en-gb/flights-from-manchester-to-bangkok",
       "destinationCityName": "Bangkok", "currency": "GBP", "price": "704",
       "cabin": "Economy", "cabinDesc": "Economy",
       "faredealOriginAirportCode": "MAN", "faredealDestinationAirportCode": "BKK",
       "priceSource": "fareCache", "destinationCountry": "Thailand"},
      {"shareurl": "/en-gb/flights-from-manchester-to-nowhere",
       "destinationCityName": "Nowhere", "currency": "GBP", "price": "1",
       "cabin": "Economy", "faredealOriginAirportCode": "MAN",
       "faredealDestinationAirportCode": ""}
    ]},
    {"city": "LON-London", "cityVO": []}
  ]
}
"""
)

SQ_URL = "https://www.singaporeair.com/home/getPromotions.form?locale=en_UK&country=GB"


def test_a_deal_missing_an_airport_code_is_skipped():
    """The whole value of this source is that its route is stated rather than
    inferred. Half a route would be published as an OND we invented one end
    of."""
    entries = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)

    assert {(e.origin, e.destination) for e in entries} == {("MAN", "SIN"), ("MAN", "BKK")}


def test_both_ends_are_iata_codes_so_the_scope_is_real():
    economy = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)[0]

    assert (economy.origin, economy.destination) == ("MAN", "SIN")
    assert (economy.price_floor, economy.currency) == (750.0, "GBP")
    assert economy.cabin == "Economy"


def test_only_the_routes_lead_in_fare_is_published():
    """SQ lists every route three times, once per cabin, and promo_dedup
    correctly reads two cabins of one route as one campaign. Rather than fight
    a layer doing its job, the cheapest cabin holds the route -- which is what
    a "from GBP 750" deal means anyway."""
    entry = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)[0]

    assert entry.price_floor == 750.0
    assert entry.cabin == "Economy"
    assert entry.url.startswith("https://www.singaporeair.com/en-gb/flights-from-manchester")
    assert entry.url.endswith("#man-sin")


def test_two_different_routes_do_not_dedupe_into_one_row():
    """The failure this title shape exists to prevent. promo_dedup matches on
    Jaccard over stemmed title tokens at 0.55, and every word two headlines
    share pushes them closer: with "Economy" and "başlangıç fiyatı" in the
    title, Manchester-Singapore and Manchester-Bangkok scored 0.556 and the
    second one merged into the first."""
    from app.pipeline.promo_dedup import subjects_conflict, title_similarity

    singapore, bangkok = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)

    assert title_similarity(singapore.campaign_name, bangkok.campaign_name) < 0.55
    assert not subjects_conflict(singapore.campaign_name, bangkok.campaign_name)


def test_a_moving_fare_updates_its_row_rather_than_creating_a_new_one():
    """The identity is route + cabin, never the price. This feed exists because
    prices move; keying on the title would file every move as a new campaign
    and the version history -- the only record that the fare changed -- would
    never be written."""
    cheaper = json.loads(json.dumps(SQ_PAYLOAD).replace('"750"', '"690"'))

    before = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)[0]
    after = sq_campaigns.map_fare_deals(cheaper, page_url=SQ_URL)[0]

    assert before.url == after.url
    assert before.price_floor != after.price_floor
    assert before.campaign_name != after.campaign_name


def test_a_fare_deal_is_an_evergreen_offer_not_a_campaign():
    """`priceSource: fareCache` is SQ saying this is the cheapest fare loaded
    for the route, not a sale. Filing it as a live campaign would be the exact
    false positive the business-class column exists to prevent."""
    entries = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)

    for entry in entries:
        assert entry.business_class == "EVERGREEN_OFFER"
        assert entry.campaign_type == "FIXED_FARE"
        assert entry.booking_text is None


async def test_an_empty_fare_list_is_a_failed_read(monkeypatch):
    async def _fake_get(url, **kwargs):
        return FetchResult(text="{}", http_status=200, payload={"promoVO": []})

    monkeypatch.setattr(sq_campaigns, "json_get", _fake_get)
    harvest = await sq_campaigns.harvest(SQ_URL)

    assert harvest.entries == ()
    assert harvest.fetch.text is None


# --- the structured builder both feeds share ---------------------------------


def test_a_two_day_ticketing_window_keeps_both_of_its_days():
    """"18-19 Mayıs 2026" is AJet's most common shape and the general parser
    reads it as one date (the 19th), because "18-" is not a date on its own.
    Publishing a one-day window for a two-day flash sale is a wrong deadline on
    an analyst's screen."""
    assert parse_window("18-19 Mayıs 2026", default_year=2026) == (
        date(2026, 5, 18),
        date(2026, 5, 19),
        False,
    )


def test_a_single_date_is_read_as_a_deadline_not_as_a_start():
    """Same reading as promo_scrape.parse_validity: guessing a start would put
    a bar somewhere the carrier never said it was."""
    assert parse_window("30 Kasım 2026", default_year=2026) == (None, date(2026, 11, 30), False)


def test_a_missing_year_is_completed_and_flagged_never_silently_filled():
    start, end, inferred = parse_window("1 Eylül – 24 Ekim 2026", default_year=2026)

    assert (start, end) == (date(2026, 9, 1), date(2026, 10, 24))
    assert inferred is True


def test_a_reversed_pair_is_ordered_rather_than_published_backwards():
    assert parse_window("20 Ocak 2027 - 24 Kasım 2026", default_year=2026) == (
        date(2026, 11, 24),
        date(2027, 1, 20),
        False,
    )


@pytest.mark.parametrize("raw", [None, "", "   ", "yakında", "21-Haziran-26"])
def test_an_unparseable_window_is_no_window_rather_than_a_guess(raw):
    assert parse_window(raw, default_year=2026) == (None, None, False)


def test_a_structured_campaign_carries_both_windows_and_no_llm_flag():
    entry = StructuredCampaign(
        campaign_name="Yurt İçi Uçuşlarda %30 İndirim",
        url="https://ajet.com/tr/kesfet/kampanyalar/yurt-ici",
        body_text="Yurt içi uçuşlarda %30 indirim fırsatı.",
        booking_text="1-2 Eylül 2026",
        travel_text="6 Ekim 2026 – 31 Aralık 2026",
        discount_pct=30,
        campaign_type="PERCENT_DISCOUNT",
    )

    campaign, reason = build_structured_campaign(
        entry,
        carrier=CARRIER_MASTER["VF"],
        detected_at=NOW,
        today=TODAY,
        source_name="AJet kampanya sayfası",
        content_hash="a" * 64,
    )

    assert reason is None
    assert (campaign.sale_starts, campaign.sale_ends) == (date(2026, 9, 1), date(2026, 9, 2))
    assert (campaign.travel_starts, campaign.travel_ends) == (
        date(2026, 10, 6),
        date(2026, 12, 31),
    )
    assert campaign.discount_pct == 30
    # The one attribute the LLM path can never carry.
    assert campaign.attrs_json["extraction_method"] == "structured"
    assert campaign.evidence_json["booking_end"]["source_text"] == "1-2 Eylül 2026"


def test_the_rule_layer_still_gets_a_veto_on_the_structured_path():
    """Skipping the model does not mean skipping validation: a sale that closed
    long ago is dropped here exactly as it is on the LLM path."""
    entry = StructuredCampaign(
        campaign_name="Geçen yılın kampanyası",
        url="https://ajet.com/tr/kesfet/kampanyalar/eski",
        body_text="Yurt içi uçuşlarda indirim.",
        booking_text="16-18 Eylül 2020",
        discount_pct=20,
    )

    campaign, reason = build_structured_campaign(
        entry,
        carrier=CARRIER_MASTER["VF"],
        detected_at=NOW,
        today=TODAY,
        source_name="AJet kampanya sayfası",
    )

    assert campaign is None
    assert reason == "sale_window_closed"


def test_a_stated_business_class_bypasses_the_rulepack_and_says_so():
    """SQ's feed has no marketing copy for the rulepacks to read. Rather than
    writing a sentence and asking a rulepack about it, the class is stated from
    the shape of the feed -- and the reason records that it was."""
    entry = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)[0]

    campaign, reason = build_structured_campaign(
        entry,
        carrier=CARRIER_MASTER["SQ"],
        detected_at=NOW,
        today=TODAY,
        source_name=sq_campaigns.SOURCE_NAME,
    )

    assert reason is None
    assert campaign.business_class == "EVERGREEN_OFFER"
    assert "yapılandırılmış kaynağından" in campaign.classification_reason


def test_a_fare_deal_resolves_to_an_ond_and_can_never_be_called_certain():
    """Two IATA codes give a real OND scope. No sale window caps the band at
    `medium`, whatever else the row has going for it -- confidence.py's
    completeness cap, doing exactly what it was written for."""
    entry = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)[0]

    campaign, _reason = build_structured_campaign(
        entry,
        carrier=CARRIER_MASTER["SQ"],
        detected_at=NOW,
        today=TODAY,
        source_name=sq_campaigns.SOURCE_NAME,
    )

    assert campaign.route.scope == "OND"
    assert campaign.route.ond == "MAN-SIN"
    assert campaign.sale_starts is None and campaign.sale_ends is None
    # The score itself is high -- official source, every field cited by
    # construction -- and the band is still `medium`, because the cap is
    # categorical rather than a weight. That is the whole argument in
    # confidence.py's docstring, and this row is the case it describes.
    assert campaign.confidence_score >= 0.75
    assert campaign.confidence_band == "medium"


# --- the direct sweep inside deep_scan ---------------------------------------


async def _run_direct(db, monkeypatch, harvests: dict, *, extraction_enabled: bool):
    from app.ingest import deep_scan

    monkeypatch.setattr(deep_scan, "DIRECT_DELAY_RANGE_S", (0.0, 0.0))
    monkeypatch.setattr(deep_scan, "DIRECT_HARVESTERS", dict(harvests))
    summary = {"scanned": 0, "changed": 0, "blocked": 0, "errors": 0, "skipped_static": 0}
    budget = deep_scan.ExtractionBudget(remaining=10)
    await deep_scan._scan_direct_carriers(
        db,
        [CARRIER_MASTER[code] for code in harvests],
        summary,
        budget=budget,
        extraction_enabled=extraction_enabled,
    )
    await db.commit()
    return summary, budget


async def test_the_direct_sweep_records_the_endpoint_it_fetched(db_session, monkeypatch):
    """AJet's run row has to name the CMS gateway, not the DataDome-walled page
    a human would open -- the run log answers "what did we fetch?"."""
    from sqlalchemy import select

    from app.models.scrape_run import ScrapeRun

    async def _handler(carrier_page):
        from app.ingest.deep_scan import DirectHarvest

        return DirectHarvest(
            fetch=FetchResult(text="Kampanya metni. " * 40, http_status=200),
            source_name="AJet kampanya sayfası",
        )

    summary, _budget = await _run_direct(
        db_session, monkeypatch, {"VF": _handler}, extraction_enabled=False
    )

    run = (await db_session.execute(select(ScrapeRun))).scalar_one()
    assert summary["scanned"] == 1
    assert run.method == "api"
    assert run.url.startswith("https://gatewaycmsint.cloud.ajet.com/")
    assert run.outcome == "ok"
    assert run.changed is True


async def test_a_structured_sweep_writes_campaigns_without_spending_the_llm_budget(
    db_session, monkeypatch
):
    """The reason the structured path was worth building: 69 SQ fare deals and
    34 AJet campaigns cost zero calls against a shared free tier."""
    from sqlalchemy import select

    from app.models.promotion import Promotion

    async def _handler(carrier_page):
        from app.ingest.deep_scan import DirectHarvest

        entries = sq_campaigns.map_fare_deals(SQ_PAYLOAD, page_url=SQ_URL)
        return DirectHarvest(
            fetch=FetchResult(
                text=sq_campaigns.digest_text(entries), http_status=200
            ),
            entries=entries,
            source_name=sq_campaigns.SOURCE_NAME,
        )

    _summary, budget = await _run_direct(
        db_session, monkeypatch, {"SQ": _handler}, extraction_enabled=True
    )

    rows = (await db_session.execute(select(Promotion))).scalars().all()
    assert {row.ond for row in rows} == {"MAN-SIN", "MAN-BKK"}
    assert all(row.airline_code == "SQ" for row in rows)
    assert all(row.business_class == "EVERGREEN_OFFER" for row in rows)
    # The whole point.
    assert (budget.spent, budget.remaining) == (0, 10)
    assert budget.inserted == 2


async def test_a_failed_direct_fetch_costs_that_carrier_only(db_session, monkeypatch):
    """A gateway that has gone away must not take the sweep with it."""
    from sqlalchemy import select

    from app.models.scrape_run import ScrapeRun

    async def _explode(carrier_page):
        raise RuntimeError("gateway is gone")

    summary, _budget = await _run_direct(
        db_session, monkeypatch, {"VF": _explode}, extraction_enabled=False
    )

    run = (await db_session.execute(select(ScrapeRun))).scalar_one()
    assert summary["errors"] == 1
    assert run.outcome == "parse_error"
    assert "gateway is gone" in run.error
    assert run.content_hash is None


# --- the round-9 seeds -------------------------------------------------------


def test_the_fare_campaign_radars_are_seeded_and_percent_encoded():
    """news.google.com answers HTTP 400 to a raw non-ASCII `q`. Decoding one of
    these "to make it readable" is how the feed silently goes dark."""
    from app.ingest.sources_seed import FREE_RSS_SOURCES

    radars = [s for s in FREE_RSS_SOURCES if "kampanya" in s.url or "sale" in s.url]
    assert len(radars) >= 9

    for source in radars:
        assert source.url.isascii(), source.name
        assert source.url.startswith("https://"), source.name

    turkish = [s for s in radars if s.language == "tr"]
    assert len(turkish) >= 6, "the densest fare-campaign sources are the TR ones"


def test_google_news_radars_declare_the_aggregator_tier():
    """confidence.py reads the tier directly. An aggregator's rewrite of a sale
    must not outrank the carrier's own page announcing it."""
    from app.ingest.sources_seed import FREE_RSS_SOURCES

    for source in FREE_RSS_SOURCES:
        if source.url.startswith("https://news.google.com/"):
            assert source.tier == "aggregator", source.name
