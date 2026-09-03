"""What the campaign pipeline actually produced, and what it threw away.

`python -m app.cli campaign-quality-report` prints this. The question it
answers is the one nobody could answer before: a sweep finishes, the page shows
eleven campaigns, and there is no way to tell whether that is eleven out of
eleven or eleven out of ninety with seventy-nine silently dropped -- nor, if
they were dropped, on which rule.

Where each number comes from, and what it is not
------------------------------------------------
This report is derived from three tables that already exist, and the honesty of
it depends on saying which:

* **`scrape_runs`** -- one row per fetch attempt, so "keşfedilen" is a real count
  of pages we actually reached, split by outcome. A carrier behind a bot wall
  shows up here as `blocked`, which is the difference between "no new TK
  campaigns" and "we have not read TK's page since Tuesday".
* **`promotions`** -- the rows that survived. Everything under "reddedilen" is
  read off the row's own `business_class` and `confidence_band`, so it counts
  rejections *that were written down*: a page classified as a loyalty promo is
  stored with that class rather than deleted, which is what makes the count
  possible.
* **`campaign_versions`** and **`campaign_sources`** -- what changed, and how
  many pages told us about each campaign.

What this cannot see, and says so in the output: an item the extraction chain
dropped in memory before any row was written (`PageExtraction.dropped` --
airline mismatch, a schema failure, a rule rejection on a page whose campaign
never became a row) leaves no database trace. The per-rule breakdown below is
therefore a breakdown of *stored* verdicts, and the "çıkarılamayan sayfa"
line -- failed and blocked fetches -- is the honest upper bound on what is
missing from it.

Everything is scoped to a window (default 7 days) on the observation clock:
`first_seen_at` for a campaign, `started_at` for a run. Not `detected_at`,
which is frozen at first sight and would keep an old row inside every window
forever.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_source import CampaignSource
from app.models.campaign_version import CampaignVersion
from app.models.promotion import Promotion
from app.models.scrape_run import ScrapeRun
from app.services.campaign_status import campaign_status
from app.taxonomy import CAMPAIGN_BUSINESS_CLASS_LABELS_TR

#: Default reporting window. A week covers the deep scan's cadence with room
#: for a skipped run, and is short enough that the numbers describe the current
#: state of the pipeline rather than its history.
DEFAULT_WINDOW_DAYS = 7

#: The business classes that mean "this was not published as a fare campaign".
#: Read from the row rather than restated: agents/campaign_airline.py owns the
#: rules, this only counts their verdicts.
NON_FARE_CLASSES: tuple[str, ...] = (
    "PRODUCT_PROMOTION",
    "LOYALTY_PROMOTION",
    "NEWS_ONLY",
    "EVERGREEN_OFFER",
)


@dataclass(frozen=True)
class ScrapeCounts:
    """`scrape_runs` for the window, by outcome."""

    attempts: int = 0
    ok: int = 0
    blocked: int = 0
    timeout: int = 0
    parse_error: int = 0
    changed: int = 0

    @property
    def unreadable(self) -> int:
        """Attempts that produced no text to extract from. The upper bound on
        what the per-rule breakdown cannot see."""
        return self.blocked + self.timeout + self.parse_error


@dataclass(frozen=True)
class CampaignQualityReport:
    window_days: int
    since: datetime
    today: date

    scrape: ScrapeCounts = field(default_factory=ScrapeCounts)

    #: Rows first seen inside the window -- what the sweep actually extracted.
    extracted: int = 0
    #: Of those, how many are publishable AND not expired: what a reader saw.
    published: int = 0
    #: Campaigns whose fields moved inside the window (one per campaign, not
    #: one per changed field).
    changed: int = 0

    #: reason -> count, over the same window. Keys are stable machine strings
    #: ("business_class:LOYALTY_PROMOTION", "expired", "low_confidence",
    #: "duplicate") so the report can be diffed run to run.
    rejected: dict[str, int] = field(default_factory=dict)

    low_confidence: int = 0
    expired: int = 0
    review_queue: int = 0

    #: campaign_kind -> count among published rows. Two buckets and a NULL.
    by_kind: dict[str, int] = field(default_factory=dict)

    @property
    def rejected_total(self) -> int:
        return sum(self.rejected.values())


def _window_start(days: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


async def campaign_quality_report(
    db: AsyncSession,
    *,
    days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> CampaignQualityReport:
    """Build the report. Read-only: this never writes, so it is safe to run
    against production while a sweep is in flight."""
    reference = now or datetime.now(timezone.utc)
    since = _window_start(days, reference)
    today = reference.date()

    outcomes = dict(
        (
            await db.execute(
                select(ScrapeRun.outcome, func.count())
                .where(ScrapeRun.started_at >= since)
                .group_by(ScrapeRun.outcome)
            )
        ).all()
    )
    changed_pages = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ScrapeRun)
                .where(ScrapeRun.started_at >= since, ScrapeRun.changed.is_(True))
            )
        ).scalar()
        or 0
    )
    scrape = ScrapeCounts(
        attempts=sum(outcomes.values()),
        ok=outcomes.get("ok", 0),
        blocked=outcomes.get("blocked", 0),
        timeout=outcomes.get("timeout", 0),
        parse_error=outcomes.get("parse_error", 0),
        changed=changed_pages,
    )

    # `first_seen_at` is the observation clock; a legacy row has none, so
    # `detected_at` stands in. COALESCE rather than an OR of two predicates so
    # the window means one thing.
    seen_at = func.coalesce(Promotion.first_seen_at, Promotion.detected_at)
    rows = (
        (await db.execute(select(Promotion).where(seen_at >= since))).scalars().all()
    )

    rejected: dict[str, int] = {}
    published = 0
    expired = 0
    low_confidence = 0
    review_queue = 0
    by_kind: dict[str, int] = {}

    for row in rows:
        status = campaign_status(
            row.sale_starts, row.sale_ends, row.travel_starts, row.travel_ends, today
        )
        if status == "EXPIRED":
            expired += 1
        if row.confidence_band == "low":
            low_confidence += 1
        if row.review_required:
            review_queue += 1

        # One reason per row, in the order the pipeline would have applied
        # them: a loyalty page that is also low-confidence was rejected for
        # being a loyalty page, and counting it twice would make the column
        # sum to more than the rows.
        if row.business_class in NON_FARE_CLASSES:
            key = f"business_class:{row.business_class}"
        elif row.superseded_at is not None:
            key = "superseded"
        elif row.confidence_band == "low":
            key = "low_confidence"
        elif status == "EXPIRED":
            key = "expired"
        else:
            key = None

        if key is not None:
            rejected[key] = rejected.get(key, 0) + 1
            continue

        published += 1
        by_kind[row.campaign_kind or "—"] = by_kind.get(row.campaign_kind or "—", 0) + 1

    # Duplicates are counted separately and deliberately not folded into the
    # loop above: a merged campaign was not rejected, it was *absorbed*, and
    # the row that survived is one of the published ones. This is how many
    # times the dedup gate stopped the timeline drawing one sale twice.
    duplicates = int(
        (
            await db.execute(
                select(func.count()).select_from(
                    select(CampaignSource.promotion_id)
                    .join(Promotion, Promotion.id == CampaignSource.promotion_id)
                    .where(seen_at >= since)
                    .group_by(CampaignSource.promotion_id)
                    .having(func.count() > 1)
                    .subquery()
                )
            )
        ).scalar()
        or 0
    )
    if duplicates:
        rejected["duplicate"] = duplicates

    changed = int(
        (
            await db.execute(
                select(func.count(func.distinct(CampaignVersion.promotion_id))).where(
                    CampaignVersion.created_at >= since
                )
            )
        ).scalar()
        or 0
    )

    return CampaignQualityReport(
        window_days=days,
        since=since,
        today=today,
        scrape=scrape,
        extracted=len(rows),
        published=published,
        changed=changed,
        rejected=rejected,
        low_confidence=low_confidence,
        expired=expired,
        review_queue=review_queue,
        by_kind=by_kind,
    )


#: Turkish labels for the machine-readable rejection keys. A key with no label
#: prints as itself rather than as nothing -- a reason nobody named is still a
#: reason, and hiding it would be the one failure this report exists to end.
REJECTION_LABELS_TR: dict[str, str] = {
    "expired": "Süresi dolmuş",
    "low_confidence": "Düşük güven bandı",
    "duplicate": "Yinelenen (birleştirildi)",
    "superseded": "Geri çekilmiş (superseded)",
}


def _label_for(key: str) -> str:
    if key.startswith("business_class:"):
        slug = key.split(":", 1)[1]
        return f"İş sınıfı — {CAMPAIGN_BUSINESS_CLASS_LABELS_TR.get(slug, slug)}"
    return REJECTION_LABELS_TR.get(key, key)


def render_report_tr(report: CampaignQualityReport) -> str:
    """The report as printable Turkish. Separated from the measurement so the
    numbers can be asserted in a test without parsing a table."""
    lines: list[str] = []
    lines.append(
        f"Kampanya veri kalitesi raporu — son {report.window_days} gün "
        f"({report.since.date().isoformat()} → {report.today.isoformat()})"
    )
    lines.append("")
    lines.append("  Tarama (scrape_runs)")
    lines.append("  ------------------------------------ --------")
    lines.append(f"  Denenen sayfa                        {report.scrape.attempts:>8}")
    lines.append(f"  Okunabilen (ok)                      {report.scrape.ok:>8}")
    lines.append(f"  İçeriği değişen                      {report.scrape.changed:>8}")
    lines.append(f"  Bot duvarı (blocked)                 {report.scrape.blocked:>8}")
    lines.append(f"  Zaman aşımı                          {report.scrape.timeout:>8}")
    lines.append(f"  Ayrıştırılamayan                     {report.scrape.parse_error:>8}")
    lines.append("")
    lines.append("  Kampanya (promotions)")
    lines.append("  ------------------------------------ --------")
    lines.append(f"  Çıkarılan (ilk kez görülen)          {report.extracted:>8}")
    lines.append(f"  Doğrulanan ve yayınlanan             {report.published:>8}")
    lines.append(f"  Alanı değişen                        {report.changed:>8}")
    lines.append(f"  Düşük güvenli                        {report.low_confidence:>8}")
    lines.append(f"  İnceleme kuyruğunda                  {report.review_queue:>8}")
    lines.append(f"  Süresi dolmuş                        {report.expired:>8}")
    lines.append("")
    lines.append("  Reddedilenler (sebep kırılımı)")
    lines.append("  ------------------------------------ --------")
    if not report.rejected:
        lines.append("  (bu pencerede reddedilen kayıt yok)")
    for key, count in sorted(report.rejected.items(), key=lambda item: -item[1]):
        lines.append(f"  {_label_for(key):<36} {count:>8}")
    lines.append(f"  {'TOPLAM':<36} {report.rejected_total:>8}")
    lines.append("")
    lines.append("  Yayınlananların türü (campaign_kind)")
    lines.append("  ------------------------------------ --------")
    if not report.by_kind:
        lines.append("  (bu pencerede yayınlanan kayıt yok)")
    for kind, count in sorted(report.by_kind.items()):
        lines.append(f"  {kind:<36} {count:>8}")
    lines.append("")
    lines.append(
        "  Not: sebep kırılımı YAZILMIŞ satırların verdiktlerini sayar. Hiç "
        "satır yazılmadan\n  elenen adaylar (havayolu uyuşmazlığı, şema hatası, "
        f"okunamayan sayfa) burada görünmez;\n  {report.scrape.unreadable} "
        "okunamayan sayfa bu görünmezliğin üst sınırıdır."
    )
    return "\n".join(lines)
