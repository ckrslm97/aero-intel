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

**Lenient about the packaging, strict about the answer.** Those two policies
are about the *content* of a response. How the response is wrapped is a third
question, and the first Azure run of the deep scan settled it the expensive
way: TK's page was fetched, the model answered, and the page was failed with
`schema_error:campaign payload must be a JSON object` because the answer was
not shaped the way the prompt drew it. A model that lists the campaigns as a
bare `[...]`, fences its JSON in a code block or writes a sentence before it
has answered the question asked -- it has simply not typed the wrapper. So
`extract_campaign_json` reads all of those (the same leniency
llm/classify.py's `_extract_json` has always applied to the article path) and
`parse_campaign_payload` wraps a bare list into the object shape.

That is a loosening of the parser, not of the contract: llm/campaign_prompt.py
still asks for `{"campaigns": [...]}` and nothing here invents, reorders or
merges what it finds. Anything that is not JSON at all, and any object without
a usable `campaigns` list, still fails the page exactly as before -- and each
item inside the list is still judged on its own.

**A cut-off answer is damaged packaging, not a wrong answer.** The second Azure
run failed TK a second time, and the log said `campaign payload must be a JSON
object` about a response whose first character was `{` -- because the model
never got to the last one. It stopped at exactly 3,072 completion tokens,
mid-card, and an unterminated document parses as nothing at all, so
`extract_campaign_json` returned None and the caller reported the shape
complaint that None happens to trip.

`recover_campaign_items` is the answer to that: it walks what did arrive and
keeps the campaign objects that are *complete* -- balanced braces, valid JSON
on their own -- discarding the half-written one the cut landed in. Nothing is
completed, closed or guessed; an object that was still being typed is dropped
exactly as an unusable card always was, and every survivor still goes through
the date, rule and route layers before it can reach a row.

The rescue is deliberately conditional on finding at least one whole item. A
truncation that produced none is not an empty page and must never be read as
one: `{"campaigns": [` says the model was interrupted before it said anything,
which is the opposite fact from "the model looked and there was nothing", and
the page stays FAILED so the next scan asks again.

Nothing here decides whether a campaign is real, whether its dates are true or
where it flies: that is the rule/date/entity half of the chain. This layer only
guarantees that what reaches those layers is typed, in range, and honest about
what it had to throw away.
"""
from __future__ import annotations

import json
import re
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
    #: The model's answer was cut off and these are the cards that had finished
    #: being written when it was. Carried so the caller can log it: a page that
    #: keeps arriving truncated is an output-ceiling problem, and it is only
    #: visible if the rescue says it happened rather than looking like a clean
    #: short answer.
    truncated: bool = False


#: Models fence their output however firmly they are asked not to. Same pattern
#: as llm/classify.py's, kept here rather than imported for the same reason
#: `_NULL_WORDS` is duplicated: a schema module importing from the llm package
#: to share one regex would couple them for nothing.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _json_candidates(text: str):
    """The substrings of a model answer that might be the JSON it was asked for.

    The whole string first -- a model that answered cleanly is the common case
    and must not be re-parsed out of a slice. Then the outermost bracketed span
    of each kind, in the order the brackets actually open, so a stray `{` in a
    sentence of preamble cannot outrank the `[` that starts the real answer.
    """
    yield text
    openers = sorted(
        (text.find(opener), opener, closer)
        for opener, closer in (("{", "}"), ("[", "]"))
        if text.find(opener) != -1
    )
    for start, _opener, closer in openers:
        end = text.rfind(closer)
        if end > start:
            yield text[start : end + 1]


#: The key `extract_campaign_json` sets on a payload it had to rescue out of a
#: truncated answer, and the only key `parse_campaign_payload` reads besides
#: `campaigns`. A marker rather than a second return value because every caller
#: in the chain passes the payload straight from one function to the other, and
#: a tuple would have to be unpacked in four places to be ignored in three.
RECOVERED_KEY = "_recovered_from_truncation"


def recover_campaign_items(text: str) -> list[dict]:
    """The complete campaign objects inside a cut-off answer, in page order.

    A single pass over the first JSON array in the text, tracking string state
    so a `"` inside a quote cannot open one and a brace inside `source_text`
    cannot close the wrong object. Only spans that start with `{`, end with the
    `}` that balances it, and parse on their own are kept -- which is precisely
    the set of cards the model finished writing before it was cut off.

    Never called for an answer that parses: `extract_campaign_json` tries the
    document itself first, and this only runs when nothing at all parsed.
    """
    start = text.find("[")
    if start == -1:
        return []

    items: list[dict] = []
    depth = 0
    in_string = False
    escaped = False
    object_start: int | None = None

    for index in range(start + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                object_start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                break
            if depth == 0 and object_start is not None:
                try:
                    parsed = json.loads(text[object_start : index + 1])
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                if isinstance(parsed, dict):
                    items.append(parsed)
                object_start = None
        elif char == "]" and depth == 0:
            # The array closed. Anything after it belongs to a different
            # structure and is not one of the campaigns.
            break

    return items


def extract_campaign_json(raw: str) -> object | None:
    """One model answer's raw text -> the JSON in it, or None.

    The counterpart of `llm/classify._extract_json` for the campaign-page
    prompt, and lenient in the same two ways (fenced blocks, prose around the
    JSON) plus one this path needs: it returns a top-level list as readily as an
    object, because "the campaigns" is a list and models write it as one. What
    that list *means* is `parse_campaign_payload`'s question, not this one's.

    None means "there is no JSON here", which the caller turns into a failed
    page. It is never an empty result: a page the model did not answer for and
    a page with no campaigns on it are opposite facts.

    The last resort, when nothing parses, is `recover_campaign_items` -- and
    only when it finds at least one whole card, because a truncation that
    finished nothing is an interrupted answer rather than an empty one.
    """
    text = (raw or "").strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, (dict, list)):
            return parsed

    recovered = recover_campaign_items(text)
    if recovered:
        return {"campaigns": recovered, RECOVERED_KEY: True}
    return None


def _is_one_campaign(payload: object) -> bool:
    """Does this object carry a campaign's identity field?

    `campaign_name` and nothing else, because it is the one field
    `RawCampaignItem` refuses to default: an object that has it is an answer to
    the question asked, however it was wrapped, and an object that does not is
    not a campaign no matter what else it contains.
    """
    if not isinstance(payload, dict):
        return False
    name = payload.get("campaign_name")
    return isinstance(name, str) and bool(name.strip())


def _campaign_list(raw_items: object) -> list | None:
    """`campaigns` as the model wrote it -> the list, or None if it is neither.

    Two shapes beyond the list the prompt draws, both seen from models asked
    for a keyed schema: the single campaign written as the value itself
    (`{"campaigns": {"campaign_name": ...}}`), and the key-per-campaign map
    (`{"campaigns": {"1": {...}, "2": {...}}}`). Both are the same answer with
    a different container, and the container is not the contract -- but a map
    with no campaign objects in it is, and that still fails.
    """
    if isinstance(raw_items, list):
        return raw_items
    if not isinstance(raw_items, dict):
        return None
    if _is_one_campaign(raw_items):
        return [raw_items]
    # Insertion order is the model's own order, which is page order.
    nested = [value for value in raw_items.values() if isinstance(value, dict)]
    return nested or None


def parse_campaign_payload(payload: object) -> RawCampaignPage:
    """Type one model answer, or raise.

    Raises `ValueError` when the response is not an object with a `campaigns`
    list -- the FAILED case, which the chain never falls back from. Items
    inside that list are individually forgiving: one unusable card does not
    cost the other twenty-one.

    A bare list is read as that list of campaigns. It is the same answer with
    the envelope left off, and failing a page whose campaigns we are holding --
    then re-fetching and re-asking for them twice a day -- would be a protocol
    complaint dressed up as a data-quality rule. `[]` therefore means what
    `{"campaigns": []}` means: the model looked and there was nothing.

    Two further containers are read the same way and for the same reason: a
    single campaign object at the top level, and `campaigns` written as a map
    instead of a list (see `_campaign_list`). Both are recognised by the
    campaign's own identity field rather than by shape alone, so an arbitrary
    object still fails -- the leniency is about the envelope, never about what
    counts as a campaign.
    """
    if isinstance(payload, list):
        payload = {"campaigns": payload}
    if not isinstance(payload, dict):
        raise ValueError("campaign payload must be a JSON object")
    if "campaigns" not in payload and _is_one_campaign(payload):
        # One campaign, written without the envelope. Same reading as the bare
        # list above and for the same reason: the model answered the question,
        # it just did not type the wrapper, and a page whose single campaign we
        # are holding must not be failed over the container it arrived in.
        payload = {"campaigns": [payload]}
    raw_items = payload.get("campaigns")
    if raw_items is None:
        raise ValueError("campaign payload is missing 'campaigns'")
    items_in = _campaign_list(raw_items)
    if items_in is None:
        raise ValueError("'campaigns' must be a list")

    items: list[RawCampaignItem] = []
    invalid = 0
    for raw in items_in:
        try:
            items.append(RawCampaignItem.model_validate(raw))
        except Exception:  # noqa: BLE001 -- one bad card, not a bad page
            invalid += 1
    return RawCampaignPage(
        campaigns=items,
        invalid_items=invalid,
        truncated=bool(payload.get(RECOVERED_KEY)),
    )
