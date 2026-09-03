"""Risk Radarı: natural-disaster and conflict signals classified out of the
news feed, grouped by country.

Grouping and ranking are done here rather than in the browser on purpose. The
page draws the same set three ways -- a map, a "Sıcak Noktalar" ranking and a
country-sectioned list -- and all three must agree on which country is worst.
Computing the weighted score once, server-side, is what guarantees that; three
client-side re-derivations of it would be three chances to disagree.

What this data CANNOT say, listed once here because every field below is shaped
by it and the UI has to keep the same discipline:

* **No event coordinates.** Placement is a country or city centroid, never the
  event's own point -- the classifier resolves a name, not a location. What is
  now checked is whether the NAME is the event's at all: see the location gate
  below, which refuses a pin rather than drawing one on a dateline.
* **No event-occurrence time.** Every timestamp here is a PUBLICATION time.
  `first_reported_at`/`last_reported_at` bracket the coverage, not the event.
* **No lifecycle.** Nothing in the feed says an event is active, contained or
  over. `is_fresh`/`is_updated` are statements about the coverage flow, and
  they are named that way so they cannot be mistaken for a status. This is also
  why the currency flags stop at is_current_event/is_historical/is_analysis/
  is_opinion/is_recap and do not attempt is_developing or is_resolved.
* **No operational impact DATA.** There is no schedule, OTP or route feed
  behind this product, so an airport named in an article is exactly that --
  named (see AirportRefOut and aviation_link_for()).
  `aviation_relevance_score` does not change that: it reads what the ARTICLE
  says happened to flying ("the airspace was closed"), which is reporting, not
  measurement. It is a filter on relevance, never a claim about operations.

Three gates run before anything reaches this page, and each one publishes its
own count so the reader can reconcile what is shown with what was found:
currency (§15), aviation relevance (§16), confidence (§17). All three treat an
UNSCORED row as publishable -- "nobody measured this" is not evidence of
failure, and a gate that reads it as one deletes the archive instead of
filtering it. Each gate's block below says how that applies to it.
"""
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.llm.heuristic import AVIATION_RELEVANCE_GATE, LOCATION_MAP_PIN_MIN
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity
from app.pipeline.verify import CONFIDENCE_FORMULA_MIN, measured_confidence
from app.pipeline.clustering import EventCandidate, cluster, entity_codes, pick_primary, tier_for_source
from app.taxonomy import (
    COUNTRY_TO_REGION,
    RISK_SEVERITY_WEIGHT,
    RISK_TYPE_FAMILY,
    RISK_TYPE_LABELS_TR,
)

router = APIRouter(prefix="/risks", tags=["risks"])


class AirportRefOut(BaseModel):
    """An airport NAMED IN the coverage of this event -- never one we claim is
    affected by it.

    These come from the entity gazetteer's airport matches across the cluster's
    articles, which is evidence that the story mentions the airport and nothing
    more. There is no operational feed behind this product, so "etkilenen
    havalimanları" would be a claim nothing in the pipeline can support; the UI
    label is "Anılan havalimanları" for exactly that reason.
    """

    code: str
    name: str


class RiskMemberOut(BaseModel):
    """One article inside the cluster: a telling of the event, with its own
    outlet, tier and publication time."""

    title: str
    url: str
    source_name: str
    #: official | regulator | agency | trade | aggregator -- see
    #: pipeline/clustering.py tier_for_source.
    source_tier: str
    published_at: datetime | None


class RiskItemOut(BaseModel):
    id: str
    headline: str
    url: str
    source_name: str
    published_at: datetime | None
    risk_type: str
    risk_family: str
    risk_type_label_tr: str
    severity: str
    country: str | None
    city: str | None
    region: str | None
    # Whether the story broke in the last 24h. Computed here so the page shows
    # a quiet "son 24 saat" tag without every card re-deriving the cutoff (and
    # without a flash animation -- this is a disaster feed, not a notification).
    is_fresh: bool
    # How many articles cluster()'d into this one card. 1 for the common case;
    # >1 means multiple outlets reported the same event and this is already
    # the merged, reconciled view -- see list_risks()'s clustering pass.
    source_count: int = 1

    # --- the cluster, unpacked ------------------------------------------
    #
    # Everything below was already loaded by list_risks()'s single query --
    # members, their sources, their airport entities, the primary's enrichment
    # -- and then discarded before serialization. Reading the page meant
    # reading a headline and a country; the evidence behind the signal existed
    # in memory on every request and reached nobody.

    #: The primary article's Turkish summary (falling back to its English one).
    #: None rather than "" when the enrichment never produced either.
    summary_tr: str | None = None
    #: Cross-source verification score of the primary article's enrichment,
    #: 0-1, and how many sources corroborated it. Shown as a band plus the
    #: number -- a band with no number behind it is an opinion.
    #:
    #: None means the confidence pass never scored this row (see
    #: `measured_confidence`), which is why the card draws no pill at all
    #: rather than a "Düşük 0.00" nobody measured.
    confidence_score: float | None = None
    corroborating_source_count: int | None = None

    #: PUBLICATION span of the cluster: when the first and the last member were
    #: published. Not the event's own start and end -- nothing in this pipeline
    #: knows when an earthquake began, only when someone wrote about it.
    first_reported_at: datetime | None = None
    last_reported_at: datetime | None = None
    #: "Still being written about": first telling older than 24h, newest one
    #: inside it. Deliberately a statement about coverage, not about the event
    #: -- there is no lifecycle (active/contained/resolved) anywhere in this
    #: data, and a badge implying one would be invented.
    is_updated: bool = False

    #: Airports named across the cluster's articles. Capped -- see AIRPORT_CAP.
    airports: list[AirportRefOut] = []
    #: "direct" | "indirect" -- see aviation_link_for(). A link-strength hint
    #: about how close the coverage sits to aviation, NOT an impact score.
    aviation_link: str = "indirect"

    #: The publication chronology, oldest first. Capped -- see MEMBER_CAP.
    members: list[RiskMemberOut] = []
    #: True when `members` is the first MEMBER_CAP of a longer list, so the UI
    #: can say so instead of silently showing a partial chronology.
    members_truncated: bool = False

    #: "normal" | "low" -- how loudly the page is entitled to state this
    #: signal. Decided here rather than in the browser for the same reason the
    #: weighted score is: the map, the ranking and the list all draw the same
    #: set, and three client-side re-derivations of "is this one weak" would be
    #: three chances to disagree. See visibility_for() for the calibration.
    visibility: str = "normal"

    #: The primary's source-language headline, when `headline` is a
    #: translation of it. None when the two are the same string -- there is
    #: nothing for the UI to reveal on hover in that case.
    headline_original: str | None = None
    #: Whether `headline` is Turkish produced by the translator. False means
    #: the card is showing source-language text, which the page says out loud
    #: with the app's existing "otomatik çeviri yok" tag rather than silently.
    is_translated: bool = False

    # --- the verification evidence --------------------------------------
    #
    # Every gate below publishes a number as well as applying it. A row that
    # was let through because nobody measured it must be distinguishable from
    # one that was measured and passed -- otherwise the page is asserting a
    # confidence the pipeline never earned, which is the failure this whole
    # revision exists to fix.

    #: How much the placement is worth, 0-1, or None when nothing resolved.
    #: Below LOCATION_MAP_PIN_MIN, `country`/`city` are BLANKED and the signal
    #: is filed under UNKNOWN_COUNTRY -- see place_for() on why a weak
    #: placement is worse than none.
    location_confidence: float | None = None
    #: True when this signal earned a map pin. False means the list shows it
    #: and the map does not.
    is_mappable: bool = True
    #: Every place the article named with the role it played:
    #: [{"name": "United States", "kind": "country", "role": "source"}].
    #: "source" is a dateline or a government quote -- named, not the scene.
    #: Served rather than kept internal because it is the audit trail for a
    #: BLANKED placement: without it, "konum belirsiz" is unanswerable.
    mentioned_locations: list[dict] = []

    #: 0-1, or None when neither the model nor the keyword floor scored this.
    #: None is not a low score, and the gate treats it accordingly.
    aviation_relevance_score: float | None = None
    #: "llm" | "heuristic" | "unscored" -- which pass produced the score.
    aviation_relevance_source: str | None = None
    #: The sentence the score was read off, in the article's own words.
    aviation_impact_evidence: str | None = None
    #: "ACTUAL" | "POTENTIAL" -- reported, or forecast.
    aviation_impact_status: str | None = None


