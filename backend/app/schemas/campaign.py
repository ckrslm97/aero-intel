"""The shape an LLM campaign-page answer has to have before anything reads it.

This is layer two of the extraction chain (llm/campaign_prompt.py is layer one,
pipeline/campaign_extract.py runs the rest). Its contract is narrow and worth
stating outright, because "validate the LLM output" is the kind of phrase that
hides two opposite policies:

**Lenient about missing, strict about malformed.** A page that states no travel
window is normal -- most do not -- so every field but the campaign's own name is
optional and defaults to None. But a `campaigns` key that is not a list, or an
item that is not an object, means the model did not answer the question it was
asked, and no part of that response can be trusted; `parse_campaign_payload`
raises and the caller fails the whole page. That is the tri-state rule from
pipeline/outcomes.py applied here: a malformed answer is FAILED, never a
partially-believed one.

**An off-taxonomy value is missing data, not a failure.** A model answering
`campaign_type: "MEGA_SALE"` has told us something real -- there is a campaign
-- in a slug nothing can render, filter or count. Dropping the slug to None and
recording it in `dropped_fields` keeps the campaign and loses only the
unusable word. Failing the item instead would throw away the model's correct
work over its vocabulary, and llm/classify.py already settled that trade the
same way for subcategories.

Nothing here decides whether a campaign is real, whether its dates are true or
where it flies: that is the rule/date/entity half of the chain. This layer only
guarantees that what reaches those layers is typed, in range, and honest about
what it had to throw away.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, model_validator

from app.taxonomy import CAMPAIGN_BUSINESS_CLASSES, CAMPAIGN_TYPES, ROUTE_SCOPES

#: The four date edges, in the order the drawer reads them. Also the allowed
#: key set for `date_text` and the date half of `source_text`.
DATE_FIELDS: tuple[str, ...] = ("booking_start", "booking_end", "travel_start", "travel_end")

#: Fields the prompt demands a verbatim quote for. Anything else the model
#: quotes is kept too (it costs nothing and may be useful in the drawer), but
#: these are the ones the chain actively checks.
EVIDENCE_FIELDS: tuple[str, ...] = DATE_FIELDS + (
    "discount_pct",
    "price_floor",
    "origin",
    "destination",
)

#: Same "the model wrote the word null" defence as llm/classify.py's
#: `_clean_str`. Kept in both places rather than shared: that module's copy is
#: load-bearing for the article path and importing across the llm/schemas
#: boundary for six words would couple them for no gain.
_NULL_WORDS = {"null", "none", "n/a", "na", "yok", "-", "belirtilmemiş", "belirtilmemis"}

#: Quotes are evidence, not prose. A model that pastes half the page into
#: source_text is not citing anything, and the drawer renders these inline.
MAX_QUOTE_CHARS = 400
MAX_NAME_CHARS = 300
MAX_FREE_TEXT_CHARS = 200


def _clean_str(value: object, *, limit: int = MAX_FREE_TEXT_CHARS) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    stripped = " ".join(value.split())
    if not stripped or stripped.casefold() in _NULL_WORDS:
        return None
    return stripped[:limit]


def _clean_pct(value: object) -> int | None:
    """1-100 or nothing. 0 is not a discount and 130 is a misparsed price."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        value = int(digits) if digits else None
    if not isinstance(value, (int, float)) or value is None:
        return None
    pct = int(value)
    return pct if 0 < pct <= 100 else None


