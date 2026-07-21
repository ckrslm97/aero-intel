"""Cross-source near-duplicate detection via MinHash + LSH.

Canonical articles (status "deduped"/"enriched") from a recent lookback window
are re-hashed into an in-memory LSH index each run and compared against
incoming "new" articles -- cheap at this scale and avoids persisting MinHash
sketches. A match makes the incoming article a duplicate pointing at the
canonical one; no match promotes it to canonical itself.

A content-only Jaccard match isn't enough: recurring templated reports (a
weekly "EUROCONTROL ... Week 25" vs "... Week 27") share so much boilerplate
that their bodies alone clear the threshold despite covering different
periods. Every LSH candidate is re-checked against the title: titles must be
reasonably similar AND must not differ *only* by an embedded number (a week/
issue/year), which signals "same template, different edition" rather than
"same story, different source".
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from datasketch import MinHash, MinHashLSH
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.article import Article, ArticleEnrichment
from app.pipeline.enrich import _importance_score
from app.pipeline.hashing import normalize_text, shingles
from app.pipeline.verify import compute_confidence

logger = get_logger(__name__)

NUM_PERM = 128
JACCARD_THRESHOLD = 0.5
LOOKBACK_DAYS = 3
TITLE_JACCARD_MIN = 0.25

_NUMBER_RE = re.compile(r"\d+")


def _minhash_for(title: str, content: str) -> MinHash:
    mh = MinHash(num_perm=NUM_PERM)
    for shingle in shingles(f"{title} {content}"):
        mh.update(shingle.encode("utf-8"))
    return mh


def _title_jaccard(title_a: str, title_b: str) -> float:
    words_a = set(normalize_text(title_a).split())
    words_b = set(normalize_text(title_b).split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _differs_only_by_number(title_a: str, title_b: str) -> bool:
    numbers_a = _NUMBER_RE.findall(title_a)
    numbers_b = _NUMBER_RE.findall(title_b)
    if numbers_a == numbers_b:
        return False
    stripped_a = normalize_text(_NUMBER_RE.sub(" ", title_a))
    stripped_b = normalize_text(_NUMBER_RE.sub(" ", title_b))
    return stripped_a == stripped_b


def _is_genuine_duplicate(title_a: str, title_b: str) -> bool:
    if _title_jaccard(title_a, title_b) < TITLE_JACCARD_MIN:
        return False
    return not _differs_only_by_number(title_a, title_b)


async def deduplicate_new_articles(db: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    canonical_result = await db.execute(
        select(Article).where(
            Article.status.in_(["deduped", "enriched"]),
            Article.is_duplicate.is_(False),
            Article.fetched_at >= cutoff,
        )
    )
    canonical_articles = list(canonical_result.scalars().all())

    lsh = MinHashLSH(threshold=JACCARD_THRESHOLD, num_perm=NUM_PERM)
    titles_by_id: dict[str, str] = {}
    for existing in canonical_articles:
        lsh.insert(str(existing.id), _minhash_for(existing.title, existing.raw_content))
        titles_by_id[str(existing.id)] = existing.title

    new_result = await db.execute(select(Article).where(Article.status == "new"))
    new_articles = list(new_result.scalars().all())

    duplicates = 0
    refreshed: set[uuid.UUID] = set()
    for article in new_articles:
        mh = _minhash_for(article.title, article.raw_content)
        genuine_match = next(
            (m for m in lsh.query(mh) if _is_genuine_duplicate(article.title, titles_by_id[m])),
            None,
        )
        if genuine_match:
            article.is_duplicate = True
            article.duplicate_of_id = uuid.UUID(genuine_match)
            article.status = "duplicate"
            duplicates += 1
            # The canonical article's corroboration count was computed when it
            # was enriched, which is usually BEFORE this duplicate arrived --
            # so a story confirmed by five outlets kept the score of a story
            # confirmed by one, and the front page ranked on stale numbers.
            refreshed.add(article.duplicate_of_id)
        else:
            article.status = "deduped"
            lsh.insert(str(article.id), mh)
            titles_by_id[str(article.id)] = article.title

    rescored = await _refresh_corroboration(db, refreshed)

    await db.commit()
    logger.info(
        "dedup_run_complete",
        rescored=rescored,
        processed=len(new_articles),
        duplicates=duplicates,
        canonical_pool=len(canonical_articles),
    )
    return len(new_articles)


async def _refresh_corroboration(db: AsyncSession, canonical_ids: set[uuid.UUID]) -> int:
    """Recompute confidence for canonical articles that just gained a duplicate.

    Corroboration is the strongest ranking signal the system has, and it was
    only ever measured once, at enrichment time. Because enrichment can lag
    ingest by hours, most corroboration arrived after the snapshot and was
    never counted.
    """
    if not canonical_ids:
        return 0

    rows = (
        await db.execute(
            select(Article, ArticleEnrichment)
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            .options(selectinload(Article.source))
            .where(Article.id.in_(canonical_ids))
        )
    ).all()

    for article, enrichment in rows:
        count, confidence = await compute_confidence(db, article)
        enrichment.corroborating_source_count = count
        enrichment.confidence_score = confidence
        enrichment.importance_score = _importance_score(confidence, count)
    return len(rows)