class SeverityCountsOut(BaseModel):
    high: int
    medium: int
    low: int


class RiskCountryOut(BaseModel):
    country: str
    region: str | None
    count: int
    # high=3, medium=2, low=1, summed. The one number the map, the ranking and
    # the list all sort by.
    score: int
    severity_counts: SeverityCountsOut
    items: list[RiskItemOut]


class RiskRadarOut(BaseModel):
    days: int
    total: int
    #: How many clusters the confidence gate removed from this window. Served
    #: rather than swallowed: a page that quietly drops rows is a page whose
    #: counts nobody can reconcile, and "3 sinyal eşiğin altında kaldı" is a
    #: fact the reader is entitled to. See CONFIDENCE_VERIFIED_MIN.
    suppressed_low_confidence: int = 0
    #: How many clusters the aviation-relevance gate removed -- events that
    #: were measured and found to have no operational bearing on flying.
    #: Separate from the line above because they are different rejections and
    #: a single "N suppressed" number would hide which rule is doing the work.
    suppressed_aviation_irrelevant: int = 0
    #: How many articles the currency gate removed BEFORE clustering -- rows a
    #: classifier explicitly marked as not-current (an anniversary, a
    #: retrospective, an analysis piece). Counted in articles rather than
    #: clusters because the filter runs in SQL, before anything is grouped.
    suppressed_not_current: int = 0
    #: How many published clusters the map will not pin, because their
    #: placement scored below LOCATION_MAP_PIN_MIN. They are in `countries`
    #: under UNKNOWN_COUNTRY, not missing -- this number is what lets the page
    #: say "N sinyalin konumu doğrulanamadı" instead of the map and the list
    #: silently disagreeing about how many events there are.
    unplaced_low_confidence: int = 0
    countries: list[RiskCountryOut]
    # Feed-wide totals per type/family, so the filter chips can show counts
    # without the client flattening every group to count them.
    type_counts: dict[str, int]
    family_counts: dict[str, int]
    # When this rollup was computed. The page stamps it as "son güncelleme",
    # which is a fact about the response and not about the newest article --
    # those two are different numbers and the page shows both.
    generated_at: datetime


class RiskTrendPointOut(BaseModel):
    #: UTC day, ISO "YYYY-MM-DD".
    day: str
    family: str
    severity: str
    #: ARTICLES published that day, not events that happened that day. See
    #: risk_trend()'s docstring.
    count: int


class RiskTrendOut(BaseModel):
    days: int
    points: list[RiskTrendPointOut]
    #: Shipped in the payload rather than left to the frontend to remember:
    #: every consumer of this series has to state what it counts, and a caption
    #: that lives only in one component is one refactor away from being lost.
    note: str = (
        "Günlük değerler yayın hacmini sayar: o gün yayımlanan risk haberi "
        "sayısı. Olayların gerçekleşme zamanı bu veride yok."
    )


# Rows whose country never resolved still belong on the page -- the event is
# real, only its placement is unknown -- so they are grouped under this label
# rather than dropped. The map skips them (there is no centroid for "unknown");
# the list shows them last.
UNKNOWN_COUNTRY = "Belirtilmemiş"

FRESH_WINDOW = timedelta(hours=24)

#: The default window, in days. Five, down from fourteen.
#:
#: A risk radar's job is to say what is happening now, and a fortnight is not
#: now: at 14 days the page's own top row was routinely a story whose newest
#: telling was a week old, sitting beside one from this morning at the same
#: visual weight. The window is what makes "still being written about"
#: (is_updated) mean something -- over 14 days almost everything qualifies.
#:
#: The upper bound is untouched and 7/14/30 remain selectable: the shorter
#: default is a statement about what the page opens on, not a claim that the
#: older window is useless.
DEFAULT_WINDOW_DAYS = 5

#: How many airports a card will name. Six is what a card and a drawer chip row
#: can carry without wrapping into a wall of codes; a story naming more than
#: six airports is a network-wide piece where the specific list stopped being
#: the point. Deterministic (sorted by code), so the same event names the same
#: airports on every request.
AIRPORT_CAP = 6

#: How many articles the publication chronology carries. Twelve is well past
#: the 3-4 members a real cluster has, and it bounds the payload for the
#: pathological case (a wire story republished by every aggregator) without
#: hiding a normal cluster's tail. `members_truncated` says when it bit.
MEMBER_CAP = 12

#: Risk types whose subject IS an aviation operation -- the event is something
#: happening to flights, an airport or an airspace, not something happening in
#: a place that flights also serve.
#:
#: Every slug here belongs to the v2 taxonomy (app/taxonomy.py
#: RISK_CATEGORIES), which /risks does not serve: production still classifies
#: with the v1 nine-type natural/conflict set, and none of those nine is an
#: aviation operation. So on today's feed this set never matches and
#: `aviation_link` is decided entirely by whether an airport was named -- which
#: is the honest answer for a wildfire or a coup. It is written out anyway
#: because the alternative is a rule that silently means "airport named" while
#: claiming to mean "aviation-operational", and because /risks moving to v2 is
#: a change of one query, not of this rule.
AVIATION_OPERATIONAL_TYPES = frozenset(
    {"accident_incident", "disruption", "airport_disruption", "atc_disruption", "restriction"}
)


