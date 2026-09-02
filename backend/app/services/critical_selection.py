"""Which of the day's articles are worth a model call, and what the paper leads with.

The Gazete's problem was never "not enough news". Measured over 30 days at
n = 4205 articles, the three sections were running at 15.7 / 3.5 / 2.7 stories
a day -- and the only dial available to thin them, `min_importance`, does not
measure importance at all (see app/services/news_scoring.py for the arithmetic).
Turning it up did not select better stories, it deleted whole sections: at
>= 0.49 Havalimanı empties, at >= 0.70 Etkinlik does, and what survives is
whichever category FOCUS_BONUS happens to prop up.

The target is 10-20 genuinely critical developments a day. This module is how
they are picked.

--- Two passes, because one of them costs money -----------------------------

  1. Every candidate is scored on the FIVE DETERMINISTIC sub-scores. Free,
     microseconds, no network.
  2. The top few per category go to the LLM for the three impact scores, and
     are rescored with all eight.

Articles that lose pass 2 are not discarded and are not unscored: they keep the
deterministic score from pass 1, which is a real number on the same scale (see
news_scoring.combine on why the two are comparable). They are simply not the
day's shortlist.

--- The quota rule ----------------------------------------------------------

**Each category fills its own quota from its own candidates. A category that
cannot fill its quota does NOT hand the remainder to another.**

This is the rule the whole design turns on, and it is deliberately a worse deal
arithmetically: on a quiet day the run spends fewer calls than its budget
allows, and the paper prints fewer stories than it could. That is the point.
Havalimanı genuinely produces about three stories a day. A pool that let
Gelir Yönetimi absorb the unused airport quota would print five RM stories
under an "Havalimanı" heading's worth of space and call the section full --
which is how the section stopped meaning anything the first time. The owner's
rule is that three real airport stories is an acceptable day; five padded ones
is not.

Second-order consequence, also deliberate: the RM quota being larger than the
others does not let RM crowd them out, because the others' slots were never
RM's to take. Each section competes only with itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.ingest.blacklist import BLACKLIST_STATUS
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.services.news_scoring import (
    ArticleSignals,
    ImpactScores,
    NewsScore,
    deterministic_components,
)
from app.services.news_scoring import combine as combine_score

logger = get_logger(__name__)

#: The three sections the Gazete actually prints (PR #69's taxonomy). Everything
#: else is still ingested, classified and searchable -- it is simply not what
#: this pass is budgeting model calls for.
GAZETE_CATEGORIES: tuple[str, ...] = ("revenue_management", "airport", "events")

#: How many articles per category may reach the LLM in one run.
#:
#: Sized against what each section actually produces rather than split evenly.
#: Production, 30 days: Gelir Yönetimi 15.7 stories/day, Havalimanı 3.5,
#: Etkinlik 2.7. RM gets the largest quota because it is the only section with
#: enough genuine volume for a top-8 to be a real selection rather than a list
#: of everything that arrived; the other two are sized just above their daily
#: output so a busy day is not truncated while a normal day simply does not
#: fill them.
#:
#: 8 + 5 + 5 = 18 calls per run at the absolute ceiling. See
#: `select_critical_articles` for why the real daily figure is far lower.
DEFAULT_QUOTAS: dict[str, int] = {
    "revenue_management": 8,
    "airport": 5,
    "events": 5,
}

#: How far back a run looks for candidates. 48 rather than 24 because the news
#: job runs every two hours but sources publish in bursts: a Friday-evening
#: capacity announcement that no run scored before Saturday morning should
#: still be reachable. The freshness sub-score (half-life 2 days) is what stops
#: the older end of this window from winning on age alone.
DEFAULT_WINDOW_HOURS = 48


async def _entity_codes(
    db: AsyncSession, article_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[set[str], set[str]]]:
    """(airline codes, airport codes) per article, in one query.

    One query for the batch rather than two per article: the selection pass
    walks every candidate in the window, and a per-article round trip is what
    turned an equivalent loop elsewhere in this codebase into the slowest job
    in the repo.
    """
    result: dict[uuid.UUID, tuple[set[str], set[str]]] = {
        article_id: (set(), set()) for article_id in article_ids
    }
    if not article_ids:
        return result

    for start in range(0, len(article_ids), 500):
        chunk = article_ids[start : start + 500]
        rows = await db.execute(
            select(ArticleEntity.article_id, Entity.entity_type, Entity.code)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(
                ArticleEntity.article_id.in_(chunk),
                Entity.entity_type.in_(("airline", "airport")),
                Entity.code.isnot(None),
            )
        )
        for article_id, entity_type, code in rows.all():
            if not code:
                continue
            airlines, airports = result[article_id]
            (airlines if entity_type == "airline" else airports).add(code.upper())

    return result


def signals_for(
    article: Article, enrichment: ArticleEnrichment | None, codes: tuple[set[str], set[str]]
) -> ArticleSignals:
    """Build the scorer's input from a stored article.

    `published_at or fetched_at`: an article with no publication date still has
    an age -- the moment this system first saw it -- and treating it as undated
    would hand it the neutral 0.5 freshness meant for feeds that omit dates
    entirely, on a row where a better answer is available.
    """
    source = article.source
    airlines, airports = codes
    return ArticleSignals(
        title=article.title or "",
        content=article.raw_content or "",
        published_at=article.published_at or article.fetched_at,
        source_tier=source.tier if source else None,
        trust_weight=source.trust_weight if source else None,
        region=enrichment.region if enrichment else None,
        airline_codes=frozenset(airlines),
        airport_codes=frozenset(airports),
    )


async def _candidates(
    db: AsyncSession, *, since: datetime, categories: tuple[str, ...], rescore: bool
) -> list[tuple[Article, ArticleEnrichment]]:
    """Enriched, non-duplicate articles in the window and in a printed section.

    `rescore` False (the default) also excludes anything already carrying LLM
    impact scores. That exclusion is what bounds the daily spend: without it,
    a run every two hours would re-ask the model the same question about the
    same articles twelve times a day -- the identical failure this PR fixes in
    app/pipeline/promotions.py.
    """
    query = (
        select(Article, ArticleEnrichment)
        .options(selectinload(Article.source))
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .where(
            Article.is_duplicate.is_(False),
            Article.status != BLACKLIST_STATUS,
            ArticleEnrichment.category.in_(categories),
            Article.published_at.isnot(None),
            Article.published_at >= since,
        )
    )
    if not rescore:
        query = query.where(ArticleEnrichment.rm_impact.is_(None))
    return list((await db.execute(query)).all())


def apply_quotas(
    ranked_by_category: dict[str, list], quotas: dict[str, int]
) -> dict[str, list]:
    """Take the top `quotas[category]` of each category, and nothing else.

    The no-spillover rule, isolated into one pure function so it can be tested
    without a database and so nobody can "improve" it back into a global
    top-N by accident. A category with fewer candidates than its quota yields
    exactly what it has; the unused slots are not redistributed and are not
    carried forward.
    """
    return {
        category: ranked[: quotas.get(category, 0)]
        for category, ranked in ranked_by_category.items()
    }


async def select_critical_articles(
    db: AsyncSession,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    quotas: dict[str, int] | None = None,
    limit: int | None = None,
    use_llm: bool = True,
    rescore: bool = False,
    now: datetime | None = None,
) -> dict[str, int]:
    """Score every candidate; send the per-category best to the model.

    Every candidate gets `intelligence_score` and `score_detail` written from
    the deterministic components -- that part is free and runs on all of them.
    Only the shortlist gets `rm_impact`/`demand_impact`/`capacity_impact` and a
    rescore over all eight components.

    Daily cost. The per-run ceiling is `sum(quotas)` = 18, but the run-to-run
    figure is bounded by the *eligible pool*, not by the quotas: an article
    scored once is excluded from every later run (see `_candidates`), so twelve
    runs a day cannot cost 12 x 18. The real bound is how many NEW articles a
    day land in the three printed sections, measured at ~32/day in production
    (112 of 484 in the local snapshot, ~140 articles/day live). `limit` is the
    hard ceiling on top of that for a day when something upstream misbehaves.
    """
    quotas = quotas or dict(DEFAULT_QUOTAS)
    categories = tuple(quotas)
    reference = now or datetime.now(timezone.utc)
    since = reference - timedelta(hours=window_hours)

    rows = await _candidates(db, since=since, categories=categories, rescore=rescore)
    stats = {
        "candidates": len(rows),
        "scored": 0,
        "shortlisted": 0,
        "llm_scored": 0,
        "llm_failed": 0,
    }
    if not rows:
        logger.info("critical_selection_complete", **stats)
        return stats

    codes = await _entity_codes(db, [article.id for article, _ in rows])

    # --- pass 1: deterministic, on everything --------------------------------
    scored: list[tuple[Article, ArticleEnrichment, NewsScore, dict[str, float]]] = []
    for article, enrichment in rows:
        components = deterministic_components(
            signals_for(article, enrichment, codes[article.id]), now=reference
        )
        result = combine_score(components)
        enrichment.intelligence_score = result.intelligence_score
        enrichment.score_detail = result.as_detail()
        scored.append((article, enrichment, result, components))
        stats["scored"] += 1

    # --- pass 2: the per-category best, to the model -------------------------
    by_category: dict[str, list] = {category: [] for category in categories}
    for entry in scored:
        by_category.setdefault(entry[1].category, []).append(entry)
    for category in by_category:
        by_category[category].sort(key=lambda e: e[2].intelligence_score, reverse=True)

    shortlist: list = []
    for category, chosen in apply_quotas(by_category, quotas).items():
        shortlist.extend(chosen)
    # Highest-scoring first across the whole shortlist, so a `limit` that cuts
    # the list short drops the least important articles rather than whichever
    # category happened to be iterated last.
    shortlist.sort(key=lambda e: e[2].intelligence_score, reverse=True)
    if limit is not None:
        shortlist = shortlist[:limit]
    stats["shortlisted"] = len(shortlist)

    if use_llm:
        from app.llm.classify import score_news_impact

        for article, enrichment, _, components in shortlist:
            outcome = await score_news_impact(
                article.title or "", article.raw_content or "", enrichment.category
            )
            if not outcome.is_classified or outcome.payload is None:
                # The article keeps its deterministic score and its three
                # columns stay NULL -- "nobody got an answer" recorded as
                # itself, not as three zeroes.
                stats["llm_failed"] += 1
                logger.info(
                    "news_impact_unavailable",
                    article_id=str(article.id),
                    reason=outcome.reason,
                )
                continue

            impact = outcome.payload
            enrichment.rm_impact = impact.rm_impact
            enrichment.demand_impact = impact.demand_impact
            enrichment.capacity_impact = impact.capacity_impact
            rescored = combine_score(
                {
                    **components,
                    **ImpactScores(
                        rm_impact=impact.rm_impact,
                        demand_impact=impact.demand_impact,
                        capacity_impact=impact.capacity_impact,
                    ).as_components(),
                }
            )
            enrichment.intelligence_score = rescored.intelligence_score
            detail = rescored.as_detail()
            if impact.rationale_tr:
                detail["rationale_tr"] = impact.rationale_tr
            enrichment.score_detail = detail
            stats["llm_scored"] += 1

    await db.commit()
    logger.info("critical_selection_complete", **stats)
    return stats
