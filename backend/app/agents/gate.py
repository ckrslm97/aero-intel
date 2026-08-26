"""The pre-LLM gate: is this item worth a classification call?

This runs on every fetched item, before any model call, and it is where "100
haber yerine gerçekten önemli 15 haber" actually happens. Two jobs, and only
two -- it is not a classifier and must not become one. The model decides what
an article *is*; the gate decides whether to ask.

What went wrong in the version this replaces, measured on 200 production
articles:

* **The keyword tables were English-only.** `Pegasus'ta 6 hatta yüzde 50'ye
  varan indirim kampanyası başladı` -- a direct competitor fare campaign, the
  single thing this product exists to catch -- scored zero and was filed as
  general news. "kampanya" and "indirim" existed in the taxonomy, but only as
  *subcategory* keywords, and subcategorisation runs after a category has
  already won. For a Turkish article those two words were structurally
  unreachable.

* **The decisive terms were too loose.** `offer`, `sale`, `price`, `bonus`,
  `miles` and `upgrade` each cleared the gate on their own, on a presence test,
  worth 6 points against a threshold of 6. Every credit-card blog post in the
  feed passed on its first paragraph: `Is The Amex Blue Business Credit Card
  Worth It?`, `Get more than $4,000 in value with the 200,000-point bonus`.
  25 of 200 sampled articles (12.5%) had no aviation or commercial relevance at
  all -- pumpkin spice at Starbucks, US house prices, a ceramics export figure,
  and a Vuelta a España stage win that was in the feed because the team is
  sponsored by an airline.

The fixes: every table is bilingual; a promotional term counts only alongside
an aviation term, so a discount on a hotel room is not a fare campaign; and
items whose dominant subject is a neighbouring industry -- rail, hotels, credit
cards -- are rejected by name rather than left to out-score aviation by
accident.

Rejections carry a machine-readable reason, so "what is the gate filtering"
can be answered. A gate that is too strict and a quiet news week look identical
without one.
"""
from __future__ import annotations

from app.agents.base import GateResult
from app.llm.heuristic import _keyword_pattern, _score, fold_text

# --- what makes something aviation ------------------------------------------
#
# Folded ASCII: fold_text() maps Turkish diacritics onto their bases before
# matching, so "uçuş" is written "ucus" here and "havalimanı" is "havalimani".
# Writing them with diacritics would silently never match.

AVIATION_TERMS: tuple[str, ...] = (
    # English
    "airline", "airlines", "airport", "aircraft", "flight", "flights",
    "aviation", "carrier", "carriers", "fleet", "route", "routes", "cabin",
    "passenger", "passengers", "boeing", "airbus", "embraer", "jet", "aviation",
    "runway", "terminal", "codeshare", "slot", "slots", "widebody", "narrowbody",
    "iata", "icao", "easa", "faa", "load factor", "seat", "seats", "fare",
    # Turkish -- absent entirely from the previous gate
    "havayolu", "havayollari", "havacilik", "ucus", "ucuslar", "sefer",
    "seferler", "havalimani", "havaalani", "ucak", "ucagi", "tarife", "bilet",
    "yolcu", "kabin", "filo", "pilot", "kokpit", "tasiyici", "rota", "kalkis",
    "koltuk", "ucus tarifesi", "hava trafik", "sivil havacilik",
)
_AVIATION = _keyword_pattern(AVIATION_TERMS)

# Named carriers. A story about any of these is what this desk watches, however
# briefly it is worded -- "Turkish Airlines Targets Lima" scored below the old
# gate purely for being terse.
WATCHED_CARRIERS: tuple[str, ...] = (
    "turkish airlines", "turk hava yollari", "thy", "ajet", "anadolujet",
    "pegasus", "emirates", "qatar airways", "etihad airways", "lufthansa",
    "air france", "klm", "british airways", "iberia", "wizz air", "ryanair",
    "sunexpress", "corendon",
)
_CARRIER = _keyword_pattern(WATCHED_CARRIERS)

# Commercial vocabulary -- the reason a revenue desk reads any of this.
COMMERCIAL_TERMS: tuple[str, ...] = (
    "yield", "revenue", "ancillary", "load factor", "capacity", "demand",
    "booking", "bookings", "ndc", "distribution", "network", "frequency",
    "codeshare", "joint venture", "alliance", "rask", "cask", "rpk", "ask",
    "hub", "slot", "unit revenue", "pricing", "tariff",
    "gelir", "doluluk", "kapasite", "talep", "rezervasyon", "fiyatlandirma",
    "ek gelir", "ortak ucus", "ittifak", "birim gelir", "arz", "koltuk arzi",
)
_COMMERCIAL = _keyword_pattern(COMMERCIAL_TERMS)

# Operational and industrial vocabulary. These are aviation news in their own
# right -- the taxonomy already has labor, safety and network/cancellation
# categories for them -- and the gate has to let them through or those
# categories can never be populated. `Airbus'ta Süresiz Grev Kararı` was scored
# at 3 against a threshold of 6 without this: an indefinite strike at the
# world's largest aircraft manufacturer, gated out for being tersely worded in
# Turkish.
OPERATIONAL_TERMS: tuple[str, ...] = (
    "strike", "walkout", "union", "layoff", "labour dispute", "labor dispute",
    "cancellation", "cancelled", "canceled", "grounded", "delay", "delays",
    "incident", "accident", "emergency landing", "diverted", "inspection",
    "certification", "order", "delivery", "deliveries", "maintenance",
    "grev", "is birakma", "sendika", "isten cikarma", "iptal", "gecikme",
    "rotustu", "kaza", "acil inis", "denetim", "sertifikasyon", "siparis",
    "teslimat", "bakim", "zorunlu inis",
)
_OPERATIONAL = _keyword_pattern(OPERATIONAL_TERMS)

