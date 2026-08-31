"""Retire articles already in the archive that come from a blacklisted domain.

The ingest-time filter in app/ingest/rss.py only protects the future. Reddit
threads that arrived before it existed are still rows in `articles`, still
enriched, and still served -- so the ban is not real until they are gone too.

"Gone" here means retired, not deleted, matching how every other rejection in
this codebase works (rejected_language, rejected_gate): the row keeps its
foreign keys and its history, its status says why it is not in the paper, and
the count stays auditable afterwards. Deleting would also break
`duplicate_of_id` chains pointing at a purged canonical article.
"""
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.ingest.blacklist import BLACKLIST_STATUS, BLACKLISTED_DOMAINS, blacklisted_domain
from app.models.article import Article

logger = get_logger(__name__)


def _candidate_filter():
    """A cheap SQL pre-filter that over-selects on purpose.

    Substring matching in SQL would ban notreddit.com; host matching in SQL
    would mean re-implementing app/ingest/blacklist.py in SQLAlchemy and having
    two rules that can drift. So SQL narrows the scan to rows that merely
    *mention* a blacklisted domain anywhere in the URL, and the real,
    already-tested matcher makes the decision in Python. The over-selection is
    bounded: a handful of rows out of the archive.
    """
    return or_(*(Article.url.ilike(f"%{domain}%") for domain in sorted(BLACKLISTED_DOMAINS)))


async def count_blacklisted_articles(db: AsyncSession) -> dict[str, int]:
    """Read-only: how many rows the purge would touch, without touching them.

    Split into "would be retired" and "already retired" so re-running the
    report after a purge reads as 0 new work rather than as the purge having
    silently failed.
    """
    result = await db.execute(select(Article.id, Article.url, Article.status).where(_candidate_filter()))
    pending = 0
    already = 0
    for _, url, status in result.all():
        if blacklisted_domain(url) is None:
            continue
        if status == BLACKLIST_STATUS:
            already += 1
        else:
            pending += 1
    return {"pending": pending, "already_purged": already}


async def purge_blacklisted_articles(db: AsyncSession) -> dict[str, int]:
    """Mark every blacklisted article rejected. Idempotent.

    A second run finds the same rows, sees they already carry the blacklist
    status, and changes nothing -- which is what makes this safe to wire into a
    dispatchable workflow anyone can press twice.
    """
    result = await db.execute(select(Article).where(_candidate_filter()))
    scanned = 0
    purged = 0
    already = 0
    by_domain: dict[str, int] = {}
    for article in result.scalars().all():
        domain = blacklisted_domain(article.url)
        if domain is None:
            # An innocent URL that merely contains the string, e.g. an article
            # *about* Reddit hosted somewhere else. The pre-filter is allowed
            # to catch these; the matcher is what must not.
            continue
        scanned += 1
        if article.status == BLACKLIST_STATUS:
            already += 1
            continue
        article.status = BLACKLIST_STATUS
        article.rejection_reason = f"blacklist:{domain}"[:60]
        purged += 1
        by_domain[domain] = by_domain.get(domain, 0) + 1

    await db.commit()
    logger.info(
        "blacklist_purge_complete", scanned=scanned, purged=purged, already_purged=already
    )
    return {
        "scanned": scanned,
        "purged": purged,
        "already_purged": already,
        "by_domain": by_domain,
    }


async def total_article_count(db: AsyncSession) -> int:
    """Denominator for the report -- "12 of 4,300" is a fact, "12" is a number."""
    result = await db.execute(select(func.count(Article.id)))
    return int(result.scalar_one())
