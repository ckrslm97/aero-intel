"""How much a story matters to a revenue-management desk, as a number.

Replaces `ArticleEnrichment.importance_score` for the Gazete's "fewer, more
critical stories" filter. That column does not measure importance, and this is
not an opinion -- it is arithmetic:

    verify.py:28   confidence = 0.4 + 0.15 * (corroborating_count - 1) + 0.3 * avg_trust
    enrich.py:129  importance = min(1, confidence * 0.7 + min(count, 5) * 0.06)

Production runs at `corroborating_count == 1` for every single article (484 of
484 in the measured snapshot), because the dedup pass almost never finds two
outlets filing the same story within its window. Substitute n = 1 and the whole
expression collapses to

    importance = 0.34 + 0.21 * source.trust_weight

which contains no term for the article at all. The column is a restatement of
which outlet published it: eighteen sources produced exactly eight distinct
values across the whole archive, and every source produced exactly one. AeroTime
scores 0.487 for a fare war and 0.487 for an airport cat.

Raising the threshold on that column therefore does not select important
stories, it selects publishers -- which is why every attempted cut-off emptied
a whole tab of the paper instead of thinning it.

--- What this scores instead -----------------------------------------------

Eight sub-scores, each in [0, 1], combined by fixed weights. The production
path of each is deliberately separated, because the expensive ones cannot run
on everything:

  DETERMINISTIC -- no network, microseconds, runs on every article
    freshness             how long ago it was published
    source_reliability    the tier ladder, as one input among eight
    competitive_impact    does it name a rival (or the home carrier), and where
    geographic_relevance  how close to a hub this desk actually sells from

  SEMI-DETERMINISTIC -- free, already calibrated against 400 production articles
    relevance             app/pipeline/relevance.py score_article(), normalised

  LLM -- one consolidated call, for the day's shortlist only (~20 articles)
    rm_impact             does this move fares, yields or revenue
    demand_impact         does this move what the market wants
    capacity_impact       does this move what carriers supply

--- The weights -------------------------------------------------------------

They sum to 1.0 (asserted below) and every one of them is an editorial claim,
so each is argued rather than tuned:

  rm_impact 0.20 leads. It is the only component that answers the actual
    question -- "does this change what my desk does on Monday" -- rather than a
    proxy for it. It leads by a small margin, not a large one, because it is
    also the only component that can be wrong in a way nobody can check.

  relevance 0.16 is second because it is the one signal in this file with a
    calibration history: it was fitted against 400 production articles and its
    failure modes are written down (see relevance.py DECISIVE_TERMS, which
    exists because rival campaign stories are terse one-liners). A free,
    audited signal outranks three of the four remaining deterministic ones.

  competitive_impact 0.14. Watching named rivals is the desk's standing brief,
    and RIVAL_CODES is the product's own list of who counts, so this is not a
    guess about relevance -- it is the definition of it, applied.

  demand_impact 0.12 and capacity_impact 0.12, equal by construction. PR #69
    split "demand_capacity" into two subcategories precisely because they are
    the two sides of one trade and an RM desk must not have them conflated;
    weighting one above the other here would silently re-merge them.

  freshness 0.10. This is a newspaper. A critical story from six days ago is
    not today's front page -- but it is a *tenth* of the answer, not the whole
    of it, because a week-old capacity cut still governs next month's fares.

  geographic_relevance 0.09. A story about IST or SAW is worth more to this
    desk than the identical story about a market it does not serve, and hub
    proximity is the cheapest honest proxy for that.

  source_reliability 0.07, deliberately the SMALLEST of the eight. Source
    identity is what the old score was made of, almost entirely; re-inflating
    it here would rebuild the exact bug this module exists to remove. It is
    kept because who published something is real evidence, and dropped to a
    seventh of the answer because it is not the answer.

--- Missing LLM components --------------------------------------------------

Only the shortlist is scored by the model, so on ~95% of articles the three
impact components are NULL -- by construction, not by failure. `combine()`
therefore RENORMALISES over the components that are present rather than
scoring an absent component as zero.

This is the opposite of what pipeline/confidence.py does with
`classifier_certainty`, and the difference is the whole justification: there,
the model was asked and did not answer, so silence is evidence. Here the model
was deliberately never asked, and treating "we chose not to spend a call on
this" as "this story has no RM impact" would make every un-shortlisted article
unrankable against every shortlisted one -- including the shortlist's own
selection pass, which runs before any LLM call exists to read.

NULL and 0.0 are kept distinct in the database for the same reason: 0.0 means
the model read the article and found no capacity angle, NULL means nobody
looked.

--- Auditability ------------------------------------------------------------

`as_detail()` stores the components AND the weights that produced the score, so
a row scored today is still explainable after the weights above have moved on.
Same pattern, and the same reason, as pipeline/confidence.py `as_detail()`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.hubs import HUBS
from app.llm.gazetteer import AIRLINES, fold_for_match
from app.pipeline.relevance import score_article
from app.taxonomy import (
    RIVAL_CODES,
    SOURCE_TIERS,
    effective_source_tier,
)

# --- weights -----------------------------------------------------------------

WEIGHT_RM_IMPACT = 0.20
WEIGHT_RELEVANCE = 0.16
WEIGHT_COMPETITIVE_IMPACT = 0.14
WEIGHT_DEMAND_IMPACT = 0.12
WEIGHT_CAPACITY_IMPACT = 0.12
WEIGHT_FRESHNESS = 0.10
WEIGHT_GEOGRAPHIC_RELEVANCE = 0.09
WEIGHT_SOURCE_RELIABILITY = 0.07

WEIGHTS: dict[str, float] = {
    "rm_impact": WEIGHT_RM_IMPACT,
    "relevance": WEIGHT_RELEVANCE,
    "competitive_impact": WEIGHT_COMPETITIVE_IMPACT,
    "demand_impact": WEIGHT_DEMAND_IMPACT,
    "capacity_impact": WEIGHT_CAPACITY_IMPACT,
    "freshness": WEIGHT_FRESHNESS,
    "geographic_relevance": WEIGHT_GEOGRAPHIC_RELEVANCE,
    "source_reliability": WEIGHT_SOURCE_RELIABILITY,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "intelligence weights must sum to 1"

#: The three the model produces. Everything else is computable offline, which
#: is what makes the shortlist selection possible in the first place.
LLM_COMPONENTS: tuple[str, ...] = ("rm_impact", "demand_impact", "capacity_impact")
DETERMINISTIC_COMPONENTS: tuple[str, ...] = tuple(
    name for name in WEIGHTS if name not in LLM_COMPONENTS
)

#: Share of the total weight the free path can reach on its own. Not a
#: constant to tune -- it is what the weights above already add up to, named
#: here so the selection pass can state what it is ranking on.
DETERMINISTIC_WEIGHT_SHARE = sum(WEIGHTS[name] for name in DETERMINISTIC_COMPONENTS)


# --- freshness ---------------------------------------------------------------

#: A story halves in value every two days. Chosen against the shortlist window
#: rather than in the abstract: the critical-selection pass looks back 24-48
#: hours (app/services/critical_selection.py DEFAULT_WINDOW_HOURS), so the
#: half-life has to make the two ends of that window distinguishable without
#: collapsing the older one to nothing -- at 2.0 days a 24-hour-old story still
#: scores 0.71 and a 48-hour-old one exactly 0.50.
#:
#: Shorter than pipeline/risk_scoring.py's 3.0 on purpose. A wildfire stays a
#: wildfire for a week; a fare move is answered by the market in a day.
FRESHNESS_HALF_LIFE_DAYS = 2.0


def freshness(published_at: datetime | None, *, now: datetime | None = None) -> float:
    """1.0 at publication, halving every FRESHNESS_HALF_LIFE_DAYS.

    An undated article scores as if it were exactly one half-life old rather
    than as brand new or as ancient. Feeds that omit dates are a property of
    the feed, not evidence about the story, and both extremes are lies the
    ranking would then act on -- 1.0 would let every undated aggregator item
    lead the paper, 0.0 would bury a genuine wire story for its publisher's
    RSS habits.
    """
    if published_at is None:
        return 0.5
    reference = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    days = (reference - published_at).total_seconds() / 86400.0
    # A future timestamp is a feed with a clock problem, not tomorrow's news.
    days = max(0.0, days)
    return round(math.pow(0.5, days / FRESHNESS_HALF_LIFE_DAYS), 4)


# --- source reliability ------------------------------------------------------

#: The tier ladder as numbers -- the same rungs and the same ordering
#: pipeline/confidence.py scores, kept as its own table because this module
#: must not import the confidence pipeline (it is read by the API layer, and
#: confidence.py is a pipeline-internal concern).
TIER_SCORES: dict[str, float] = {
    "official": 1.00,
    "regulator": 0.90,
    "agency": 0.75,
    "trade": 0.60,
    "aggregator": 0.40,
}

assert set(TIER_SCORES) == set(SOURCE_TIERS), "tier score table must cover every tier"

#: How much of the reliability score the declared ladder decides, with the rest
#: left to the source's own trust_weight. Not 1.0: two trade outlets seeded at
#: 0.55 and 0.70 are not equally trusted by the people who seeded them, and a
#: pure ladder would flatten a distinction the source list already makes.
#: Not 0.5 either -- the ladder is a deliberate editorial statement about who
#: publishes what, and trust_weight is a number somebody typed.
TIER_SHARE = 0.75


def source_reliability(tier: str | None, trust_weight: float | None) -> float:
    """Where this outlet sits on the source ladder, softened by its trust weight.

    `tier` is nullable on the model, so the effective tier is resolved exactly
    as every other consumer resolves it (app.taxonomy.effective_source_tier) --
    a source seeded before the column existed falls back to its trust_weight
    bucket rather than silently scoring as an aggregator.
    """
    resolved = effective_source_tier(tier, trust_weight)
    ladder = TIER_SCORES.get(resolved, TIER_SCORES["trade"])
    weight = 0.0 if trust_weight is None else max(0.0, min(1.0, float(trust_weight)))
    return round(TIER_SHARE * ladder + (1.0 - TIER_SHARE) * weight, 4)


# --- competitive impact ------------------------------------------------------

#: The home carrier. Deliberately not in taxonomy.RIVAL_CODES -- TK is what the
#: desk works FOR, not what it watches -- but a story about the home carrier is
#: at least as commercially urgent as one about a rival, so it scores here.
HOME_CARRIER_CODES: frozenset[str] = frozenset({"TK"})
WATCHED_CARRIER_CODES: frozenset[str] = frozenset(RIVAL_CODES) | HOME_CARRIER_CODES

#: code -> every alias the gazetteer recognises, inverted from its own table so
#: the two can never drift. Used to answer "was the carrier named in the
#: headline or only somewhere in the body", which the entity links cannot say.
#:
#: The aliases are FOLDED here, because the gazetteer stores them unfolded --
#: its keys include "türk hava yolları" with its diacritics intact, while
#: `fold_for_match` strips them to "turk hava yollari". Matching a raw key
#: against a folded title silently never fires, which would have scored every
#: Turkish-language story about the home carrier as mentioning nobody.
_ALIASES_BY_CODE: dict[str, tuple[str, ...]] = {}
for _alias, (_name, _code) in AIRLINES.items():
    if _code in WATCHED_CARRIER_CODES:
        _folded = fold_for_match(_alias)
        if _folded:
            _ALIASES_BY_CODE.setdefault(_code, ())
            _ALIASES_BY_CODE[_code] += (_folded,)

#: A carrier in the HEADLINE means the story is about that carrier.
COMPETITIVE_TITLE = 1.0
#: Two or more watched carriers in the body is a comparison, a market piece or
#: a fare-war story -- worth more than one passing mention, less than a headline.
COMPETITIVE_MULTI_BODY = 0.75
#: One watched carrier, body only. Real signal; often a list or a quote.
COMPETITIVE_BODY = 0.6
#: Nothing watched. Genuinely zero -- unlike geography, "no rival is involved"
#: is a statement about the story, not a gap in what we know about it.
COMPETITIVE_NONE = 0.0


def competitive_impact(title: str, airline_codes: frozenset[str] | set[str]) -> float:
    """Whether a watched carrier is in this story, and how centrally.

    `airline_codes` comes from the entity links, which is the authoritative
    answer to *whether* a carrier appears. Position is then read off the title
    directly, because the link table records that an article mentions Emirates,
    never that "Emirates" is the first word of the headline -- and those two
    articles are not equally important to a desk that watches Emirates.
    """
    watched = {code for code in airline_codes if code in WATCHED_CARRIER_CODES}
    if not watched:
        return COMPETITIVE_NONE

    folded_title = fold_for_match(title or "")
    for code in watched:
        for alias in _ALIASES_BY_CODE.get(code, ()):
            if alias in folded_title:
                return COMPETITIVE_TITLE

    return COMPETITIVE_MULTI_BODY if len(watched) > 1 else COMPETITIVE_BODY


# --- geographic relevance ----------------------------------------------------

#: Derived from app/hubs.py rather than hand-listed, so adding a hub there
#: cannot leave this table behind. "Home" is the country the desk sells from,
#: which is exactly how hubs.py already labels IST and SAW.
HOME_HUB_CODES: frozenset[str] = frozenset(
    hub.code for hub in HUBS if hub.country == "Turkey"
)
#: A hub a watched rival is based at -- where a capacity or fare move lands
#: directly on top of this desk's own network.
RIVAL_HUB_CODES: frozenset[str] = frozenset(
    hub.code
    for hub in HUBS
    if hub.code not in HOME_HUB_CODES and set(hub.carriers) & frozenset(RIVAL_CODES)
)
OTHER_HUB_CODES: frozenset[str] = frozenset(
    hub.code for hub in HUBS if hub.code not in HOME_HUB_CODES | RIVAL_HUB_CODES
)

#: The region this desk sells from. taxonomy.py files Turkey with the Gulf
#: rather than with Europe -- that is the benchmark set a Turkish carrier's
#: revenue desk works against -- and hubs.py follows the same call.
HOME_REGION = "middle-east"

GEO_HOME_HUB = 1.0
GEO_RIVAL_HUB = 0.8
GEO_OTHER_HUB = 0.6
GEO_HOME_REGION = 0.5
GEO_KNOWN_REGION = 0.35
#: No geography at all. Not zero: an unplaced story is unplaced, not
#: irrelevant, and industry-wide news (an IATA demand forecast, an NDC mandate)
#: routinely names no airport. Scoring it 0 would let a parochial story about a
#: hub nobody flies to outrank a global fare-structure change.
GEO_UNPLACED = 0.15


def geographic_relevance(
    region: str | None, airport_codes: frozenset[str] | set[str]
) -> float:
    """How close this story lands to where the desk actually sells.

    Strongest signal wins rather than accumulating: an article naming both IST
    and JFK is an IST story with a destination, and averaging the two would
    make it score below an article that named IST alone.
    """
    codes = {code.upper() for code in airport_codes if code}
    if codes & HOME_HUB_CODES:
        return GEO_HOME_HUB
    if codes & RIVAL_HUB_CODES:
        return GEO_RIVAL_HUB
    if codes & OTHER_HUB_CODES:
        return GEO_OTHER_HUB
    if region == HOME_REGION:
        return GEO_HOME_REGION
    if region:
        return GEO_KNOWN_REGION
    return GEO_UNPLACED


# --- relevance ---------------------------------------------------------------

#: Raw score at which the normalised relevance reaches exactly 0.5.
#:
#: Measured, not assumed. Over the 484-article production snapshot
#: `score_article()` returns: min 0, median 8, p75 18, p90 28, p95 36, p99 61,
#: max 327 (mean 12.7). It is an unbounded keyword count with a very long tail,
#: so it needs a curve, not a divisor.
#:
#: A linear `min(1, raw / N)` was the first attempt and it is wrong for this
#: distribution whichever N you pick: N=20 saturates everything above p75, N=28
#: everything above p90. Those are precisely the articles the shortlist is
#: chosen from, so a hard clip destroys the ordering exactly where the whole
#: mechanism depends on it -- a fare-war feature scoring 64 and a routine item
#: scoring 28 would tie at 1.0.
#:
#: `1 - 0.5 ** (raw / RELEVANCE_HALF_SCORE)` is monotone over the entire range
#: and approaches 1.0 without reaching it, so nothing ties across the band the
#: shortlist is actually drawn from. At 12 the landmarks fall: the LLM gate
#: (6, settings.llm_relevance_threshold) -> 0.29, median -> 0.37, p75 -> 0.65,
#: p90 -> 0.80, p95 -> 0.87, p99 -> 0.97. Only a far outlier (raw > ~160, past
#: the observed max of 327) rounds to 1.0 at four decimal places, which is
#: three times the p99 and not a range anything is ranked within.
RELEVANCE_HALF_SCORE = 12.0


def relevance(title: str, content: str) -> float:
    """The existing local relevance score, normalised to [0, 1).

    Deliberately reuses app/pipeline/relevance.py rather than restating it.
    That scorer is the one component here with a calibration history against
    real articles, its keyword tables are the taxonomy's own, and it already
    runs on every article at enrichment time -- a second implementation would
    be a second thing to keep in step and would throw that calibration away.
    """
    raw = max(0, score_article(title or "", content or "").score)
    return round(1.0 - math.pow(0.5, raw / RELEVANCE_HALF_SCORE), 4)


# --- inputs and result -------------------------------------------------------


@dataclass(frozen=True)
class ArticleSignals:
    """Everything the deterministic half of the score is allowed to depend on.

    A plain dataclass rather than an ORM object so both callers can build one:
    the enrichment pipeline has entity *mentions* in memory and no article row
    yet, while the critical-selection pass has a stored article and reads its
    entity links back out of Postgres.
    """

    title: str
    content: str
    published_at: datetime | None
    source_tier: str | None
    trust_weight: float | None
    region: str | None = None
    airline_codes: frozenset[str] = frozenset()
    airport_codes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ImpactScores:
    """The model's three answers, or the absence of them.

    Every field is optional and None is a first-class value meaning "not
    asked": see the module docstring on why that is not the same as 0.0.
    """

    rm_impact: float | None = None
    demand_impact: float | None = None
    capacity_impact: float | None = None

    @property
    def is_empty(self) -> bool:
        return all(
            getattr(self, name) is None
            for name in ("rm_impact", "demand_impact", "capacity_impact")
        )

    def as_components(self) -> dict[str, float]:
        return {
            name: value
            for name, value in (
                ("rm_impact", self.rm_impact),
                ("demand_impact", self.demand_impact),
                ("capacity_impact", self.capacity_impact),
            )
            if value is not None
        }


@dataclass(frozen=True)
class NewsScore:
    intelligence_score: float
    components: dict[str, float]
    #: The weights actually applied, after renormalising over whichever
    #: components were present. Stored, not recomputed -- that is what lets a
    #: score written today still be explained once WEIGHTS above has changed.
    applied_weights: dict[str, float] = field(default_factory=dict)

    @property
    def has_llm_components(self) -> bool:
        return any(name in self.components for name in LLM_COMPONENTS)

    def as_detail(self) -> dict:
        """The JSON written to `score_detail`.

        Same shape and same purpose as pipeline/confidence.py `as_detail()`:
        components plus the weights that combined them, so the number is
        reconstructible from the row alone.
        """
        return {
            "score": round(self.intelligence_score, 4),
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "weights": {k: round(v, 4) for k, v in self.applied_weights.items()},
            "llm_scored": self.has_llm_components,
        }


def combine(components: dict[str, float]) -> NewsScore:
    """Weighted mean of whichever sub-scores are present.

    Renormalising over the present components -- rather than summing
    `component * WEIGHTS[name]` and letting absent ones contribute zero -- is
    what makes a deterministic-only score comparable with an LLM-scored one.
    See the module docstring; it is the single most consequential decision in
    this file.

    Unknown component names are ignored rather than raising: a `score_detail`
    written by a future version of this module must still be readable by an
    older one.
    """
    present = {
        name: max(0.0, min(1.0, float(value)))
        for name, value in components.items()
        if name in WEIGHTS and value is not None
    }
    if not present:
        return NewsScore(intelligence_score=0.0, components={}, applied_weights={})

    total_weight = sum(WEIGHTS[name] for name in present)
    applied = {name: WEIGHTS[name] / total_weight for name in present}
    score = sum(present[name] * applied[name] for name in present)
    return NewsScore(
        intelligence_score=round(min(1.0, max(0.0, score)), 4),
        components=present,
        applied_weights=applied,
    )


def deterministic_components(
    signals: ArticleSignals, *, now: datetime | None = None
) -> dict[str, float]:
    """The five sub-scores that cost nothing. Runs on every article."""
    return {
        "freshness": freshness(signals.published_at, now=now),
        "source_reliability": source_reliability(signals.source_tier, signals.trust_weight),
        "competitive_impact": competitive_impact(signals.title, signals.airline_codes),
        "geographic_relevance": geographic_relevance(signals.region, signals.airport_codes),
        "relevance": relevance(signals.title, signals.content),
    }


def score(
    signals: ArticleSignals,
    impact: ImpactScores | None = None,
    *,
    now: datetime | None = None,
) -> NewsScore:
    """The intelligence score for one article.

    `impact` omitted (the common case, ~95% of articles) produces a score built
    from the deterministic components alone -- a real, comparable number, not a
    placeholder. Passing the model's answers adds three components and shifts
    the score; it does not change its meaning or its scale.
    """
    components = deterministic_components(signals, now=now)
    if impact is not None:
        components.update(impact.as_components())
    return combine(components)