# ---------------------------------------------------------------------------
# CONFIDENCE GATING
#
# `confidence_score` on this page comes from app/pipeline/verify.py:
#
#     0.4 + 0.15 * (corroborating_sources - 1) + 0.3 * avg_source_trust
#
# It is not a 0-100 "how sure are we" scale, and the thresholds below were
# measured rather than chosen, because guessing at them produces numbers that
# either hide the whole radar or hide nothing.
#
# MEASUREMENT (local Postgres, 484 enriched articles, 18 of them risk-classified,
# 18 distinct sources; taken while writing this):
#
#   * corroborating_source_count == 1 on 484/484 rows. Nothing in this corpus
#     ever formed a duplicate group, so every score is the single-source case
#     and the formula collapses to `0.4 + 0.3 * trust_weight` -- a relabelling
#     of the source's trust weight and nothing more.
#   * Whole feed:   0.565 (3.3%) | 0.58 (40.3%) | 0.595 (9.3%) | 0.61 (33.5%)
#                 | 0.655 (2.1%) | 0.67 (4.3%), plus 7.2% of curated/seeded rows
#                   carrying a hand-set 0.8/0.9 that the formula never produced.
#   * Risk subset:  0.58 x4 (22%) | 0.595 x2 (11%) | 0.61 x12 (67%).
#                   p10 = 0.58, median = 0.61.
#   * The seeded source catalogue spans trust 0.45-0.95, so the theoretical
#     single-source range is 0.535-0.685; the live corpus exercises 0.565-0.67
#     of it.
#
# WHY A 70/85 SCALE DOES NOT TRANSFER. On this formula one article can never
# reach 0.70: that needs trust > 1.0. A 0.85 gate would empty the page, and a
# 0.70 gate would keep only clusters with a second independent source (the
# corroboration bonus alone puts a two-source cluster at >= 0.715). The two
# thresholds below sit where this distribution actually has structure.
#
# CONFIDENCE_FLOOR = 0.58 -- the 10th percentile of the enriched corpus.
#   Strictly below it lies exactly the trust < 0.60 band, i.e. the weakest
#   aggregators: 3.3% of the feed and 0 of today's 18 risk rows. Cutting AT
#   0.58 instead of below it would remove 40% of the feed in a single step,
#   because the distribution is discrete and 0.58 is its mode -- which is why
#   the floor is `< FLOOR` and not `<= FLOOR`.
#
# CONFIDENCE_LOW_BAND = 0.61 -- the median of the risk subset, and the score of
#   a 0.70-trust source, which is this catalogue's default trade-press weight.
#   Below it: a story told once, by an outlet we weight below the default.
#   6 of today's 18 risk rows (33%). Those are de-emphasised, not hidden.
#
# MULTI-SOURCE EXEMPTION. Neither threshold applies to a cluster more than one
# outlet reported. Corroboration is the evidence this score is mostly made of,
# and a weak outlet that a second newsroom independently backed is a stronger
# signal than the arithmetic -- built from the primary's row alone -- can see.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# THE 0.60 GATE, AND WHAT IT ACTUALLY SELECTS FOR
#
# Re-measured on the local corpus (18 risk-classified articles, 18 clusters --
# nothing in it co-clusters) while writing this:
#
#   window     clusters   conf > 0.60   has official/regulator source
#   14 days       18          12                     0
#    5 days       10           6                     0
#
#   confidence values present: 0.58 (x4), 0.595 (x2), 0.61 (x12)
#   corroborating_source_count: 1 on every row
#
# ONE PREMISE HAD TO BE CORRECTED. A 0.60 gate is often described as meaning
# "two independent sources", on the reasoning that a single-source story cannot
# reach it. That is NOT true of this formula. pipeline/verify.py computes
#
#     0.4 + 0.15 * (sources - 1) + 0.3 * avg_trust
#
# so a single source with trust_weight 0.70 -- the catalogue's default
# trade-press weight -- scores exactly 0.61 and clears a 0.60 gate on its own.
# The measurement above is that fact: 12 of 18 clusters pass, and every one of
# them is single-source. The single-source range on the seeded catalogue is
# 0.535-0.685 (trust 0.45-0.95), not a 0.54 ceiling.
#
# So this gate does not select for corroboration. It selects for
# `trust_weight > 0.667` -- i.e. it removes the outlets we weight below the
# default trade press. That is a defensible rule and it is the one being
# applied, but it has to be named accurately, because a threshold believed to
# mean "two newsrooms agreed" would be read as far stronger evidence than it is.
#
# THE OFFICIAL-SOURCE EXEMPTION is implemented even though the measurement says
# it changes nothing today: 0 of the 18 risk rows come from an official or
# regulator source (every one is trade tier, trust 0.6-0.7). It is here because
# the rule is right independently of the sample -- a NOTAM or a civil-aviation
# authority notice is verified BY BEING the authority's own statement, and a
# gate that hid one for want of a second outlet would be hiding the primary
# source in favour of the people quoting it. It costs nothing now and is
# correct the first time such a source appears.
# ---------------------------------------------------------------------------

#: At or below this, a single-source cluster from an ordinary outlet is not
#: published. Strictly greater than, so 0.60 exactly does not pass -- the
#: distribution is discrete and the values that matter sit at 0.595 and 0.61.
CONFIDENCE_VERIFIED_MIN = 0.60

#: Tiers whose own statement IS the verification. See the exemption note above.
VERIFIED_SOURCE_TIERS = frozenset({"official", "regulator"})

#: Below this (and above the gate), a cluster published on an exemption rather
#: than on its own score is shown as `visibility="low"`: same facts, quieter
#: presentation.
CONFIDENCE_LOW_BAND = 0.61

#: The formula's own arithmetic minimum, imported from the module that owns the
#: formula rather than re-typed here. A score BELOW it cannot have come out of
#: pipeline/verify.py at all, so it means the confidence pass never ran for that
#: row -- ArticleEnrichment.confidence_score is a NOT NULL column defaulting to
#: 0.0, which is exactly what an unscored row carries. Those are published
#: normally: the gate acts on evidence of weakness, and a number nobody computed
#: is not evidence. Treating "we did not measure this" as "we measured it and it
#: was bad" would be inventing the very reading the gate claims to be applying.
CONFIDENCE_UNSCORED_BELOW = CONFIDENCE_FORMULA_MIN


def visibility_for(
    confidence: float | None,
    distinct_sources: int,
    corroborating_sources: int | None,
    *,
    has_verified_source: bool = False,
) -> str:
    """"normal" | "low" | "hidden" for one cluster.

    `distinct_sources` is how many different outlets clustered into this
    signal; `corroborating_sources` is the primary's own duplicate-group size.
    Either one being >1 means a second newsroom told this story, which is the
    strongest exemption -- they are two different mechanisms (event clustering
    vs. near-duplicate detection) for detecting the same fact.

    `has_verified_source` is true when any member came from an official or
    regulator tier. That publishes the cluster, but quietly: an authority's
    own notice is verified, and a trade-press paraphrase of one scoring 0.58
    is still a single weak telling. The exemption says "do not hide this", not
    "treat it as well-sourced".
    """
    if distinct_sources > 1 or (corroborating_sources or 1) > 1:
        return "normal"
    if confidence is None or confidence < CONFIDENCE_UNSCORED_BELOW:
        return "normal"
    if confidence > CONFIDENCE_VERIFIED_MIN:
        return "normal" if confidence >= CONFIDENCE_LOW_BAND else "low"
    return "low" if has_verified_source else "hidden"


