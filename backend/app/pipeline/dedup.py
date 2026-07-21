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
from app.pipeline.headlines import strip_publisher_suffix
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


# --- second pass: the same story told in two languages -------------------

# MinHash+LSH compares title AND body, so two outlets covering one story with
# different wording never become candidates -- and when the originals are in
# different languages the titles barely overlap at all. Measured on production:
#
#   "Arajet incorpora nuevos servicios adicionales..."   (es)
#   "Arajet introduces new ancillary services..."        (en)
#      original-title similarity 0.10  -> missed
#      Turkish-translation similarity 0.62 -> obvious
#
# Translation normalises vocabulary, so the Turkish headlines the site actually
# displays are the better signal. This pass runs after enrichment, compares
# only within same-entity/same-day groups (so the O(n^2) stays tiny), and takes
# the stronger of the two languages.
CROSS_LANGUAGE_MIN = 0.30
SECOND_PASS_DAYS = 3


# Two stories can share almost every word and still be different events.
# Caught in testing: Riyadh Air "firms up order for six more Airbus A350-1000s"
# and "firms up order for 28 Boeing 787s" -- same airline, same show, same
# phrasing, two separate orders. Model designations and manufacturer names are
# what tells them apart, so a clash in either blocks the merge.
_MODEL_TOKEN = re.compile(r"\b[a-z]?\d[\w-]*\b")
_MANUFACTURERS = ("airbus", "boeing", "embraer", "bombardier", "atr", "comac")
# Acronyms carry the identity of the counterparty in supplier stories, and they
# survive translation untouched. Caught in testing: "Turkish Airlines Signs
# Multi-Year Agreement With CAE" was merged into "...Signs Agreement with
# HAVELSAN for 12 Flight Simulators" -- two different vendors, two deals,
# titles otherwise nearly identical.
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")
# Acronyms that describe the subject rather than name a party, so a clash in
# them says nothing about whether two stories are the same.
_GENERIC_ACRONYMS = frozenset({
    "MRO", "CEO", "COO", "CFO", "AI", "IT", "US", "USA", "UK", "EU", "UAE",
    "NDC", "GDS", "IATA", "ICAO", "FAA", "EASA", "SAF", "ESG", "VIP", "FIA",
})


def _named_parties(title: str) -> set[str]:
    """Acronyms that identify who a story is about, publisher credit removed."""
    head = strip_publisher_suffix(title)
    return {a for a in _ACRONYM.findall(head) if a not in _GENERIC_ACRONYMS}


def _mentions_conflict(title_a: str, title_b: str) -> bool:
    """True when the titles name different aircraft, makers or counterparties."""
    norm_a, norm_b = normalize_text(title_a), normalize_text(title_b)

    makers_a = {m for m in _MANUFACTURERS if m in norm_a}
    makers_b = {m for m in _MANUFACTURERS if m in norm_b}
    if makers_a and makers_b and not (makers_a & makers_b):
        return True

    models_a = set(_MODEL_TOKEN.findall(norm_a))
    models_b = set(_MODEL_TOKEN.findall(norm_b))
    if models_a and models_b and not (models_a & models_b):
        return True

    parties_a, parties_b = _named_parties(title_a), _named_parties(title_b)
    if parties_a and parties_b and not (parties_a & parties_b):
        return True
    return False


def _best_title_similarity(
    title_a: str, title_b: str, tr_a: str | None, tr_b: str | None
) -> float:
    """How alike two stories read, in whichever language shows it more clearly."""
    original = _title_jaccard(title_a, title_b)
    translated = _title_jaccard(tr_a or "", tr_b or "") if tr_a and tr_b else 0.0
    return max(original, translated)


async def deduplicate_translated_articles(db: AsyncSession) -> int:
    """Catch near-duplicates the first pass could not see.

    Runs after enrichment because it needs the Turkish headlines. Only articles
    that share an entity and a publication day are compared, which keeps this
    to a handful of comparisons per group while covering the case that actually
    reaches the reader: the same story listed twice in the newspaper.
    """
    from app.models.entity import ArticleEntity

    cutoff = datetime.now(timezone.utc) - timedelta(days=SECOND_PASS_DAYS)
    rows = (
        await db.execute(
            select(Article, ArticleEnrichment.headline_tr, ArticleEntity.entity_id)
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            .join(ArticleEntity, ArticleEntity.article_id == Article.id)
            .where(
                Article.is_duplicate.is_(False),
                Article.status == "enriched",
                Article.published_at >= cutoff,
            )
        )
    ).all()

    # (entity, day) -> [(article, turkish headline)]
    groups: dict[tuple, list] = {}
    seen_pairs: set = set()
    for article, headline_tr, entity_id in rows:
        if (article.id, entity_id) in seen_pairs:
            continue
        seen_pairs.add((article.id, entity_id))
        day = (article.published_at or article.fetched_at).date()
        groups.setdefault((entity_id, day), []).append((article, headline_tr))

    marked = 0
    already: set = set()
    gained_duplicates: set = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        # Oldest first: the earliest version of a story stays canonical.
        members.sort(key=lambda m: m[0].published_at or m[0].fetched_at)
        for i, (canonical, canonical_tr) in enumerate(members):
            if canonical.id in already:
                continue
            for other, other_tr in members[i + 1 :]:
                if other.id in already or other.id == canonical.id:
                    continue
                if _differs_only_by_number(canonical.title, other.title):
                    continue  # weekly templated reports, not duplicates
                if _mentions_conflict(canonical.title, other.title):
                    continue  # different aircraft or different manufacturer
                similarity = _best_title_similarity(
                    canonical.title, other.title, canonical_tr, other_tr
                )
                if similarity >= CROSS_LANGUAGE_MIN:
                    other.is_duplicate = True
                    other.duplicate_of_id = canonical.id
                    other.status = "duplicate"
                    already.add(other.id)
                    gained_duplicates.add(canonical.id)
                    marked += 1

    # The canonical story is now corroborated by one more source; its
    # confidence and importance were scored before this duplicate arrived.
    await _refresh_corroboration(db, gained_duplicates)
    await db.commit()
    logger.info("second_pass_dedup_complete", groups=len(groups), marked=marked)
    return marked
