"""What the Risk Radarı's gates actually kept, what each one threw away, and
WHICH ROWS.

Two consumers, one measurement pass: `python -m app.cli risk-quality-report`
prints the funnel, and `GET /risks/quality` + `GET /risks/rejected` serve it to
the doğrulama screen. Both come out of `risk_quality_report()` because a funnel
computed by one code path and a rejection list computed by another is two
answers to the same question, and the first time they disagree neither is
trustworthy.

The question they answer is the one the radar page cannot: the page shows six
signals, and nothing on it says whether that is six out of six or six out of
forty with thirty-four removed -- nor, if they were removed, by which rule, nor
which articles they were.

That matters more here than anywhere else in the app, because three of the four
gates below were added at once (spec §15, §16, §17) and every one of them is
calibrated against a distribution that will move as LLM coverage grows. A gate
whose yield nobody measures is a gate nobody can tighten.

WHY NOTHING IS WRITTEN DOWN
---------------------------
A rejection is computed when it is asked for and stored nowhere. The
alternative -- a `risk_rejections` table written by the enrichment pass -- was
measured and rejected, and the reasoning is worth keeping because it is not
obvious:

* **Volume does not justify it.** The rejection set is bounded by the risk
  candidates in the window, which is ~10²: production carries 252
  risk-classified rows across the whole archive (13.906 articles scanned) and
  9 published signals in the 5-day window. One indexed pass, no LLM, no
  network. A table would add a write per enriched article to buy back a query
  that is already cheap.
* **A stored reason goes stale against the gate that produced it.** Every
  threshold here is explicitly provisional -- `AVIATION_RELEVANCE_GATE`,
  `LOCATION_MAP_PIN_MIN` and `CONFIDENCE_VERIFIED_MIN` all tighten as coverage
  arrives. A row stamped `aviation_relevance_low` under yesterday's threshold
  and read back today is a claim about a rule that no longer exists, and it
  reads exactly like a claim about the current one. Recomputing cannot drift.
* **The funnel is a snapshot question.** "Why is this news not on the page"
  is asked about the page as it is now. A persistent audit trail answers a
  different and genuinely separate question -- "what did we reject last month"
  -- which needs its own retention policy, its own migration and its own
  backfill, and would be built as its own job rather than smuggled in here.

The cost of the choice, stated so nobody discovers it later: there is no
history. A rejection that has since been fixed leaves no trace, and a
regression between two runs is invisible unless someone captured the output.
The 30-case verification suite (app/tests/test_risk_verification_cases.py) is
the deliberate answer to that -- it pins the behaviour in the repository
instead of in a table.

The funnel, stage by stage, and what each number is NOT
------------------------------------------------------
Read top to bottom; each stage is a subset of the one above it, and
`passed + dropped == previous.passed` holds at every stage (asserted by
test_risk_radar.py, because a funnel whose arithmetic does not close is a
picture, not a measurement).

  toplam            every article with an enrichment row, whole archive. The
                    denominator, so "9 signals" has something to be 9 of.
  risk_adayi        classified with a risk_type at all -- keyword and model
                    classification, before any verification. The drop here is
                    NOT a rejection: the other rows are simply not risk news.
                    From this stage down, every count is over risk candidates
                    only, which is what makes the rejection list below exactly
                    the union of the stages' drops.
  pencere           published inside the window. The drop is `outside_window`,
                    which is the largest single reason and almost always the
                    right answer to "it was there yesterday".
  tekil             not flagged by the near-duplicate pass. Drop: `duplicate`.
  guncel            minus the rows a classifier explicitly marked
                    is_current_event = false. NOT "rows known to be current":
                    NULL is the majority state and passes -- see risks.py's
                    currency gate on why `IS NOT FALSE` and not `IS TRUE`.
  guven             cleared the confidence gate: confidence > 0.60, OR
                    corroborated, OR from an official/regulator source, OR
                    never scored. Counted per ARTICLE here, unlike the page,
                    which counts it per cluster -- see `note` in the output.
  havacilik         cleared the aviation-relevance gate: score >= 0.70 or
                    unscored. The unscored share is broken out separately,
                    because a gate that is passing everything unmeasured is a
                    gate that is not yet doing anything, and that fact must be
                    visible rather than flattering.
  konum             location_confidence >= 0.70 (or NULL, during the
                    transition). Not "correctly placed" -- nothing here can
                    check a placement against the world, only against the
                    article's own internal agreement.
  kume              what clustering made of the survivors: the number the page
                    actually shows. The drop from the line above is duplicate
                    tellings MERGING, not a rejection -- it carries
                    `drop_kind="merged"` so no reader can mistake the two.

Deliberately read-only and free: no LLM, no network, two aggregate counts and
one pass over the window's risk candidates. Safe to dispatch against production
at any time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.risks import (
    CONFIDENCE_UNSCORED_BELOW,
    CONFIDENCE_VERIFIED_MIN,
    DEFAULT_WINDOW_DAYS,
    VERIFIED_SOURCE_TIERS,
    aviation_gate,
    is_mappable,
)
from app.llm.heuristic import LOCATION_CONFIDENCE_CONFLICT
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity
from app.pipeline.clustering import EventCandidate, cluster, entity_codes, tier_for_source

# ---------------------------------------------------------------------------
# REJECTION REASONS
#
# One slug per rule that can remove a risk candidate from the page, in funnel
# order. They are API values (the doğrulama screen filters on them) and test
# expectations, so they are named here once rather than spelled inline.
#
# There is deliberately no "other": a rejection this module cannot name is a
# rejection nobody can act on, and every path out of the funnel below ends at
# one of these.
# ---------------------------------------------------------------------------

#: Published before the window opened. The largest bucket by far, and the
#: correct answer to "this was on the page yesterday".
REASON_OUTSIDE_WINDOW = "outside_window"
#: The near-duplicate pass (app/pipeline/dedup.py) folded this row into
#: another. The EVENT is still on the page -- told by the surviving article.
REASON_DUPLICATE = "duplicate"
#: A classifier looked at this and called it not-current: an anniversary
#: piece, a retrospective, an analysis. Never fires on an unscored row.
REASON_NOT_CURRENT_EVENT = "not_current_event"
#: confidence_score at or below CONFIDENCE_VERIFIED_MIN with no exemption --
#: single-source, from an outlet weighted below the default trade press.
REASON_CONFIDENCE_BELOW_FLOOR = "confidence_below_floor"
#: Measured and found to have no operational bearing on flying. Never fires on
#: an unscored row: see aviation_gate().
REASON_AVIATION_RELEVANCE_LOW = "aviation_relevance_low"
#: A placement was produced and it scored below the pin threshold -- typically
#: a SOURCE-role country ("Washington said") or a country the resolver could
#: recognise but not verify in the text.
REASON_LOCATION_UNRESOLVED = "location_unresolved"
#: The article named a city that is not in the country it also named. Split
#: out from the line above because it is a different failure: not "we could not
#: place this" but "the article disagreed with itself".
REASON_LOCATION_CONFLICT = "location_conflict"

REJECTION_REASONS: tuple[str, ...] = (
    REASON_OUTSIDE_WINDOW,
    REASON_DUPLICATE,
    REASON_NOT_CURRENT_EVENT,
    REASON_CONFIDENCE_BELOW_FLOOR,
    REASON_AVIATION_RELEVANCE_LOW,
    REASON_LOCATION_UNRESOLVED,
    REASON_LOCATION_CONFLICT,
)

REJECTION_REASON_LABELS_TR: dict[str, str] = {
    REASON_OUTSIDE_WINDOW: "Pencere dışında",
    REASON_DUPLICATE: "Yinelenen haber",
    REASON_NOT_CURRENT_EVENT: "Güncel olay değil",
    REASON_CONFIDENCE_BELOW_FLOOR: "Güven eşiğinin altında",
    REASON_AVIATION_RELEVANCE_LOW: "Havacılıkla ilgisiz",
    REASON_LOCATION_UNRESOLVED: "Konum doğrulanamadı",
    REASON_LOCATION_CONFLICT: "Konum çelişkili",
}

#: How many rejected rows one call will build PER REASON. Per reason and not
#: overall, because the screen's whole interaction is the reason filter: a cap
#: applied to the mixed list would silently truncate a small bucket behind a
#: large one, so "no location conflicts this window" and "200 currency
#: rejections came first" would render identically. The list is an audit
#: sample, not an export -- it bounds the payload against a pathological window
#: (a wire story republished by forty aggregators) without ever emptying a
#: bucket the reader asked for.
REJECTION_CAP = 200


@dataclass(frozen=True)
class FunnelStage:
    """One line of the funnel: what reached it, and what left."""

    key: str
    label_tr: str
    #: How many rows cleared this stage.
    passed: int
    #: `previous.passed - passed`. Always non-negative.
    dropped: int
    #: The rejection slug the dropped rows carry, or None when the drop is not
    #: a rejection (the first stage has nothing above it; `risk_adayi` drops
    #: non-risk news; `kume` merges rather than removes).
    #:
    #: A stage can carry MORE THAN ONE -- the location gate splits into
    #: `location_unresolved` and `location_conflict` -- and `reason` is then
    #: only the first of them. `reason_counts` is the whole answer, and it is
    #: what a filter must be built from: a chip labelled "3 elendi ·
    #: location_unresolved" that returns one row when clicked is a screen
    #: contradicting itself.
    reason: str | None = None
    #: reason -> how many of `dropped` carry it. Empty for a non-rejecting
    #: stage. Sums to `dropped` (asserted in test_risk_radar.py).
    reason_counts: dict[str, int] = field(default_factory=dict)
    #: "rejected" | "merged" | None. The distinction the page must not blur: a
    #: merged cluster is still on the radar, a rejected article is not.
    drop_kind: str | None = None
    #: One sentence for the reader, when the count alone would mislead.
    note_tr: str | None = None


@dataclass(frozen=True)
class RiskRejection:
    """One risk candidate the page does not show, and everything that was in
    front of the rule when it decided.

    The values are the DECISION INPUTS, not a summary of them: a screen that
    says "aviation_relevance_low" without the score is asking the reader to
    trust the label, which is the exact failure this revision exists to fix.
    """

    article_id: str
    title: str
    url: str
    source_name: str
    #: official | regulator | agency | trade | aggregator.
    source_tier: str
    published_at: datetime | None
    reason: str
    #: Every OTHER gate this row would also have failed, in funnel order.
    #: `reason` is the first one, which is an ordering choice and not a claim
    #: that the others are fine -- a row rejected for currency that would also
    #: have failed the location gate is a different fix from one that would
    #: have passed everything else.
    also_failed: tuple[str, ...] = ()

    risk_type: str | None = None
    risk_severity: str | None = None
    confidence_score: float | None = None
    corroborating_source_count: int | None = None
    aviation_relevance_score: float | None = None
    aviation_relevance_source: str | None = None
    location_confidence: float | None = None
    #: What the resolver decided the event's place was, before any gate.
    detected_country: str | None = None
    detected_city: str | None = None
    #: Every place the article named with the role it played. The audit trail
    #: for a location rejection: without it "konum doğrulanamadı" is
    #: unanswerable, and the reader cannot tell a correct refusal from a bug.
    mentioned_locations: list[dict] = field(default_factory=list)


@dataclass
class RiskQualityReport:
    window_days: int
    since: datetime
    generated_at: datetime

    total_articles: int = 0
    risk_candidates: int = 0
    in_window: int = 0
    unique: int = 0
    current: int = 0
    confidence_passed: int = 0
    aviation_passed: int = 0
    location_passed: int = 0
    clusters: int = 0

    #: How each gate's survivors break down by WHY they survived. The whole
    #: point of the report: "passed" and "was never measured" are different
    #: outcomes and a single count hides which one is carrying the funnel.
    aviation_unscored: int = 0
    aviation_by_source: dict[str, int] = field(default_factory=dict)
    confidence_unscored: int = 0
    confidence_exempt_official: int = 0
    confidence_exempt_corroborated: int = 0
    location_unscored: int = 0

    #: Every risk candidate the funnel removed, newest first, capped at
    #: REJECTION_CAP. `rejected_counts` is the UNCAPPED tally, so a truncated
    #: list can still state how much it is a sample of.
    rejections: list[RiskRejection] = field(default_factory=list)
    rejected_counts: dict[str, int] = field(default_factory=dict)

    # -- legacy names, kept because the CLI report and its tests read them ---

    @property
    def rejected_not_current(self) -> int:
        return self.unique - self.current

    @property
    def rejected_confidence(self) -> int:
        return self.current - self.confidence_passed

    @property
    def rejected_aviation(self) -> int:
        return self.confidence_passed - self.aviation_passed

    @property
    def rejected_location(self) -> int:
        return self.aviation_passed - self.location_passed

    def _counts(self, *reasons: str) -> dict[str, int]:
        """The rejection tally for one stage, keyed by reason.

        Reads back from the same `rejected_counts` the pass filled, so a stage
        can never claim a split its own rejections do not add up to. Reasons
        that fired zero times are kept: a filter option that appears and
        disappears with the data cannot be learned, and "no location conflicts
        this window" is a fact worth showing as a zero.
        """
        return {reason: self.rejected_counts.get(reason, 0) for reason in reasons}

    @property
    def stages(self) -> list[FunnelStage]:
        """The funnel as an ordered list, which is how both the CLI table and
        the doğrulama screen draw it.

        Derived rather than accumulated so the arithmetic cannot drift from
        the counters above: every `dropped` here is a subtraction of two
        fields, so `passed + dropped == previous.passed` is true by
        construction and the test that asserts it is checking the ORDER and the
        labels, which are the parts that can actually be got wrong.
        """
        return [
            FunnelStage(
                key="toplam",
                label_tr="Toplam makale",
                passed=self.total_articles,
                dropped=0,
            ),
            FunnelStage(
                key="risk_adayi",
                label_tr="Risk adayı",
                passed=self.risk_candidates,
                dropped=self.total_articles - self.risk_candidates,
                drop_kind=None,
                note_tr=(
                    "Elenen değil: risk sınıflandırması almayan haberler. "
                    "Bu satırdan aşağısı yalnızca risk adaylarını sayar."
                ),
            ),
            FunnelStage(
                key="pencere",
                label_tr=f"Pencere içinde (son {self.window_days} gün)",
                passed=self.in_window,
                dropped=self.risk_candidates - self.in_window,
                reason=REASON_OUTSIDE_WINDOW,
                reason_counts=self._counts(REASON_OUTSIDE_WINDOW),
                drop_kind="rejected",
            ),
            FunnelStage(
                key="tekil",
                label_tr="Yinelenmemiş",
                passed=self.unique,
                dropped=self.in_window - self.unique,
                reason=REASON_DUPLICATE,
                reason_counts=self._counts(REASON_DUPLICATE),
                drop_kind="rejected",
                note_tr="Olay kaybolmaz: yinelenen anlatı, kalan haberde duruyor.",
            ),
            FunnelStage(
                key="guncel",
                label_tr="Güncel olay",
                passed=self.current,
                dropped=self.rejected_not_current,
                reason=REASON_NOT_CURRENT_EVENT,
                reason_counts=self._counts(REASON_NOT_CURRENT_EVENT),
                drop_kind="rejected",
                note_tr="Yalnızca bir sınıflandırıcının açıkça 'güncel değil' dediği satırlar.",
            ),
            FunnelStage(
                key="guven",
                label_tr="Güven kapısı",
                passed=self.confidence_passed,
                dropped=self.rejected_confidence,
                reason=REASON_CONFIDENCE_BELOW_FLOOR,
                reason_counts=self._counts(REASON_CONFIDENCE_BELOW_FLOOR),
                drop_kind="rejected",
                note_tr=(
                    "Makale başına sayılır; sayfa küme başına sayar ve kümedeki "
                    "ikinci bir kaynak ek muafiyet getirir. Bu sayı bir üst sınırdır."
                ),
            ),
            FunnelStage(
                key="havacilik",
                label_tr="Havacılık ilgisi",
                passed=self.aviation_passed,
                dropped=self.rejected_aviation,
                reason=REASON_AVIATION_RELEVANCE_LOW,
                reason_counts=self._counts(REASON_AVIATION_RELEVANCE_LOW),
                drop_kind="rejected",
                note_tr=(
                    f"{self.aviation_unscored} satır ölçülmediği için geçti — "
                    "kapının henüz iş yapmadığı pay."
                ),
            ),
            FunnelStage(
                key="konum",
                label_tr="Konum doğrulandı",
                passed=self.location_passed,
                dropped=self.rejected_location,
                reason=REASON_LOCATION_UNRESOLVED,
                # The one stage with two of them.
                reason_counts=self._counts(
                    REASON_LOCATION_UNRESOLVED, REASON_LOCATION_CONFLICT
                ),
                drop_kind="rejected",
                note_tr=(
                    f"{self.location_unscored} satır ölçülmediği için geçti. "
                    "Çelişkili konumlar ayrı bir sebeple listelenir."
                ),
            ),
            FunnelStage(
                key="kume",
                label_tr="Kümeleme sonrası sinyal",
                passed=self.clusters,
                dropped=self.location_passed - self.clusters,
                reason=None,
                drop_kind="merged",
                note_tr=(
                    "Eleme değil, BİRLEŞME: aynı olayı anlatan haberler tek "
                    "sinyalde toplandı. Sayfanın gösterdiği sayı budur."
                ),
            ),
        ]


def _confidence_verdict(enrichment, source) -> tuple[bool, str]:
    """(published, why) for one article's confidence gate.

    Mirrors risks.visibility_for's exemption order at the article level. It
    cannot mirror the CLUSTER exemption (a second outlet telling the same
    story), because that only exists after clustering -- so this count is a
    lower bound on what the page publishes, which the report says out loud
    rather than quietly overstating the rejection rate.
    """
    if (enrichment.corroborating_source_count or 1) > 1:
        return True, "corroborated"
    score = enrichment.confidence_score
    if score is None or score < CONFIDENCE_UNSCORED_BELOW:
        return True, "unscored"
    if score > CONFIDENCE_VERIFIED_MIN:
        return True, "scored"
    if tier_for_source(source) in VERIFIED_SOURCE_TIERS:
        return True, "official"
    return False, "below_gate"


def location_reason(location_confidence: float | None) -> str:
    """Which of the two location rejections a below-threshold score is.

    LOCATION_CONFIDENCE_CONFLICT is a NAMED case, not a tuned number
    (app/llm/heuristic.py), so reading it back is reading the resolver's own
    verdict rather than inferring one from a magnitude. Everything else below
    the pin threshold is "we could not verify where", which is a different
    thing for the analyst to go and fix.
    """
    if location_confidence == LOCATION_CONFIDENCE_CONFLICT:
        return REASON_LOCATION_CONFLICT
    return REASON_LOCATION_UNRESOLVED


def _rejection(article, reason: str, *, also_failed: tuple[str, ...] = ()) -> RiskRejection:
    enrichment = article.enrichment
    mentions = enrichment.mentioned_locations or []
    return RiskRejection(
        article_id=str(article.id),
        title=article.title,
        url=article.url,
        source_name=article.source.name if article.source else "",
        source_tier=tier_for_source(article.source),
        published_at=article.published_at,
        reason=reason,
        also_failed=also_failed,
        risk_type=enrichment.risk_type,
        risk_severity=enrichment.risk_severity,
        confidence_score=enrichment.confidence_score,
        corroborating_source_count=enrichment.corroborating_source_count,
        aviation_relevance_score=enrichment.aviation_relevance_score,
        aviation_relevance_source=enrichment.aviation_relevance_source,
        location_confidence=enrichment.location_confidence,
        detected_country=enrichment.risk_country,
        detected_city=enrichment.risk_city,
        mentioned_locations=[m for m in mentions if isinstance(m, dict)],
    )


def _downstream_failures(article, first: str) -> tuple[str, ...]:
    """Every OTHER gate this row would also have failed, in funnel order.

    Evaluated unconditionally rather than short-circuited, which is the whole
    point: "rejected for currency, and would also have failed the location
    gate" is a different piece of work from "rejected for currency, otherwise
    clean". Without it the reader fixes one rule and the row stays hidden for a
    reason nothing told them about.

    Only the four ROW-LEVEL gates are testable this way. `outside_window` and
    `duplicate` are properties of the article rather than of a gate reading its
    enrichment, and they are already the `reason` when they apply.
    """
    enrichment = article.enrichment
    verdicts = (
        (REASON_NOT_CURRENT_EVENT, enrichment.is_current_event is False),
        (
            REASON_CONFIDENCE_BELOW_FLOOR,
            not _confidence_verdict(enrichment, article.source)[0],
        ),
        (
            REASON_AVIATION_RELEVANCE_LOW,
            not aviation_gate(enrichment.aviation_relevance_score),
        ),
        (
            location_reason(enrichment.location_confidence),
            not is_mappable(enrichment.location_confidence),
        ),
    )
    return tuple(reason for reason, failed in verdicts if failed and reason != first)


async def risk_quality_report(
    db: AsyncSession, *, days: int = DEFAULT_WINDOW_DAYS, with_rejections: bool = True
) -> RiskQualityReport:
    """The funnel and the rejection list, from one pass.

    `with_rejections=False` skips only the row-building, not the counting: the
    CLI prints the table and has no use for 200 dataclasses.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    report = RiskQualityReport(window_days=days, since=since, generated_at=now)

    # The two denominators, as aggregates. They span the whole archive, so they
    # must never become row fetches: production is ~14k articles and this
    # endpoint is meant to be safe to call from a page.
    report.total_articles = (
        await db.execute(
            select(func.count())
            .select_from(Article)
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        )
    ).scalar_one()
    report.risk_candidates = (
        await db.execute(
            select(func.count())
            .select_from(Article)
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            .where(ArticleEnrichment.risk_type.is_not(None))
        )
    ).scalar_one()

    # Duplicates are NOT filtered out here, unlike every other query against
    # this table: `duplicate` is one of the rejections the screen has to be
    # able to explain, and a row the query never returned cannot be explained.
    rows = (
        (
            await db.execute(
                select(Article)
                .options(
                    selectinload(Article.source),
                    selectinload(Article.enrichment),
                    # .entity as well as the link row: entity_codes() reads
                    # link.entity.code, and a lazy load of it inside the async
                    # session raises rather than querying. Caught only against
                    # a corpus that actually has entity links -- an article
                    # with none never reaches the attribute.
                    selectinload(Article.entity_links).selectinload(ArticleEntity.entity),
                )
                .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
                .where(
                    ArticleEnrichment.risk_type.is_not(None),
                    Article.published_at.is_not(None),
                    Article.published_at >= since,
                )
                .order_by(Article.published_at.desc())
            )
        )
        .scalars()
        .unique()
        .all()
    )

    survivors: list[Article] = []
    by_reason: dict[str, list[RiskRejection]] = {}

    def reject(article, reason: str) -> None:
        report.rejected_counts[reason] = report.rejected_counts.get(reason, 0) + 1
        if not with_rejections:
            return
        bucket = by_reason.setdefault(reason, [])
        if len(bucket) < REJECTION_CAP:
            bucket.append(
                _rejection(article, reason, also_failed=_downstream_failures(article, reason))
            )

    for article in rows:
        enrichment = article.enrichment
        if enrichment is None:
            continue
        report.in_window += 1

        if article.is_duplicate:
            reject(article, REASON_DUPLICATE)
            continue
        report.unique += 1

        if enrichment.is_current_event is False:
            reject(article, REASON_NOT_CURRENT_EVENT)
            continue
        report.current += 1

        published, why = _confidence_verdict(enrichment, article.source)
        if not published:
            reject(article, REASON_CONFIDENCE_BELOW_FLOOR)
            continue
        report.confidence_passed += 1
        if why == "unscored":
            report.confidence_unscored += 1
        elif why == "official":
            report.confidence_exempt_official += 1
        elif why == "corroborated":
            report.confidence_exempt_corroborated += 1

        if not aviation_gate(enrichment.aviation_relevance_score):
            reject(article, REASON_AVIATION_RELEVANCE_LOW)
            continue
        report.aviation_passed += 1
        if enrichment.aviation_relevance_score is None:
            report.aviation_unscored += 1
        source_label = enrichment.aviation_relevance_source or "unscored"
        report.aviation_by_source[source_label] = (
            report.aviation_by_source.get(source_label, 0) + 1
        )

        if not is_mappable(enrichment.location_confidence):
            reject(article, location_reason(enrichment.location_confidence))
            continue
        report.location_passed += 1
        if enrichment.location_confidence is None:
            report.location_unscored += 1
        survivors.append(article)

    # `outside_window` is counted rather than listed. Listing it would return
    # the archive: every risk candidate ever classified is outside a 5-day
    # window sooner or later, and a rejection list whose default answer is
    # "everything, eventually" tells the reader nothing. The rows are still
    # reachable -- `rejected_candidates(reason="outside_window")` fetches the
    # ones that most recently aged out, which is the question people actually
    # ask ("this was here yesterday").
    report.rejected_counts[REASON_OUTSIDE_WINDOW] = report.risk_candidates - report.in_window

    candidates = [
        EventCandidate(
            article_id=article.id,
            title=article.title,
            entities=entity_codes(article),
            tier=tier_for_source(article.source),
            published_at=article.published_at.isoformat() if article.published_at else None,
        )
        for article in survivors
    ]
    report.clusters = len(cluster(candidates))
    # Back to one list, newest first -- the order the rows arrived in, restored
    # after the per-reason bucketing. `published_at` is never None here (the
    # query filters it out), so the sort key needs no fallback.
    report.rejections = sorted(
        (row for bucket in by_reason.values() for row in bucket),
        key=lambda r: r.published_at or report.since,
        reverse=True,
    )
    return report


