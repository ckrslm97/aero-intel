"""No-key fallback pipeline: extractive summarization, keyword categorization,
lexicon sentiment, and gazetteer entity extraction. Runs with zero external
dependencies so the platform works before any LLM is configured, and is what
every other provider falls back to if a live call fails.
"""
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from app.llm.base import EntityMention
from app.llm.gazetteer import (
    AIRLINE_ALIASES,
    AIRPORT_COUNTRY,
    AIRPORTS,
    ALIAS_FIRST_TOKENS,
    AMBIGUOUS_BARE_CODES,
    COUNTRY_ALIASES,
    MAX_ALIAS_TOKENS,
    RISK_CITY_COUNTRY,
    fold_tokens,
)
from app.pipeline.hashing import normalize_text
from app.taxonomy import (
    CATEGORY_KEYWORDS,
    COUNTRY_TO_REGION,
    GENERAL_CATEGORY,
    RM_SHIFT_FROM_CATEGORIES,
    RM_SHIFT_KEYWORDS,
    RM_SHIFT_MIN_SCORE,
    RM_SHIFT_TARGET,
    SUBCATEGORY_KEYWORDS,
)

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


def _apply_rm_shift(category: str, title_text: str, body_text: str) -> str:
    """Move a fleet/finance story to revenue_management when it carries an
    explicit market effect -- see RM_SHIFT_KEYWORDS in app/taxonomy.py for the
    rule and for why it is drawn this tightly.

    Both arguments are already normalize_text'd; this runs on the same two
    strings categorize() just scored, so the rule costs one extra pattern match
    and never re-reads the article.
    """
    if category not in RM_SHIFT_FROM_CATEGORIES:
        return category
    evidence = _score(_keyword_pattern(tuple(RM_SHIFT_KEYWORDS)), title_text, body_text)
    return RM_SHIFT_TARGET if evidence >= RM_SHIFT_MIN_SCORE else category


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
        return _apply_rm_shift(best_category, title_text, body_text)

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
        return extract_entity_mentions(title, content)


def _airport_match_is_credible(
    gram: str, cased: list[str], start: int, end: int
) -> bool:
    """Whether an airport alias hit is worth believing.

    Multi-word aliases ("john f kennedy") are self-evidencing, and so is any
    code that is not also an ordinary word. The one case that needs a second
    look is a bare three-letter code that doubles as prose -- see
    `AMBIGUOUS_BARE_CODES`. There the deciding evidence is capitalisation,
    which the folded token view has already thrown away: a wire writes the
    code as "JAN" and the month as "Jan", so requiring the original token to
    be upper-case keeps "flights to JAN" and drops "Okinawa Jan 2027".
    """
    if end != start:  # multi-token alias: not a bare code
        return True
    if gram.upper() not in AMBIGUOUS_BARE_CODES:
        return True
    return cased[start].isupper()


def extract_entity_mentions(title: str, content: str) -> list[EntityMention]:
    """Airlines, airports and countries named in the text, in the order they
    appear.

    Whole-word matching, never substring: plain `in` tagged every article
    containing "management" with All Nippon ("ana") -- 96 false links in
    production. It is done by sliding a token n-gram window over the folded
    text and looking each gram up in the gazetteer's alias tables, which is the
    same whole-word semantics as the old regex-per-alias loop (normalised text
    is space-separated [a-z0-9] tokens, so token edges *are* word boundaries)
    at a fraction of the cost -- the airport table grew from 30 aliases to
    ~11.6k when the OurAirports dataset landed, and 11.6k regex scans per
    article is not a thing you can run over an archive.

    Text order also makes `detect_region` deterministic: it takes the first
    country it sees, and "first" used to mean whatever order a Python set
    happened to iterate in.
    """
    tokens, cased = fold_tokens(f"{title} {content}")
    mentions: list[EntityMention] = []
    seen: set[tuple[str, str]] = set()

    def note(entity_type: str, name: str, code: str | None) -> None:
        key = (entity_type, name)
        if key not in seen:
            seen.add(key)
            mentions.append(EntityMention(entity_type, name, code))

    total = len(tokens)
    for start, first in enumerate(tokens):
        if first not in ALIAS_FIRST_TOKENS:
            continue
        gram = first
        for end in range(start, min(start + MAX_ALIAS_TOKENS, total)):
            if end > start:
                gram = f"{gram} {tokens[end]}"
            airline = AIRLINE_ALIASES.get(gram)
            if airline:
                note("airline", airline[0], airline[1])
            airport = AIRPORTS.get(gram)
            if airport and _airport_match_is_credible(gram, cased, start, end):
                note("airport", airport[0], airport[1])
            country = COUNTRY_ALIASES.get(gram)
            if country:
                note("country", country.title(), None)
    return mentions


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
# Four mechanisms, in order:
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
#
#  4. RETROSPECTIVE SUPPRESSION. An anniversary or "on this day" piece is
#     about a real disaster that happened years ago, and this data has no
#     event date to file it under -- only the publication time, which would
#     put it on today's radar. See the RETROSPECTIVE GUARD section below.
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
    # "at war OVER something" is the commercial construction and always was:
    # carriers are at war over slots, over a hub, over a bilateral. Real
    # conflict coverage writes "at war since", "at war with Russia", "a country
    # at war" -- it does not name what the war is over in the same breath. Only
    # the "over" form is masked, so the strong "at war" keyword survives for the
    # reporting that actually means it.
    "at war over", "at war for", "went to war over", "go to war over",
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
    # The Sikorsky CH-148 Cyclone is the Royal Canadian Air Force's maritime
    # helicopter, in service and in this feed. Same trap as Typhoon and
    # Tornado, and it was missed when those were fixed: the type designation is
    # masked here, and the bare token is additionally discounted under military
    # context below (see _WEATHER_NAMED_AIRCRAFT) for the headlines that write
    # it without the number.
    "ch 148 cyclone", "ch 148", "cyclone helicopter", "cyclone helicopters",
    "cyclone fleet", "cyclone maritime helicopter",
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
    # Added with the same evidence as the other three: the CH-148 Cyclone is a
    # current RCAF type, so "Cyclone" in a paragraph that also says "air force"
    # or "squadron" is a helicopter. A real cyclone's coverage carries no
    # military-aviation vocabulary at all, so it keeps its full score.
    "cyclone", "cyclones",
)

