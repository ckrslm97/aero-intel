"""Evidence-backed action recommendations ("Öneriler") derived from the data
the pipeline already stores.

The rule of this module: **no recommendation without evidence**. Every item
returned here is a counting statement about rows in Postgres (articles and
their enrichment, entity links, TK reviews, the events calendar) and carries
the very rows it was derived from in `evidence`, so a reader can click through
and check the claim. Nothing is predicted, nothing is inferred by an LLM --
this is deliberately deterministic, both because a forecast we cannot source
would be dishonest and because the Groq quota is spent on the daily digests.

Thresholds are named constants, never inline numbers: each one encodes an
editorial judgement about what counts as a *pattern* rather than noise, and
that judgement has to be readable and tunable in one place.

Shape of one recommendation::

    {id, title, rationale, severity, category, region, airline_code,
     evidence: [{headline, url, source_name, published_at}],
     metric: {label, value, previous} | None}

`title` and `rationale` are Turkish and action-shaped; `evidence` is never
empty (the only sourceless-by-nature item is the calendar event, whose
evidence is the calendar entry itself).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.core.tr_dates import format_date_range
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.event import AviationEvent
from app.models.tk_review import REVIEW_THEMES, TkReview
from app.services.insights_service import airline_momentum

# --- shared limits -------------------------------------------------------

# Evidence is a proof, not a reading list: five links are enough to show the
# pattern is real, and keep the payload small enough to cache.
EVIDENCE_LIMIT = 5
# Hard ceiling on rows any single detector pulls out of Postgres. A quiet week
# is far below this; a flood of ingestion must not turn the page into a scan.
MAX_SCAN_ARTICLES = 400
# The page is a to-do list, not an archive -- past this many items nobody acts.
MAX_RECOMMENDATIONS = 20

# TK is the home carrier, not a rival: "our own campaigns intensified" is not
# a competitive alert, so it is excluded from the rival detectors unless the
# reader explicitly filters for TK.
HOME_AIRLINE_CODE = "TK"

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# --- 1) rival campaign clustering ---------------------------------------

PROMO_CATEGORY = "revenue_management"
PROMO_SUBCATEGORIES = ("promotion", "pricing")
# Two price/campaign stories about the same carrier inside the window is the
# smallest count that can't be a single announcement echoed once -- one story
# is news, two is a move.
PROMO_MIN_ARTICLES = 2
# Three or more is a campaign wave: it outranks everything else on the page.
PROMO_HIGH_ARTICLES = 3

# --- 2) regional network movement ---------------------------------------

ROUTE_CATEGORY = "network"
ROUTE_SUBCATEGORY = "new_route"
# Under three announcements a region's "increase" is one or two extra stories,
# which the previous window would just as easily have produced by chance.
ROUTE_SURGE_MIN_CURRENT = 3
# "Belirgin artış" = at least doubled. Anything gentler is not worth an alert.
ROUTE_SURGE_RATIO = 2.0
ROUTE_SURGE_HIGH_CURRENT = 6

# --- 3) airline momentum -------------------------------------------------

# How many movers airline_momentum() is asked for before filtering.
MOMENTUM_SCAN_LIMIT = 12
# A swing of three articles is roughly one editorial day of coverage: below
# that, week-to-week noise dominates.
MOMENTUM_MIN_DELTA = 3
# ... and it must be a swing off a real base, not 0 -> 3 for a carrier the
# archive barely knows.
MOMENTUM_MIN_MENTIONS = 3
MOMENTUM_HIGH_DELTA = 5
# At most this many momentum items, so one loud week can't fill the page.
MOMENTUM_MAX_RECS = 3

# --- 4) negative sentiment clustering ------------------------------------

# A share needs a denominator: under five articles one bad story reads as 50%.
NEGATIVE_MIN_ARTICLES = 5
# Half the coverage negative is already far above the archive's baseline.
NEGATIVE_SHARE_MIN = 0.5
NEGATIVE_SHARE_HIGH = 0.7
# Safety news is negative by definition (crashes, incidents, groundings), so a
# "negative sentiment" alert there reports the base rate, not a change.
NEGATIVE_EXEMPT_CATEGORIES = frozenset({"safety"})

# --- 5) TK review themes -------------------------------------------------

# Reviews are curated in occasional passes, not ingested hourly, so a 7-day
# news window is far too short to hold any: the theme detector widens the
# window by this factor on both sides of the comparison.
TK_REVIEW_WINDOW_MULTIPLIER = 4
TK_THEME_MIN_CURRENT = 3
TK_THEME_RATIO = 1.5
TK_THEME_NEGATIVE_HIGH_SHARE = 0.6
# Review excerpts are quotes, not headlines -- keep the evidence line short.
TK_EXCERPT_CHARS = 160

# --- 6) upcoming events --------------------------------------------------

# Two weeks is the planning horizon that still leaves room to act on a fair or
# a holiday peak; beyond that the calendar page is the right place to look.
EVENT_HORIZON_DAYS = 14
# Inside a week it stops being a heads-up and becomes this week's work.
EVENT_IMMINENT_DAYS = 7
# Types that move demand or the commercial calendar. Sports/festival entries
# are seeded for context, not for revenue-management action.
EVENT_HIGH_IMPACT_TYPES = ("airshow", "conference", "holiday")
EVENT_MAX_RECS = 4

# Turkish display labels. Mirrors frontend/src/lib/nav.ts `worldRegions` and
# frontend/src/lib/taxonomy.ts `CATEGORIES` -- the titles are written here, so
# the labels have to live here too.
REGION_LABELS_TR: dict[str, str] = {
    "europe": "Avrupa",
    "middle-east": "Orta Doğu",
    "africa": "Afrika",
    "north-america": "Kuzey Amerika",
    "south-america": "Güney Amerika",
    "central-america": "Orta Amerika",
    "asia": "Asya",
    "southeast-asia": "Güneydoğu Asya",
    "oceania": "Okyanusya",
}

CATEGORY_LABELS_TR: dict[str, str] = {
    "revenue_management": "Gelir Yönetimi",
    "fleet": "Filo",
    "network": "Ağ & Rota",
    "finance": "Finans",
    "safety": "Emniyet",
    "regulatory": "Regülasyon",
    "sustainability": "Sürdürülebilirlik",
    "airport": "Havalimanı",
    "labor": "İşgücü",
    "events": "Etkinlik",
    "general": "Genel",
}


def _region_label(slug: str | None) -> str:
    return REGION_LABELS_TR.get(slug or "", slug or "Genel")


def _category_label(slug: str | None) -> str:
    return CATEGORY_LABELS_TR.get(slug or "", slug or "Genel")


def _airline_key_expr():
    """The carrier's stable key: IATA code when we have one, name otherwise --
    the same rule insights_service.airline_momentum() uses, so filters and
    momentum items agree on what "EK" means."""
    return func.coalesce(Entity.code, Entity.name)


def _article_evidence(article: Article, enrichment: ArticleEnrichment) -> dict:
    return {
        "headline": enrichment.headline_tr or enrichment.headline or article.title,
        "url": article.url,
        "source_name": article.source.name if article.source else "",
        "published_at": article.published_at.isoformat() if article.published_at else None,
    }


async def _competitor_promotions(
    db: AsyncSession, *, days: int, region: str | None, airline: str | None
) -> list[dict]:
    """A rival stacking price/campaign announcements inside the window."""
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    previous_start = now - timedelta(days=2 * days)

    query = (
        select(Article, ArticleEnrichment, Entity.code, Entity.name)
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .join(ArticleEntity, ArticleEntity.article_id == Article.id)
        .join(Entity, Entity.id == ArticleEntity.entity_id)
        # Only headline+link are rendered; the scraped bodies must stay in Postgres.
        .options(selectinload(Article.source), defer(Article.raw_content))
        .where(
            Article.is_duplicate.is_(False),
            Article.published_at >= previous_start,
            Entity.entity_type == "airline",
            ArticleEnrichment.category == PROMO_CATEGORY,
            ArticleEnrichment.subcategory.in_(PROMO_SUBCATEGORIES),
        )
        .order_by(Article.published_at.desc().nulls_last())
        .limit(MAX_SCAN_ARTICLES)
    )
    if region:
        query = query.where(ArticleEnrichment.region == region)
    if airline:
        query = query.where(func.upper(_airline_key_expr()) == airline.upper())

    buckets: dict[str, dict] = {}
    for article, enrichment, code, name in (await db.execute(query)).all():
        key = code or name
        if key.upper() == HOME_AIRLINE_CODE and not airline:
            continue  # home carrier: not a competitive signal
        bucket = buckets.setdefault(key, {"name": name, "current": [], "previous": 0})
        if article.published_at >= current_start:
            bucket["current"].append(_article_evidence(article, enrichment))
        else:
            bucket["previous"] += 1

    recommendations = []
    for key, bucket in buckets.items():
        count = len(bucket["current"])
        if count < PROMO_MIN_ARTICLES:
            continue
        name = bucket["name"]
        recommendations.append(
            {
                "id": f"promo-{key.lower()}",
                "title": f"{name}: son {days} günde {count} kampanya/fiyat hamlesi",
                "rationale": (
                    f"{name} bu dönemde {count} kampanya veya fiyatlandırma haberiyle "
                    f"öne çıktı (önceki {days} günde {bucket['previous']}). "
                    "Ortak pazarlarda fiyat karşılaştırması yapın."
                ),
                "severity": "high" if count >= PROMO_HIGH_ARTICLES else "medium",
                "category": PROMO_CATEGORY,
                "region": region,
                "airline_code": key,
                "evidence": bucket["current"][:EVIDENCE_LIMIT],
                "metric": {
                    "label": "Kampanya/fiyat haberi",
                    "value": count,
                    "previous": bucket["previous"],
                },
            }
        )
    return recommendations


async def _regional_route_surge(
    db: AsyncSession, *, days: int, region: str | None, airline: str | None
) -> list[dict]:
    """New-route announcements in a region clearly outpacing the window before."""
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    previous_start = now - timedelta(days=2 * days)

    query = (
        select(Article, ArticleEnrichment)
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .options(selectinload(Article.source), defer(Article.raw_content))
        .where(
            Article.is_duplicate.is_(False),
            Article.published_at >= previous_start,
            ArticleEnrichment.category == ROUTE_CATEGORY,
            ArticleEnrichment.subcategory == ROUTE_SUBCATEGORY,
        )
        .order_by(Article.published_at.desc().nulls_last())
        .limit(MAX_SCAN_ARTICLES)
    )
    if region:
        query = query.where(ArticleEnrichment.region == region)
    if airline:
        query = (
            query.join(ArticleEntity, ArticleEntity.article_id == Article.id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(
                Entity.entity_type == "airline",
                func.upper(_airline_key_expr()) == airline.upper(),
            )
        )

    buckets: dict[str, dict] = {}
    for article, enrichment in (await db.execute(query)).all():
        # A region-less announcement can't support a *regional* claim.
        if not enrichment.region:
            continue
        bucket = buckets.setdefault(enrichment.region, {"current": [], "previous": 0})
        if article.published_at >= current_start:
            bucket["current"].append(_article_evidence(article, enrichment))
        else:
            bucket["previous"] += 1

    recommendations = []
    for region_slug, bucket in buckets.items():
        current = len(bucket["current"])
        previous = bucket["previous"]
        if current < ROUTE_SURGE_MIN_CURRENT:
            continue
        if previous and current < previous * ROUTE_SURGE_RATIO:
            continue
        label = _region_label(region_slug)
        recommendations.append(
            {
                "id": f"route-surge-{region_slug}",
                "title": f"{label}: yeni hat duyuruları {previous} → {current}",
                "rationale": (
                    f"Son {days} günde {label} bölgesinde {current} yeni hat duyurusu "
                    f"yayımlandı, önceki {days} günde {previous}. Bölgedeki kapasite ve "
                    "fiyat konumlandırmanızı gözden geçirin."
                ),
                "severity": (
                    "high" if current >= ROUTE_SURGE_HIGH_CURRENT else "medium"
                ),
                "category": ROUTE_CATEGORY,
                "region": region_slug,
                "airline_code": airline.upper() if airline else None,
                "evidence": bucket["current"][:EVIDENCE_LIMIT],
                "metric": {
                    "label": "Yeni hat duyurusu",
                    "value": current,
                    "previous": previous,
                },
            }
        )
    return recommendations


async def _airline_momentum_recs(
    db: AsyncSession, *, days: int, region: str | None, airline: str | None
) -> list[dict]:
    """Carriers whose coverage volume moved sharply, straight off the existing
    insights aggregate (insights_service.airline_momentum)."""
    if region:
        # Momentum is computed over entity links, which carry no region; a
        # region-filtered momentum claim would be unsupported by the data.
        return []

    movers = await airline_momentum(db, window_days=days, limit=MOMENTUM_SCAN_LIMIT)
    selected = [
        m
        for m in movers
        if abs(m["delta"]) >= MOMENTUM_MIN_DELTA
        and max(m["current"], m["previous"]) >= MOMENTUM_MIN_MENTIONS
        and (not airline or m["code"].upper() == airline.upper())
    ][:MOMENTUM_MAX_RECS]
    if not selected:
        return []

    keys = [m["code"] for m in selected]
    since = datetime.now(timezone.utc) - timedelta(days=2 * days)
    # Evidence spans both windows on purpose: a carrier that fell out of the
    # news has little or nothing in the current window, and the honest citation
    # for "coverage dropped" is the coverage it used to have.
    rows = (
        await db.execute(
            select(Article, ArticleEnrichment, _airline_key_expr())
            .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
            .join(ArticleEntity, ArticleEntity.article_id == Article.id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .options(selectinload(Article.source), defer(Article.raw_content))
            .where(
                Article.is_duplicate.is_(False),
                Article.published_at >= since,
                Entity.entity_type == "airline",
                _airline_key_expr().in_(keys),
            )
            .order_by(Article.published_at.desc().nulls_last())
            .limit(MAX_SCAN_ARTICLES)
        )
    ).all()

    evidence_by_key: dict[str, list[dict]] = {}
    for article, enrichment, key in rows:
        evidence_by_key.setdefault(key, []).append(_article_evidence(article, enrichment))

    recommendations = []
    for mover in selected:
        evidence = evidence_by_key.get(mover["code"], [])[:EVIDENCE_LIMIT]
        if not evidence:
            continue  # no citable article -> no recommendation
        rising = mover["delta"] > 0
        name = mover["name"]
        recommendations.append(
            {
                "id": f"momentum-{mover['code'].lower()}",
                "title": (
                    f"{name} gündemi hızlanıyor: {mover['previous']} → {mover['current']} haber"
                    if rising
                    else f"{name} gündemden çekiliyor: {mover['previous']} → {mover['current']} haber"
                ),
                "rationale": (
                    f"Son {days} günde {name} hakkındaki haber sayısı "
                    f"{abs(mover['delta'])} arttı. Taşıyıcının son hamlelerini inceleyin."
                    if rising
                    else f"Son {days} günde {name} hakkındaki haber sayısı "
                    f"{abs(mover['delta'])} azaldı. Önceki dönemin gündemi kapanmış olabilir."
                ),
                "severity": (
                    "high" if abs(mover["delta"]) >= MOMENTUM_HIGH_DELTA else "medium"
                ),
                # Momentum is volume across every category -- claiming one
                # would be inventing a focus the number doesn't have.
                "category": None,
                "region": None,
                "airline_code": mover["code"],
                "evidence": evidence,
                "metric": {
                    "label": "Haber sayısı",
                    "value": mover["current"],
                    "previous": mover["previous"],
                },
            }
        )
    return recommendations


async def _negative_sentiment_clusters(
    db: AsyncSession, *, days: int, region: str | None, airline: str | None
) -> list[dict]:
    """Categories where the window's coverage skews negative."""
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    previous_start = now - timedelta(days=2 * days)
    is_current = (Article.published_at >= current_start).label("is_current")

    query = (
        select(ArticleEnrichment.category, ArticleEnrichment.sentiment, is_current, func.count())
        .join(Article, Article.id == ArticleEnrichment.article_id)
        .where(Article.is_duplicate.is_(False), Article.published_at >= previous_start)
        .group_by(ArticleEnrichment.category, ArticleEnrichment.sentiment, is_current)
    )
    if region:
        query = query.where(ArticleEnrichment.region == region)
    if airline:
        query = (
            query.join(ArticleEntity, ArticleEntity.article_id == Article.id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(
                Entity.entity_type == "airline",
                func.upper(_airline_key_expr()) == airline.upper(),
            )
        )

    stats: dict[str, dict] = {}
    for category, sentiment, current_window, count in (await db.execute(query)).all():
        bucket = stats.setdefault(
            category, {"total": 0, "negative": 0, "prev_total": 0, "prev_negative": 0}
        )
        if current_window:
            bucket["total"] += count
            if sentiment == "negative":
                bucket["negative"] += count
        else:
            bucket["prev_total"] += count
            if sentiment == "negative":
                bucket["prev_negative"] += count

    hits = {
        category: bucket
        for category, bucket in stats.items()
        if category not in NEGATIVE_EXEMPT_CATEGORIES
        and bucket["total"] >= NEGATIVE_MIN_ARTICLES
        and bucket["negative"] / bucket["total"] >= NEGATIVE_SHARE_MIN
    }
    if not hits:
        return []

    evidence_query = (
        select(Article, ArticleEnrichment)
        .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
        .options(selectinload(Article.source), defer(Article.raw_content))
        .where(
            Article.is_duplicate.is_(False),
            Article.published_at >= current_start,
            ArticleEnrichment.sentiment == "negative",
            ArticleEnrichment.category.in_(list(hits)),
        )
        .order_by(
            ArticleEnrichment.importance_score.desc(),
            Article.published_at.desc().nulls_last(),
        )
        .limit(MAX_SCAN_ARTICLES)
    )
    if region:
        evidence_query = evidence_query.where(ArticleEnrichment.region == region)
    if airline:
        evidence_query = (
            evidence_query.join(ArticleEntity, ArticleEntity.article_id == Article.id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(
                Entity.entity_type == "airline",
                func.upper(_airline_key_expr()) == airline.upper(),
            )
        )

    evidence_by_category: dict[str, list[dict]] = {}
    for article, enrichment in (await db.execute(evidence_query)).all():
        evidence_by_category.setdefault(enrichment.category, []).append(
            _article_evidence(article, enrichment)
        )

    recommendations = []
    for category, bucket in hits.items():
        evidence = evidence_by_category.get(category, [])[:EVIDENCE_LIMIT]
        if not evidence:
            continue
        share = round(bucket["negative"] / bucket["total"] * 100)
        previous_share = (
            round(bucket["prev_negative"] / bucket["prev_total"] * 100)
            if bucket["prev_total"]
            else None
        )
        label = _category_label(category)
        recommendations.append(
            {
                "id": f"negative-{category}",
                "title": f"{label}: haberlerin %{share}'i olumsuz",
                "rationale": (
                    f"Son {days} günde {label} başlığındaki {bucket['total']} haberin "
                    f"{bucket['negative']} tanesi olumsuz tonda. Bu başlıkta risk "
                    "birikiyor olabilir; kaynak haberleri inceleyin."
                ),
                "severity": (
                    "high"
                    if bucket["negative"] / bucket["total"] >= NEGATIVE_SHARE_HIGH
                    else "medium"
                ),
                "category": category,
                "region": region,
                "airline_code": airline.upper() if airline else None,
                "evidence": evidence,
                "metric": {
                    "label": "Olumsuz haber oranı (%)",
                    "value": share,
                    "previous": previous_share,
                },
            }
        )
    return recommendations


async def _tk_review_themes(
    db: AsyncSession, *, days: int, region: str | None, airline: str | None
) -> list[dict]:
    """A theme rising in the curated TK passenger reviews."""
    if region:
        return []  # reviews carry no region dimension
    if airline and airline.upper() != HOME_AIRLINE_CODE:
        return []

    window = days * TK_REVIEW_WINDOW_MULTIPLIER
    today = datetime.now(timezone.utc).date()
    current_start = today - timedelta(days=window)
    previous_start = today - timedelta(days=2 * window)

    reviews = (
        (
            await db.execute(
                select(TkReview)
                .where(TkReview.review_date >= previous_start)
                .order_by(TkReview.review_date.desc())
            )
        )
        .scalars()
        .all()
    )

    buckets: dict[str, dict] = {}
    for review in reviews:
        for slug in review.themes or []:
            if slug not in REVIEW_THEMES:
                continue  # unknown tag in seed data -- skip rather than crash
            bucket = buckets.setdefault(
                slug, {"current": [], "negative": 0, "previous": 0}
            )
            if review.review_date >= current_start:
                excerpt = review.excerpt_tr or review.excerpt
                bucket["current"].append(
                    {
                        "headline": (
                            excerpt
                            if len(excerpt) <= TK_EXCERPT_CHARS
                            else excerpt[:TK_EXCERPT_CHARS].rstrip() + "…"
                        ),
                        "url": review.url,
                        "source_name": review.source_name,
                        "published_at": review.review_date.isoformat(),
                    }
                )
                if review.sentiment == "negative":
                    bucket["negative"] += 1
            else:
                bucket["previous"] += 1

    recommendations = []
    for slug, bucket in buckets.items():
        current = len(bucket["current"])
        previous = bucket["previous"]
        if current < TK_THEME_MIN_CURRENT:
            continue
        if previous and current < previous * TK_THEME_RATIO:
            continue
        label = REVIEW_THEMES[slug]
        negative_share = bucket["negative"] / current
        recommendations.append(
            {
                "id": f"tk-theme-{slug}",
                "title": f"Yolcu yorumlarında “{label}” teması artıyor: {previous} → {current}",
                "rationale": (
                    f"Son {window} günde {label} temalı {current} yorum toplandı "
                    f"(önceki {window} günde {previous}); {bucket['negative']} tanesi "
                    "olumsuz. Yorumların kendisini okuyun."
                ),
                "severity": (
                    "high" if negative_share >= TK_THEME_NEGATIVE_HIGH_SHARE else "medium"
                ),
                # Reviews live outside the article taxonomy -- no category slug
                # would be truthful here.
                "category": None,
                "region": None,
                "airline_code": HOME_AIRLINE_CODE,
                "evidence": bucket["current"][:EVIDENCE_LIMIT],
                "metric": {"label": "Yorum sayısı", "value": current, "previous": previous},
            }
        )
    return recommendations


async def _upcoming_events(
    db: AsyncSession, *, region: str | None, airline: str | None
) -> list[dict]:
    """Demand-moving calendar entries starting inside the planning horizon.

    The one item whose evidence is not a news article: a calendar entry is its
    own source, and it links to the organiser's page.
    """
    if airline:
        return []  # the calendar has no carrier dimension

    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=EVENT_HORIZON_DAYS)
    query = (
        select(AviationEvent)
        .where(
            AviationEvent.starts >= today,
            AviationEvent.starts <= horizon,
            AviationEvent.event_type.in_(EVENT_HIGH_IMPACT_TYPES),
        )
        .order_by(AviationEvent.starts)
        .limit(EVENT_MAX_RECS)
    )
    if region:
        query = query.where(AviationEvent.region == region)

    recommendations = []
    for event in (await db.execute(query)).scalars().all():
        days_until = (event.starts - today).days
        recommendations.append(
            {
                "id": f"event-{event.id}",
                "title": f"{event.name} yaklaşıyor ({format_date_range(event.starts, event.ends)})",
                "rationale": (
                    f"{event.city} — {days_until} gün sonra başlıyor. "
                    "Talep planlaması ve fiyat konumlandırması için takviminize alın."
                ),
                "severity": "medium" if days_until <= EVENT_IMMINENT_DAYS else "low",
                "category": "events",
                "region": event.region,
                "airline_code": None,
                "evidence": [
                    {
                        "headline": event.name,
                        "url": event.url,
                        "source_name": "Etkinlik takvimi",
                        "published_at": event.starts.isoformat(),
                    }
                ],
                "metric": {
                    "label": "Başlamasına kalan gün",
                    "value": days_until,
                    "previous": None,
                },
            }
        )
    return recommendations


async def build_recommendations(
    db: AsyncSession,
    days: int = 7,
    category: str | None = None,
    region: str | None = None,
    airline: str | None = None,
) -> list[dict]:
    """Every pattern the data currently supports, most urgent first.

    Filters narrow, they never widen: an item survives a filter only when it
    actually carries that dimension. A momentum item has no category, so a
    category filter drops it -- claiming otherwise would attach the number to a
    focus it does not have.
    """
    recommendations: list[dict] = []
    recommendations += await _competitor_promotions(
        db, days=days, region=region, airline=airline
    )
    recommendations += await _regional_route_surge(
        db, days=days, region=region, airline=airline
    )
    recommendations += await _airline_momentum_recs(
        db, days=days, region=region, airline=airline
    )
    recommendations += await _negative_sentiment_clusters(
        db, days=days, region=region, airline=airline
    )
    recommendations += await _tk_review_themes(
        db, days=days, region=region, airline=airline
    )
    recommendations += await _upcoming_events(db, region=region, airline=airline)

    if category:
        recommendations = [r for r in recommendations if r["category"] == category]
    if region:
        recommendations = [r for r in recommendations if r["region"] == region]
    if airline:
        recommendations = [
            r
            for r in recommendations
            if r["airline_code"] and r["airline_code"].upper() == airline.upper()
        ]

    # The invariant of this module, enforced once at the exit rather than
    # trusted in six places.
    recommendations = [r for r in recommendations if r["evidence"]]

    recommendations.sort(
        key=lambda r: (SEVERITY_ORDER.get(r["severity"], 9), -len(r["evidence"]), r["title"])
    )
    return recommendations[:MAX_RECOMMENDATIONS]