def aviation_gate(score: float | None) -> bool:
    """Whether a cluster clears the aviation-relevance gate (spec §16).

    GRADUATED ON PURPOSE, and the graduation is the whole point:

        score >= AVIATION_RELEVANCE_GATE  publish -- measured and relevant
        score <  AVIATION_RELEVANCE_GATE  drop    -- measured and irrelevant
        score is None                     publish -- NOBODY MEASURED IT

    The third line is what stops this from emptying the page in one deploy.
    Model coverage of this feed is partial and the deterministic floor only
    fires on an explicit operational phrase, so `None` is the majority state
    today, and reading it as a low score would delete nearly every signal on
    the strength of a keyword list's silence. `aviation_relevance_source`
    records which rows are which, so the gate can be tightened later against a
    measured denominator rather than a guess -- see the enrichment column.
    """
    return score is None or score >= AVIATION_RELEVANCE_GATE


def is_mappable(location_confidence: float | None) -> bool:
    """Whether a placement earned a pin (spec §13).

    Graduated the same way aviation_gate() is, and for the same reason:

        confidence >= LOCATION_MAP_PIN_MIN  pin -- measured and trustworthy
        confidence <  LOCATION_MAP_PIN_MIN  no  -- measured and weak
        confidence is None                  pin -- NOBODY MEASURED IT

    The third line is the transition. Every row written before this revision
    carries NULL here, and reading NULL as "weak" would blank the map on the
    deploy -- a page that looks broken, in the name of a check that has not run
    yet. Fresh enrichment always writes the column, so new rows are gated
    immediately, and `python -m app.cli backfill-risks` fills the archive; the
    gate tightens as the evidence arrives rather than ahead of it.

    A row with no country at all is separately unplaced regardless: there is no
    centroid for "unknown", which is the same answer arrived at honestly.
    """
    return location_confidence is None or location_confidence >= LOCATION_MAP_PIN_MIN


def _best_aviation_reading(members: list):
    """The cluster's strongest aviation-relevance reading -- the whole reading,
    not just its number -- or None when no member carries one.

    The best-scoring MEMBER rather than max() over the scores alone, so the
    score, the quoted evidence, the ACTUAL/POTENTIAL status and the provenance
    all come from the same article. Taking the score from one member and the
    evidence from another would produce a card whose quote does not support
    its own number.

    Best across the cluster rather than the primary's own: one outlet writing
    "the airspace was closed" is evidence about the EVENT, and the primary is
    chosen for source tier and earliness, not for how completely it reported
    the operational detail. None survives only when nothing in the cluster was
    scored at all -- see aviation_gate() on why that publishes.
    """
    scored = [
        m.enrichment
        for m in members
        if m.enrichment is not None and m.enrichment.aviation_relevance_score is not None
    ]
    if not scored:
        return None
    return max(scored, key=lambda e: e.aviation_relevance_score)


#: Strongest-wins order when the same place carries different roles in
#: different members of a cluster. Lower is stronger.
_ROLE_RANK = {"event": 0, "source": 1, "unverified": 2}


def _mentions_across(members: list) -> list[dict]:
    """Every place the cluster's articles named, de-duplicated by name+kind.

    An EVENT role anywhere wins over a SOURCE one, which in turn wins over
    UNVERIFIED: one article's dateline does not disqualify a place another
    article puts the event in, and a tested role beats an untested one. Same
    resolution rule heuristic._place_role uses within a single article, applied
    one level up.
    """
    merged: dict[tuple[str, str], dict] = {}
    for member in members:
        enrichment = member.enrichment
        for entry in (enrichment.mentioned_locations if enrichment else None) or []:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            key = (str(entry["name"]).lower(), str(entry.get("kind") or "unknown"))
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(entry)
            elif _ROLE_RANK.get(str(entry.get("role")), 9) < _ROLE_RANK.get(
                str(existing.get("role")), 9
            ):
                existing["role"] = entry["role"]
    return sorted(merged.values(), key=lambda e: (e.get("kind") or "", str(e["name"])))


def aviation_link_for(risk_type: str, risk_family: str, airport_count: int) -> str:
    """"direct" or "indirect" -- how close this signal sits to aviation.

    A LINK STRENGTH, not an impact score. It says why this event is on an
    aviation desk's radar at all: either the event itself is an aviation
    operation, or the coverage names an airport. It does not say the airport is
    affected, how badly, or whether any flight moved -- none of which this
    pipeline can know (there is no schedule, OTP or route feed behind it).

    Two inputs rather than one so the rule keeps meaning what it says once
    /risks reads the v2 taxonomy; see AVIATION_OPERATIONAL_TYPES.
    """
    if risk_type in AVIATION_OPERATIONAL_TYPES or risk_family == "operational":
        return "direct"
    return "direct" if airport_count > 0 else "indirect"