async def rejected_candidates(
    db: AsyncSession,
    *,
    days: int = DEFAULT_WINDOW_DAYS,
    reason: str | None = None,
    limit: int = 50,
) -> list[RiskRejection]:
    """The rejection list for one reason, or all of them, newest first.

    Split from the report because `outside_window` needs a different query --
    it is by definition the rows the window excluded, so the funnel's own pass
    never sees them.
    """
    limit = max(1, min(limit, REJECTION_CAP))
    if reason == REASON_OUTSIDE_WINDOW:
        return await _aged_out_candidates(db, days=days, limit=limit)

    report = await risk_quality_report(db, days=days)
    rows = report.rejections
    if reason is not None:
        rows = [r for r in rows if r.reason == reason]
    return rows[:limit]


async def _aged_out_candidates(
    db: AsyncSession, *, days: int, limit: int
) -> list[RiskRejection]:
    """Risk candidates that fell out of the window most recently.

    Ordered newest first and hard-limited, so this is the tail of the archive
    pressing against the window's edge rather than the archive itself. The
    answer to "it was on the radar yesterday and now it is not".
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = (
        (
            await db.execute(
                select(Article)
                .options(
                    selectinload(Article.source),
                    selectinload(Article.enrichment),
                )
                .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
                .where(
                    ArticleEnrichment.risk_type.is_not(None),
                    Article.published_at.is_not(None),
                    Article.published_at < since,
                )
                .order_by(Article.published_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return [
        _rejection(
            article,
            REASON_OUTSIDE_WINDOW,
            also_failed=_downstream_failures(article, REASON_OUTSIDE_WINDOW),
        )
        for article in rows
        if article.enrichment is not None
    ]


def _row(label: str, value: int, of: int | None = None) -> str:
    share = f"  ({value / of:.0%})" if of else ""
    return f"  {label:<34} {value:>7}{share}"


def render_report_tr(report: RiskQualityReport) -> str:
    """The funnel as printable Turkish. Separated from the measurement so the
    numbers can be asserted in a test without parsing a table."""
    total = report.total_articles or None
    lines = [
        f"Risk Radarı veri kalitesi hunisi — son {report.window_days} gün "
        f"({report.since.date().isoformat()} → {report.generated_at.date().isoformat()})",
        "",
        "  Huni (makale bazında)",
        "  ---------------------------------- -------  ------",
    ]
    for stage in report.stages:
        lines.append(_row(stage.label_tr, stage.passed, total))
    lines += [
        "",
        "  Elenenler (sebep bazında)",
        "  ---------------------------------- -------",
    ]
    for slug in REJECTION_REASONS:
        lines.append(
            _row(REJECTION_REASON_LABELS_TR[slug], report.rejected_counts.get(slug, 0))
        )
    lines += [
        "",
        "  Kapılar neden geçirdi? (kademeli devreye alma)",
        "  ---------------------------------- -------",
        _row("Güven: ölçülmemiş", report.confidence_unscored),
        _row("Güven: resmi/düzenleyici", report.confidence_exempt_official),
        _row("Güven: çoklu kaynak", report.confidence_exempt_corroborated),
        _row("Havacılık: ölçülmemiş", report.aviation_unscored),
        _row("Konum: ölçülmemiş", report.location_unscored),
        "",
        "  Havacılık skorunun kaynağı",
        "  ---------------------------------- -------",
    ]
    if not report.aviation_by_source:
        lines.append("  (bu pencerede havacılık kapısını geçen kayıt yok)")
    for source_label, count in sorted(report.aviation_by_source.items()):
        lines.append(_row(source_label, count))
    lines += [
        "",
        "  Not: 'ölçülmemiş' satırları kapının HENÜZ iş yapmadığı payı gösterir.",
        "  Bu bilinçli bir seçimdir: ölçülmemiş bir satırı elemek, kanıt yokken",
        "  karar vermektir (bkz. app/api/v1/risks.py). Sayı düştükçe kapı",
        "  gerçekten devreye girmiş olur.",
        "",
        "  Not: güven kapısı burada MAKALE başına sayılır; sayfa KÜME başına",
        "  sayar ve kümedeki ikinci bir kaynak ek muafiyet getirir. Bu yüzden",
        "  buradaki eleme sayısı bir üst sınırdır.",
    ]
    return "\n".join(lines)
