"""Curated rival-airline campaign/promotion articles for the Gazete
(revenue_management > promotion).

Snapshot collected 2026-07-19. Airline offer pages are mostly bot-protected
JS apps, so each entry below was verified one of two ways:
- official: the campaign URL was fetched live and the campaign appeared in the
  page's own link list (Pegasus).
- news: the offer page itself could not be fetched; the claim comes from a
  trade-news report and that report is the citation.
Verified-inaccessible at collection time, recorded honestly rather than
guessed: Emirates (503), Qatar offers page (403), AJet (timeout), Etihad
(timeout; its "up to 30%" global sale had ended May 14), Lufthansa/Air France/
KLM/British Airways (nothing verifiable beyond coupon-aggregator spam, which
we do not cite). Ongoing coverage comes from the Google News promo radar in
sources_seed.py -- this file is a point-in-time snapshot, not a scraper.

Idempotent by URL, same pattern as events_seed.

Round 9 addendum -- this seed now writes TWO things per entry:
  * the Gazete article it always wrote (revenue_management > promotion), and
  * a structured `promotions` row, so /kampanyalar and the calendar's campaign
    ribbons have data on day one instead of an empty timeline.

The structured half carries only what each entry's own source actually states.
`discount_pct` and `markets` are read off the campaign copy; the sale window is
filled in for the single entry whose window was re-verified live against the
campaign page (see PC_KKTC_WINDOW below) and left NULL for every other, because
the 2026-07-19 snapshot did not record one. Null is not a gap to be filled here
-- the timeline draws a dateless campaign as a point marker at detection rather
than as a bar, which is the honest rendering. Dated rows arrive continuously
from the Pegasus scraper (app/ingest/promo_scrape.py) and from the
article-derived extractor (app/pipeline/promotions.py).
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.promotion import Promotion
from app.models.source import Source
from app.pipeline.promo_dedup import PromoCandidate, find_duplicate, merge_candidate
from app.pipeline.hashing import content_hash
from app.pipeline.search_indexing import index_article_text
from app.repositories.article_repository import ArticleRepository

logger = get_logger(__name__)

SOURCE_NAME = "Rakip Kampanya Takibi"
SOURCE_URL = "https://www.flypgs.com/kampanyali-ucak-biletleri"


@dataclass(frozen=True)
class RivalPromo:
    airline_code: str  # IATA code matching entities.code
    headline_tr: str
    summary_tr: str
    url: str
    # revenue_management subcategory: "promotion" for actual campaigns,
    # "pricing" for pricing-strategy intel (e.g. a rival explicitly NOT
    # discounting is intelligence too).
    subcategory: str = "promotion"
    region: str | None = "middle-east"

    # --- structured half (the `promotions` row) ---
    # The headline rate the copy states, or None when it states a fare floor
    # ("9 Euro'dan başlayan") rather than a percentage.
    discount_pct: int | None = None
    # Comma-separated region slugs and/or city names, as written in the copy.
    markets: str | None = None
    # Sale window. None on almost every entry on purpose -- the snapshot did
    # not record one, and inventing it would draw a bar the airline never
    # published. See the module docstring.
    sale_starts: date | None = None
    sale_ends: date | None = None


# Re-verified live against flypgs.com/kampanyali-ucak-biletleri/aktif-kampanyalar
# on 2026-08-22: the page states this campaign's validity outright, so it is a
# measured window rather than a guessed one.
PC_KKTC_WINDOW = (date(2026, 8, 21), date(2026, 8, 23))


PROMOS: list[RivalPromo] = [
    RivalPromo(
        airline_code="PC",
        headline_tr="Pegasus: 2026 yaz sezonu yurt dışı biletleri BolBol üyelerine 9 Euro + vergi",
        summary_tr=(
            "Pegasus, 2026 yaz sezonu yurt dışı uçuşlarını BolBol üyelerine 9 Euro artı "
            "vergilerden başlayan fiyatlarla satışa açtı. Kampanya seçili yurt dışı rotalarını "
            "kapsıyor; koltuk kontenjanı ve tarih ayrıntıları resmi kampanya sayfasında."
        ),
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/2026-yaz-sezonu-yurt-disi-biletlerim-bolbollura-9-euro-vergilerden-baslayan-fiyatlarla",
        # A fare floor, not a percentage -- discount_pct stays None.
        markets="europe",
    ),
    RivalPromo(
        airline_code="PC",
        headline_tr="Pegasus: yurt içi uçuşlarda mobil uygulamaya özel %30 indirim",
        summary_tr=(
            "Pegasus, BolBol üyelerine yurt içi uçuşlarda mobil uygulama üzerinden yapılan "
            "rezervasyonlarda %30 indirim sunuyor. Doğrudan kanala (mobil) yönlendirme ve "
            "sadakat programı bağlama stratejisinin tipik bir örneği."
        ),
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/bolbollulara-yurt-ici-ucuslari-mobil-uygulamaya-ozel-30-indirimli",
        discount_pct=30,
    ),
    RivalPromo(
        airline_code="PC",
        headline_tr="Pegasus: Genç BolBol üyelerine yurt dışı uçuşlarda %50 indirim",
        summary_tr=(
            "Pegasus, genç (öğrenci/genç yetişkin) BolBol üyelerine yurt dışı uçuşlarda %50 "
            "indirim veriyor. Gençlik segmentinde erken sadakat kazanımına dönük agresif bir "
            "fiyat hamlesi."
        ),
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/genc-bolbollulara-yurt-disi-ucuslari-50-indirimli",
        discount_pct=50,
        markets="europe",
    ),
    RivalPromo(
        airline_code="PC",
        headline_tr="Pegasus: Kuzey Kıbrıs uçuşları salı-perşembe %40 indirimli",
        summary_tr=(
            "Pegasus, Kuzey Kıbrıs uçuşlarında salı, çarşamba ve perşembe günleri %40 indirim "
            "uyguluyor; İstanbul Havalimanı çıkışlı KKTC uçuşlarında ise %50'ye varan ayrı bir "
            "kampanya yürütüyor. Zayıf günlere talep kaydırma (day-of-week pricing) örneği."
        ),
        url="https://www.flypgs.com/kampanyali-ucak-biletleri/kuzey-kibris-ucuslari-salidan-persembeye-40-indirimli",
        discount_pct=40,
        markets="kuzey kıbrıs",
        sale_starts=PC_KKTC_WINDOW[0],
        sale_ends=PC_KKTC_WINDOW[1],
    ),
    RivalPromo(
        airline_code="QR",
        headline_tr="Qatar Airways: birlikte seyahatte %25'e varan indirim, öğrencilere %20",
        summary_tr=(
            "Sektör basınına göre Qatar Airways, birlikte rezervasyon yapıp birlikte uçan "
            "yolculara seçili rotalarda baz ücrette %25'e varan indirim uygulayan bir flash "
            "kampanya yürütüyor; Student Club üyelerine ise %20'ye varan indirim, esnek "
            "değişiklik ve ek bagaj hakkı sunuluyor. (Kaynak: sektör haberi; resmi kampanya "
            "sayfası bot koruması nedeniyle doğrulanamadı.)"
        ),
        url="https://www.travelandtourworld.com/news/article/nx1x6rzjiftn/",
        discount_pct=25,
    ),
    RivalPromo(
        airline_code="EK",
        headline_tr="Emirates 2026 yazında geniş indirime gitmiyor: yield disiplini + frekans artışı",
        summary_tr=(
            "Sektör basınına göre Emirates, 2026 yaz sezonunda ağ genelinde indirimden "
            "kaçınıyor; bunun yerine sıkı yield yönetimi, frekans artışları ve hizmet "
            "iyileştirmeleriyle ilerliyor. Rakipler (Etihad, Qatar, flydubai) agresif yaz "
            "kampanyaları yürütürken Emirates'in fiyat disiplinini koruması, kapasite gücüne "
            "duyulan güvenin sinyali."
        ),
        url="https://www.travelandtourworld.com/news/article/etihad-joins-emirates-qatar-lufthansa-flydubai-and-more-airlines-to-wage-an-epic-battle-for-summer-2026-travel-domination-with-unbelievable-discounts-explosive-route-expansions-and-unmatched-globa/",
        subcategory="pricing",
    ),
]


async def _get_or_create_source(db: AsyncSession) -> Source:
    existing = await db.execute(select(Source).where(Source.name == SOURCE_NAME))
    source = existing.scalar_one_or_none()
    if source is not None:
        return source
    source = Source(
        name=SOURCE_NAME,
        url=SOURCE_URL,
        source_type="curated",
        category="airline",
        # Campaign claims come from official pages or a single trade report --
        # lower than organiser-published event dates.
        trust_weight=0.7,
    )
    db.add(source)
    await db.flush()
    return source


async def _airline_entity(db: AsyncSession, code: str) -> Entity | None:
    return (
        await db.execute(
            select(Entity).where(Entity.entity_type == "airline", Entity.code == code)
        )
    ).scalar_one_or_none()


# Airline display names for the structured rows, keyed the same way the
# timeline's lanes are (frontend/src/lib/nav.ts airlineTabs).
AIRLINE_NAMES: dict[str, str] = {
    "AF": "Air France", "BA": "British Airways", "EK": "Emirates",
    "EY": "Etihad Airways", "KL": "KLM", "LH": "Lufthansa",
    "QR": "Qatar Airways", "PC": "Pegasus Airlines", "VF": "AJet",
    "TK": "Turkish Airlines",
}


async def _seed_promotion_rows(db: AsyncSession, now: datetime) -> int:
    """The structured half: one `promotions` row per campaign entry.

    Only `subcategory == "promotion"` entries become rows. The Emirates entry
    is filed under "pricing" because it reports a carrier explicitly *not*
    discounting -- real intelligence, and exactly the thing that must not be
    drawn as a campaign bar on a campaign timeline.

    Idempotent by URL, and a re-run refreshes the row in place so a corrected
    date or rate propagates. `detected_at` is set once and never touched again:
    re-seeding is not re-detecting, and refreshing it would keep these
    permanently badged "Yeni".

    Idempotent by *campaign* as well, because the URL alone is not enough: once
    a seeded campaign has been merged with the airline's own page for it
    (app/pipeline/promo_dedup.py), the merged row lives at the airline's URL and
    a re-seed would find nothing under this one and helpfully re-create the
    duplicate the merge just removed.
    """
    inserted = 0
    for promo in PROMOS:
        if promo.subcategory != "promotion":
            continue
        existing = (
            await db.execute(select(Promotion).where(Promotion.url == promo.url))
        ).scalar_one_or_none()
        candidate = PromoCandidate(
            airline_code=promo.airline_code,
            airline_name=AIRLINE_NAMES.get(promo.airline_code, promo.airline_code),
            title_tr=promo.headline_tr[:300],
            summary_tr=promo.summary_tr,
            url=promo.url[:500],
            source_name=SOURCE_NAME,
            detected_at=now,
            discount_pct=promo.discount_pct,
            markets=promo.markets,
            sale_starts=promo.sale_starts,
            sale_ends=promo.sale_ends,
            region=promo.region,
        )
        if existing is not None:
            # Curation is the newer reading of what this entry says, so it wins
            # every field it states -- but a blank here must not erase a window
            # the airline's own page contributed.
            #
            # The returned diff is dropped on both branches: PROMOS is a
            # hand-maintained constant in this file, so a change here is a code
            # edit arriving with a deploy, and a version row saying "the
            # campaign moved" would be attributing our own commit to the
            # carrier.
            merge_candidate(existing, candidate, prefer_candidate=True)
            continue
        twin = await find_duplicate(db, candidate)
        if twin is not None:
            merge_candidate(twin, candidate)
            await db.flush()
            continue
        db.add(
            Promotion(
                airline_code=promo.airline_code,
                airline_name=AIRLINE_NAMES.get(promo.airline_code, promo.airline_code),
                title_tr=promo.headline_tr[:300],
                summary_tr=promo.summary_tr,
                discount_pct=promo.discount_pct,
                markets=promo.markets,
                sale_starts=promo.sale_starts,
                sale_ends=promo.sale_ends,
                travel_starts=None,
                travel_ends=None,
                url=promo.url[:500],
                source_name=SOURCE_NAME,
                region=promo.region,
                detected_at=now,
            )
        )
        inserted += 1
    return inserted


async def seed_promos(db: AsyncSession) -> int:
    """Write each promo as a curated Gazete article (idempotent by URL) with an
    entity link to its airline, so the Ana Rakipler filter catches it."""
    source = await _get_or_create_source(db)
    repo = ArticleRepository(db)
    now = datetime.now(timezone.utc)
    inserted = 0

    for promo in PROMOS:
        if await repo.url_exists(promo.url):
            continue

        article = Article(
            source_id=source.id,
            url=promo.url,
            title=promo.headline_tr,
            raw_content=promo.summary_tr,
            word_count=len(promo.summary_tr.split()),
            author=None,
            published_at=now,
            fetched_at=now,
            content_hash=content_hash(promo.headline_tr, promo.summary_tr),
            status="enriched",  # curated: nothing for the AI pipeline to add
        )
        db.add(article)
        await db.flush()

        db.add(
            ArticleEnrichment(
                article_id=article.id,
                headline=promo.headline_tr,
                summary=promo.summary_tr,
                # Written in Turkish at curation time, not machine-translated.
                headline_tr=promo.headline_tr,
                summary_tr=promo.summary_tr,
                translated_at=now,
                translation_provider="curated",
                category="revenue_management",
                subcategory=promo.subcategory,
                region=promo.region,
                importance_score=0.3,  # below news: a campaign should never outrank the day's reporting
                sentiment="neutral",
                confidence_score=0.8,
                corroborating_source_count=1,
                verified_at=now,
                llm_provider_used="curated",
                tags="promo",
            )
        )
        # The airline entity link is what makes /articles?airline=PC find this.
        entity = await _airline_entity(db, promo.airline_code)
        if entity is not None:
            db.add(ArticleEntity(article_id=article.id, entity_id=entity.id, relevance=1.0))
        await index_article_text(db, article.id, f"{article.title} {promo.summary_tr}")
        inserted += 1

    structured = await _seed_promotion_rows(db, now)

    await db.commit()
    logger.info(
        "promos_seeded", inserted=inserted, structured=structured, total=len(PROMOS)
    )
    return inserted