def _clean_amount(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        cleaned = value.replace(",", ".").strip()
        try:
            value = float(cleaned)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    amount = float(value)
    return amount if amount > 0 else None


def _clean_currency(value: object) -> str | None:
    text = _clean_str(value, limit=8)
    if text is None:
        return None
    code = text.upper()
    return code if len(code) == 3 and code.isalpha() else None


def _parse_iso(value: object) -> date | None:
    text = _clean_str(value, limit=32)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _enum_or_none(value: object, allowed: tuple[str, ...]) -> tuple[str | None, str | None]:
    """(value, rejected_spelling). An unknown slug is dropped, never raised."""
    text = _clean_str(value, limit=40)
    if text is None:
        return None, None
    slug = text.upper().replace(" ", "_").replace("-", "_")
    if slug in allowed:
        return slug, None
    return None, text


class RawCampaignItem(BaseModel):
    """One campaign as the model described it, after typing and range checks.

    Deliberately *not* the row: no confidence, no route resolution, no
    business-class verdict. Those are decisions the chain makes about this
    answer, and keeping them out of the schema is what stops "the model said
    so" from becoming "the database says so".
    """

    model_config = ConfigDict(extra="ignore")

    campaign_name: str
    campaign_type: str | None = None
    is_fare_campaign: bool | None = None
    business_class_hint: str | None = None

    booking_start: date | None = None
    booking_end: date | None = None
    travel_start: date | None = None
    travel_end: date | None = None
    #: Dates the page states without a year, or in a form that is not ISO --
    #: kept verbatim for the regex layer to resolve against the scan year, with
    #: `date_flags_json.inferred_year` recording that it had to.
    date_text: dict[str, str] = {}

    discount_pct: int | None = None
    price_floor: float | None = None
    currency: str | None = None
    promo_code: str | None = None
    cabin: str | None = None

    origin: str | None = None
    destination: str | None = None
    route_scope_hint: str | None = None

    eligibility: str | None = None
    sales_channel: str | None = None

    #: field -> short verbatim quote from the page.
    source_text: dict[str, str] = {}

    #: What this layer refused, as "field:spelling". Carried rather than logged
    #: away: a model consistently answering "MEGA_SALE" is a taxonomy gap, and
    #: it is only visible if the rejected spelling survives the parse.
    dropped_fields: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: object) -> dict:
        if not isinstance(data, dict):
            # Strict half of the contract: an item that is not an object is a
            # malformed answer, not a sparse one.
            raise ValueError("campaign item must be an object")

        dropped: list[str] = []
        name = _clean_str(data.get("campaign_name"), limit=MAX_NAME_CHARS)
        if not name:
            # The name is the one field with no honest default: it is the
            # campaign's identity, the row's title, and the per-campaign URL
            # fragment (see campaign_extract's idempotency key).
            raise ValueError("campaign_name is required")

        campaign_type, bad_type = _enum_or_none(data.get("campaign_type"), CAMPAIGN_TYPES)
        if bad_type:
            dropped.append(f"campaign_type:{bad_type}")
        business_class, bad_class = _enum_or_none(
            data.get("business_class_hint"), CAMPAIGN_BUSINESS_CLASSES
        )
        if bad_class:
            dropped.append(f"business_class_hint:{bad_class}")
        route_scope, bad_scope = _enum_or_none(data.get("route_scope_hint"), ROUTE_SCOPES)
        if bad_scope:
            dropped.append(f"route_scope_hint:{bad_scope}")

        raw_date_text = data.get("date_text")
        date_text: dict[str, str] = {}
        if isinstance(raw_date_text, dict):
            for field in DATE_FIELDS:
                quoted = _clean_str(raw_date_text.get(field), limit=MAX_QUOTE_CHARS)
                if quoted:
                    date_text[field] = quoted

        dates: dict[str, date | None] = {}
        for field in DATE_FIELDS:
            raw = data.get(field)
            parsed = _parse_iso(raw)
            dates[field] = parsed
            if parsed is None and _clean_str(raw, limit=MAX_QUOTE_CHARS):
                # An unparseable date string is exactly what date_text is for:
                # keep the words, let the regex layer try, never guess here.
                date_text.setdefault(field, _clean_str(raw, limit=MAX_QUOTE_CHARS))
                dropped.append(f"{field}:not_iso")

        source_text: dict[str, str] = {}
        raw_source = data.get("source_text")
        if isinstance(raw_source, dict):
            for field, quote in raw_source.items():
                cleaned = _clean_str(quote, limit=MAX_QUOTE_CHARS)
                if cleaned and isinstance(field, str):
                    source_text[field] = cleaned

        currency = _clean_currency(data.get("currency"))
        price_floor = _clean_amount(data.get("price_floor"))
        if price_floor is not None and currency is None:
            # "başlayan fiyatlarla 199" is not a price. A floor without a
            # currency cannot be compared, converted or rendered, and inventing
            # the carrier's home currency for it would be a guess with a
            # decimal point on it.
            dropped.append("price_floor:no_currency")
            price_floor = None

        is_fare = data.get("is_fare_campaign")
        return {
            "campaign_name": name,
            "campaign_type": campaign_type,
            "is_fare_campaign": is_fare if isinstance(is_fare, bool) else None,
            "business_class_hint": business_class,
            **dates,
            "date_text": date_text,
            "discount_pct": _clean_pct(data.get("discount_pct")),
            "price_floor": price_floor,
            "currency": currency,
            "promo_code": _clean_str(data.get("promo_code"), limit=40),
            "cabin": _clean_str(data.get("cabin"), limit=40),
            "origin": _clean_str(data.get("origin"), limit=80),
            "destination": _clean_str(data.get("destination"), limit=80),
            "route_scope_hint": route_scope,
            "eligibility": _clean_str(data.get("eligibility")),
            "sales_channel": _clean_str(data.get("sales_channel"), limit=60),
            "source_text": source_text,
            "dropped_fields": dropped,
        }

    def quote_for(self, field: str) -> str | None:
        return self.source_text.get(field)

    def quoted_text(self) -> str:
        """Everything this item says about itself, as one string.

        What the rulepacks in agents/campaign_airline.py read. Deliberately the
        item's own words rather than the whole page: an offers page carrying a
        baggage promo in card 7 must not make cards 1-6 product promotions.
        """
        parts = [self.campaign_name]
        parts.extend(self.source_text.values())
        parts.extend(self.date_text.values())
        parts.extend(
            value
            for value in (self.eligibility, self.cabin, self.promo_code, self.sales_channel)
            if value
        )
        return "\n".join(parts)


class RawCampaignPage(BaseModel):
    """Every campaign one page's answer described, plus what was unusable."""

    model_config = ConfigDict(extra="ignore")

    campaigns: list[RawCampaignItem] = []
    #: Items that were objects but could not be typed at all (no name). Counted
    #: rather than dropped silently: a page whose every item lands here looks
    #: identical to an empty page otherwise, and those are opposite facts.
    invalid_items: int = 0


def parse_campaign_payload(payload: object) -> RawCampaignPage:
    """Type one model answer, or raise.

    Raises `ValueError` when the response is not an object with a `campaigns`
    list -- the FAILED case, which the chain never falls back from. Items
    inside that list are individually forgiving: one unusable card does not
    cost the other twenty-one.
    """
    if not isinstance(payload, dict):
        raise ValueError("campaign payload must be a JSON object")
    raw_items = payload.get("campaigns")
    if raw_items is None:
        raise ValueError("campaign payload is missing 'campaigns'")
    if not isinstance(raw_items, list):
        raise ValueError("'campaigns' must be a list")

    items: list[RawCampaignItem] = []
    invalid = 0
    for raw in raw_items:
        try:
            items.append(RawCampaignItem.model_validate(raw))
        except Exception:  # noqa: BLE001 -- one bad card, not a bad page
            invalid += 1
    return RawCampaignPage(campaigns=items, invalid_items=invalid)
