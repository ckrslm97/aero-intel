"""Faz 13's daily data-quality job: five real invariants over what's actually
published, checked against the live tables rather than assumed from the code
that is supposed to enforce them upstream. Each of these was already meant to
be impossible by construction (the language gate, the confidence bands, the
required-field caps) -- this is the defense-in-depth check that catches a
regression in that guarantee rather than trusting it silently.

No custom ticketing here: `check_data_quality()` returns the violations, and
the CLI command (`app.cli evaluate-data-quality`) exits non-zero when there
are any. A failed step in a scheduled GitHub Actions run *is* the task this
opens -- the same mechanism ci.yml's taxonomy-codegen check already uses, not
a second system to keep in sync with the first.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.news_event import NewsEvent
from app.models.promotion import Promotion
from app.repositories.kpi_repository import KpiRepository
from app.services.kpi_service import LIVE_FX_PAIRS

PUBLISHABLE_BANDS = ("high", "medium")
ALLOWED_LANGUAGES = ("en", "tr")

#: How stale a live FX reading can be before the 15-minute refresh job (see
#: kpi_service.py) is considered to have actually stopped running, not just
#: mid-cycle. Set well above the 15-minute cadence so a single missed tick
#: doesn't fire a false alarm.
FX_FRESHNESS_HOURS = 24


@dataclass(frozen=True)
class Violation:
    check: str
    detail: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _check_published_language(db: AsyncSession) -> list[Violation]:
    rows = (
        await db.execute(
            select(NewsEvent.id, NewsEvent.slug, Article.language)
            .join(Article, Article.id == NewsEvent.primary_article_id)
            .where(
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                NewsEvent.superseded_at.is_(None),
            )
        )
    ).all()
    return [
        Violation("published_language", f"event {slug} ({event_id}): language={language!r}")
        for event_id, slug, language in rows
        if language not in ALLOWED_LANGUAGES
    ]


async def _check_no_below_threshold_published(db: AsyncSession) -> list[Violation]:
    """`is_published=True` is only meant to be set on rows the read endpoints
    would actually serve -- see NewsEvent's own confidence_band docstring
    ("low rows are kept as the record of what the pipeline chose not to
    show"). A low-band row with is_published=True would leak past that."""
    rows = (
        await db.execute(
            select(NewsEvent.id, NewsEvent.slug, NewsEvent.confidence_band).where(
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band == "low",
                NewsEvent.superseded_at.is_(None),
            )
        )
    ).all()
    return [
        Violation("below_threshold_published", f"event {slug} ({event_id}): band=low")
        for event_id, slug, _band in rows
    ]


async def _check_no_sourceless_events(db: AsyncSession) -> list[Violation]:
    rows = (
        await db.execute(
            select(NewsEvent.id, NewsEvent.slug).where(
                NewsEvent.is_published.is_(True),
                NewsEvent.confidence_band.in_(PUBLISHABLE_BANDS),
                NewsEvent.superseded_at.is_(None),
                NewsEvent.primary_article_id.is_(None),
            )
        )
    ).all()
    return [
        Violation("sourceless_event", f"event {slug} ({event_id}): no primary_article_id")
        for event_id, slug in rows
    ]


async def _check_no_dateless_campaigns(db: AsyncSession) -> list[Violation]:
    rows = (
        await db.execute(
            select(Promotion.id, Promotion.title_tr).where(
                Promotion.confidence_band.in_(PUBLISHABLE_BANDS),
                Promotion.superseded_at.is_(None),
                Promotion.sale_starts.is_(None),
                Promotion.sale_ends.is_(None),
            )
        )
    ).all()
    return [
        Violation("dateless_campaign", f"promotion {title!r} ({promo_id}): no sale window")
        for promo_id, title in rows
    ]


async def _check_fx_freshness(db: AsyncSession) -> list[Violation]:
    repo = KpiRepository(db)
    cutoff = _now() - timedelta(hours=FX_FRESHNESS_HOURS)
    violations: list[Violation] = []
    for metric_key, *_rest in LIVE_FX_PAIRS:
        latest = await repo.latest(metric_key)
        if latest is None:
            violations.append(Violation("fx_freshness", f"{metric_key}: no observation at all"))
        elif latest.as_of < cutoff:
            age_hours = (_now() - latest.as_of).total_seconds() / 3600
            violations.append(
                Violation("fx_freshness", f"{metric_key}: last reading {age_hours:.1f}h old")
            )
    return violations


async def check_data_quality(db: AsyncSession) -> list[Violation]:
    violations: list[Violation] = []
    violations += await _check_published_language(db)
    violations += await _check_no_below_threshold_published(db)
    violations += await _check_no_sourceless_events(db)
    violations += await _check_no_dateless_campaigns(db)
    violations += await _check_fx_freshness(db)
    return violations
