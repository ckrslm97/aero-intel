"""The extraction chain: LLM -> schema -> rule -> date -> entity -> row.

One official campaign page in, zero or more validated campaigns out. The
ordering is the whole design, and each link exists because the one before it
cannot be trusted on its own:

1. **LLM** (llm/campaign_prompt.py). The only layer that can read marketing
   prose in two languages and find twenty-two offers in one document. It is
   also the only layer that can invent a route that is not there, so nothing
   downstream takes its word for anything.
2. **Schema** (schemas/campaign.py). Types, ranges and the closed taxonomies.
   A malformed answer fails the page outright -- FAILED never falls back to a
   heuristic (pipeline/outcomes.py); a whole official page guessed at by
   keyword matching is exactly the 129-wrong-rows failure this rebuild exists
   to end.
3. **Rule** (agents/campaign_airline.validate_campaign). Is this a fare
   campaign at all? Baggage promos, mileage sales and standing student offers
   are dropped here, with the phrase that decided it recorded.
4. **Date.** Every date the model returned is looked for again by the
   deterministic regex layer (pipeline/promotions.find_dates_flagged), in the
   model's own quote first and then anywhere on the page. A date that appears
   in neither is not published -- it is recorded in `evidence_json` as a
   rejected value, which is the honest form of "the model said 30 September
   and the page does not". Year-less dates ("30 Kasım'a kadar") are resolved
   against the scan year and flagged `inferred_year`, never silently
   completed. The agreement ratio from this step is what finally feeds the
   dormant `signal_agreement` weight in pipeline/confidence.py.
5. **Entity.** The airline must be the carrier whose domain we fetched: a
   partner's offer sitting on Emirates' page is not an Emirates campaign.
   Routes resolve through the bundled airport/country tables, and the scope
   ladder (OND -> CITY_PAIR -> COUNTRY -> REGION -> NETWORK_WIDE) is a floor,
   never a ceiling: a REGION campaign is never fanned out into invented OND
   pairs. See `resolve_route`.

What this module refuses to do
------------------------------
It never fills a field the page does not state, never translates a route into
codes it cannot verify, and never turns a failure into a partial answer. A
campaign with no dates comes out with no dates and a low confidence band, which
means invisible -- not a bar drawn between two numbers nobody said.

The idempotency key
-------------------
`promotions.url` is UNIQUE and one page carries N campaigns, so the page URL
cannot be the key for more than one of them. Each row's url is therefore
`{page_url}#{slug(campaign_name)}` -- stable across runs (the same campaign
name yields the same fragment), unique within the page, and still a link a
human can click, since a fragment the page does not define is ignored by every
browser. The alternative -- an index (`#1`, `#2`) -- would be stable only as
long as the carrier never reorders its cards, and reordering would silently
rewrite every campaign on the page.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache

from app.agents.campaign_airline import validate_campaign
from app.core.logging import get_logger
from app.core.tr_dates import format_optional_range, format_short_date
from app.data import airports_by_iata, country_name
from app.llm.classify import CampaignExtraction
from app.llm.gazetteer import (
    AIRLINE_ALIASES,
    AMBIGUOUS_BARE_CODES,
    COUNTRY_ALIASES,
    fold_for_match,
)
from app.models.promotion import Promotion
from app.pipeline.confidence import HIGH_THRESHOLD, ConfidenceInput, score
from app.pipeline.promo_dedup import PromoCandidate
from app.pipeline.promotions import find_dates_flagged
from app.schemas.campaign import (
    DATE_FIELDS,
    EVIDENCE_FIELDS,
    RawCampaignItem,
    parse_campaign_payload,
)
from app.taxonomy import COUNTRY_TO_REGION, REGION_LABELS_TR

logger = get_logger(__name__)

#: What a campaign row needs before it can be called complete. Not the same
#: list as agents/campaign_airline.REQUIRED_FIELDS: a news article about a
#: campaign is doing well to state a sale window at all, while a carrier's own
#: page states the terms it is selling on, so an official row missing its rate
#: *and* its route is missing something the source had.
REQUIRED_FIELDS: tuple[str, ...] = ("sale_window", "route_scope", "offer_terms")

#: Phrases that mean "everywhere we fly". Written folded (fold_for_match:
#: lowercase, diacritics stripped, punctuation collapsed) because that is the
#: space they are matched in -- "tüm uçuşlarda" is "tum ucuslarda" there.
NETWORK_WIDE_CUES: tuple[str, ...] = (
    "tum ucus", "tum hat", "tum destinasyon", "tum seferler", "butun ucus",
    "tum yurt disi", "tum yurt ici", "tum noktalar",
    "all flights", "all destinations", "all routes", "all our destinations",
    "network wide", "networkwide", "entire network", "everywhere we fly",
)

#: Turkish exonyms for the cities this product's carriers actually sell. The
#: bundled airport dataset carries local/English city names ("London",
#: "Vienna"), and a Turkish campaign page writes "Londra'ya" -- without this
#: map those pages resolve to nothing at all. Deliberately short and
#: hand-checked rather than generated: a wrong city here is a wrong campaign
#: market on an analyst's screen, and the long tail is better left unresolved
#: (route_scope null) than guessed.
TR_CITY_EXONYMS: dict[str, str] = {
    "londra": "London", "roma": "Rome", "atina": "Athens", "viyana": "Vienna",
    "munih": "Munich", "moskova": "Moscow", "kahire": "Cairo", "tiflis": "Tbilisi",
    "baku": "Baku", "saraybosna": "Sarajevo", "budapeste": "Budapest",
    "belgrad": "Belgrade", "kopenhag": "Copenhagen", "cenevre": "Geneva",
    "milano": "Milan", "floransa": "Florence", "prag": "Prague",
    "varsova": "Warsaw", "lizbon": "Lisbon", "bruksel": "Brussels",
    "marsilya": "Marseille", "selanik": "Thessaloniki", "sam": "Damascus",
    "tahran": "Tehran", "pekin": "Beijing", "seul": "Seoul", "tokyo": "Tokyo",
    "abu dabi": "Abu Dhabi", "dubai": "Dubai", "doha": "Doha",
    "new york": "New York", "los angeles": "Los Angeles", "sikago": "Chicago",
}

#: Trailing Turkish case endings on a proper noun, as their own folded token:
#: "İstanbul'dan" folds to "istanbul dan" because the apostrophe collapses to a
#: space. Stripping one trailing suffix token is what lets "Avrupa'ya" match
#: "avrupa" -- and it is limited to one token, and only these, so it can never
#: eat a real second word of a two-word place name.
_TR_SUFFIX_TOKENS: frozenset[str] = frozenset(
    {"a", "e", "ya", "ye", "da", "de", "ta", "te", "dan", "den", "tan", "ten",
     "na", "ne", "nda", "nde", "ndan", "nden", "i", "ı", "u", "un", "in", "nin",
     "nun", "ile", "icin", "arasi", "arasinda"}
)

#: "IST-LHR" written into a single field. The model is asked for origin and
#: destination separately, but campaign copy writes the pair as one token often
#: enough that refusing to read it would be pedantry.
_PAIR_SEPARATOR = re.compile(r"\s*(?:-|–|—|>|→|/|\bto\b|\bile\b)\s*", re.IGNORECASE)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

#: Coarsest-last. The scope of a route is the coarsest thing either end forces:
#: a country-to-airport campaign is a COUNTRY campaign, because the country end
#: is the part we would be inventing detail about.
_GRANULARITY = {"airport": 0, "city": 1, "country": 2, "region": 3}
_SCOPE_BY_GRANULARITY = {0: "OND", 1: "CITY_PAIR", 2: "COUNTRY", 3: "REGION"}


# --- small lookups -----------------------------------------------------------


@lru_cache(maxsize=1)
def _city_index() -> dict[str, tuple[str, str | None]]:
    """Folded city name -> (city as the dataset writes it, country or None).

    Cities resolve to a NAME, never to an airport code. The alias table is
    built from airport names, so `fold_for_match("paris")` lands on Le Bourget
    and `"roma"` on Roma, Queensland -- picking one of a city's airports is an
    invention, and for a campaign it is the wrong kind of precision anyway
    ("İstanbul'dan Londra'ya" is not a statement about Heathrow).

    The country comes with it only when every airport in the dataset writing
    that city name agrees on it. There are two Tripolis and three Springfields,
    and filing a campaign under the wrong country is worse than filing it under
    none: the analyst's region filter would quietly hide it from the market it
    belongs to.
    """
    countries: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for airport in airports_by_iata().values():
        if not airport.city:
            continue
        folded = fold_for_match(airport.city)
        names.setdefault(folded, airport.city)
        country = country_name(airport.country)
        if country:
            countries.setdefault(folded, set()).add(country)

    index: dict[str, tuple[str, str | None]] = {}
    for folded, city in names.items():
        found = countries.get(folded, set())
        index[folded] = (city, found.pop() if len(found) == 1 else None)
    for turkish, english in TR_CITY_EXONYMS.items():
        entry = index.get(fold_for_match(english))
        index[fold_for_match(turkish)] = entry or (english, None)
    return index


@lru_cache(maxsize=1)
def _region_aliases() -> dict[str, str]:
    """Folded region name (TR and EN) -> world-region slug."""
    aliases: dict[str, str] = {}
    for slug, label_tr in REGION_LABELS_TR.items():
        aliases[fold_for_match(label_tr)] = slug
        aliases[fold_for_match(slug.replace("-", " "))] = slug
    aliases.update(
        {
            "ortadogu": "middle-east",
            "uzak dogu": "asia",
            "avrupa kitasi": "europe",
            "amerika": "north-america",
            "far east": "asia",
            "middle east": "middle-east",
        }
    )
    return aliases


def slugify_campaign(name: str) -> str:
    """The per-campaign URL fragment. Stable for a stable campaign name."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("-", ascii_name.lower()).strip("-")[:80]
    return slug or "kampanya"