# Promotional vocabulary. These no longer clear the gate alone -- see
# PROMO_WITH_AVIATION_BONUS.
PROMO_TERMS: tuple[str, ...] = (
    "promotion", "promo", "discount", "fare sale", "seat sale", "campaign",
    "special offer", "price cut", "cheap fare", "flash sale",
    "kampanya", "indirim", "promosyon", "firsat", "ucuz bilet",
    "erken rezervasyon", "bilet fiyati", "fiyat indirimi", "avantaj",
)
_PROMO = _keyword_pattern(PROMO_TERMS)

# --- what makes something NOT this product ----------------------------------
#
# Neighbouring industries that share vocabulary with aviation. Each of these
# produced real published rows: Etihad Rail tickets and a Eurostar review were
# shown as airline campaigns; a Marriott Bonvoy guide and a Wyndham credit-card
# review were attributed to Emirates and Turkish Airlines respectively.

DISTRACTOR_TERMS: dict[str, tuple[str, ...]] = {
    "rail": (
        "rail", "railway", "railways", "train", "trains", "rail network",
        "high-speed rail", "etihad rail", "eurostar", "amtrak", "metro line",
        "demiryolu", "tren", "hizli tren", "rayli sistem",
    ),
    "hotel": (
        "hotel", "hotels", "resort", "bonvoy", "hyatt", "marriott", "hilton",
        "wyndham", "guest room", "check-in desk", "suite",
        "otel", "tatil koyu", "konaklama",
    ),
    "card": (
        "credit card", "card review", "annual fee", "signup bonus",
        "sign-up bonus", "welcome bonus", "amex", "american express",
        "chase sapphire", "capital one", "points transfer", "reward card",
        "kredi karti", "puan transferi",
    ),
    "property": ("house prices", "housing market", "konut fiyat", "kira", "emlak"),
    "sport": (
        "vuelta", "tour de france", "la liga", "premier league", "stage win",
        "cycling", "футбол", "maç", "sampiyonlugu", "transfer donemi",
    ),
}
_DISTRACTORS = {kind: _keyword_pattern(terms) for kind, terms in DISTRACTOR_TERMS.items()}

# --- weights -----------------------------------------------------------------

#: A promotional term is worth a lot, but only when the item is also about
#: aviation. This is the single change that stops credit-card and hotel
#: content walking through: "%50 indirim" on a hotel room is not a fare sale.
PROMO_WITH_AVIATION_BONUS = 6

#: A named carrier in the title settles it.
CARRIER_TITLE_BONUS = 6

#: Google News radars deliver headlines with no body. Scoring those on the same
#: scale gates them out for the length of their body rather than for what they
#: are about.
STUB_BODY_CHARS = 120
HEADLINE_ONLY_BONUS = 3

#: Default pass mark. An item needs either a named carrier, a promotional term
#: alongside aviation vocabulary, or a genuine accumulation of aviation and
#: commercial terms.
DEFAULT_THRESHOLD = 6


def evaluate(title: str, content: str, *, threshold: int = DEFAULT_THRESHOLD) -> GateResult:
    """Score an item and decide whether it earns a classification call."""
    title_text = fold_text(title or "")
    body_text = fold_text(content or "")
    both = f"{title_text} {body_text}"

    aviation = _score(_AVIATION, title_text, body_text)
    carrier_in_title = bool(_CARRIER.search(title_text))
    carrier = _score(_CARRIER, title_text, body_text)

    # An item about a neighbouring industry that merely mentions an airline is
    # not an aviation story. Compared rather than blacklisted: an airline's own
    # hotel partnership is legitimately about both, and the stronger signal
    # should win rather than a keyword veto.
    aviation_signal = aviation + carrier
    for kind, pattern in _DISTRACTORS.items():
        distractor = _score(pattern, title_text, body_text)
        # A headline names its subject. "Etihad Rail passenger tickets: 50%
        # discount on fares" matches `passenger` and `fares` and out-scored the
        # rail signal on body counts alone -- so it was published as an airline
        # campaign, three times. When a neighbouring industry is named in the
        # title and no watched carrier is, the title wins.
        if pattern.search(title_text) and not carrier_in_title:
            return GateResult.reject(
                f"off_domain:{kind}", score=aviation_signal, distractor=distractor
            )
        if distractor > aviation_signal:
            return GateResult.reject(
                f"off_domain:{kind}", score=aviation_signal, distractor=distractor
            )

    if aviation_signal == 0:
        return GateResult.reject("no_aviation_terms")

    commercial = _score(_COMMERCIAL, title_text, body_text)
    operational = _score(_OPERATIONAL, title_text, body_text)
    promo_hit = bool(_PROMO.search(both))
    # The fix for the structurally-unreachable Turkish campaign: a promotional
    # term is a top-level gate feature now, not a subcategory keyword that only
    # gets consulted after a category has already been chosen.
    promo = PROMO_WITH_AVIATION_BONUS if promo_hit else 0
    carrier_bonus = CARRIER_TITLE_BONUS if carrier_in_title else 0
    stub = (
        HEADLINE_ONLY_BONUS
        if len(content or "") < STUB_BODY_CHARS
        and (commercial > 0 or operational > 0 or promo_hit)
        else 0
    )

    score = aviation + carrier + commercial + operational + promo + carrier_bonus + stub
    if score < threshold:
        return GateResult.reject("below_threshold", score=score)

    return GateResult.accept(
        score,
        aviation=aviation,
        carrier=carrier,
        commercial=commercial,
        operational=operational,
        promo=promo_hit,
    )
