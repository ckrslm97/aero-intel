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
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.article import Article, ArticleEnrichment
from app.models.entity import ArticleEntity, Entity
from app.models.source import Source
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

    await db.commit()
    logger.info("promos_seeded", inserted=inserted, total=len(PROMOS))
    return inserted