_MILITARY_AVIATION_CONTEXT: tuple[str, ...] = (
    "eurofighter", "gripen", "rafale", "raf", "luftwaffe", "nato", "squadron",
    "scrambled", "scramble", "intercept", "intercepted", "interceptor",
    "fighter jet", "fighter jets", "fighter aircraft", "combat aircraft",
    "warplane", "warplanes", "air force", "sixth generation", "stacks up",
    "f 16", "f 35", "f 22", "su 35", "su 57", "mig", "spitfire", "messerschmitt",
    "airshow", "air show", "aerodrome", "mcas", "noaa",
    # The acronyms. "air force" above never reaches them -- an article that
    # says "RCAF" or "USAF" throughout says "air force" nowhere -- and the
    # CH-148 Cyclone lives almost entirely in RCAF copy.
    "rcaf", "usaf", "raaf", "rnlaf", "maritime helicopter",
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
            "ash cloud", "ash plume", "volkan patlamasi", "lava akintisi",
            "lava akisi", "lav akintisi",
        ),
        # Not "ash" (a name, and Ash Wednesday) and not "erupted" ("chaos
        # erupted") -- both matched non-volcanic stories in production. Bare
        # "volcano"/"volkanik"/"yanardag" moved here from strong: a dormant
        # crater lake's tourism coverage calls it a "volcanic formation" or
        # "volcanic landscape" just as naturally as breaking eruption news
        # does -- Nemrut Kalderası being declared a national park matched
        # "volkanik" and published as a HIGH-severity live event. A real
        # eruption still brings _RISK_CONTEXT words (evacuated, disaster,
        # destroyed) or one of the unambiguous strong compounds above.
        #
        # Bare "lava" moved down here with them, for the reason the Spanish
        # "junta" bug already taught this module: "lava" is the ordinary
        # third-person present of Spanish *lavar*, and the feed carries
        # Spanish-language aviation press. "Así se lava un Boeing 747" is an
        # aircraft-washing feature, and as a STRONG keyword it published as a
        # live volcano. The compound "lava akıntısı" stays strong.
        weak=("eruption", "volcano", "volcanoes", "volkanik", "yanardag", "lava"),
    ),
    _RiskRule(
        "storm",
        strong=(
            "hurricane", "hurricanes", "typhoon", "typhoons", "cyclone", "cyclones",
            "blizzard", "tropical storm", "winter storm", "snowstorm", "windstorm",
            "tornado", "tornadoes", "kasirga", "tayfun", "kar firtinasi",
        ),
        # "hortum" is Turkish for both "tornado" and "hose", and the hose sense
        # is ordinary maintenance vocabulary on this feed (yakıt hortumu,
        # hidrolik hortum). Demoted from strong for exactly the reason bare
        # "yangın" never entered the wildfire rule: a real hortum flattens
        # greenhouses and injures people, so it arrives with _RISK_CONTEXT
        # words, and a burst hydraulic line does not.
        weak=(
            "storm", "storms", "thunderstorm", "thunderstorms", "gale",
            "severe weather", "firtina", "hortum",
        ),
    ),
    _RiskRule(
        "war",
        strong=(
            "civil war", "war zone", "warzone", "war crimes", "war torn", "at war",
            "armed conflict", "military offensive",
            # EASA and the FAA both publish airspace warnings under this exact
            # phrase ("Conflict Zone Information Bulletin"), which is how a
            # regulator says "there is a war under this airspace". It was
            # missed entirely: bare "conflict" is weak and needs a casualty
            # word beside it, and a bulletin telling airlines to stay out of
            # four countries' airspace contains none -- it is a notice, not a
            # casualty report. Safe as a strong term because the three
            # ordinary-business senses of "conflict" are already masked
            # (conflict of interest / scheduling conflict / conflict
            # resolution) and none of them is ever written "conflict zone".
            "conflict zone", "conflict zones", "catisma bolgesi",
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
            # The "-strike" forms of the three attack compounds already above.
            # Bare "strike" stays out of this whole taxonomy (a pilots' strike
            # is `labor`), but these three are compounds and none of them has a
            # labour reading. Measured miss: "Yemen strikes capital's airport
            # runway to block a Mahan Air flight" classified as nothing at all
            # -- a runway bombed to stop an aircraft landing is the most
            # aviation-relevant conflict event this feed can carry.
            "drone strike", "drone strikes", "missile strike", "missile strikes",
            "rocket strike", "rocket strikes", "air raid", "air raids",
            "struck the runway", "struck the airport", "struck the terminal",
            "insansiz hava araci saldirisi", "fuze saldirisi", "hava akini",
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

# ===========================================================================
# RETROSPECTIVE GUARD -- mechanism (4)
#
# Publication time is the only time this pipeline has (see app/api/v1/risks.py's
# module docstring): `published_at` is when somebody WROTE about an event, never
# when the event happened. That is exactly right for breaking coverage and
# exactly wrong for the anniversary piece -- "Kahramanmaraş depreminin yıl
# dönümü", filed this morning, puts a 2023 earthquake on the radar as a signal
# from today, and there is no field anywhere in this data that could correct it.
#
# Extracting an event date out of the prose is NOT the fix, and was rejected on
# purpose: a date parsed from a sentence is a guess wearing the costume of a
# fact, and one bad parse moves a live event into the past, which is a strictly
# worse failure than the one being fixed.
#
# What IS readable off the surface is the article's VOICE. A retelling
# announces itself, in the headline, in wire style, reliably: "yıl dönümü",
# "on this day", "remembering", "10 years ago". Two triggers, both scoped to
# the TITLE:
#
#  1. An explicit retrospective marker. Title-scoped rather than whole-text
#     because live coverage routinely reaches one paragraph back ("a similar
#     quake struck 20 years ago", "the deadliest season since 2018"), and
#     vetoing on that would suppress the very event the article reports.
#
#  2. A year at least RETROSPECTIVE_YEAR_GAP old in the title, alongside
#     past-tense narration in the same title ("In 2011 a tsunami STRUCK
#     Fukushima"). Neither half carries it alone: "2026 hurricane season" is
#     this year's, and "Earthquake strikes Izmir" names no year at all.
#
# Suppression, not down-ranking: an anniversary story is not a weak signal, it
# is a signal about a different day, and the radar has no way to say so.
# ===========================================================================

#: The reason string recorded when this guard fires. Named rather than inlined
#: because two call sites write it -- detect_risk_type() drops the
#: classification outright, and app/agents/runner.py records it as the v2
#: pipeline's `not_applicable["risk"]`, which is what makes the veto auditable
#: instead of invisible.
RETROSPECTIVE_REASON = "retrospective"

#: How old a year in the title has to be before it reads as history. Two, not
#: one: a January piece about "the 2025 wildfire season" is still writing about
#: the season that just ended, and an article naming its own year is ordinary.
RETROSPECTIVE_YEAR_GAP = 2

#: Headline phrasings that exist to say "this is a look backwards". Written in
#: folded form like every other pattern here (see fold_text), and the Turkish
#: entries are repeated with their case suffixes because \b anchors both ends
#: -- "yil donumu" does not match "yıl dönümünde", which is how a Turkish
#: headline almost always inflects it.
_RETROSPECTIVE_MARKERS: tuple[str, ...] = (
    "anniversary", "anniversaries", "years ago", "year ago", "decades ago",
    "years on", "years since", "decades since", "on this day", "looking back",
    "a look back", "remembering", "in memory of", "in memoriam", "throwback",
    "flashback", "retrospective", "commemorates", "commemorated",
    "commemoration", "we remember",
    "yil donumu", "yil donumunde", "yil donumunu", "yildonumu", "yildonumunde",
    "yildonumunu", "yil once", "yillar once", "yil onceki", "tarihinde bugun",
    "anma toreni", "anma toreninde", "anma gunu", "anma gununde", "anisina",
    "geriye bakis", "unutulmadi", "aninda",
)

#: Past-tense narration. Only consulted alongside an old year in the same
#: title, which is what keeps ordinary words like "was" usable: a terse news
#: headline that both names a year from three years ago AND narrates in the
#: past is telling a story, not reporting one. Deliberately excludes the
#: breaking-news verbs ("kills", "hits", "destroys") -- those are the register
#: this guard must never touch.
_RETROSPECTIVE_PAST_TENSE: tuple[str, ...] = (
    "was", "were", "had", "struck", "claimed", "sank", "became", "marked",
    "remembered", "commemorated", "died", "ended", "began",
    "yilinda", "olmustu", "vurmustu", "yasanmisti", "gerceklesmisti",
    "kaybetmisti", "meydana gelmisti", "gomuldu",
)

#: 1900-2099. Narrower than \d{4} so a flight number, a fleet size or an
#: aircraft type ("Boeing 7378", "A350 1000") cannot be read as a year.
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def is_retrospective(title: str, *, year_now: int | None = None) -> bool:
    """True when the HEADLINE says the piece is looking backwards.

    `year_now` is injectable so the year arithmetic is testable without
    freezing the clock; it defaults to the current UTC year.
    """
    title_text = fold_text(title)
    if _any(_RETROSPECTIVE_MARKERS, title_text):
        return True

    current = year_now if year_now is not None else datetime.now(timezone.utc).year
    old_year = any(
        int(match) <= current - RETROSPECTIVE_YEAR_GAP for match in _YEAR_RE.findall(title_text)
    )
    return old_year and _any(_RETROSPECTIVE_PAST_TENSE, title_text)


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
    # Not bare "oldu": ASCII-folding collapses "öldü" (died) and "oldu"
    # (became/happened -- one of the most common auxiliary verbs in Turkish)
    # onto the same token. "...milli park destinasyonları arasına girmiş
    # oldu" (has thus become a national park) matched this and inflated a
    # tourism story to HIGH severity in production. "olduruldu" (was killed)
    # and "hayatini kaybetti" (lost their life) already cover the real
    # death-verb forms without the collision.
    "olu", "olen", "hayatini kaybetti", "can kaybi", "afet", "felaket",
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


def _best_rule(title_text: str, body_text: str, *, aircraft_discount: int = 0) -> str | None:
    """The highest-scoring rule over ALREADY FOLDED text, or None.

    Split out of detect_risk_type so risk_veto() below can run the same scoring
    with one guard disabled at a time and read off WHICH guard was the one that
    removed the match. Two implementations of this loop would be two answers to
    "does this article's own vocabulary support a hazard claim".
    """
    has_context = _any(_RISK_CONTEXT, f"{title_text} {body_text}")
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


def _aircraft_discount(title_text: str, body_text: str) -> int:
    """Typhoon, Tornado, Hurricane and Cyclone are aircraft here as often as
    they are weather. Discount exactly their contribution when the article is
    plainly about military aviation, so "RAF Typhoons scrambled to intercept"
    scores zero for `storm` while "Typhoon Noul threatens South China airports"
    keeps its full score."""
    if not _any(_MILITARY_AVIATION_CONTEXT, f"{title_text} {body_text}"):
        return 0
    return _score(_keyword_pattern(_WEATHER_NAMED_AIRCRAFT), title_text, body_text)


def detect_risk_type(title: str, content: str) -> str | None:
    """The closed-taxonomy risk type for this article, or None.

    None is the expected answer for the overwhelming majority of an aviation
    news feed, and the whole design above is biased towards returning it rather
    than guessing.
    """
    # Before any scoring: an anniversary piece is a well-written article about
    # a real disaster, so every rule below would match it enthusiastically and
    # file a 2023 earthquake as a signal from this morning. See mechanism (4).
    if is_retrospective(title):
        return None

    title_text = _masked(fold_text(title))
    body_text = _masked(fold_text(content))
    return _best_rule(
        title_text,
        body_text,
        aircraft_discount=_aircraft_discount(title_text, body_text),
    )


# ---------------------------------------------------------------------------
# THE VETO, AND THE GAP IT CLOSES
#
# Every guard above -- the metaphor mask, the weather-named-aircraft discount,
# the retrospective rule, the 14 regression cases in test_risk_radar.py -- runs
# inside detect_risk_type(). And detect_risk_type() is the FALLBACK path:
# app/pipeline/enrich.py asks the LLM first and only reaches the keyword pass
# when the model declines to answer.
#
# So on the deployment that has a model configured -- which is production --
# none of those guards had any effect on a fresh article. "RAF Typhoons
# scrambled to escort a 777" is pinned in CI as a false positive and could
# still reach the live radar as a `storm`, because the model, not the keyword
# pass, decided. The regression suite was guarding a code path production does
# not take.
#
# risk_veto() is that suite applied to whatever produced the answer. It returns
# a reason ONLY when a guard actively fired -- when the article's own
# vocabulary contains the evidence that the classification is wrong -- and
# never merely because the keyword pass found nothing:
#
#   guard fired      -> a reason. The text says "Typhoon" and also says
#                       "squadron"; it says "fare war" and nothing else;
#                       the headline narrates 1988. Veto.
#   no keyword found -> None. This vocabulary is English and Turkish only, so
#                       silence on a Spanish-language earthquake report is the
#                       list's limitation, not evidence about the article. A
#                       veto here would delete exactly the stories the model is
#                       there to catch.
#
# The one asymmetric case is MILITARY_AVIATION_PROSE, and it is deliberate: an
# article whose own words say it is about military aircraft, carrying no hazard
# vocabulary at all, is not reporting a natural disaster or a conflict event.
# That is the shape of nearly every entry in PRODUCTION_FALSE_POSITIVES
# (Typhoons, Rafale/Gripen comparisons, a Hurricane warbird, a Tornado
# procurement retrospective, the NOAA hurricane hunter, an F-22 budget piece, a
# Skyraider training loss) and of the live examples this phase was opened with
# (a Boeing MH-139A delivery, "Helicopter Vs. Fighter: The Cold War Exercise",
# a Civil Air Patrol squadron deactivation). It stays narrow by requiring the
# military-aviation vocabulary to be present: a Spanish earthquake story
# carries none of it and is untouched.
# ---------------------------------------------------------------------------

#: The headline narrates the past. See is_retrospective.
RISK_VETO_RETROSPECTIVE = "retrospective"
#: The only hazard tokens in the article sat inside a masked idiom -- "fare
#: war", "under fire", "perfect storm", "political earthquake".
RISK_VETO_FIGURATIVE = "figurative_language"
#: The hazard token is an aircraft type in an article about military aviation.
RISK_VETO_WEATHER_NAMED_AIRCRAFT = "weather_named_aircraft"
#: Military-aviation prose with no hazard vocabulary anywhere in it.
RISK_VETO_MILITARY_AVIATION = "military_aviation_prose"


def risk_veto(title: str, content: str) -> str | None:
    """A reason to REFUSE a risk classification, whoever produced it, or None.

    None means "no guard fired", which is emphatically not "this is a risk" --
    it is the absence of counter-evidence, and the caller's own classification
    stands. See the section header on why that asymmetry is the whole point.
    """
    if is_retrospective(title):
        return RISK_VETO_RETROSPECTIVE

    folded_title = fold_text(title)
    folded_body = fold_text(content)
    masked_title = _masked(folded_title)
    masked_body = _masked(folded_body)

    discount = _aircraft_discount(masked_title, masked_body)
    if _best_rule(masked_title, masked_body, aircraft_discount=discount) is not None:
        # The article's own words support a hazard claim. Which hazard is the
        # classifier's business, not this function's -- the keyword pass is a
        # far worse taxonomist than the model and must not overrule it on
        # WHICH type, only on WHETHER there is one at all.
        return None

    # Nothing survived. Turn one guard off at a time to name which removed it.
    if discount and _best_rule(masked_title, masked_body) is not None:
        return RISK_VETO_WEATHER_NAMED_AIRCRAFT
    # The mask, tested by PRESENCE rather than by re-scoring the unmasked text.
    # Re-scoring misses the commonest shape: "fare war" contributes a WEAK
    # token, weak tokens need a _RISK_CONTEXT word beside them, and a pricing
    # story has none -- so both passes score zero and the comparison sees no
    # difference. What is actually true about that article is what this asks:
    # a masked idiom is in it, and after removing the idioms no hazard
    # vocabulary is left anywhere. Its only risk-shaped words were figures of
    # speech.
    if _mask_pattern().search(f"{folded_title} {folded_body}"):
        return RISK_VETO_FIGURATIVE
    if _any(_MILITARY_AVIATION_CONTEXT, f"{masked_title} {masked_body}"):
        return RISK_VETO_MILITARY_AVIATION
    return None


# ===========================================================================
# WHERE THE EVENT HAPPENED, vs. WHERE SOMEBODY TALKED ABOUT IT
#
# The rule this section exists to break: "the first geographic entity in the
# text is the event's location". That is what the previous implementation did
# -- it walked `entities` and took the first country it recognised -- and it is
# wrong in a way that is invisible on the map, because a wrong pin looks
# exactly like a right one.
#
# The failing shape is a sentence like:
#
#     "Washington said an earthquake struck Japan."
#
# Read left to right, the first country-bearing name is the United States. The
# earthquake is in Japan. The old chain pinned it to the US, and nothing
# downstream could tell.
#
# The fix is not a better ordering -- it is a distinction the data never made:
# a place name can appear in an article in two entirely different ROLES.
#
#   EVENT  the thing happened there
#   SOURCE the government, ministry, capital or spokesperson that SPOKE about
#          it is there
#
# A place in the SOURCE role is recorded in `mentioned_locations` (it is a true
# fact about the article) and is never written to risk_country. The syntactic
# signal for the SOURCE role is cheap and reliable: the place name is the
# SUBJECT of a discourse verb ("Washington SAID", "Ankara ANNOUNCED", "Tokyo
# URGED"), or it is qualified by government vocabulary ("the Japanese
# GOVERNMENT", "Turkey's foreign MINISTRY").
#
# What is deliberately NOT attempted here: verifying a resolved country against
# the coordinates it will be drawn at. There is no polygon dataset on the
# server -- placement is a frontend centroid table -- so a "does this lat/lon
# fall inside this country" check has nothing to run against. See
# `location_confidence` instead, which is the honest substitute: it says how
# much the resolution is worth, and the map refuses to pin anything below
# LOCATION_MAP_PIN_MIN rather than drawing a confident-looking dot on a guess.
# ===========================================================================

#: Verbs whose subject is speaking ABOUT an event rather than being in it. A
#: place name immediately in front of one of these is a dateline or a
#: metonym for a government, not a location. Written in folded form like every
#: other pattern in this module (see fold_text).
_DISCOURSE_VERBS: tuple[str, ...] = (
    # Bare "warning" is deliberately absent: "tsunami warning", "storm
    # warning" and "fire warning" are nouns, and including it marked the
    # country in "France was also affected by the tsunami warning" as a
    # speaker. Only the finite verb forms are discourse acts.
    "said", "says", "saying", "announced", "announces", "announcing",
    "warned", "warns", "urged", "urges", "condemned", "condemns",
    "denied", "denies", "confirmed", "confirms", "reported", "reports",
    "claimed", "claims", "accused", "accuses", "pledged", "vowed", "stated",
    "declared", "declares", "called", "calls", "told", "tells", "insisted",
    "welcomed", "rejected", "rejects", "criticised", "criticized",
    "acikladi", "aciklama", "aciklamasinda", "duyurdu", "bildirdi", "uyardi",
    "kinadi", "belirtti", "dedi", "cagrisinda", "acikliyor", "sundu",
    "reddetti", "dogruladi", "yalanladi",
)

#: Vocabulary that turns a place name into the institution that governs it.
#: "Japan's foreign ministry" and "the Turkish government" are speakers, not
#: scenes. Matched in a window AFTER the name (English possessive order) and
#: BEFORE it (adjectival order is handled by the same window on the name's
#: left, see `_role_for_occurrence`).
_GOVERNMENT_CONTEXT: tuple[str, ...] = (
    "government", "governments", "officials", "official", "ministry",
    "ministries", "minister", "embassy", "consulate", "president",
    "presidency", "state department", "foreign office", "spokesperson",
    "spokesman", "spokeswoman", "authorities", "parliament", "senate",
    "administration", "white house", "kremlin", "downing street",
    "hukumeti", "hukumet", "disisleri", "bakanligi", "bakan", "buyukelciligi",
    "yetkilileri", "yetkilisi", "sozcusu", "cumhurbaskani", "meclisi",
)

#: How many words may sit between a place name and the discourse verb that
#: makes it a speaker. Three covers "Washington on Tuesday said" and "Japan's
#: foreign ministry said"; anything looser starts reading the rest of the
#: sentence. A character window was tried first and was measurably too greedy
#: -- with 42 characters, "France was also affected by the tsunami warning"
#: reached "warning", and "the Chile earthquake" reached a "ministry" that
#: belonged to the previous clause.
_ROLE_MAX_GAP_WORDS = 3

#: A city resolved AND consistent with the country resolved independently of
#: it: two signals that agree, which is the strongest thing this pipeline can
#: produce for a location.
LOCATION_CONFIDENCE_CITY_CONFIRMED = 0.9

#: A country from a country entity in the EVENT role -- no city to confirm it,
#: but nothing contradicting it either.
LOCATION_CONFIDENCE_COUNTRY = 0.8

#: A country derived from a named airport. Slightly below a country mention:
#: the airport is certainly in that country, but the article naming an airport
#: does not by itself say the event happened at it.
LOCATION_CONFIDENCE_AIRPORT_DERIVED = 0.75

#: A city was found and it contradicted the resolved country. The city is
#: DROPPED (see resolve_risk_location) and what remains is a country the
#: article disagreed with itself about -- published, but not pinned.
LOCATION_CONFIDENCE_CONFLICT = 0.5

#: The gazetteer matched a country, but its name never appears literally in
#: the text -- it was recognised through an abbreviation or an inflected form
#: this resolver does not index -- so the role test had nothing to read and the
#: mention cannot be placed OR rejected. Used, and kept below the pin
#: threshold: "we found a country and could not check it" is exactly the state
#: that must not be drawn as a confident dot.
LOCATION_CONFIDENCE_UNVERIFIED = 0.55

#: The only country the article offered was in the SOURCE role. Kept rather
#: than discarded -- "Washington said" really is evidence the story is
#: US-adjacent, and dropping the row entirely would lose the event -- but
#: deliberately below LOCATION_MAP_PIN_MIN, because it is exactly the
#: resolution that used to produce confident wrong pins.
LOCATION_CONFIDENCE_SOURCE_ONLY = 0.4

#: The map draws nothing below this. A pin is a claim about a point on the
#: earth; a guess rendered as a dot is indistinguishable from a fact rendered
#: as a dot, and the reader has no way to tell them apart. Below the line the
#: signal still appears in the list, labelled as unplaced.
LOCATION_MAP_PIN_MIN = 0.70


@dataclass(frozen=True)
class MentionedLocation:
    """One place named in the article, with the role it played in it."""

    name: str
    #: "country" | "city"
    kind: str
    #: "event" | "source" | "unverified" -- see the section header. "source"
    #: means the place is the speaker's, not the event's; "unverified" means
    #: the gazetteer recognised it through a form this resolver could not find
    #: in the text, so no role test ever ran on it. The third value exists
    #: because labelling an untested mention "event" would put a guess and a
    #: measurement under the same word.
    role: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "kind": self.kind, "role": self.role}


@dataclass(frozen=True)
class RiskLocation:
    """Where a risk event happened, and how much that answer is worth."""

    country: str | None
    city: str | None
    #: 0-1, or None when nothing resolved at all. See the LOCATION_CONFIDENCE_*
    #: constants -- each value is a named case, not a tuned number.
    confidence: float | None
    #: Every place the article named, event and source roles alike. A superset
    #: of `country`/`city` on purpose: the fact that an article mentions
    #: Washington is worth keeping even when Washington is not where the
    #: earthquake was.
    mentioned: tuple[MentionedLocation, ...] = ()

    @property
    def mappable(self) -> bool:
        return self.confidence is not None and self.confidence >= LOCATION_MAP_PIN_MIN


#: Datelines, where the discourse verb sits IN FRONT of the place rather than
#: after it: "Reported from London", "İstanbul'dan bildirdi". Kept to a short
#: explicit list rather than "any discourse verb before the name", which would
#: mark Jakarta as a source in "Officials said the flood hit Jakarta".
_DATELINE_PREFIXES: tuple[str, ...] = (
    "reported from", "reporting from", "writing from", "speaking from",
    "filed from", "dateline", "dan bildirdi", "den bildirdi", "muhabirimiz",
)


def _alternation(patterns: tuple[str, ...]) -> str:
    return "|".join(re.escape(p) for p in patterns)


@lru_cache(maxsize=1)
def _speaker_after_re() -> re.Pattern[str]:
    """The text right AFTER a place name, when that name is the speaker.

    Anchored at the start and bounded to _ROLE_MAX_GAP_WORDS intervening words,
    so it reads the place's own clause rather than the rest of the sentence.
    Matches "Washington said", "Washington on Tuesday said", "Japan's foreign
    ministry" (folded to "japan s foreign ministry") -- and does NOT match
    "Chile earthquake death toll rises as officials confirmed", where the
    government word belongs to somebody else.
    """
    gap = rf"(?:\s+\w+){{0,{_ROLE_MAX_GAP_WORDS}}}\s+"
    return re.compile(
        rf"^{gap}(?:{_alternation(_DISCOURSE_VERBS)}|{_alternation(_GOVERNMENT_CONTEXT)})\b"
    )


@lru_cache(maxsize=1)
def _speaker_before_re() -> re.Pattern[str]:
    """The text right BEFORE a place name, when that name is the speaker.

    Anchored at the END, because this is the adjectival/possessive order --
    "the government of JAPAN", "reported from LONDON". Anchoring is what stops
    "foreign ministry on the CHILE earthquake" from marking Chile: the
    government word has to be adjacent to the name, not merely nearby.
    """
    connector = r"(?:\s+(?:of|in|for|from|by|the|a))*\s+$"
    return re.compile(
        rf"\b(?:{_alternation(_GOVERNMENT_CONTEXT)}|{_alternation(_DATELINE_PREFIXES)})"
        rf"{connector}"
    )


def _role_for_occurrence(sentence: str, start: int, end: int) -> str:
    """"source" when this occurrence of a place name is the speaker's, else
    "event".

    Two tests, both local to the occurrence and both confined to ITS OWN
    SENTENCE (see _folded_sentences): a discourse verb or government word in
    the place's own clause after it, or government/dateline vocabulary directly
    in front of it.

    The sentence confinement is not a refinement, it is the difference between
    working and not. "Flooding in Jakarta. Reported from London." folds to one
    unpunctuated string, and a window that runs past the full stop reads
    "jakarta reported from london" -- marking the flood's own city as a
    dateline. Same failure put "Earthquake hits Kahramanmaras. Damage reported
    across the region." in the source bucket.
    """
    if _speaker_after_re().search(sentence[end:]):
        return "source"
    if _speaker_before_re().search(sentence[:start]):
        return "source"
    return "event"


def _folded_sentences(title: str, content: str) -> list[str]:
    """The article as folded sentences, the headline first and separate.

    Split BEFORE folding, because folding strips the punctuation the split
    needs. The headline is joined with a full stop so it cannot merge with the
    opening sentence of the body.
    """
    return [fold_text(s) for s in _sentences(f"{title}. {content}") if s.strip()]


#: Words that put an event INSIDE the place that follows them. English carries
#: the marker in front ("in Russia", "across Taiwan"); Turkish carries it
#: behind, and fold_text turns the apostrophe into a space, so "Japonya'da"
#: arrives here as "japonya da" -- two tokens, matched by the suffix list.
_LOCATIVE_PREFIXES: tuple[str, ...] = (
    "in", "at", "across", "near", "inside", "throughout", "within",
    "around", "over",
)
_LOCATIVE_TR_SUFFIXES: tuple[str, ...] = ("da", "de", "nda", "nde", "ta", "te")


@lru_cache(maxsize=256)
def _locative_re(alias: str) -> re.Pattern[str]:
    return re.compile(
        rf"\b(?:{_alternation(_LOCATIVE_PREFIXES)})\s+{re.escape(alias)}\b"
        rf"|\b{re.escape(alias)}\s+(?:{_alternation(_LOCATIVE_TR_SUFFIXES)})\b"
    )


def _is_locative(sentences: list[str], aliases: tuple[str, ...]) -> bool:
    """Whether any of these aliases is grammatically marked as WHERE.

    The tie-break the resolver needed and did not have. Role alone answers
    "is this place the speaker or the scene", and when TWO countries both come
    back "event" the old code simply took whichever the gazetteer happened to
    list first -- which is document order, so the headline's subject wins.

    "Ukraine strikes Russian pipeline station ... struck the station in
    Russia's Republic of Bashkortostan" is that failure: both countries are in
    the event role (nobody is quoted), Ukraine is named first, and the strike
    is pinned to the attacker instead of to the target. Neither is a dateline,
    so the discourse-verb rule has nothing to say about it.

    A locative marker is real syntactic evidence and document order is not, so
    it wins. It only ever chooses BETWEEN countries the role test already
    accepted -- it can neither promote a source-role country nor reject a
    country outright, which is what keeps it from re-opening the class of bug
    the role test closed.
    """
    return any(
        _locative_re(alias).search(sentence) for alias in aliases for sentence in sentences
    )


def _place_role(sentences: list[str], aliases: tuple[str, ...]) -> str | None:
    """The role these aliases play across the article, or None when none of
    them appears at all.

    A place named several times is an EVENT location if ANY of its occurrences
    is one. A story that opens "Ankara said" and later writes "the fire near
    Ankara" is about a fire in Ankara -- one dateline does not disqualify a
    place from also being the scene. The asymmetry is deliberate: "source" is
    the label that REMOVES a candidate, so it has to be unanimous.
    """
    pattern = _keyword_pattern(aliases)
    found = False
    for sentence in sentences:
        for match in pattern.finditer(sentence):
            found = True
            if _role_for_occurrence(sentence, match.start(), match.end()) == "event":
                return "event"
    return "source" if found else None


@lru_cache(maxsize=1)
def _aliases_by_country() -> dict[str, tuple[str, ...]]:
    """Canonical country name -> every folded alias that resolves to it.

    The role test can only judge a name it can find in the text, and the
    gazetteer recognises countries through aliases the canonical name does not
    cover ("türkiye" for turkey, "amerika" for united states). Testing only the
    canonical name would make every alias-matched country untestable, which the
    resolver would then have to treat as unverified -- see
    LOCATION_CONFIDENCE_UNVERIFIED.
    """
    grouped: dict[str, list[str]] = {}
    for alias, canonical in COUNTRY_ALIASES.items():
        grouped.setdefault(canonical, []).append(fold_text(alias))
    for canonical in grouped:
        folded = fold_text(canonical)
        if folded not in grouped[canonical]:
            grouped[canonical].append(folded)
    return {name: tuple(sorted(set(a for a in aliases if a))) for name, aliases in grouped.items()}


def resolve_risk_location(
    title: str, content: str, entities: list[EntityMention]
) -> RiskLocation:
    """Where the event happened, separated from where it was talked about.

    Resolution order, and why:

    1. **Country entities in the EVENT role.** The gazetteer already ran for
       this article, so this costs a role test per country it found. A country
       that only ever appears as a discourse subject is skipped here and kept
       in `mentioned` instead -- this is the Washington/Japan fix.
    2. **The country behind a named airport.** An airport is a fixed point on
       the ground, so it is real evidence of place, but weaker than the article
       naming the country outright (LOCATION_CONFIDENCE_AIRPORT_DERIVED).
    3. **A city from RISK_CITY_COUNTRY**, which can also supply the country
       when nothing above did.
    4. **A SOURCE-role country, as a last resort**, at
       LOCATION_CONFIDENCE_SOURCE_ONLY -- below the map's pin threshold. This
       is the deliberate soft landing: the previous behaviour is preserved as
       a fallback rather than deleted, so no event disappears, but it can no
       longer masquerade as a confident placement.

    CONSISTENCY (spec §12): a city is accepted only when RISK_CITY_COUNTRY
    agrees with the country resolved above it. A city that contradicts it is
    dropped and the confidence falls to LOCATION_CONFIDENCE_CONFLICT -- the
    article disagreed with itself about where this happened, and that is
    information, not noise to be averaged away.
    """
    sentences = _folded_sentences(title, content)
    alias_index = _aliases_by_country()

    mentioned: list[MentionedLocation] = []
    seen: set[tuple[str, str]] = set()

    def remember(name: str, kind: str, role: str) -> None:
        key = (name.lower(), kind)
        if key not in seen:
            seen.add(key)
            mentioned.append(MentionedLocation(name=name, kind=kind, role=role))

    # ---- pass 1: cities, and the roles they play ------------------------
    #
    # Cities are resolved BEFORE countries, which is not the obvious order.
    # The reason is metonymy: "Ankara condemned the attack in Damascus" never
    # writes the word Turkey, so the country's own role test has nothing to
    # read -- but the capital's does, and a capital that is speaking is its
    # country speaking. Pass 2 consults these roles for exactly that.
    city_roles: dict[str, set[str]] = {}
    city_matches: list[tuple[str, str, str]] = []
    for alias, (city_name, city_country) in RISK_CITY_COUNTRY.items():
        role = _place_role(sentences, (alias,))
        if role is None:
            continue
        remember(city_name, "city", role)
        city_roles.setdefault(city_country, set()).add(role)
        city_matches.append((city_name, city_country, role))

    # ---- pass 2: countries ----------------------------------------------
    event_country: str | None = None
    #: The first event-role country the gazetteer offered, kept separately from
    #: the first LOCATIVELY MARKED one. Document order is the fallback, never
    #: the preference -- see _is_locative.
    event_country_first: str | None = None
    source_country: str | None = None
    unverified_country: str | None = None
    confidence: float | None = None
    seen_countries: set[str] = set()

    for mention in entities:
        if mention.entity_type != "country":
            continue
        canonical = mention.name.lower()
        if canonical not in COUNTRY_TO_REGION:
            continue
        role = _place_role(sentences, alias_index.get(canonical, (canonical,)))
        if role is None:
            # The gazetteer recognised this country through something this
            # resolver cannot find in the text -- an abbreviation, an inflected
            # form, or a capital standing in for the government. Its cities are
            # the next best evidence: a country whose only named city is
            # speaking is itself speaking.
            roles = city_roles.get(canonical, set())
            role = "event" if "event" in roles else ("source" if roles else None)
        # Still None means nothing tested it at all. Recorded as "unverified"
        # rather than "event": a mention whose role was never tested must not
        # read like one that passed the test, and must not outrank one either.
        seen_countries.add(canonical)
        remember(canonical.title(), "country", role or "unverified")
        if role == "event":
            if event_country_first is None:
                event_country_first = canonical
            if event_country is None and _is_locative(
                sentences, alias_index.get(canonical, (canonical,))
            ):
                event_country = canonical
        elif role == "source":
            if source_country is None:
                source_country = canonical
        elif unverified_country is None:
            unverified_country = canonical

    if event_country is None:
        event_country = event_country_first

    if event_country is not None:
        confidence = LOCATION_CONFIDENCE_COUNTRY
    else:
        for mention in entities:
            if mention.entity_type == "airport" and mention.code:
                mapped = AIRPORT_COUNTRY.get(mention.code)
                if mapped:
                    event_country = mapped
                    confidence = LOCATION_CONFIDENCE_AIRPORT_DERIVED
                    remember(mapped.title(), "country", "event")
                    break

    # ---- pass 3: which city, given the country --------------------------
    city: str | None = None
    conflicted = False
    for city_name, city_country, role in city_matches:
        if role == "source":
            # "Washington said" names Washington and places nothing.
            continue
        if event_country is not None and city_country != event_country:
            # §12: the article named a city that is not in the country it also
            # named. Recorded in `mentioned`, refused here.
            conflicted = True
            continue
        if city is None:
            city = city_name
            if event_country is None:
                event_country = city_country
                # Two independent signals agreeing is the strongest placement
                # this pipeline produces -- and they agree whether or not the
                # country's own role test could run. A gazetteer country the
                # text never spells out, confirmed by a city inside it, is
                # exactly that agreement.
                confidence = (
                    LOCATION_CONFIDENCE_CITY_CONFIRMED
                    if city_country in seen_countries
                    else LOCATION_CONFIDENCE_COUNTRY
                )
            else:
                confidence = LOCATION_CONFIDENCE_CITY_CONFIRMED

    if conflicted and city is None:
        confidence = LOCATION_CONFIDENCE_CONFLICT

    # The two soft landings, in order of how much they are worth. Both sit
    # below LOCATION_MAP_PIN_MIN: the event is published, and the map declines
    # to claim it knows where.
    if event_country is None and unverified_country is not None:
        event_country = unverified_country
        confidence = LOCATION_CONFIDENCE_UNVERIFIED
    if event_country is None and source_country is not None:
        event_country = source_country
        confidence = LOCATION_CONFIDENCE_SOURCE_ONLY

    return RiskLocation(
        country=event_country.title() if event_country else None,
        city=city,
        confidence=confidence if event_country else None,
        mentioned=tuple(mentioned),
    )


def detect_risk_place(
    title: str, content: str, entities: list[EntityMention]
) -> tuple[str | None, str | None]:
    """(country, city) for a risk event -- the two-value view of
    `resolve_risk_location`, kept because several callers want only the place.

    City is the honest weak spot. The bundled airport dataset only knows cities
    that have an airport, so the city vocabulary here stays the hand-built
    RISK_CITY_COUNTRY table in app/llm/gazetteer.py. Anything outside it
    resolves to a country with no city, and that is most of the world -- the
    map falls back to a country centroid for those rows rather than pretending
    to a precision it does not have.
    """
    resolved = resolve_risk_location(title, content, entities)
    return (resolved.country, resolved.city)


# ===========================================================================
# AVIATION RELEVANCE (spec §4-6, §16-17)
#
# The gate this feed most needed and least had. Every rule below exists to
# enforce one sentence of the spec: **the presence of an aviation WORD is not
# aviation relevance.** An earthquake story that happens to say "the airline
# industry" scores nothing here. What scores is a concrete operational fact --
# an airspace closed, flights cancelled, a runway shut, a NOTAM issued.
#
# So this is deliberately a small, closed list of OPERATIONAL patterns rather
# than a broad aviation vocabulary. A broad vocabulary is what the old
# `aviation_link` heuristic effectively was, and it could only ever answer
# "an airport was named", which is why /risks has always had to label its own
# output "anılan havalimanları" rather than "etkilenen".
#
# NULL IS NOT ZERO, and the distinction is the whole design. A score of None
# means no operational signal was FOUND -- which on a keyword pass is weak
# evidence of absence, not evidence. The gate in app/api/v1/risks.py therefore
# publishes unscored rows and filters only rows something actually measured.
# ===========================================================================

#: Operational impact, stated. Every entry names a thing that happened to an
#: aircraft, an airport or an airspace -- not a thing that happened near one.
_AVIATION_OPERATIONAL: tuple[str, ...] = (
    # Airspace
    "airspace closed", "airspace closure", "airspace closures", "airspace shut",
    "closed its airspace", "closed their airspace", "close its airspace",
    "airspace restriction", "airspace restrictions", "airspace ban",
    "no fly zone", "no flight zone",
    "hava sahasi kapatildi", "hava sahasini kapatti", "hava sahasi kapali",
    "hava sahasi kapanisi", "ucusa yasak bolge",
    # Flights
    "flights diverted", "flight diverted", "flights were diverted",
    "flights cancelled", "flights canceled", "flight cancellations",
    "flights suspended", "flights halted", "flights grounded",
    "grounded flights", "flights delayed en masse", "ground stop",
    "flight ban", "flight bans", "banned from flying", "flights resumed",
    "ucuslar iptal", "ucus iptal", "seferler iptal", "ucuslar durduruldu",
    "ucuslar askiya", "ucuslar yonlendirildi", "ucusa kapatildi",
    "ucus yasagi", "ucuslar ertelendi",
    # Airports
    "airport closed", "airport closure", "airport closures", "airport shut",
    "closed the airport", "suspended operations", "suspends operations",
    "terminal evacuated", "terminal closed", "runway closed",
    "runway closure", "runway shut", "apron closed",
    "havalimani kapandi", "havalimani kapatildi", "havalimani kapali",
    "terminal tahliye", "pist kapatildi", "pist kapali",
    "havalimani faaliyetleri durduruldu",
    # Air traffic control and formal notices
    "notam", "atc strike", "air traffic control strike",
    "air traffic controllers strike", "air traffic controller strike",
    "atc disruption", "hava trafik kontrolorleri grevi", "atc grevi",
    # Airspace AVOIDANCE, which is the regulator's instrument and was missing.
    # A closure is a state authority shutting its own sky; an avoidance
    # bulletin is a different authority telling its own airlines to stay out of
    # someone else's. Operationally they are the same fact -- routes move,
    # sectors empty, fuel burn changes -- and the EASA bulletin that told
    # airlines not to operate over Bahrain, Kuwait, Qatar and the UAE scored
    # nothing here, which is the exact opposite of what §5 asks for. "Conflict
    # Zone Information Bulletin" is the formal instrument's own name, in the
    # same class as NOTAM above.
    "conflict zone information bulletin", "conflict zone bulletin",
    "avoid the airspace", "avoiding the airspace", "airspace advisory",
    "hava sahasindan kacinilmasi", "hava sahasini kullanmamalari",
)

#: The same operational facts, written with the verb held away from the noun:
#: "flights could be cancelled", "the airport will be closed", "uçuşlar bugün
#: iptal edildi". A short regex tier rather than another hundred literals,
#: because the literal list cannot enumerate the auxiliaries.
#:
#: Still tight: each one requires the AVIATION NOUN and an OPERATIONAL VERB
#: within a few words of each other. "The airline industry expressed
#: condolences" matches nothing here, which is the rule these patterns exist
#: to keep (§5).
_AVIATION_OPERATIONAL_RE = re.compile(
    r"\bflights?\b(?:\s+\w+){0,4}?\s+\b(?:cancell?ed|cancellations?|diverted|"
    r"suspended|grounded|halted|rerouted)\b"
    # The same fact with the verb in FRONT, which is how a headline writes it:
    # "Airlines cancel dozens of Taiwan and Hong Kong flights as Typhoon Bavi
    # nears" scored nothing, because every alternative here read noun-then-verb.
    # A typhoon cancelling flights at three airports is the textbook §16 case
    # and it was passing the gate only on the unscored exemption -- publishing
    # for want of a measurement rather than because of one.
    r"|\b(?:cancel|cancels|cancell?ing|cancell?ed|divert|diverts|diverting|"
    r"ground|grounds|grounding|suspend|suspends|suspending|halt|halts|halting)\b"
    r"(?:\s+\w+){0,5}?\s+\bflights?\b"
    r"|\bairspace\b(?:\s+\w+){0,3}?\s+\b(?:closed|closure|closures|shut|"
    r"restricted|reopened)\b"
    r"|\b(?:airport|airports|runway|runways|terminal|terminals)\b"
    r"(?:\s+\w+){0,4}?\s+\b(?:closed|closure|closures|shut|shutdown|evacuated|"
    r"suspended|reopened)\b"
    r"|\bucus(?:lar|u|lari|larin)?\b(?:\s+\w+){0,4}?\s+"
    r"\b(?:iptal|durduruldu|ertelendi|yonlendirildi|askiya)\b"
    r"|\b(?:havalimani|havaalani|pist|terminal)\b(?:\s+\w+){0,4}?\s+"
    r"\b(?:kapatildi|kapandi|kapali|tahliye)\b"
    # Told to stay out of an airspace. Verb BEFORE the noun, which the closure
    # alternatives above cannot express: "avoid Gulf airspace", "not to operate
    # in the airspace of Bahrain".
    r"|\b(?:avoid|avoiding|avoided|not to operate in|not to fly through)\b"
    r"(?:\s+\w+){0,4}?\s+\bairspace\b"
    # An airport, runway or terminal STRUCK. The closure alternatives above
    # read "runway closed"; a runway bombed to stop a flight landing is the
    # same operational fact reported the other way round, and it scored
    # nothing. The verbs are deliberately the unambiguous damage ones -- "hit"
    # is excluded, because "Middle East conflict ... hit Frankfurt Airport
    # traffic" is a traffic statistic and must keep scoring nothing (§5).
    r"|\b(?:struck|shelled|bombed|attacked|damaged|destroyed)\b"
    r"(?:\s+\w+){0,3}?\s+"
    r"\b(?:airport|airports|runway|runways|terminal|terminals|control tower)\b"
    r"|\b(?:vuruldu|bombalandi|vurdu)\b(?:\s+\w+){0,3}?\s+"
    r"\b(?:havalimani|havaalani|pist)\b"
)

#: Language that makes an operational statement a FORECAST rather than a
#: report. Decides ACTUAL vs POTENTIAL; it never changes the score, because
#: "the airspace may close tomorrow" is exactly as relevant to a planner as
#: "the airspace closed today" -- it is just a different kind of fact.
_AVIATION_PROSPECTIVE: tuple[str, ...] = (
    "could", "may", "might", "expected to", "expects to", "set to", "plans to",
    "risk of", "at risk", "warns", "warned", "warning", "threatens",
    "threatening", "if the", "would be", "prepared to", "considering",
    "olabilir", "beklen", "riski", "uyardi", "tehdit", "planliyor",
    "hazirlaniyor", "ihtimali",
)

#: An operational signal in the HEADLINE. The headline is what the article is
#: about, so a closure named there is the story.
AVIATION_RELEVANCE_TITLE = 0.85

#: An operational signal in the body only. Above the gate, because a body that
#: reports cancelled flights is reporting cancelled flights -- but below the
#: headline case, which is the stronger claim.
AVIATION_RELEVANCE_BODY = 0.75

#: The publish gate (spec §16). A score at or above this is aviation-relevant.
AVIATION_RELEVANCE_GATE = 0.70

#: Longest quotable evidence sentence. Long enough for a real news sentence,
#: short enough that a run-on paragraph does not become the "quote".
MAX_EVIDENCE_CHARS = 300


@dataclass(frozen=True)
class AviationRelevance:
    """A deterministic reading of how directly an article touches flying."""

    score: float
    #: The sentence the score came from, quoted from the article as written.
    #: Not a paraphrase: an evidence field a reader cannot check against the
    #: source is decoration.
    evidence: str | None
    #: "ACTUAL" | "POTENTIAL" -- did it happen, or is it forecast?
    status: str


def detect_aviation_relevance(title: str, content: str) -> AviationRelevance | None:
    """The deterministic aviation-relevance floor, or None when no operational
    signal is present at all.

    None rather than 0.0, and the difference is load-bearing: this pass reads
    keywords, so "found nothing" means "this pass found nothing", not "there is
    no aviation impact". Returning 0.0 would let a gate delete an article on
    the strength of a keyword list's silence. See the section header.
    """
    folded_title = _masked(fold_text(title))
    folded_body = _masked(fold_text(content))

    in_title = _has_operational_signal(folded_title)
    if not in_title and not _has_operational_signal(folded_body):
        return None

    score = AVIATION_RELEVANCE_TITLE if in_title else AVIATION_RELEVANCE_BODY
    evidence, prospective = _aviation_evidence(title if in_title else content)
    return AviationRelevance(
        score=score,
        evidence=evidence,
        status="POTENTIAL" if prospective else "ACTUAL",
    )


def _aviation_evidence(source_text: str) -> tuple[str | None, bool]:
    """(the sentence that matched, is it forecast rather than report).

    Sentences are folded one at a time so the QUOTE comes back in the
    article's own words while the MATCH runs on normalised text -- a reader
    checking the evidence against the source has to find the sentence verbatim.
    """
    for sentence in _sentences(source_text) or [source_text]:
        folded = _masked(fold_text(sentence))
        if not _has_operational_signal(folded):
            continue
        return sentence.strip()[:MAX_EVIDENCE_CHARS], _any(_AVIATION_PROSPECTIVE, folded)
    return None, False


def _has_operational_signal(folded: str) -> bool:
    """Either tier: a literal operational phrase, or the held-apart form."""
    return _any(_AVIATION_OPERATIONAL, folded) or bool(_AVIATION_OPERATIONAL_RE.search(folded))


# ===========================================================================
# CURRENCY FLAGS (spec §15) -- the heuristic half
#
# The LLM answers all five (is_current_event, is_historical, is_analysis,
# is_opinion, is_recap); this function answers only the two that PR #62's
# retrospective guard already has real evidence for, and leaves the rest None.
#
# None means "nobody looked", and it must not be spelled False. An
# `is_current_event=False` written on no evidence is a row deleted by a gate
# that never measured anything -- which is the failure mode the confidence
# floor in app/api/v1/risks.py already documents at length for its own
# unscored case.
# ===========================================================================


def detect_currency_flags(title: str) -> dict[str, bool | None]:
    """is_historical / is_recap from the retrospective guard; the rest None.

    `is_retrospective` reads the HEADLINE for anniversary markers and for an
    old year narrated in the past tense -- both of which say "this piece is
    looking backwards". That is the same claim as is_historical, so the signal
    is reused rather than re-derived.

    is_current_event is the negation ONLY when the guard fired: a headline that
    is not retrospective has not thereby been shown to be current, so it stays
    None and the uniqueness gate lets it through.
    """
    looking_back = is_retrospective(title)
    return {
        "is_current_event": False if looking_back else None,
        "is_historical": True if looking_back else None,
        "is_recap": True if looking_back else None,
        "is_analysis": None,
        "is_opinion": None,
    }


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