def campaign_url(page_url: str, name: str) -> str:
    """`promotions.url` for one campaign on a shared page. See module docstring."""
    return f"{page_url}#{slugify_campaign(name)}"


# --- entity validation: airline ---------------------------------------------


def named_airlines(text: str) -> set[str]:
    """IATA codes of every airline the gazetteer can find named in `text`."""
    folded = f" {fold_for_match(text)} "
    found: set[str] = set()
    for alias, (_name, code) in AIRLINE_ALIASES.items():
        if f" {alias} " in folded:
            found.add(code)
    return found


def _airline_mismatch(item: RawCampaignItem, carrier_code: str) -> str | None:
    """The other carrier this campaign belongs to, or None.

    A campaign page carries partner offers ("flydubai ile Maldivler"), and a
    row attributed to the wrong airline is the single error this whole rebuild
    started from. The rule is narrow on purpose: another carrier is only
    disqualifying when the page's own carrier is not named alongside it, so a
    codeshare campaign naming both stays with the airline whose site it is on.
    """
    named = named_airlines(item.quoted_text())
    others = named - {carrier_code}
    if others and carrier_code not in named:
        return sorted(others)[0]
    return None


# --- entity validation: route ------------------------------------------------


@dataclass(frozen=True)
class RouteEndpoint:
    kind: str  # airport | city | country | region | unknown
    text: str
    code: str | None = None
    airport: str | None = None
    city: str | None = None
    country: str | None = None
    region: str | None = None

    def as_json(self) -> dict:
        return {
            key: value
            for key, value in {
                "kind": self.kind,
                "text": self.text,
                "code": self.code,
                "airport": self.airport,
                "city": self.city,
                "country": self.country,
                "region": self.region,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class RouteResolution:
    scope: str | None
    ond: str | None = None
    origin_code: str | None = None
    dest_code: str | None = None
    origin: RouteEndpoint | None = None
    dest: RouteEndpoint | None = None

    def as_json(self) -> dict | None:
        payload: dict = {}
        if self.origin is not None:
            payload["origin"] = self.origin.as_json()
        if self.dest is not None:
            payload["dest"] = self.dest.as_json()
        if self.scope:
            payload["scope"] = self.scope
        return payload or None

    def markets(self) -> dict | None:
        """The cascading-filter view: regions, countries, cities.

        Airports contribute their city and country rather than their code --
        `markets_json` is what the Region -> Country -> City filter reads, and
        an IATA code is not any of those three.
        """
        buckets: dict[str, list[str]] = {"regions": [], "countries": [], "cities": []}
        for endpoint in (self.origin, self.dest):
            if endpoint is None:
                continue
            for key, value in (
                ("regions", endpoint.region),
                ("countries", endpoint.country),
                ("cities", endpoint.city),
            ):
                if value and value not in buckets[key]:
                    buckets[key].append(value)
        return buckets if any(buckets.values()) else None


def _strip_case_suffix(folded: str) -> str:
    """"istanbul dan" -> "istanbul". One trailing suffix token, no more."""
    tokens = folded.split()
    if len(tokens) > 1 and tokens[-1] in _TR_SUFFIX_TOKENS:
        return " ".join(tokens[:-1])
    return folded


def _country_endpoint(name: str, raw: str) -> RouteEndpoint:
    return RouteEndpoint(
        kind="country",
        text=raw,
        country=name,
        region=COUNTRY_TO_REGION.get(name),
    )


def resolve_endpoint(raw: str | None) -> RouteEndpoint | None:
    """One end of a route, resolved as precisely as the words allow.

    Order is most-specific-first, with one exception: countries and regions are
    asked before the airport alias table, because that table is built from
    airport *names* and would happily answer "Georgia" with an airport in the
    US state.
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    bare = text.replace(".", "").strip()
    if len(bare) == 3 and bare.isalpha():
        code = bare.upper()
        airport = airports_by_iata().get(code)
        # An ambiguous code is only read as a code when it is written like one.
        # "May" in an origin field is not Mayaguana.
        if airport is not None and (bare.isupper() or code not in AMBIGUOUS_BARE_CODES):
            return RouteEndpoint(
                kind="airport",
                text=text,
                code=code,
                airport=airport.name,
                city=airport.city or None,
                country=country_name(airport.country),
                region=COUNTRY_TO_REGION.get(country_name(airport.country) or ""),
            )

    folded = fold_for_match(text)
    for candidate in (folded, _strip_case_suffix(folded)):
        if not candidate:
            continue
        region = _region_aliases().get(candidate)
        if region:
            return RouteEndpoint(kind="region", text=text, region=region)
        country = COUNTRY_ALIASES.get(candidate)
        if country:
            return _country_endpoint(country, text)
        city = _city_index().get(candidate)
        if city:
            name, country = city
            return RouteEndpoint(
                kind="city",
                text=text,
                city=name,
                country=country,
                region=COUNTRY_TO_REGION.get(country or ""),
            )

    # Stated but unresolved. Recorded rather than dropped: the analyst can see
    # what the page said, and route_scope stays null because we genuinely do
    # not know how wide this is.
    return RouteEndpoint(kind="unknown", text=text)


def _split_pair(raw: str | None) -> tuple[str | None, str | None]:
    """"IST-LHR" -> ("IST", "LHR"). Anything else comes back unsplit."""
    if not raw:
        return None, None
    parts = [part for part in _PAIR_SEPARATOR.split(raw.strip()) if part]
    if len(parts) == 2:
        return parts[0], parts[1]
    return raw, None


def is_network_wide(text: str) -> bool:
    folded = fold_for_match(text or "")
    return any(cue in folded for cue in NETWORK_WIDE_CUES)


def resolve_route(
    origin: str | None, destination: str | None, *, text: str = ""
) -> RouteResolution:
    """Origin/destination as the page wrote them -> scope, codes, detail.

    The ladder never climbs: OND requires two airports, CITY_PAIR two
    city-or-airport ends, and anything coarser at either end drags the whole
    route down to that level. "Türkiye'den Avrupa'ya" is REGION with no `ond`
    and no codes -- fanning a region out into the airport pairs it *might*
    mean is the single most tempting wrong enrichment available here, and it
    would invent a competitive claim the carrier never made.
    """
    if destination is None:
        origin, destination = _split_pair(origin)

    start = resolve_endpoint(origin)
    end = resolve_endpoint(destination)

    known = [e for e in (start, end) if e is not None and e.kind != "unknown"]
    scope: str | None = None
    if len(known) == 2:
        scope = _SCOPE_BY_GRANULARITY[max(_GRANULARITY[e.kind] for e in known)]
    elif len(known) == 1:
        only = known[0]
        if only.kind in ("region", "country"):
            # "Avrupa'ya kampanya" is a real, publishable scope on its own.
            scope = "REGION" if only.kind == "region" else "COUNTRY"
        elif is_network_wide(text):
            # "İstanbul'dan tüm hatlarda": one end plus the whole network.
            scope = "NETWORK_WIDE"
    elif is_network_wide(text):
        scope = "NETWORK_WIDE"

    origin_code = start.code if start and start.kind == "airport" else None
    dest_code = end.code if end and end.kind == "airport" else None
    ond = f"{origin_code}-{dest_code}" if scope == "OND" else None

    return RouteResolution(
        scope=scope,
        ond=ond,
        origin_code=origin_code,
        dest_code=dest_code,
        origin=start,
        dest=end,
    )


# --- date validation ---------------------------------------------------------


def _dates_in(text: str, default_year: int) -> set[date]:
    return {parsed for _offset, parsed, _inferred in find_dates_flagged(text, default_year)}


@dataclass
class DateVerdict:
    values: dict[str, date | None] = field(default_factory=dict)
    evidence: dict[str, dict] = field(default_factory=dict)
    flags: dict = field(default_factory=dict)
    checked: int = 0
    agreed: int = 0

    @property
    def agreement(self) -> float | None:
        """Regex-vs-LLM agreement, or None when there was nothing to check."""
        if self.checked == 0:
            return None
        return self.agreed / self.checked


def verify_dates(item: RawCampaignItem, page_text: str, *, default_year: int) -> DateVerdict:
    """Cross-check every date the model returned against the page itself.

    Two shapes, one rule. An ISO date is believed only if the deterministic
    parser finds that same date in the model's own quote or somewhere on the
    page (or the page writes it in ISO outright, which the regexes do not
    read). A `date_text` string is believed only if it actually appears on the
    page, and its year -- absent by construction, that is what the field is for
    -- is completed from the scan year and flagged.

    An unverifiable date is dropped, not down-weighted into the column. A date
    in `sale_ends` is drawn as the end of a bar and read as a deadline; there
    is no rendering of "we are 40% sure this is when it closes". The rejected
    value stays in `evidence_json` so the failure is auditable instead of
    invisible.
    """
    verdict = DateVerdict()
    folded_page = fold_for_match(page_text)
    page_dates = _dates_in(page_text, default_year)
    inferred_fields: list[str] = []

    for field_name in DATE_FIELDS:
        quote = item.quote_for(field_name)
        value: date | None = getattr(item, field_name)

        if value is not None:
            verdict.checked += 1
            quoted_dates = _dates_in(quote, default_year) if quote else set()
            corroborated = (
                value in quoted_dates
                or value in page_dates
                or value.isoformat() in page_text
            )
            if corroborated:
                verdict.agreed += 1
                verdict.values[field_name] = value
                verdict.evidence[field_name] = {
                    "value": value.isoformat(),
                    "source_text": quote,
                    "confidence": 1.0 if quoted_dates else 0.8,
                }
            else:
                verdict.values[field_name] = None
                verdict.evidence[field_name] = {
                    "value": None,
                    "source_text": quote,
                    "confidence": 0.0,
                    "rejected_value": value.isoformat(),
                    "note": "Model tarihi verdi ancak sayfa metninde doğrulanamadı.",
                }
            continue

        raw_text_value = item.date_text.get(field_name)
        if not raw_text_value:
            continue

        verdict.checked += 1
        if fold_for_match(raw_text_value) not in folded_page:
            verdict.values[field_name] = None
            verdict.evidence[field_name] = {
                "value": None,
                "source_text": raw_text_value,
                "confidence": 0.0,
                "note": "Alıntı sayfa metninde bulunamadı.",
            }
            continue

        parsed = find_dates_flagged(raw_text_value, default_year)
        if not parsed:
            verdict.values[field_name] = None
            verdict.evidence[field_name] = {
                "value": None,
                "source_text": raw_text_value,
                "confidence": 0.0,
                "note": "Tarih metinden çözülemedi.",
            }
            continue

        _offset, resolved, inferred = parsed[0]
        verdict.agreed += 1
        verdict.values[field_name] = resolved
        if inferred:
            inferred_fields.append(field_name)
        verdict.evidence[field_name] = {
            "value": resolved.isoformat(),
            "source_text": raw_text_value,
            "confidence": 0.7 if inferred else 1.0,
            **({"inferred_year": True} if inferred else {}),
        }

    if inferred_fields:
        verdict.flags["inferred_year"] = True
        verdict.flags["inferred_year_fields"] = inferred_fields

    _drop_reversed_windows(verdict)
    return verdict


def _drop_reversed_windows(verdict: DateVerdict) -> None:
    """A window that ends before it starts is not a window.

    Both ends go, not just one: there is no way to tell which of the two the
    model misread, and keeping the "plausible-looking" half would publish a
    date chosen by a coin flip.
    """
    for start_field, end_field in (("booking_start", "booking_end"), ("travel_start", "travel_end")):
        start, end = verdict.values.get(start_field), verdict.values.get(end_field)
        if start and end and end < start:
            for name in (start_field, end_field):
                verdict.values[name] = None
                entry = verdict.evidence.setdefault(name, {})
                entry["rejected_value"] = entry.get("value")
                entry["value"] = None
                entry["confidence"] = 0.0
                entry["note"] = "Tarih aralığı ters (bitiş başlangıçtan önce)."


# --- the extracted campaign --------------------------------------------------


@dataclass(frozen=True)
class ExtractedCampaign:
    """One validated campaign, carrying everything a Promotion row needs."""

    campaign_name: str
    url: str
    carrier_code: str
    carrier_name: str
    summary_tr: str
    campaign_type: str | None
    business_class: str
    classification_reason: str
    discount_pct: int | None
    sale_starts: date | None
    sale_ends: date | None
    travel_starts: date | None
    travel_ends: date | None
    route: RouteResolution
    attrs_json: dict
    evidence_json: dict
    date_flags_json: dict | None
    confidence_score: float
    confidence_band: str
    confidence_detail: dict
    review_required: bool
    raw_text: str
    content_hash: str | None
    source_name: str
    detected_at: datetime

    @property
    def has_sale_window(self) -> bool:
        return self.sale_starts is not None or self.sale_ends is not None


@dataclass(frozen=True)
class PageExtraction:
    """What one page produced, and whether the page was actually read.

    `succeeded` is not "found campaigns": a page the model read and correctly
    found nothing on succeeded. The distinction is what deep_scan's carry-over
    depends on -- a failed page must stay queued for the next run, an empty one
    must not be re-asked forever.
    """

    campaigns: tuple[ExtractedCampaign, ...] = ()
    succeeded: bool = True
    reason: str | None = None
    dropped: tuple[tuple[str, str], ...] = ()
    llm_calls: int = 0

    @property
    def count(self) -> int:
        return len(self.campaigns)


def _summary_for(item: RawCampaignItem, values: dict[str, date | None]) -> str:
    """A factual Turkish line, assembled from what was verified.

    Not a translation and not a rewrite of the carrier's marketing copy: every
    clause here is a field that survived validation, so the summary cannot say
    anything the row does not.
    """
    return compose_summary(
        discount_pct=item.discount_pct,
        price_floor=item.price_floor,
        currency=item.currency,
        promo_code=item.promo_code,
        values=values,
    )


def compose_summary(
    *,
    discount_pct: int | None,
    price_floor: float | None,
    currency: str | None,
    promo_code: str | None,
    values: dict[str, date | None],
    extra: str | None = None,
) -> str:
    """The summary sentence, from fields rather than from a RawCampaignItem.

    Shared with the structured path (`build_structured_campaign`), which has
    the same fields and no model answer to carry them in. `extra` is one
    leading clause a structured source can state that no prose has -- SQ's
    cabin, for instance -- and it goes first because it qualifies everything
    after it.
    """
    parts: list[str] = []
    if extra:
        parts.append(extra)
    if discount_pct is not None:
        parts.append(f"%{discount_pct} indirim")
    if price_floor is not None and currency:
        parts.append(f"{price_floor:g} {currency} taban fiyat")
    parts.extend(_window_phrase("Satış", values.get("booking_start"), values.get("booking_end")))
    parts.extend(_window_phrase("Seyahat", values.get("travel_start"), values.get("travel_end")))
    if promo_code:
        parts.append(f"promosyon kodu {promo_code}")
    if not parts:
        return ""
    # Not capitalised: the first clause is usually "%30 indirim", and
    # str.capitalize() would also lowercase everything after it -- turning
    # "15 Eylül" into "15 eylül" and a promo code into gibberish.
    return f"{'; '.join(parts)}."


def _window_phrase(label: str, starts: date | None, ends: date | None) -> list[str]:
    """One clause naming a window, or nothing when the page states neither end.

    `format_optional_range`'s "başlangıç belirtilmedi — 15 Eylül" is the right
    phrasing for a table cell and the wrong one for a sentence, so a half-known
    window is written the way the page itself writes it: a deadline.
    """
    if starts and ends:
        return [f"{label.lower()} {format_optional_range(starts, ends)}"]
    if ends:
        return [f"son {'rezervasyon' if label == 'Satış' else 'seyahat'} tarihi {format_short_date(ends)}"]
    if starts:
        return [f"{label.lower()} {format_short_date(starts)} tarihinde başlıyor"]
    return []


def _evidence_for(item: RawCampaignItem, date_evidence: dict[str, dict]) -> dict:
    """Per-field {value, source_text, confidence}, dates already judged.

    Confidence here is about the *citation*, not about the campaign: a value
    the model quoted the page for is worth more than the same value asserted
    bare, and that difference is the only thing this layer can honestly
    measure for a non-date field.
    """
    evidence: dict = dict(date_evidence)
    for name in EVIDENCE_FIELDS:
        if name in DATE_FIELDS:
            continue
        value = getattr(item, name, None)
        if value is None:
            continue
        quote = item.quote_for(name)
        evidence[name] = {
            "value": value,
            "source_text": quote,
            "confidence": 0.9 if quote else 0.5,
        }
    return evidence


def _citation_ratio(item: RawCampaignItem) -> float | None:
    """How much of what the model asserted it was willing to quote for.

    Stands in for the per-campaign certainty the page prompt deliberately does
    not ask for: a self-reported number from a model that is answering about
    twenty-two campaigns at once is worth less than counting whether it cited
    the page for each one.
    """
    stated = [name for name in EVIDENCE_FIELDS if getattr(item, name, None) is not None]
    stated += [name for name in DATE_FIELDS if item.date_text.get(name)]
    if not stated:
        return None
    quoted = sum(
        1
        for name in stated
        if item.quote_for(name) or (name in DATE_FIELDS and item.date_text.get(name))
    )
    return quoted / len(stated)


def _completeness(values: dict[str, date | None], item: RawCampaignItem, route: RouteResolution) -> int:
    present = 0
    if values.get("booking_start") or values.get("booking_end"):
        present += 1
    if route.scope:
        present += 1
    if item.discount_pct is not None or item.price_floor is not None or item.promo_code:
        present += 1
    return present


def _campaign_for_rules(item: RawCampaignItem, values: dict[str, date | None], carrier_code: str):
    return CampaignExtraction(
        airline_code=carrier_code,
        discount_pct=item.discount_pct,
        sale_starts=values.get("booking_start"),
        sale_ends=values.get("booking_end"),
        travel_starts=values.get("travel_start"),
        travel_ends=values.get("travel_end"),
        markets={},
    )


def _reason_with_evidence(base: str, route: RouteResolution, verdict: DateVerdict) -> str:
    """The rule layer's Turkish sentence, plus what the page actually backed up."""
    extras: list[str] = []
    if verdict.checked:
        extras.append(f"{verdict.agreed}/{verdict.checked} tarih sayfa metninde doğrulandı")
    if route.scope:
        extras.append(f"rota kapsamı {route.scope}")
    if verdict.flags.get("inferred_year"):
        extras.append("yıl sayfada yazmadığı için tarama yılından tamamlandı")
    if not extras:
        return base
    return f"{base.rstrip('.')} — {', '.join(extras)}."


async def extract_campaigns_from_page(
    raw_text: str,
    *,
    carrier,
    page_url: str,
    source_quality: float = 1.0,
    detected_at: datetime,
    today: date,
    content_hash: str | None = None,
    generate=None,
) -> PageExtraction:
    """Run the whole chain over one page's already-extracted text.

    `generate` is the raw completion coroutine; None means "ask the factory",
    and a factory that has no live model configured is a FAILED page -- never a
    heuristic pass over a carrier's whole offers page. `raw_text` is the
    normalised text deep_scan already read in this run, so no page is fetched
    twice within a run.
    """
    if generate is None:
        from app.llm.factory import get_raw_generator

        generate = get_raw_generator()
    if generate is None:
        logger.warning("campaign_extract_no_llm", carrier=carrier.code, url=page_url)
        return PageExtraction(succeeded=False, reason="no_llm_configured")

    from app.llm.campaign_prompt import build_campaign_page_prompt

    prompt = build_campaign_page_prompt(
        carrier.code, carrier.display_name, page_url, raw_text
    )
    try:
        response = await generate(prompt)
    except Exception as exc:  # noqa: BLE001 -- any provider failure is a FAILED page
        logger.warning(
            "campaign_extract_call_failed", carrier=carrier.code, url=page_url, error=str(exc)
        )
        return PageExtraction(succeeded=False, reason="llm_call_error", llm_calls=1)

    # The same JSON extractor the article path uses: models fence their output
    # however firmly they are asked not to, and one page's formatting habit
    # must not read as a different failure here than it does there.
    from app.llm.classify import _extract_json

    payload = _extract_json(response or "")
    try:
        page = parse_campaign_payload(payload)
    except ValueError as exc:
        # No retry, deliberately. llm/classify.py does not retry a malformed
        # response either, and a second call is a second charge against a
        # shared free tier for a model that has already answered the wrong
        # question once. The page stays queued (deep_scan withholds its hash),
        # so the next scheduled run tries again for free.
        logger.info(
            "campaign_extract_schema_failed",
            carrier=carrier.code,
            url=page_url,
            error=str(exc),
            sample=(response or "")[:160],
        )
        return PageExtraction(succeeded=False, reason=f"schema_error:{exc}", llm_calls=1)

    default_year = detected_at.year
    campaigns: list[ExtractedCampaign] = []
    dropped: list[tuple[str, str]] = []

    for item in page.campaigns:
        other_airline = _airline_mismatch(item, carrier.code)
        if other_airline:
            dropped.append((item.campaign_name, f"airline_mismatch:{other_airline}"))
            logger.info(
                "campaign_extract_airline_mismatch",
                carrier=carrier.code,
                found=other_airline,
                campaign=item.campaign_name,
            )
            continue

        verdict = verify_dates(item, raw_text, default_year=default_year)
        rule_input = _campaign_for_rules(item, verdict.values, carrier.code)
        rule_verdict = validate_campaign(
            item.campaign_name, rule_input, today=today, text=item.quoted_text()
        )
        if not rule_verdict.is_classified:
            dropped.append((item.campaign_name, rule_verdict.reason or "rejected"))
            logger.info(
                "campaign_extract_rule_rejected",
                carrier=carrier.code,
                campaign=item.campaign_name,
                reason=rule_verdict.reason,
                classification_reason=rule_verdict.details.get("classification_reason"),
            )
            continue

        route = resolve_route(item.origin, item.destination, text=item.quoted_text())
        source_tier = "official" if source_quality >= 0.9 else "trade"
        confidence = score(
            ConfidenceInput(
                source_tier=source_tier,
                classifier_certainty=_citation_ratio(item),
                required_fields_present=_completeness(verdict.values, item, route),
                required_fields_total=len(REQUIRED_FIELDS),
                # The dormant weight, finally fed: how much of what the model
                # said about dates the deterministic parser could confirm.
                signal_agreement=verdict.agreement,
                source_count=1,
            )
        )

        campaigns.append(
            ExtractedCampaign(
                campaign_name=item.campaign_name,
                url=campaign_url(page_url, item.campaign_name),
                carrier_code=carrier.code,
                carrier_name=carrier.display_name,
                summary_tr=_summary_for(item, verdict.values),
                campaign_type=item.campaign_type,
                business_class=rule_verdict.details.get("business_class") or "ACTIVE_CAMPAIGN",
                classification_reason=_reason_with_evidence(
                    rule_verdict.details.get("classification_reason") or "", route, verdict
                ),
                discount_pct=item.discount_pct,
                # booking -> sale, travel -> travel. The prompt asks in the
                # words a campaign page uses; the columns are named for what
                # they have always meant, and the two are mapped exactly once,
                # here.
                sale_starts=verdict.values.get("booking_start"),
                sale_ends=verdict.values.get("booking_end"),
                travel_starts=verdict.values.get("travel_start"),
                travel_ends=verdict.values.get("travel_end"),
                route=route,
                attrs_json={
                    key: value
                    for key, value in {
                        "cabin": item.cabin,
                        "promo_code": item.promo_code,
                        "currency": item.currency,
                        "price_floor": item.price_floor,
                        "sales_channel": item.sales_channel,
                        "eligibility": item.eligibility,
                        "is_fare_campaign": item.is_fare_campaign,
                        "route_scope_hint": item.route_scope_hint,
                        "dropped_fields": item.dropped_fields or None,
                        "source_quality": source_quality,
                    }.items()
                    if value is not None
                },
                evidence_json=_evidence_for(item, verdict.evidence),
                date_flags_json=verdict.flags or None,
                confidence_score=confidence.score,
                confidence_band=confidence.band,
                confidence_detail=confidence.as_detail(),
                review_required=confidence.score < HIGH_THRESHOLD,
                raw_text=item.quoted_text(),
                content_hash=content_hash,
                source_name=f"{carrier.display_name} kampanya sayfası",
                detected_at=detected_at,
            )
        )

    logger.info(
        "campaign_extract_page",
        carrier=carrier.code,
        url=page_url,
        extracted=len(campaigns),
        dropped=len(dropped),
        invalid_items=page.invalid_items,
    )
    return PageExtraction(
        campaigns=tuple(campaigns),
        succeeded=True,
        dropped=tuple(dropped),
        llm_calls=1,
    )


# --- the structured path: same chain, no model -------------------------------
#
# Two carriers publish their campaigns as JSON with the windows in their own
# labelled fields (app/ingest/ajet_campaigns.py, app/ingest/sq_campaigns.py).
# For those, links 1 and 2 of the chain -- the LLM and the schema -- have
# nothing to do: there is no prose to read and no answer to validate the shape
# of. What is left is links 3 to 5, which is exactly what this function runs.
#
# It is not a shortcut around the rule layer. `validate_campaign` still decides
# whether each item is a fare campaign, the deterministic date parser still
# reads every window, and `resolve_route` still refuses to invent a scope. The
# only thing removed is the guess, and with it the LLM call.

#: "30-31 Mart 2026" -- a two-day ticketing window written with one month and
#: one year, which is AJet's single most common shape. `find_dates_flagged`
#: reads it as one date (the 31st) because the leading "30-" is not a date on
#: its own, and taking only that would publish a one-day window for a two-day
#: sale. Narrow on purpose: both numbers, one month name, one 4-digit year,
#: anchored at the start of the field. Anything else falls through to the
#: general parser.
_TR_SHORT_DAY_RANGE = re.compile(
    r"^\s*(\d{1,2})\s*[-–—]\s*(\d{1,2})\s+([^\W\d_]+)\s+(\d{4})", re.UNICODE
)


def parse_window(raw: str | None, *, default_year: int) -> tuple[date | None, date | None, bool]:
    """A carrier's own date-range field -> (start, end, year_was_inferred).

    Same reading as `promo_scrape.parse_validity`, and deliberately so: two
    dates are a range in whatever order they appear, and ONE date alone is the
    END of an open-ended run ("30 Kasım'a kadar"), because guessing a start
    would put a bar somewhere the carrier never said it was.

    The one addition is `_TR_SHORT_DAY_RANGE` -- see above.
    """
    if not raw or not raw.strip():
        return None, None, False

    short = _TR_SHORT_DAY_RANGE.match(raw)
    if short is not None:
        first_day, last_day, month_word, year = short.groups()
        expanded = f"{first_day} {month_word} {year} - {last_day} {month_word} {year}"
        parsed = find_dates_flagged(expanded, default_year)
        if len(parsed) >= 2:
            return parsed[0][1], parsed[1][1], False

    parsed = find_dates_flagged(raw, default_year)
    inferred = any(flag for _offset, _value, flag in parsed)
    if len(parsed) >= 2:
        first, second = parsed[0][1], parsed[1][1]
        return (first, second, inferred) if second >= first else (second, first, inferred)
    if len(parsed) == 1:
        return None, parsed[0][1], inferred
    return None, None, False


@dataclass(frozen=True)
class StructuredCampaign:
    """One campaign as a structured carrier feed states it.

    Every field is either copied verbatim from a labelled field of the
    carrier's own API or left None. Nothing here is inferred from prose, which
    is the whole difference between this and `RawCampaignItem`.
    """

    campaign_name: str
    #: The row's own URL. Unlike the page path this is already unique per
    #: campaign (a CMS detail link, a fare deal's share URL), so it is not run
    #: through `campaign_url` a second time by the builder.
    url: str
    #: What the rule layer reads and what the dates are quoted against. For a
    #: JSON source this is the carrier's own description text, tags stripped.
    body_text: str = ""
    booking_text: str | None = None
    travel_text: str | None = None
    discount_pct: int | None = None
    price_floor: float | None = None
    currency: str | None = None
    cabin: str | None = None
    promo_code: str | None = None
    origin: str | None = None
    destination: str | None = None
    campaign_type: str | None = None
    #: Stated rather than judged, for a feed whose shape settles the question.
    #: `None` means "ask `validate_campaign`", which is what a prose-carrying
    #: source like AJet does.
    business_class: str | None = None
    #: One extra clause for the summary sentence; see `compose_summary`.
    summary_prefix: str | None = None
    extra_attrs: dict = field(default_factory=dict)


def build_structured_campaign(
    entry: StructuredCampaign,
    *,
    carrier,
    detected_at: datetime,
    today: date,
    source_name: str,
    source_quality: float = 1.0,
    content_hash: str | None = None,
) -> tuple[ExtractedCampaign | None, str | None]:
    """Links 3-5 of the chain over one structured record.

    Returns `(campaign, None)` when it survives, `(None, reason)` when the rule
    layer drops it -- the same two outcomes `extract_campaigns_from_page`
    produces per item, so both paths feed `deep_scan`'s counters identically.

    **On the confidence inputs**, because two of the five are judgement calls
    that a reader deserves to see argued rather than assumed:

    `classifier_certainty` is 1.0. In the LLM path that component is
    `_citation_ratio` -- how much of what the model asserted it was willing to
    quote the page for. Here every asserted value *is* a quote: it was copied
    out of a field the carrier labelled `TicketingDates` or
    `faredealOriginAirportCode`. There is no interpretation step to be
    uncertain about, so claiming less would understate what we know.

    `signal_agreement` is None, which the scorer reads as neutral rather than
    as disagreement. That component measures the deterministic parser agreeing
    with the model, and here there is no model to agree with. Feeding it 1.0
    would be counting one signal twice.
    """
    default_year = detected_at.year
    booking_start, booking_end, booking_inferred = parse_window(
        entry.booking_text, default_year=default_year
    )
    travel_start, travel_end, travel_inferred = parse_window(
        entry.travel_text, default_year=default_year
    )
    values: dict[str, date | None] = {
        "booking_start": booking_start,
        "booking_end": booking_end,
        "travel_start": travel_start,
        "travel_end": travel_end,
    }

    rule_input = CampaignExtraction(
        airline_code=carrier.code,
        discount_pct=entry.discount_pct,
        sale_starts=booking_start,
        sale_ends=booking_end,
        travel_starts=travel_start,
        travel_ends=travel_end,
        markets={},
    )
    judged_text = f"{entry.campaign_name}\n{entry.body_text}".strip()
    business_class = entry.business_class
    if business_class is None:
        verdict = validate_campaign(
            entry.campaign_name, rule_input, today=today, text=judged_text
        )
        if not verdict.is_classified:
            return None, verdict.reason or "rejected"
        business_class = verdict.details.get("business_class") or "ACTIVE_CAMPAIGN"
        classification_reason = verdict.details.get("classification_reason") or ""
    else:
        # A feed whose shape answers the question the rulepacks ask of prose.
        # Stated here rather than inferred, and the reason says which feed and
        # why, so it reads the same way in the drawer as a rule verdict does.
        classification_reason = (
            f"{carrier.display_name} yapılandırılmış kaynağından doğrudan alındı; "
            f"iş sınıfı kaynağın veri şeklinden belirlendi ({business_class})."
        )

    route = resolve_route(entry.origin, entry.destination, text=judged_text)

    evidence: dict = {}
    for name, raw_text, resolved, inferred in (
        ("booking_start", entry.booking_text, booking_start, booking_inferred),
        ("booking_end", entry.booking_text, booking_end, booking_inferred),
        ("travel_start", entry.travel_text, travel_start, travel_inferred),
        ("travel_end", entry.travel_text, travel_end, travel_inferred),
    ):
        if resolved is None:
            continue
        evidence[name] = {
            "value": resolved.isoformat(),
            "source_text": raw_text,
            "confidence": 0.7 if inferred else 1.0,
            **({"inferred_year": True} if inferred else {}),
        }
    for name, value in (
        ("discount_pct", entry.discount_pct),
        ("price_floor", entry.price_floor),
        ("currency", entry.currency),
        ("cabin", entry.cabin),
        ("promo_code", entry.promo_code),
    ):
        if value is None:
            continue
        evidence[name] = {
            "value": value,
            "source_text": entry.campaign_name,
            "confidence": 1.0,
        }

    flags: dict = {}
    inferred_fields = [
        name
        for name, inferred in (
            ("booking_start", booking_inferred and booking_start is not None),
            ("booking_end", booking_inferred and booking_end is not None),
            ("travel_start", travel_inferred and travel_start is not None),
            ("travel_end", travel_inferred and travel_end is not None),
        )
        if inferred
    ]
    if inferred_fields:
        flags["inferred_year"] = True
        flags["inferred_year_fields"] = inferred_fields

    completeness = 0
    if booking_start or booking_end:
        completeness += 1
    if route.scope:
        completeness += 1
    if entry.discount_pct is not None or entry.price_floor is not None or entry.promo_code:
        completeness += 1

    confidence = score(
        ConfidenceInput(
            source_tier="official" if source_quality >= 0.9 else "trade",
            classifier_certainty=1.0,
            required_fields_present=completeness,
            required_fields_total=len(REQUIRED_FIELDS),
            signal_agreement=None,
            source_count=1,
        )
    )

    attrs = {
        key: value
        for key, value in {
            "cabin": entry.cabin,
            "promo_code": entry.promo_code,
            "currency": entry.currency,
            "price_floor": entry.price_floor,
            "source_quality": source_quality,
            # The one attribute the LLM path can never carry: this row was not
            # read by a model at all. Worth being able to filter on when the
            # two paths' precision is compared.
            "extraction_method": "structured",
            **entry.extra_attrs,
        }.items()
        if value is not None
    }

    return (
        ExtractedCampaign(
            campaign_name=entry.campaign_name,
            url=entry.url,
            carrier_code=carrier.code,
            carrier_name=carrier.display_name,
            summary_tr=compose_summary(
                discount_pct=entry.discount_pct,
                price_floor=entry.price_floor,
                currency=entry.currency,
                promo_code=entry.promo_code,
                values=values,
                extra=entry.summary_prefix,
            ),
            campaign_type=entry.campaign_type,
            business_class=business_class,
            classification_reason=_reason_with_evidence(
                classification_reason, route, DateVerdict()
            ),
            discount_pct=entry.discount_pct,
            sale_starts=booking_start,
            sale_ends=booking_end,
            travel_starts=travel_start,
            travel_ends=travel_end,
            route=route,
            attrs_json=attrs,
            evidence_json=evidence,
            date_flags_json=flags or None,
            confidence_score=confidence.score,
            confidence_band=confidence.band,
            confidence_detail=confidence.as_detail(),
            review_required=confidence.score < HIGH_THRESHOLD,
            raw_text=judged_text[:2000],
            content_hash=content_hash,
            source_name=source_name,
            detected_at=detected_at,
        ),
        None,
    )


# --- persistence helpers -----------------------------------------------------


def candidate_for(extracted: ExtractedCampaign) -> PromoCandidate:
    """The dedup view of an extracted campaign.

    Every write path asks promo_dedup first (see that module): the same
    campaign reported by a news article and published on the carrier's own page
    are one campaign with two URLs, and inserting both draws it twice.
    """
    markets = extracted.route.markets() or {}
    flat = ",".join(
        value
        for key in ("regions", "countries", "cities")
        for value in markets.get(key, [])
    )
    return PromoCandidate(
        airline_code=extracted.carrier_code,
        airline_name=extracted.carrier_name,
        title_tr=extracted.campaign_name,
        summary_tr=extracted.summary_tr,
        url=extracted.url,
        source_name=extracted.source_name,
        detected_at=extracted.detected_at,
        discount_pct=extracted.discount_pct,
        markets=flat or None,
        sale_starts=extracted.sale_starts,
        sale_ends=extracted.sale_ends,
        travel_starts=extracted.travel_starts,
        travel_ends=extracted.travel_ends,
        region=(extracted.route.origin or extracted.route.dest).region
        if (extracted.route.origin or extracted.route.dest)
        else None,
        campaign_type=extracted.campaign_type,
        # Stated rather than inferred from the source name: this page is on the
        # carrier's own domain (app/ingest/carriers.py), which is what makes it
        # win a disagreement with a report about it.
        source_tier="official",
    )


#: The v2 columns whose movement belongs in a version row. Everything else
#: `_refresh_row` writes is either a blob nobody reads as a diff
#: (evidence_json, route_json, attrs_json, raw_text), a per-scan fingerprint
#: (content_hash) or a derived number that moves on its own (confidence_*). A
#: version row is read by a person asking what the carrier changed; two
#: paragraphs of JSON side by side would not answer that.
VERSIONED_V2_COLUMNS: tuple[str, ...] = (
    "campaign_type",
    "business_class",
    "route_scope",
    "ond",
    "origin_code",
    "dest_code",
)


def _refresh_row(
    row: Promotion, extracted: ExtractedCampaign, *, prefer: bool
) -> dict[str, dict]:
    """Bring the v2 columns on an existing row up to date; return what moved.

    `promo_dedup.merge_candidate` knows the columns that predate this rebuild
    and its rule -- null never overwrites a value -- is the right one here too,
    so this only handles what that function has never heard of. What happens
    here is the observation lifecycle (`last_seen_at` always moves,
    `first_seen_at` only backwards) plus filling the classification columns a
    legacy or news-sourced row does not have.

    The returned diff has the same shape `merge_candidate` returns and is
    merged into it before `record_version` writes, so one scan of one page
    produces one version row rather than two.
    """
    now = extracted.detected_at
    row.last_seen_at = now
    if row.first_seen_at is None or now < row.first_seen_at:
        row.first_seen_at = now

    changed: dict[str, dict] = {}
    for column, value in (
        ("campaign_type", extracted.campaign_type),
        ("business_class", extracted.business_class),
        ("route_scope", extracted.route.scope),
        ("ond", extracted.route.ond),
        ("origin_code", extracted.route.origin_code),
        ("dest_code", extracted.route.dest_code),
        ("route_json", extracted.route.as_json()),
        ("attrs_json", extracted.attrs_json or None),
        ("evidence_json", extracted.evidence_json or None),
        ("classification_reason", extracted.classification_reason),
        ("date_flags_json", extracted.date_flags_json),
        ("content_hash", extracted.content_hash),
        ("raw_text", extracted.raw_text),
        ("review_required", extracted.review_required),
        ("confidence_score", extracted.confidence_score),
        ("confidence_band", extracted.confidence_band),
        ("confidence_detail", extracted.confidence_detail),
    ):
        if value is None:
            continue
        previous = getattr(row, column)
        if (prefer or previous is None) and previous != value:
            setattr(row, column, value)
            if column in VERSIONED_V2_COLUMNS:
                changed[column] = {"previous": previous, "new": value}
    return changed


async def persist_extracted(db, extracted: ExtractedCampaign) -> str:
    """Insert, refresh or merge one extracted campaign. Returns which it was.

    Three cases, in the order that keeps `promotions.url` (UNIQUE) honest:

    * **Same URL.** The same campaign on the same page, seen again. That is the
      idempotency key doing its job -- refreshed in place, and the incoming
      reading wins, because it is the same source restating itself.
    * **A duplicate under another URL.** The news path already wrote this
      campaign from an article. Merged rather than inserted; the carrier's own
      page outranks the report about it (promo_dedup.is_airline_sourced), which
      is what closes the documented "insert without asking" gap for this path.
    * **New.** A row.

    Every one of the three writes its provenance: the page's URL is filed in
    `campaign_sources` (so a campaign always has at least one recorded source,
    and a merge has two), and anything that actually moved is written to
    `campaign_versions`. Creation writes no version row -- see
    `promo_dedup.record_version` for why.

    Flushed, not committed: the caller owns the transaction, exactly as
    `record_run` does.
    """
    from sqlalchemy import select

    from app.pipeline.promo_dedup import (
        ensure_source_row,
        find_duplicate,
        merge_candidate,
        record_version,
        rescore_for_corroboration,
    )

    candidate = candidate_for(extracted)
    existing = (
        await db.execute(select(Promotion).where(Promotion.url == extracted.url))
    ).scalar_one_or_none()
    if existing is not None:
        changed = merge_candidate(existing, candidate, prefer_candidate=True)
        changed.update(_refresh_row(existing, extracted, prefer=True))
        await db.flush()
        await _file_page_source(db, existing, extracted)
        await record_version(db, existing, changed, source_url=extracted.url)
        return "updated"

    match = await find_duplicate(db, candidate)
    if match is not None:
        # Read before the merge: the carrier's page is about to take the row's
        # URL and source name, and the page it displaces is the second source.
        displaced_url, displaced_source = match.url, match.source_name
        changed = merge_candidate(match, candidate)
        changed.update(_refresh_row(match, extracted, prefer=False))
        await db.flush()
        await ensure_source_row(
            db,
            match,
            url=displaced_url,
            source_name=displaced_source,
            seen_at=match.first_seen_at or match.detected_at,
        )
        await _file_page_source(db, match, extracted)
        await rescore_for_corroboration(db, match)
        await record_version(db, match, changed, source_url=extracted.url)
        logger.info(
            "campaign_extract_merged",
            airline=extracted.carrier_code,
            kept_id=str(match.id),
            incoming_url=extracted.url,
        )
        return "merged"

    row = build_promotion_from_page(extracted)
    db.add(row)
    await db.flush()
    await _file_page_source(db, row, extracted)
    return "inserted"


async def _file_page_source(db, row: Promotion, extracted: ExtractedCampaign):
    """The carrier's own campaign page, as a `campaign_sources` row.

    `official` without asking: this path only ever runs over a page from
    app/ingest/carriers.py, which is the carrier's own domain by construction.
    """
    from app.pipeline.promo_dedup import ensure_source_row

    return await ensure_source_row(
        db,
        row,
        url=extracted.url,
        source_name=extracted.source_name,
        tier="official",
        quality=extracted.attrs_json.get("source_quality"),
        seen_at=extracted.detected_at,
        content_hash=extracted.content_hash,
        raw_excerpt=extracted.raw_text,
    )


def build_promotion_from_page(extracted: ExtractedCampaign) -> Promotion:
    """The row, for the deep-scan path.

    A sibling of agents/campaign_airline.build_promotion rather than a widening
    of it: that one builds a row from a news *event* (it needs the event, the
    primary article and the cluster size), and this one from a page that has
    none of those three. Sharing a signature would mean five optional
    parameters and a branch, which is two functions wearing one name.
    """
    candidate = candidate_for(extracted)
    return Promotion(
        airline_code=extracted.carrier_code,
        airline_name=extracted.carrier_name,
        title_tr=extracted.campaign_name[:300],
        summary_tr=extracted.summary_tr,
        discount_pct=extracted.discount_pct,
        markets=candidate.markets,
        markets_json=extracted.route.markets(),
        sale_starts=extracted.sale_starts,
        sale_ends=extracted.sale_ends,
        travel_starts=extracted.travel_starts,
        travel_ends=extracted.travel_ends,
        url=extracted.url[:500],
        source_name=extracted.source_name,
        region=candidate.region,
        validation_state="valid" if extracted.has_sale_window else "incomplete",
        confidence_score=extracted.confidence_score,
        confidence_band=extracted.confidence_band,
        confidence_detail=extracted.confidence_detail,
        detected_at=extracted.detected_at,
        campaign_type=extracted.campaign_type,
        business_class=extracted.business_class,
        route_scope=extracted.route.scope,
        ond=extracted.route.ond,
        origin_code=extracted.route.origin_code,
        dest_code=extracted.route.dest_code,
        route_json=extracted.route.as_json(),
        attrs_json=extracted.attrs_json or None,
        evidence_json=extracted.evidence_json or None,
        classification_reason=extracted.classification_reason,
        review_required=extracted.review_required,
        date_flags_json=extracted.date_flags_json,
        content_hash=extracted.content_hash,
        first_seen_at=extracted.detected_at,
        last_seen_at=extracted.detected_at,
        raw_text=extracted.raw_text,
    )
