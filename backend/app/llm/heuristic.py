"""No-key fallback pipeline: extractive summarization, keyword categorization,
lexicon sentiment, and gazetteer entity extraction. Runs with zero external
dependencies so the platform works before any LLM is configured, and is what
every other provider falls back to if a live call fails.
"""
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from app.llm.base import EntityMention
from app.llm.gazetteer import (
    AIRLINES,
    AIRPORT_COUNTRY,
    AIRPORTS,
    COUNTRIES,
    RISK_CITY_COUNTRY,
)
from app.pipeline.hashing import normalize_text
from app.taxonomy import CATEGORY_KEYWORDS, COUNTRY_TO_REGION, GENERAL_CATEGORY, SUBCATEGORY_KEYWORDS

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "has",
    "have", "had", "it", "its", "this", "that", "will", "would", "said", "also",
    "which", "their", "than", "into", "after", "before", "over", "more", "new",
    "said.",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# How much louder a keyword in the headline counts than one in the body.
_TITLE_WEIGHT = 3


@lru_cache(maxsize=None)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Match keywords as whole words, not substrings.

    Plain `text.count("ask")` also fires on "asked" and "task", and "max" fires
    on "maximum" -- so short metric names silently mis-categorised articles.
    Word boundaries make short keywords like ASK and RPK usable at all.

    An empty keyword tuple compiles to a never-matching pattern, not to "" --
    `"|".join(())` is the empty string, which matches at every position, so a
    rule with no keywords would otherwise score against every character in the
    article. (Caught exactly that way: giving the wildfire rule an empty weak
    tier made it match everything.)
    """
    if not keywords:
        return re.compile(r"(?!)")
    return re.compile("|".join(rf"\b{re.escape(kw)}\b" for kw in keywords))


def _score(pattern: re.Pattern[str], title_text: str, body_text: str) -> int:
    return len(pattern.findall(title_text)) * _TITLE_WEIGHT + len(pattern.findall(body_text))

_POSITIVE_WORDS = {
    "growth", "record", "profit", "expand", "launch", "award", "success", "improve",
    "increase", "milestone", "celebrate", "achievement", "strong", "recovery",
}
_NEGATIVE_WORDS = {
    "crash", "delay", "cancel", "loss", "strike", "grounded", "incident", "decline",
    "layoff", "investigation", "emergency", "disruption", "fine", "lawsuit",
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


class HeuristicProvider:
    name = "heuristic"

    async def generate_headline(self, title: str, content: str) -> str:
        return title.strip()

    async def generate_summary(self, title: str, content: str) -> str:
        sentences = _sentences(content)
        if not sentences:
            return ""
        if len(sentences) <= 2:
            return " ".join(sentences)

        words = normalize_text(content).split()
        freq = Counter(w for w in words if w not in _STOPWORDS)

        scored = sorted(
            range(len(sentences)),
            key=lambda i: sum(freq.get(w, 0) for w in normalize_text(sentences[i]).split()),
            reverse=True,
        )
        top_indices = sorted(scored[:3])
        return " ".join(sentences[i] for i in top_indices)

    async def categorize(self, title: str, content: str) -> str:
        # A keyword in the headline says what the story is *about*; the same
        # word buried in the body is often incidental ("...the airport shuttle
        # departs hourly"). Weighting the title heavily keeps a long body from
        # outvoting the headline on sheer word count.
        title_text = normalize_text(title)
        body_text = normalize_text(content)
        best_category = GENERAL_CATEGORY
        best_score = 0
        for category, keywords in CATEGORY_KEYWORDS.items():
            score = _score(_keyword_pattern(tuple(keywords)), title_text, body_text)
            if score > best_score:
                best_score = score
                best_category = category
        return best_category

    async def subcategorize(self, title: str, content: str, category: str) -> str | None:
        """Second keyword pass within the chosen category. Returns None for
        categories with no subcategory taxonomy (safety, regulatory, ...), and
        for "events" -- that one is decided by enrich.py from the detected
        region instead (general vs. regional), not by keyword scoring.
        """
        if category == "events":
            return None
        sub_keywords = SUBCATEGORY_KEYWORDS.get(category)
        if not sub_keywords:
            return None
        title_text = normalize_text(title)
        body_text = normalize_text(content)
        best_sub: str | None = None
        best_score = 0
        for sub, keywords in sub_keywords.items():
            if not keywords:
                continue
            score = _score(_keyword_pattern(tuple(keywords)), title_text, body_text)
            if score > best_score:
                best_score = score
                best_sub = sub
        return best_sub

    async def translate(self, text: str, target: str = "tr") -> str | None:
        """The keyless heuristic engine has no translation capability -- return
        None so callers know to leave the original text untranslated rather
        than silently passing it through as if it were Turkish."""
        return None

    async def sentiment(self, title: str, content: str) -> str:
        words = set(normalize_text(f"{title} {content}").split())
        positive = len(words & _POSITIVE_WORDS)
        negative = len(words & _NEGATIVE_WORDS)
        if positive > negative:
            return "positive"
        if negative > positive:
            return "negative"
        return "neutral"

    async def extract_entities(self, title: str, content: str) -> list[EntityMention]:
        text = normalize_text(f"{title} {content}")
        mentions: list[EntityMention] = []

        # Whole-word matching, same as categorisation: plain substring search
        # tagged every article containing "management" with All Nippon ("ana")
        # -- 96 false links in production.
        for alias, (name, code) in AIRLINES.items():
            if _keyword_pattern((alias,)).search(text):
                mentions.append(EntityMention("airline", name, code))
        for alias, (name, code) in AIRPORTS.items():
            if _keyword_pattern((alias,)).search(text):
                mentions.append(EntityMention("airport", name, code))
        for country in COUNTRIES:
            if _keyword_pattern((country,)).search(text):
                mentions.append(EntityMention("country", country.title(), None))

        # de-duplicate while preserving order
        seen: set[tuple[str, str]] = set()
        unique: list[EntityMention] = []
        for m in mentions:
            key = (m.entity_type, m.name)
            if key not in seen:
                seen.add(key)
                unique.append(m)
        return unique


def detect_region(entities: list[EntityMention]) -> str | None:
    """Region detection is entity-based, not LLM-based, so it runs the same way
    regardless of which provider (heuristic or live) extracted the entities --
    the first recognized country entity maps to its world-region slug via
    app.taxonomy.COUNTRY_TO_REGION. Articles that name only an airport (very
    common in route news: "Heathrow slot changes") fall back to that airport's
    country. Returns None if nothing mapped.
    """
    for mention in entities:
        if mention.entity_type != "country":
            continue
        region = COUNTRY_TO_REGION.get(mention.name.lower())
        if region:
            return region
    for mention in entities:
        if mention.entity_type != "airport" or not mention.code:
            continue
        country = AIRPORT_COUNTRY.get(mention.code)
        if country:
            region = COUNTRY_TO_REGION.get(country)
            if region:
                return region
    return None


# ===========================================================================
# Risk Radarı: natural-disaster and conflict classification
#
# Runs over the same article text the categorizer sees, with no external data
# source. The hard part is not recall, it is precision: this vocabulary
# overlaps with ordinary aviation and business prose more than any other in the
# app, and a false "Savaş" row on a disaster page is far worse than a miss.
#
# Three mechanisms, in order:
#
#  1. MASKING. `_RISK_MASK` phrases are blanked out of the text *before* any
#     matching. This is what makes bare tokens usable at all: "fare war" and
#     "price war" are literally keywords of the revenue_management category
#     above, and "under fire from regulators" / "fired up" / "a flood of
#     bookings" / "perfect storm" / "heart attack" are everyday wire phrasing.
#     Masking rather than vetoing the whole article matters -- an article that
#     says "fare war" in one paragraph and reports a real civil war in another
#     still classifies correctly, because only the phrase is removed.
#
#  2. STRONG vs WEAK patterns. Strong terms are compound or unambiguous
#     ("wildfire", "civil war", "coup attempt") and match on their own. Weak
#     terms are the ambiguous singles ("blaze", "storm", "conflict", "protest")
#     and only count when a disaster-context word (`_RISK_CONTEXT`) also
#     appears. Same discipline as SUBCATEGORY_KEYWORDS' compound phrases in
#     app/taxonomy.py, applied harder.
#
#  3. NO BARE "fire", EVER. The word appears constantly in aviation copy --
#     "fired up", "engine fire", "under fire from regulators", a firefighting
#     demo at an airshow -- and none of those are wildfires. The wildfire rule
#     requires an explicit wildfire noun ("wildfire", "forest fire",
#     "bushfire", "orman yangını"); aircraft/hangar fires are masked outright
#     because they belong to the existing `safety` category, not here.
# ===========================================================================

# Turkish letters do not survive normalize_text (its character class is
# [^a-z0-9\s], so "yangın" becomes "yang n" and "saldırı" becomes "sald r ").
# Folding to ASCII first is what makes the Turkish half of this vocabulary work
# at all; every pattern below is therefore written in folded form.
_TR_FOLD = str.maketrans(
    {
        "ı": "i", "İ": "i", "ğ": "g", "Ğ": "g", "ş": "s", "Ş": "s",
        "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u",
        "â": "a", "î": "i", "û": "u", "Â": "a", "Î": "i", "Û": "u",
    }
)


def fold_text(text: str) -> str:
    """normalize_text, but Turkish diacritics survive as their ASCII bases.

    Folding must happen before lowercasing: "İ".lower() is "i" plus a combining
    dot in Python, and the combining mark is then stripped to a space, which
    splits the word in half.
    """
    return normalize_text(text.translate(_TR_FOLD))


# Phrases removed from the text before matching -- see mechanism (1) above.
# Every entry here was chosen because the risk token inside it is a metaphor,
# an idiom, or an aviation term of art rather than a real-world event.
_RISK_MASK: tuple[str, ...] = (
    # "war" as commercial metaphor -- the single biggest false-positive source
    # on this feed, and two of these are revenue_management keywords.
    "fare war", "fare wars", "price war", "price wars", "trade war", "trade wars",
    "tariff war", "bidding war", "talent war", "streaming war", "war of words",
    "war chest", "war room", "star wars", "world war", "cold war", "post war",
    "pre war", "warring parties over",
    # "fire" in aviation prose. None of these are wildfires; the aircraft-fire
    # ones are `safety` category events and must not surface here as "Yangın".
    "fired up", "under fire", "fire drill", "firefighting demo",
    "firefighting demonstration", "firefighting display", "firefighting aircraft",
    "firefighting fleet", "water bomber", "fire suppression system", "fire drill",
    "engine fire", "cabin fire", "cargo fire", "apu fire", "hangar fire",
    "fire warning", "fire indication", "fire extinguisher", "ceasefire",
    "open fire sale", "fire sale",
    # "flood" as volume metaphor.
    "flood of", "flooded with", "flooded the market", "flooding the market",
    "flood the market", "floodgates", "flooding the zone",
    # "storm" as agitation metaphor.
    "perfect storm", "brainstorm", "brainstorming", "storm of criticism",
    "storm of protest", "political storm", "media storm", "storm off",
    # "attack" as medical or commercial metaphor. Cyber incidents are excluded
    # deliberately: this surface is about physical risk to people and
    # operations, and a ransomware story would sit oddly beside an earthquake.
    "heart attack", "panic attack", "cyber attack", "cyberattack",
    "attack on market share", "attack ad", "attack ads", "shooting for",
    "shooting star", "shooting range",
    # "earthquake"/"seismic" as figures of speech.
    "political earthquake", "seismic shift", "seismic change", "seismic move",
    # "eruption" as figure of speech.
    "eruption of applause", "eruption of joy", "eruption of anger",
    # "demonstration" in aviation means a display flight, not a protest --
    # exactly the airshow trap that rules out bare "fire" too.
    "demonstration flight", "demonstration flights", "flight demonstration",
    "technology demonstration", "demonstrator aircraft", "demonstration aircraft",
    "aerial demonstration", "flying demonstration", "demo flight",
    "gosteri ucusu", "gosteri ucuslari",
    # "conflict"/"invasion" in ordinary business usage.
    "conflict of interest", "scheduling conflict", "conflict resolution",
    "invasion of privacy",
    # "coup" as a French loan, and Turkish "darbe" in its figurative
    # "a blow to X" sense, which is how the Turkish business press almost
    # always uses it ("sektore darbe" = "a blow to the sector").
    "coup de grace", "coup de foudre", "darbe vurdu", "darbe indirdi",
    "buyuk darbe", "agir darbe", "darbe niteliginde", "sektore darbe",
    "ekonomiye darbe", "darbe aldi",
    # "riot" as an intensifier.
    "riot of color", "riot of colour",
    # Insurance/credit-card peril boilerplate, which lists half this taxonomy
    # as covered events without reporting any of them.
    "acts of war", "act of war", "war exclusion", "war risk insurance",
    "earthquake insurance", "earthquake coverage", "flood insurance",
    # Military history and heritage aviation, which are not current events.
    # Vintage-airshow copy is dense with war vocabulary ("a Great War
    # aerodrome", "warbird display"), and two airshow-injury stories filed as
    # "Savaş" in the production measurement because of it.
    "normandy invasion", "d day landings", "world war ii", "world war i",
    "great war", "first world war", "second world war", "wartime", "war memorial",
    "warbird", "warbirds", "war grave", "war veteran", "war veterans",
    # Hurricane-hunter research aircraft are met-office hardware, not weather.
    "hurricane hunter", "hurricane hunters",
    # "erupt"/"flood" as verbs applied to non-hazards.
    "erupted into", "erupted in chaos", "chaos erupted", "floods cabin",
    "floods the cabin", "flooded the cabin", "flooded the cockpit",
    # Aerial-firefighting *capability* stories: an air-tanker procurement or a
    # water-bomber production line is aviation industry news, not a fire.
    "water bomber", "water bombers", "air tanker", "air tankers",
    "firefighting helicopter", "firefighting helicopters", "firefighting crew",
    "firefighting plane", "firefighting planes", "firefighting capability",
    "aerial firefighting force", "converted into air tankers",
)

# Aircraft named after weather. This feed is full of them and they are the
# single largest false-positive source for the `storm` type -- measured over 30
# days of production articles, "Eurofighter Typhoon", "RAF Typhoons", "Panavia
# Tornado" and "Hawker Hurricane" produced more storm hits than actual weather
# did. Masking the phrases is not enough on its own: fighter-comparison
# headlines write the type name bare ("...Gripen, & Typhoon In 2026"), so these
# three tokens are additionally discounted whenever the surrounding text is
# clearly about military aviation (see detect_risk_type).
_WEATHER_NAMED_AIRCRAFT: tuple[str, ...] = (
    "typhoon", "typhoons", "tornado", "tornadoes", "hurricane", "hurricanes",
)

_MILITARY_AVIATION_CONTEXT: tuple[str, ...] = (
    "eurofighter", "gripen", "rafale", "raf", "luftwaffe", "nato", "squadron",
    "scrambled", "scramble", "intercept", "intercepted", "interceptor",
    "fighter jet", "fighter jets", "fighter aircraft", "combat aircraft",
    "warplane", "warplanes", "air force", "sixth generation", "stacks up",
    "f 16", "f 35", "f 22", "su 35", "su 57", "mig", "spitfire", "messerschmitt",
    "airshow", "air show", "aerodrome", "mcas", "noaa",
    # Non-English military vocabulary from the German- and Spanish-language
    # feeds, which the English context words above never reach.
    "luftstreitkrafte", "kampfflugzeug", "bundeswehr", "fuerza aerea",
)

# Words that make an ambiguous (weak) risk term count. Deliberately excludes
# bare "emergency": "emergency landing" and "emergency descent" are routine
# aviation copy and would re-open every gate this module closes.
_RISK_CONTEXT: tuple[str, ...] = (
    "killed", "dead", "death toll", "deaths", "fatalities", "casualties",
    "injured", "wounded", "evacuated", "evacuation", "evacuations", "rescue",
    "rescuers", "displaced", "destroyed", "devastated", "devastation",
    "disaster", "catastrophe", "catastrophic", "state of emergency",
    "victims", "survivors", "collapsed", "magnitude", "aftermath", "toll rose",
    "olu", "olen", "hayatini kaybetti", "yarali", "tahliye", "afet", "felaket",
    "enkaz", "kurtarma", "hasar", "yikildi", "can kaybi",
)


@dataclass(frozen=True)
class _RiskRule:
    slug: str
    # Compound or unambiguous -- counts on its own.
    strong: tuple[str, ...]
    # Ambiguous single words -- only count alongside a _RISK_CONTEXT word.
    weak: tuple[str, ...]


# Order is the tie-break order when two types score equally: natural-hazard
# types first, matching app/taxonomy.py RISK_TYPES.
_RISK_RULES: tuple[_RiskRule, ...] = (
    _RiskRule(
        "earthquake",
        strong=(
            "earthquake", "earthquakes", "quake", "aftershock", "aftershocks",
            "epicenter", "epicentre", "richter", "seismic activity",
            "deprem", "depremi", "depremde", "artci sarsinti",
        ),
        # "magnitude" is deliberately NOT here: it is also a _RISK_CONTEXT
        # word, so a weak term that appears in both lists satisfies its own
        # precondition and matches on any article that says "the magnitude of
        # the fleet expansion".
        weak=("tremor", "tremors", "sarsinti"),
    ),
    _RiskRule(
        "flood",
        strong=(
            "flash flood", "flash flooding", "floodwaters", "flood waters",
            "flooding", "floods", "flood damage", "flood warning", "inundated",
            "sel baskini", "sel felaketi", "sel sulari", "su baskini",
            "sel nedeniyle", "selde",
        ),
        weak=("flooded", "monsoon", "heavy rain", "torrential rain", "sel", "siddetli yagis"),
    ),
    _RiskRule(
        "wildfire",
        # No bare "fire" -- see mechanism (3). Every entry names the wildland
        # character of the fire explicitly.
        strong=(
            "wildfire", "wildfires", "forest fire", "forest fires", "bushfire",
            "bushfires", "bush fire", "brush fire", "grass fire", "wildland fire",
            "orman yangini", "orman yanginlari",
        ),
        # No weak tier at all. "blaze" and bare Turkish "yangın" describe
        # structure and aircraft fires just as readily as wildland ones -- they
        # produced temple fires, hangar fires and post-crash fires in the
        # production measurement. The compound strong list carries this type.
        weak=(),
    ),
    _RiskRule(
        "volcano",
        strong=(
            "volcanic eruption", "volcanic ash", "volcano erupted", "volcano erupts",
            "ash cloud", "ash plume", "volcano", "volcanoes", "volkanik",
            "volkan patlamasi", "yanardag", "lava",
        ),
        # Not "ash" (a name, and Ash Wednesday) and not "erupted" ("chaos
        # erupted") -- both matched non-volcanic stories in production.
        weak=("eruption",),
    ),
    _RiskRule(
        "storm",
        strong=(
            "hurricane", "hurricanes", "typhoon", "typhoons", "cyclone", "cyclones",
            "blizzard", "tropical storm", "winter storm", "snowstorm", "windstorm",
            "tornado", "tornadoes", "kasirga", "tayfun", "kar firtinasi", "hortum",
        ),
        weak=(
            "storm", "storms", "thunderstorm", "thunderstorms", "gale",
            "severe weather", "firtina",
        ),
    ),
    _RiskRule(
        "war",
        strong=(
            "civil war", "war zone", "warzone", "war crimes", "war torn", "at war",
            "armed conflict", "military offensive",
            "airstrike", "airstrikes", "air strike", "air strikes", "shelling",
            "bombardment", "savas bolgesi", "ic savas", "silahli catisma",
            "ates kes", "isgal",
        ),
        # Bare "frontline" is deliberately absent: "frontline staff" and
        # "frontline workers" are ordinary airline-operations vocabulary.
        # "invasion"/"invaded" sit here rather than in `strong`: they carry
        # WWII history pieces ("the Normandy invasion") and insurance-peril
        # lists, and real invasion coverage always brings casualty language
        # with it.
        weak=(
            "war", "conflict", "troops", "militia", "invasion", "invaded",
            "savas", "catisma",
        ),
    ),
    _RiskRule(
        "coup",
        strong=(
            "coup attempt", "attempted coup", "military coup", "failed coup",
            "coup d etat", "coup plotters", "coup leaders",
            # "military junta", never bare "junta": in Spanish-language
            # aviation copy "junta" is simply a board or a meeting ("junta
            # directiva"), and it tagged LATAM results coverage as a coup.
            "military junta", "ruling junta",
            "darbe girisimi", "askeri darbe", "darbe tesebbusu",
        ),
        weak=("coup", "darbe"),
    ),
    _RiskRule(
        "attack",
        strong=(
            "terror attack", "terrorist attack", "terror attacks", "bomb attack",
            "suicide attack", "suicide bomber", "drone attack", "missile attack",
            "rocket attack", "armed attack", "gun attack", "car bomb", "bombing",
            "gunmen", "opened fire", "hijack", "hijacking", "hijacked", "assassination",
            "teror saldirisi", "bombali saldiri", "silahli saldiri", "suikast",
        ),
        weak=("attack", "attacks", "attackers", "militants", "shooting", "saldiri"),
    ),
    _RiskRule(
        "unrest",
        # "strike" appears nowhere in this rule on purpose: pilot and cabin-crew
        # strikes are the `labor` category and are among the most common stories
        # on this feed. Treating them as civil unrest would swamp the page.
        strong=(
            "civil unrest", "riots", "rioting", "rioters", "anti government protest",
            "anti government protests", "mass protest", "mass protests",
            "violent protest", "violent protests", "protesters clashed",
            "civil disorder", "ayaklanma", "halk ayaklanmasi", "toplumsal olaylar",
            "sokak eylemleri", "protesto gosterileri",
        ),
        weak=("protest", "protests", "protesters", "unrest", "curfew", "protesto"),
    ),
)

# Headline voice matters here: wires write "Earthquake kills hundreds", not
# "hundreds were killed", so the present-tense forms have to be listed
# explicitly or every breaking story reads as low severity. (Severity is only
# ever computed for an article that already classified as a risk event, so
# these are narrow-context words, not general-purpose ones.)
_SEVERITY_HIGH: tuple[str, ...] = (
    "killed", "kills", "kill", "killing", "dead", "death toll", "deaths",
    "died", "dies", "die", "perished", "fatalities", "fatal", "casualties",
    "destroyed", "destroys", "devastated", "devastates", "devastation",
    "state of emergency", "catastrophic", "catastrophe", "mass evacuation",
    "leaves dead", "bodies recovered",
    "olu", "olen", "oldu", "hayatini kaybetti", "can kaybi", "afet", "felaket",
    "yikildi", "olduruldu",
)
_SEVERITY_MEDIUM: tuple[str, ...] = (
    "injured", "injures", "injuring", "injuries", "wounded", "wounds", "hurt",
    "evacuated", "evacuates", "evacuation", "evacuations", "displaced",
    "damage", "damages", "damaged", "rescue", "rescued", "missing", "stranded",
    "collapsed", "curfew", "warning", "disrupted", "cancelled flights",
    "yarali", "tahliye", "hasar", "enkaz", "mahsur",
)


@lru_cache(maxsize=1)
def _mask_pattern() -> re.Pattern[str]:
    return _keyword_pattern(_RISK_MASK)


def _masked(text: str) -> str:
    """Blank out the idiom/metaphor phrases so the tokens inside them cannot
    be matched by any rule. Replaced with a space rather than deleted so word
    boundaries around the removed phrase stay intact."""
    return _mask_pattern().sub(" ", text)


def _any(patterns: tuple[str, ...], text: str) -> bool:
    return bool(_keyword_pattern(patterns).search(text))


def detect_risk_severity(title_text: str, body_text: str) -> str:
    """high when the article reports loss of life or destruction, medium when it
    reports injury/evacuation/damage, low otherwise. Severity is about what the
    story says happened, not about the hazard type -- a magnitude-3 earthquake
    nobody was hurt in is a low-severity earthquake."""
    combined = f"{title_text} {body_text}"
    if _any(_SEVERITY_HIGH, combined):
        return "high"
    if _any(_SEVERITY_MEDIUM, combined):
        return "medium"
    return "low"


def detect_risk_type(title: str, content: str) -> str | None:
    """The closed-taxonomy risk type for this article, or None.

    None is the expected answer for the overwhelming majority of an aviation
    news feed, and the whole design above is biased towards returning it rather
    than guessing.
    """
    title_text = _masked(fold_text(title))
    body_text = _masked(fold_text(content))
    has_context = _any(_RISK_CONTEXT, f"{title_text} {body_text}")

    # Typhoon, Tornado and Hurricane are aircraft here as often as they are
    # weather. Discount exactly their contribution when the article is plainly
    # about military aviation, so "RAF Typhoons scrambled to intercept" scores
    # zero for `storm` while "Typhoon Noul threatens South China airports"
    # keeps its full score.
    aircraft_discount = 0
    if _any(_MILITARY_AVIATION_CONTEXT, f"{title_text} {body_text}"):
        aircraft_discount = _score(
            _keyword_pattern(_WEATHER_NAMED_AIRCRAFT), title_text, body_text
        )

    best_slug: str | None = None
    best_score = 0
    for rule in _RISK_RULES:
        score = _score(_keyword_pattern(rule.strong), title_text, body_text)
        if has_context:
            score += _score(_keyword_pattern(rule.weak), title_text, body_text)
        if rule.slug == "storm":
            score -= aircraft_discount
        if score > best_score:
            best_score = score
            best_slug = rule.slug
    return best_slug


def detect_risk_place(
    title: str, content: str, entities: list[EntityMention]
) -> tuple[str | None, str | None]:
    """(country, city) for a risk event.

    Country reuses the entity gazetteer that already ran for this article --
    country mentions first, then the country behind any recognised airport,
    which is the same fallback chain detect_region() uses.

    City is the honest weak spot. Stage 3's airport/city reference dataset is
    not on this branch, so the only city vocabulary available is the hand-built
    RISK_CITY_COUNTRY table in app/llm/gazetteer.py (136 entries). Anything
    outside it resolves to a country with no city, and that is most of the
    world -- the map falls back to a country centroid for those rows rather
    than pretending to a precision it does not have. A city is only accepted
    when it does not contradict an already-resolved country, so a Reuters piece
    naming both London and a flood in Jakarta cannot place the flood in London.
    """
    text = fold_text(f"{title} {content}")

    country: str | None = None
    for mention in entities:
        if mention.entity_type == "country" and mention.name.lower() in COUNTRY_TO_REGION:
            country = mention.name.lower()
            break
    if country is None:
        for mention in entities:
            if mention.entity_type == "airport" and mention.code:
                mapped = AIRPORT_COUNTRY.get(mention.code)
                if mapped:
                    country = mapped
                    break

    city: str | None = None
    for alias, (city_name, city_country) in RISK_CITY_COUNTRY.items():
        if country is not None and city_country != country:
            continue
        if _keyword_pattern((alias,)).search(text):
            city = city_name
            if country is None:
                country = city_country
            break

    return (country.title() if country else None, city)


def classify_risk_heuristic(
    title: str, content: str, entities: list[EntityMention]
) -> dict[str, str | None]:
    """Full no-LLM risk classification for one article. Returns all-None when
    the article is not a risk event, which is the common case."""
    risk_type = detect_risk_type(title, content)
    if risk_type is None:
        return {"risk_type": None, "severity": None, "country": None, "city": None}
    country, city = detect_risk_place(title, content, entities)
    return {
        "risk_type": risk_type,
        "severity": detect_risk_severity(_masked(fold_text(title)), _masked(fold_text(content))),
        "country": country,
        "city": city,
    }