@router.get("", response_model=RiskRadarOut)
async def list_risks(
    days: int = Query(DEFAULT_WINDOW_DAYS, ge=1, le=90),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> RiskRadarOut:
    """Every classified risk event in the window, grouped by country and sorted
    by weighted severity score."""
    # AGGREGATES, not ARTICLES: this is a grouped rollup like /insights and
    # /hubs, not a raw article list, and it changes only when the enrichment
    # cron reclassifies something.
    public_cache(response, AGGREGATES)
    return await aggregate_risks(db, days=days)


async def aggregate_risks(db: AsyncSession, days: int = DEFAULT_WINDOW_DAYS) -> RiskRadarOut:
    """The rollup itself, split out from the endpoint so a second caller can
    reuse it rather than re-deriving severity counts from a cheaper query.

    Kokpit's "Risk Radarı" signal tile does exactly that (see
    app/services/cockpit_signals_service.py). The tile states a high-severity
    count and names the worst country, and the page it links to states the same
    two things -- a second, simpler `SELECT count(*) ... WHERE risk_severity =
    'high'` would have been faster and would have disagreed, because it would
    count three outlets covering one eruption as three signals where this
    function clusters them into one. Same reasoning as the module docstring's:
    compute it once, so every surface agrees.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    base_filters = (
        Article.is_duplicate.is_(False),
        ArticleEnrichment.risk_type.is_not(None),
        Article.published_at.is_not(None),
        Article.published_at >= since,
    )

    # THE CURRENCY GATE (spec §15), and why it is `IS NOT FALSE` rather than
    # `IS TRUE`.
    #
    # `is_current_event` has three states and the third one is the reason this
    # is written the awkward way round: NULL means no classifier ever answered
    # the question for that row. Coverage is partial -- the LLM answers it only
    # for articles it classifies live, and the keyword fallback can only ever
    # say "this headline reads as retrospective", never "this one is current".
    # So `IS TRUE` would not filter the archive, it would delete it.
    #
    # What is removed is exactly the rows something looked at and called stale:
    # an anniversary piece, a retrospective, a court case about an old
    # disaster. That is a small set today and it will grow as coverage does,
    # which is the intended shape -- the gate tightens as the evidence arrives,
    # rather than acting on evidence that does not exist yet.
    current_filter = ArticleEnrichment.is_current_event.is_not(False)

    result = await db.execute(
        select(Article)
        .options(
            selectinload(Article.source),
            selectinload(Article.enrichment),
            selectinload(Article.entity_links).selectinload(ArticleEntity.entity),
        )
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .where(*base_filters, current_filter)
        .order_by(Article.published_at.desc())
    )
    articles = [
        a
        for a in result.scalars().unique().all()
        if a.enrichment is not None and a.enrichment.risk_type is not None
    ]

    # What the currency gate removed, counted rather than inferred. A page that
    # drops rows silently is a page whose numbers nobody can reconcile; the
    # count is one aggregate against an index-covered predicate, not a second
    # pass over the articles.
    not_current = (
        await db.execute(
            select(func.count())
            .select_from(Article)
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            .where(*base_filters, ArticleEnrichment.is_current_event.is_(False))
        )
    ).scalar_one()

    grouped: dict[str, list[RiskItemOut]] = {}
    type_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    suppressed = 0
    suppressed_aviation = 0
    unplaced = 0

    # Three outlets covering one eruption used to be three cards, independently
    # classified, and they could disagree on severity and even on which
    # country it happened in (a passing "ash also reached Malta" aside once
    # outranked a correctly-resolved Catania/Italy in a sibling article). One
    # cluster, one card: reuse the same entity-overlap + distinctive-token
    # clustering v2 uses for news_events (app/pipeline/clustering.py) rather
    # than inventing a second, Risk-Radarı-specific notion of "same event".
    by_id = {a.id: a for a in articles}
    candidates = [
        EventCandidate(
            article_id=a.id,
            title=a.title,
            entities=entity_codes(a),
            tier=tier_for_source(a.source),
            published_at=a.published_at.isoformat() if a.published_at else None,
        )
        for a in articles
    ]

    for group in cluster(candidates):
        members = [by_id[c.article_id] for c in group]
        primary = by_id[pick_primary(group).article_id]
        primary_enrichment = primary.enrichment

        # Severity: the most severe member wins. A vaguer report that never
        # mentions the closure's scale should not water down one that does --
        # under-stating a live hazard is the wrong failure mode here.
        severity = max(
            (m.enrichment.risk_severity or "low" for m in members),
            key=lambda s: RISK_SEVERITY_WEIGHT.get(s, 1),
        )

        # Country/city: prefer whichever member actually resolved a city --
        # that is real evidence (a named airport or landmark), not an
        # incidental mention -- over one that only ever produced a bare
        # country, and over the primary's own placement if a better one
        # exists elsewhere in the cluster. Earliest member first among ties,
        # matching pick_primary's own "first telling" preference.
        by_published = sorted(members, key=lambda m: m.published_at or now)
        city_bearer = next((m for m in by_published if m.enrichment.risk_city), None)
        country_bearer = city_bearer or next(
            (m for m in by_published if m.enrichment.risk_country), None
        )
        risk_country = country_bearer.enrichment.risk_country if country_bearer else None
        risk_city = city_bearer.enrichment.risk_city if city_bearer else None
        # The winning member's own location score travels with its placement --
        # taking the max across the cluster would let a well-placed member
        # launder a badly-placed one's country onto the map.
        location_confidence = (
            country_bearer.enrichment.location_confidence if country_bearer else None
        )
        mentioned_locations = _mentions_across(by_published)

        # THE MAP GATE (spec §13). Below the threshold the placement is not
        # merely shown quietly -- `country` and `city` are BLANKED and the
        # signal is filed under UNKNOWN_COUNTRY.
        #
        # Blanking rather than flagging, because the map reads `item.country`
        # to find a centroid (frontend risk-map.tsx) and a country left in
        # place would still be drawn as a dot. A dot on a guess is
        # indistinguishable from a dot on a fact, and the reader has no way to
        # tell them apart -- which makes a weak placement worse than none.
        #
        # Nothing is lost: `location_confidence` says why, and
        # `mentioned_locations` carries every place the article named with the
        # role it played, so "konum belirsiz" is answerable rather than blank.
        placed = is_mappable(location_confidence)
        if not placed and risk_country is not None:
            unplaced += 1
            risk_country = None
            risk_city = None
        country = risk_country or UNKNOWN_COUNTRY

        # Risk type: the most-agreed-on classification; primary's own call
        # breaks a tie, since it is the highest-tier/earliest telling.
        type_votes: dict[str, int] = {}
        for m in members:
            type_votes[m.enrichment.risk_type] = type_votes.get(m.enrichment.risk_type, 0) + 1
        risk_type = max(
            type_votes,
            key=lambda t: (type_votes[t], t == primary_enrichment.risk_type),
        )
        family = (
            primary_enrichment.risk_family
            if primary_enrichment.risk_type == risk_type
            else None
        ) or RISK_TYPE_FAMILY.get(risk_type)
        if family is None:
            continue

        # THE AVIATION-RELEVANCE GATE (spec §16), applied before the
        # confidence one because it is the cheaper rejection and the more
        # decisive: a well-corroborated earthquake with no bearing on flying
        # does not belong on an aviation desk's radar however many outlets
        # reported it. Best score across the cluster, since one member
        # spelling out the operational effect is evidence for the event, not
        # just for that article.
        aviation = _best_aviation_reading(members)
        aviation_score = aviation.aviation_relevance_score if aviation else None
        if not aviation_gate(aviation_score):
            suppressed_aviation += 1
            continue

        # The publish gate. Distinct SOURCES, not member count: one outlet
        # republishing its own story twice is one telling, and counting it as
        # corroboration would let a weak source exempt itself.
        distinct_sources = len({m.source_id for m in members})
        has_verified_source = any(
            tier_for_source(m.source) in VERIFIED_SOURCE_TIERS for m in members
        )
        visibility = visibility_for(
            primary_enrichment.confidence_score,
            distinct_sources,
            primary_enrichment.corroborating_source_count,
            has_verified_source=has_verified_source,
        )
        if visibility == "hidden":
            suppressed += 1
            continue

        # The publication chronology. `by_published` is already the cluster in
        # publication order, which is the only timeline this data has: these are
        # the moments outlets WROTE about the event, never the moments the event
        # itself did anything. The drawer that renders them says so out loud.
        member_rows = [
            RiskMemberOut(
                title=m.title,
                url=m.url,
                source_name=m.source.name if m.source else "",
                source_tier=tier_for_source(m.source),
                published_at=m.published_at,
            )
            for m in by_published
        ]
        published_times = [m.published_at for m in by_published if m.published_at]
        first_reported = published_times[0] if published_times else None
        last_reported = published_times[-1] if published_times else None
        # "Still being written about": the story is older than a day and
        # somebody added to it today. Two members are not required -- a single
        # article cannot satisfy both halves, so this is false for the common
        # one-article cluster by arithmetic rather than by a special case.
        is_updated = bool(
            first_reported
            and last_reported
            and (now - first_reported) > FRESH_WINDOW
            and (now - last_reported) <= FRESH_WINDOW
        )

        # Airports NAMED across the cluster -- see AirportRefOut on why the
        # label is "anılan" and never "etkilenen". Distinct by code and sorted
        # by it, so the same event lists the same airports in the same order on
        # every request rather than in whatever order the join came back.
        airports_by_code: dict[str, str] = {}
        for m in by_published:
            for link in m.entity_links:
                entity = link.entity
                if entity is None or entity.entity_type != "airport" or not entity.code:
                    continue
                airports_by_code.setdefault(entity.code.upper(), entity.name)
        airports = [
            AirportRefOut(code=code, name=name)
            for code, name in sorted(airports_by_code.items())[:AIRPORT_CAP]
        ]

        published = primary.published_at
        # The headline, both ways round. `headline` stays "the best text we
        # have" so no caller has to re-derive the fallback chain, but the page
        # also has to be able to say WHICH it is showing: an untranslated row
        # gets the app's quiet "otomatik çeviri yok" tag instead of passing as
        # Turkish, and a translated one carries the source-language original so
        # a reader can check the wording against it. `translated_at is not
        # None` is the same test schemas/article.py's is_translated uses --
        # never implied, always earned.
        source_headline = primary_enrichment.headline or primary.title
        translated_headline = (
            primary_enrichment.headline_tr
            if primary_enrichment.translated_at is not None and primary_enrichment.headline_tr
            else None
        )
        item = RiskItemOut(
            id=str(primary.id),
            headline=translated_headline or source_headline,
            headline_original=(
                source_headline
                if translated_headline and source_headline != translated_headline
                else None
            ),
            is_translated=translated_headline is not None,
            url=primary.url,
            source_name=primary.source.name if primary.source else "",
            published_at=published,
            risk_type=risk_type,
            risk_family=family,
            risk_type_label_tr=RISK_TYPE_LABELS_TR.get(risk_type, risk_type),
            severity=severity,
            country=risk_country,
            city=risk_city,
            # The RESOLVED COUNTRY's region first, the article's own detected
            # region only as a fallback -- AND ONLY WHEN THE PLACEMENT WAS
            # PUBLISHED AT ALL.
            #
            # The ordering is the older half of this rule: the other way round
            # put "Ülke: United States" next to "Bölge: Orta Doğu" in the
            # detail panel, because ArticleEnrichment.region is derived from
            # every country the article mentions -- a Pentagon story about
            # Middle East operations is filed under middle-east while its
            # risk_country is the US. Both facts are true about the ARTICLE;
            # only one of them is true about the PLACE this signal is pinned
            # to, and this field is the place.
            #
            # `placed` is the newer half, and it closes a hole the blanking
            # above opened. When the map gate blanks a weak placement,
            # `country` becomes UNKNOWN_COUNTRY, COUNTRY_TO_REGION has no entry
            # for it, and the fallback fired -- so the pipeline said "konum
            # doğrulanamadı" while the card still wore a "Orta Doğu" chip. A
            # region IS a placement claim, only a coarser one, and publishing
            # the coarse version of an answer we just refused to give is the
            # same failure blanking exists to prevent. Unplaced signals now
            # carry no region at all, and `mentioned_locations` remains the
            # audit trail for what the article actually named.
            region=COUNTRY_TO_REGION.get(country.lower())
            or (country_bearer.enrichment.region if placed and country_bearer else None),
            is_fresh=bool(published and (now - published) <= FRESH_WINDOW),
            source_count=len(members),
            # The primary's own summary: it is the telling that was picked as
            # most reliable, so it is the one whose words stand for the event.
            summary_tr=(primary_enrichment.summary_tr or primary_enrichment.summary) or None,
            # Null when nobody scored this row (`measured_confidence`), never
            # 0.0: the card's ConfidencePill draws a score it is given, so the
            # raw NOT NULL column turned an unmeasured article into a "Düşük
            # 0.00" verdict the system never reached. The GATE above still
            # reads the raw value -- visibility_for treats unscored as
            # publishable, which is the same principle in the other direction.
            confidence_score=measured_confidence(primary_enrichment.confidence_score),
            corroborating_source_count=primary_enrichment.corroborating_source_count,
            first_reported_at=first_reported,
            last_reported_at=last_reported,
            is_updated=is_updated,
            airports=airports,
            aviation_link=aviation_link_for(risk_type, family, len(airports_by_code)),
            members=member_rows[:MEMBER_CAP],
            members_truncated=len(member_rows) > MEMBER_CAP,
            visibility=visibility,
            location_confidence=location_confidence,
            is_mappable=placed,
            mentioned_locations=mentioned_locations,
            aviation_relevance_score=aviation_score,
            # All four from the SAME member -- see _best_aviation_reading. A
            # score read off one article and a quote read off another is a card
            # whose evidence does not support its own number.
            aviation_relevance_source=(
                aviation.aviation_relevance_source
                if aviation
                else primary_enrichment.aviation_relevance_source
            ),
            aviation_impact_evidence=(
                aviation.aviation_impact_evidence if aviation else None
            ),
            aviation_impact_status=(aviation.aviation_impact_status if aviation else None),
        )
        grouped.setdefault(country, []).append(item)
        type_counts[risk_type] = type_counts.get(risk_type, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1

    countries: list[RiskCountryOut] = []
    for country, items in grouped.items():
        counts = {"high": 0, "medium": 0, "low": 0}
        for item in items:
            if item.severity in counts:
                counts[item.severity] += 1
        score = sum(RISK_SEVERITY_WEIGHT.get(i.severity, 1) for i in items)
        countries.append(
            RiskCountryOut(
                country=country,
                region=COUNTRY_TO_REGION.get(country.lower()),
                count=len(items),
                score=score,
                severity_counts=SeverityCountsOut(**counts),
                # Within a country: confident signals first, then worst first,
                # then newest. A reader scanning a country section should meet
                # its worst well-sourced event first, and the low-confidence
                # tail last -- which is also where the page collapses it into
                # its own "Düşük güvenli sinyaller" block. Severity does not
                # promote a weak signal past a solid one: how bad the story
                # would be if true is not evidence that it is.
                items=sorted(
                    items,
                    key=lambda i: (
                        i.visibility == "low",
                        -RISK_SEVERITY_WEIGHT.get(i.severity, 1),
                        -(i.published_at.timestamp() if i.published_at else 0),
                    ),
                ),
            )
        )

    # Score desc, then count desc, then name -- a stable order the ranking and
    # the list can both rely on. The unplaced bucket sorts last regardless of
    # its score: it is a data-quality residue, not the worst-hit country.
    countries.sort(
        key=lambda c: (c.country == UNKNOWN_COUNTRY, -c.score, -c.count, c.country)
    )

    return RiskRadarOut(
        days=days,
        # Signals shown, not articles scanned: with clustering, the same
        # eruption reported by three outlets is one signal, not three, and
        # the page's own "X / Y sinyal" counter needs Y to be a number X can
        # actually reach.
        total=sum(len(items) for items in grouped.values()),
        suppressed_low_confidence=suppressed,
        suppressed_aviation_irrelevant=suppressed_aviation,
        suppressed_not_current=not_current,
        unplaced_low_confidence=unplaced,
        countries=countries,
        type_counts=type_counts,
        family_counts=family_counts,
        # `now`, captured at the top of this function -- the moment the window
        # was cut, not the moment the response is serialized. The page stamps
        # this as its freshness, and it must mean "this is the state of the
        # radar as of", not "a clock ran while I rendered".
        generated_at=now,
    )


@router.get("/trend", response_model=RiskTrendOut)
async def risk_trend(
    days: int = Query(30, ge=7, le=90),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> RiskTrendOut:
    """Daily risk-classified PUBLICATION counts, split by family and severity.

    What this counts, said plainly: how many risk-classified articles were
    published each day. It is not how many events happened -- this pipeline has
    no event-occurrence time anywhere (see the module docstring's data notes),
    only publication timestamps, and a single earthquake covered by six outlets
    over three days is six points spread across three days here.

    So the honest reading of a spike is "the feed wrote more about risk that
    day", which is genuinely useful (it is what a desk's attention actually
    tracked) and is emphatically not "more disasters happened". The response
    carries that sentence in `note` so no consumer has to remember it.

    Unclustered on purpose, unlike GET /risks: clustering is a whole-window
    operation and re-running it per day would produce daily totals that do not
    sum to the window's own total. A shape over time wants a consistent unit,
    and the article is the only unit that is consistent day by day.
    """
    public_cache(response, AGGREGATES)

    # Whole UTC days, back-counted from today -- so "30 gün" is 30 day buckets
    # including today, not a 30x24h window that cuts today's bucket in half.
    since = datetime.combine(
        datetime.now(timezone.utc).date() - timedelta(days=days - 1),
        time.min,
        tzinfo=timezone.utc,
    )
    # coalesce(published_at, fetched_at) is what ix_articles_day_expr indexes
    # (partial, is_duplicate = false), so the range predicate below can use it.
    # The published_at IS NOT NULL filter keeps this counting exactly the
    # population GET /risks draws from -- and under that filter the coalesce is
    # published_at, so bucketing on it changes no number while keeping the
    # index applicable.
    day_expr = func.coalesce(Article.published_at, Article.fetched_at)
    # timezone('UTC', ...) first: date_trunc on a bare timestamptz truncates in
    # the SESSION timezone, which shifts every late-evening UTC article into the
    # wrong day on a non-UTC deployment. Same guard as the archive's
    # count_by_day (app/repositories/article_repository.py).
    day_col = func.date_trunc("day", func.timezone("UTC", day_expr))

    # Grouped by risk_type, not by risk_family, and folded to the family here:
    # risk_family is a denormalisation of risk_type and a row written before it
    # existed (or by the CLI backfill) can carry a type with a null family.
    # Grouping on the nullable column would put those rows in a "null" bucket
    # the chart has no series for; folding from the type means the trend's
    # totals always equal the feed's.
    result = await db.execute(
        select(
            day_col.label("day"),
            ArticleEnrichment.risk_type,
            ArticleEnrichment.risk_severity,
            func.count().label("count"),
        )
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .where(
            Article.is_duplicate.is_(False),
            ArticleEnrichment.risk_type.is_not(None),
            Article.published_at.is_not(None),
            # The same currency gate list_risks applies, for the same reason
            # the published_at filter above is here: this series has to count
            # the population the page draws from. A retrospective piece that
            # the list refuses would otherwise still raise the trend line, and
            # a reader comparing the two would find a spike with no signals
            # behind it.
            ArticleEnrichment.is_current_event.is_not(False),
            day_expr >= since,
        )
        .group_by(day_col, ArticleEnrichment.risk_type, ArticleEnrichment.risk_severity)
        .order_by(day_col)
    )

    folded: dict[tuple[str, str, str], int] = {}
    for day, risk_type, severity, count in result.all():
        family = RISK_TYPE_FAMILY.get(risk_type)
        if family is None:
            # An off-taxonomy slug that predates is_valid_risk_type's gate. It
            # has no family, no label and no chip; counting it under a real
            # family would be worse than leaving it out of the shape.
            continue
        key = (day.date().isoformat(), family, severity or "low")
        folded[key] = folded.get(key, 0) + count

    points = [
        RiskTrendPointOut(day=day, family=family, severity=severity, count=count)
        for (day, family, severity), count in sorted(folded.items())
    ]
    # Days with nothing classified are simply absent: a zero-filled series is
    # the chart's job (it knows its own axis), and inventing rows here would
    # make an empty window look like 30 measured zeroes.
    return RiskTrendOut(days=days, points=points)


# ===========================================================================
# THE VERIFICATION SURFACE (spec §23-24)
#
# Everything above answers "what is on the radar". The two endpoints below
# answer the two questions the radar itself cannot, and which an analyst has to
# be able to answer before trusting any of it:
#
#   * "Why is this news NOT showing?"  -> GET /risks/rejected
#   * "Is what I see six out of six, or six out of forty?" -> GET /risks/quality
#
# Both are strictly read-only and compute their answer from the same single
# pass (app/services/risk_quality.py). Nothing is written down: the storage
# decision and its cost are argued in that module's docstring.
#
# The import is deferred into the handlers because risk_quality imports the
# gates from THIS module -- the dependency runs one way at module level and the
# other way at call time, which is the smaller of the two evils compared with
# moving four constants and two predicates into a third module nobody would
# think to look in.
# ===========================================================================


class RiskFunnelStageOut(BaseModel):
    """One line of the funnel."""

    key: str
    label_tr: str
    passed: int
    dropped: int
    #: The rejection slug `dropped` rows carry, or None when the drop is not a
    #: rejection. `GET /risks/rejected?reason=` takes exactly these values.
    #: Only the FIRST when a stage carries several -- the location gate splits
    #: into unresolved and conflict -- so a filter must be built from
    #: `reason_counts`, never from this.
    reason: str | None = None
    #: reason -> how many of `dropped` carry it. Sums to `dropped`. Empty for a
    #: stage whose drop is not a rejection.
    reason_counts: dict[str, int] = {}
    #: "rejected" | "merged" | None. A merged cluster is still on the radar and
    #: a rejected article is not; the screen must never draw them alike.
    drop_kind: str | None = None
    note_tr: str | None = None


class RiskRejectionOut(BaseModel):
    """One risk candidate the page does not show, with the values the rule
    actually read. A label without its inputs asks the reader to trust the
    label, which is the failure this whole surface exists to fix."""

    article_id: str
    title: str
    url: str
    source_name: str
    source_tier: str
    published_at: datetime | None
    reason: str
    reason_label_tr: str
    #: Every other gate this row would also have failed. Empty is the good
    #: case: fix the one rule and the row appears.
    also_failed: list[str] = []

    #: Every row-level gate's verdict, pass AND fail, keyed by
    #: risk_quality.GATE_KEYS: currency | confidence | aviation | location.
    #:
    #: `reason` and `also_failed` list only what went wrong, and the table
    #: built on them could not tell "rejected for currency, clean otherwise"
    #: from "rejected for currency, and three gates were never evaluated" --
    #: an absent verdict and a passing one rendered the same. The full map is
    #: what lets the screen show the DECISION each rule actually reached.
    #:
    #: Populated for every rejection, including the two that are not gate
    #: verdicts (`outside_window`, `duplicate`): those rows still have an
    #: enrichment for the four rules to read, and an analyst widening the
    #: window wants to know what the row would hit next.
    gates: dict[str, bool] = {}
    #: Whether the confidence gate published this row, called out of `gates`
    #: because it is the only gate with an exemption ladder rather than a
    #: threshold.
    confidence_gate_passed: bool = True
    #: Which rung of that ladder decided it: "corroborated" | "unscored" |
    #: "scored" | "official" | "below_gate". The one the table has to be able
    #: to show is "unscored" -- a row published because nobody measured it is
    #: not a row that passed anything, and `confidence_score` being None is
    #: only half of that sentence.
    confidence_gate_reason: str = "unscored"

    risk_type: str | None = None
    risk_severity: str | None = None
    confidence_score: float | None = None
    corroborating_source_count: int | None = None
    aviation_relevance_score: float | None = None
    aviation_relevance_source: str | None = None
    location_confidence: float | None = None
    #: What the resolver decided the event's place was, BEFORE the map gate
    #: blanked it. GET /risks blanks a weak placement on purpose; this surface
    #: is the one place the rejected answer has to remain visible, or a wrong
    #: placement cannot be told from an absent one.
    detected_country: str | None = None
    detected_city: str | None = None
    mentioned_locations: list[dict] = []


class RiskQualityOut(BaseModel):
    days: int
    generated_at: datetime
    since: datetime
    stages: list[RiskFunnelStageOut]
    #: Rejections per reason, UNCAPPED -- so a truncated list can still say how
    #: much of the whole it is showing.
    rejected_counts: dict[str, int]
    reason_labels_tr: dict[str, str]
    #: How much of each gate's yield is carried by rows nobody measured. A gate
    #: passing everything unscored is a gate not yet doing anything, and the
    #: screen has to be able to say so rather than flatter itself.
    aviation_unscored: int
    location_unscored: int
    confidence_unscored: int
    aviation_by_source: dict[str, int]


def _rejection_out(row) -> "RiskRejectionOut":
    from app.services.risk_quality import REJECTION_REASON_LABELS_TR

    return RiskRejectionOut(
        article_id=row.article_id,
        title=row.title,
        url=row.url,
        source_name=row.source_name,
        source_tier=row.source_tier,
        published_at=row.published_at,
        reason=row.reason,
        reason_label_tr=REJECTION_REASON_LABELS_TR.get(row.reason, row.reason),
        also_failed=list(row.also_failed),
        gates=dict(row.gates),
        confidence_gate_passed=row.confidence_gate_passed,
        confidence_gate_reason=row.confidence_gate_reason,
        risk_type=row.risk_type,
        risk_severity=row.risk_severity,
        confidence_score=row.confidence_score,
        corroborating_source_count=row.corroborating_source_count,
        aviation_relevance_score=row.aviation_relevance_score,
        aviation_relevance_source=row.aviation_relevance_source,
        location_confidence=row.location_confidence,
        detected_country=row.detected_country,
        detected_city=row.detected_city,
        mentioned_locations=row.mentioned_locations,
    )


@router.get("/quality", response_model=RiskQualityOut)
async def risk_quality(
    days: int = Query(DEFAULT_WINDOW_DAYS, ge=1, le=90),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> RiskQualityOut:
    """The funnel behind GET /risks: what was found, and what each gate removed.

    AGGREGATES, like every other rollup here: two counts and one pass over the
    window's risk candidates, changing only when the enrichment cron
    reclassifies something. Deliberately not `FRESH` -- this is a diagnostic
    view, and a reader comparing it against the radar wants the same 5-minute
    snapshot the radar is serving, not a newer one that disagrees with it.
    """
    public_cache(response, AGGREGATES)
    from app.services.risk_quality import REJECTION_REASON_LABELS_TR, risk_quality_report

    report = await risk_quality_report(db, days=days, with_rejections=False)
    return RiskQualityOut(
        days=days,
        generated_at=report.generated_at,
        since=report.since,
        stages=[
            RiskFunnelStageOut(
                key=stage.key,
                label_tr=stage.label_tr,
                passed=stage.passed,
                dropped=stage.dropped,
                reason=stage.reason,
                reason_counts=stage.reason_counts,
                drop_kind=stage.drop_kind,
                note_tr=stage.note_tr,
            )
            for stage in report.stages
        ],
        rejected_counts=report.rejected_counts,
        reason_labels_tr=dict(REJECTION_REASON_LABELS_TR),
        aviation_unscored=report.aviation_unscored,
        location_unscored=report.location_unscored,
        confidence_unscored=report.confidence_unscored,
        aviation_by_source=report.aviation_by_source,
    )


@router.get("/rejected", response_model=list[RiskRejectionOut])
async def risk_rejected(
    days: int = Query(DEFAULT_WINDOW_DAYS, ge=1, le=90),
    limit: int = Query(50, ge=1, le=200),
    reason: str | None = Query(None),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> list[RiskRejectionOut]:
    """The risk candidates the gates removed, newest first.

    `reason` takes any slug from RiskFunnelStageOut.reason. An unknown one
    returns an empty list rather than a 422: the filter is a UI affordance over
    a set that changes as gates are added, and a screen that 422s because it
    remembered last week's slug is worse than one that shows nothing and says
    so.
    """
    public_cache(response, AGGREGATES)
    from app.services.risk_quality import rejected_candidates

    rows = await rejected_candidates(db, days=days, reason=reason, limit=limit)
    return [_rejection_out(row) for row in rows]
