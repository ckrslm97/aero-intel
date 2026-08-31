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
  event's own point -- the classifier resolves a name, not a location.
* **No event-occurrence time.** Every timestamp here is a PUBLICATION time.
  `first_reported_at`/`last_reported_at` bracket the coverage, not the event.
* **No lifecycle.** Nothing in the feed says an event is active, contained or
  over. `is_fresh`/`is_updated` are statements about the coverage flow, and
  they are named that way so they cannot be mistaken for a status.
* **No operational impact.** There is no schedule, OTP or route data behind
  this product, so an airport named in an article is exactly that -- named.
  See AirportRefOut and aviation_link_for().
"""
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.cache_headers import AGGREGATES, public_cache
from app.core.db import get_db
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity
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
    #: How many clusters the confidence floor removed from this window. Served
    #: rather than swallowed: a page that quietly drops rows is a page whose
    #: counts nobody can reconcile, and "3 sinyal eşiğin altında kaldı" is a
    #: fact the reader is entitled to. See CONFIDENCE_FLOOR.
    suppressed_low_confidence: int = 0
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

#: Below this, a single-source cluster is not published at all.
CONFIDENCE_FLOOR = 0.58

#: Below this (and at or above the floor), a single-source cluster is published
#: as `visibility="low"`: same facts, quieter presentation.
CONFIDENCE_LOW_BAND = 0.61

#: The formula's own arithmetic minimum: 0.4 + 0.15 * 0 + 0.3 * 0. A score
#: BELOW this cannot have come out of pipeline/verify.py at all, so it means
#: the confidence pass never ran for that row -- ArticleEnrichment.confidence_
#: score is a NOT NULL column defaulting to 0.0, which is exactly what an
#: unscored row carries. Those are published normally: the gate acts on
#: evidence of weakness, and a number nobody computed is not evidence.
#: Treating "we did not measure this" as "we measured it and it was bad" would
#: be inventing the very reading the gate claims to be applying.
CONFIDENCE_UNSCORED_BELOW = 0.4


def visibility_for(
    confidence: float | None, distinct_sources: int, corroborating_sources: int | None
) -> str:
    """"normal" | "low" | "hidden" for one cluster.

    `distinct_sources` is how many different outlets clustered into this
    signal; `corroborating_sources` is the primary's own duplicate-group size.
    Either one being >1 means a second newsroom told this story, which is the
    exemption -- they are two different mechanisms (event clustering vs.
    near-duplicate detection) for detecting the same fact.
    """
    if distinct_sources > 1 or (corroborating_sources or 1) > 1:
        return "normal"
    if confidence is None or confidence < CONFIDENCE_UNSCORED_BELOW:
        return "normal"
    if confidence < CONFIDENCE_FLOOR:
        return "hidden"
    if confidence < CONFIDENCE_LOW_BAND:
        return "low"
    return "normal"


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
    days: int = Query(14, ge=1, le=90),
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


async def aggregate_risks(db: AsyncSession, days: int = 14) -> RiskRadarOut:
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

    result = await db.execute(
        select(Article)
        .options(
            selectinload(Article.source),
            selectinload(Article.enrichment),
            selectinload(Article.entity_links).selectinload(ArticleEntity.entity),
        )
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .where(
            Article.is_duplicate.is_(False),
            ArticleEnrichment.risk_type.is_not(None),
            Article.published_at.is_not(None),
            Article.published_at >= since,
        )
        .order_by(Article.published_at.desc())
    )
    articles = [
        a
        for a in result.scalars().unique().all()
        if a.enrichment is not None and a.enrichment.risk_type is not None
    ]

    grouped: dict[str, list[RiskItemOut]] = {}
    type_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    suppressed = 0

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

        # The publish gate. Distinct SOURCES, not member count: one outlet
        # republishing its own story twice is one telling, and counting it as
        # corroboration would let a weak source exempt itself.
        distinct_sources = len({m.source_id for m in members})
        visibility = visibility_for(
            primary_enrichment.confidence_score,
            distinct_sources,
            primary_enrichment.corroborating_source_count,
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
            # region only as a fallback. The other way round put "Ülke: United
            # States" next to "Bölge: Orta Doğu" in the detail panel, because
            # ArticleEnrichment.region is derived from every country the
            # article mentions -- a Pentagon story about Middle East operations
            # is filed under middle-east while its risk_country is the US.
            # Both facts are true about the ARTICLE; only one of them is true
            # about the PLACE this signal is pinned to, and this field is the
            # place.
            region=COUNTRY_TO_REGION.get(country.lower())
            or (country_bearer.enrichment.region if country_bearer else None),
            is_fresh=bool(published and (now - published) <= FRESH_WINDOW),
            source_count=len(members),
            # The primary's own summary: it is the telling that was picked as
            # most reliable, so it is the one whose words stand for the event.
            summary_tr=(primary_enrichment.summary_tr or primary_enrichment.summary) or None,
            confidence_score=primary_enrichment.confidence_score,
            corroborating_source_count=primary_enrichment.corroborating_source_count,
            first_reported_at=first_reported,
            last_reported_at=last_reported,
            is_updated=is_updated,
            airports=airports,
            aviation_link=aviation_link_for(risk_type, family, len(airports_by_code)),
            members=member_rows[:MEMBER_CAP],
            members_truncated=len(member_rows) > MEMBER_CAP,
            visibility=visibility,
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
