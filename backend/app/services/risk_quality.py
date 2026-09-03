"""What the Risk Radarı's gates actually kept, and what each one threw away.

`python -m app.cli risk-quality-report` prints this. The question it answers is
the one the page cannot: the radar shows six signals, and nothing on it says
whether that is six out of six or six out of forty with thirty-four removed --
nor, if they were removed, by which rule.

That matters more here than anywhere else in the app, because three of the four
gates below were added at once (spec §15, §16, §17) and every one of them is
calibrated against a distribution that will move as LLM coverage grows. A gate
whose yield nobody measures is a gate nobody can tighten.

The funnel, stage by stage, and what each number is NOT
------------------------------------------------------
Read top to bottom; each stage is a subset of the one above it.

  toplam            every non-duplicate article published in the window. The
                    denominator, so a "3 signals" line has something to be 3 of.
  guncel            minus the rows a classifier explicitly marked
                    is_current_event = false. NOT "rows known to be current":
                    NULL is the majority state and passes -- see risks.py's
                    currency gate on why `IS NOT FALSE` and not `IS TRUE`.
  risk_adayi        classified with a risk_type at all. This is the keyword and
                    model classification, before any verification.
  guven_gecti       cleared the confidence gate: confidence > 0.60, OR
                    corroborated, OR from an official/regulator source, OR
                    never scored. Counted per ARTICLE here, unlike the page,
                    which counts it per cluster -- see `note` in the output.
  havacilik_gecti   cleared the aviation-relevance gate: score >= 0.70 or
                    unscored. The unscored share is broken out separately,
                    because a gate that is passing everything unmeasured is a
                    gate that is not yet doing anything, and that fact must be
                    visible rather than flattering.
  konum_dogrulandi  location_confidence >= 0.70 (or NULL, during the
                    transition). Not "correctly placed" -- nothing here can
                    check a placement against the world, only against the
                    article's own internal agreement.
  kume              what clustering made of the survivors: the number the page
                    actually shows. The drop from the line above is duplicate
                    tellings merging, not a rejection.

Deliberately read-only and free: no LLM, no network, one pass over the window's
enrichment rows. Safe to dispatch against production at any time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
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
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity
from app.pipeline.clustering import EventCandidate, cluster, entity_codes, tier_for_source


@dataclass
class RiskQualityReport:
    window_days: int
    since: datetime
    generated_at: datetime

    total_articles: int = 0
    current: int = 0
    risk_candidates: int = 0
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

    @property
    def rejected_not_current(self) -> int:
        return self.total_articles - self.current

    @property
    def rejected_confidence(self) -> int:
        return self.risk_candidates - self.confidence_passed

    @property
    def rejected_aviation(self) -> int:
        return self.confidence_passed - self.aviation_passed

    @property
    def rejected_location(self) -> int:
        return self.aviation_passed - self.location_passed


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


async def risk_quality_report(
    db: AsyncSession, *, days: int = DEFAULT_WINDOW_DAYS
) -> RiskQualityReport:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    report = RiskQualityReport(window_days=days, since=since, generated_at=now)

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
                    Article.is_duplicate.is_(False),
                    Article.published_at.is_not(None),
                    Article.published_at >= since,
                )
            )
        )
        .scalars()
        .unique()
        .all()
    )

    survivors: list[Article] = []
    for article in rows:
        enrichment = article.enrichment
        if enrichment is None:
            continue
        report.total_articles += 1

        if enrichment.is_current_event is False:
            continue
        report.current += 1

        if enrichment.risk_type is None:
            continue
        report.risk_candidates += 1

        published, why = _confidence_verdict(enrichment, article.source)
        if not published:
            continue
        report.confidence_passed += 1
        if why == "unscored":
            report.confidence_unscored += 1
        elif why == "official":
            report.confidence_exempt_official += 1
        elif why == "corroborated":
            report.confidence_exempt_corroborated += 1

        if not aviation_gate(enrichment.aviation_relevance_score):
            continue
        report.aviation_passed += 1
        if enrichment.aviation_relevance_score is None:
            report.aviation_unscored += 1
        source_label = enrichment.aviation_relevance_source or "unscored"
        report.aviation_by_source[source_label] = (
            report.aviation_by_source.get(source_label, 0) + 1
        )

        if not is_mappable(enrichment.location_confidence):
            continue
        report.location_passed += 1
        if enrichment.location_confidence is None:
            report.location_unscored += 1
        survivors.append(article)

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
    return report


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
        _row("Toplam makale", report.total_articles),
        _row("Güncel (is_current_event≠false)", report.current, total),
        _row("Risk adayı (risk_type var)", report.risk_candidates, total),
        _row("Güven kapısını geçen", report.confidence_passed, total),
        _row("Havacılık kapısını geçen", report.aviation_passed, total),
        _row("Konumu doğrulanan", report.location_passed, total),
        _row("Kümeleme sonrası sinyal", report.clusters, total),
        "",
        "  Elenenler (kapı bazında)",
        "  ---------------------------------- -------",
        _row("Güncel değil", report.rejected_not_current),
        _row("Güven eşiğinin altında", report.rejected_confidence),
        _row("Havacılıkla ilgisiz", report.rejected_aviation),
        _row("Konum güveni düşük", report.rejected_location),
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
