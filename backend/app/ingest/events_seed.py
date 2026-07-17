"""A curated calendar of the industry's major events.

RSS feeds only report an event once it makes news -- usually the week it opens,
and only if an outlet we follow covers it. That left the Etkinlik category
nearly empty and biased toward whatever Simple Flying happened to write about.
A calendar is the right shape for this data: events are scheduled, known months
ahead, and published on the organisers' own sites.

Every entry below was verified against the organiser's site or a trade report
at the time of writing (July 2026), with the official URL kept as the citation.
Dates move: re-run `python -m app.cli seed-events` after updating this file, or
add next year's editions as they're announced. Idempotent -- keyed on URL.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
# Re-exported deliberately: format_date_range reads as part of this module's
# surface (it builds the event headlines below) but lives in core/tr_dates so
# the newsletter can share the same month names.
from app.core.tr_dates import format_date_range
from app.models.article import Article, ArticleEnrichment
from app.models.source import Source
from app.pipeline.hashing import content_hash
from app.pipeline.search_indexing import index_article_text
from app.repositories.article_repository import ArticleRepository

logger = get_logger(__name__)

SOURCE_NAME = "Etkinlik Takvimi"
SOURCE_URL = "https://www.aerotime.aero/articles/aviation-airshows-events-2026"


@dataclass(frozen=True)
class AviationEvent:
    name: str
    starts: date
    ends: date
    city: str
    country: str
    # A world-region slug from app/taxonomy.py COUNTRY_TO_REGION's value set.
    # None means the event is global in scope rather than tied to a market --
    # those show under "Genel" in the UI.
    region: str | None
    url: str
    summary: str


EVENTS: list[AviationEvent] = [
    AviationEvent(
        name="Farnborough International Airshow 2026",
        starts=date(2026, 7, 20),
        ends=date(2026, 7, 24),
        city="Farnborough",
        country="Birleşik Krallık",
        region="europe",
        url="https://www.farnboroughairshow.com/",
        summary=(
            "Dünyanın en büyük havacılık fuarlarından biri. Yaklaşık 48 ülkeden 1.500'ü aşkın "
            "katılımcı ve 80.000 civarı sektör ziyaretçisi bekleniyor; sipariş duyurularının "
            "yoğunlaştığı hafta."
        ),
    ),
    AviationEvent(
        name="Aviation Africa Summit 2026",
        starts=date(2026, 9, 9),
        ends=date(2026, 9, 10),
        city="Nairobi",
        country="Kenya",
        region="africa",
        url="https://www.aviationafrica.aero/",
        summary=(
            "Afrika havacılığının 10. zirvesi, Sarit Expo Centre'da. 100'ü aşkın katılımcı, "
            "kıtadaki havayolları ve düzenleyici kurumlar bir araya geliyor."
        ),
    ),
    AviationEvent(
        name="World Aviation Festival 2026",
        starts=date(2026, 10, 13),
        ends=date(2026, 10, 15),
        city="Lizbon",
        country="Portekiz",
        region="europe",
        url="https://worldaviationfestival.com/",
        summary=(
            "Havayolu ve havalimanlarının ticari strateji ve teknoloji konferansı: dağıtım, "
            "sadakat, perakendecilik ve dijital dönüşümden sorumlu üst yönetim katılıyor. "
            "Gelir yönetimi gündeminin en yoğun olduğu etkinliklerden biri."
        ),
    ),
    AviationEvent(
        name="Routes World 2026",
        starts=date(2026, 10, 18),
        ends=date(2026, 10, 20),
        city="Riyad",
        country="Suudi Arabistan",
        region="middle-east",
        url="https://www.routesonline.com/routes-world/",
        summary=(
            "Havayolları, havalimanları ve turizm kurumlarının ağ planlama görüşmelerini "
            "yürüttüğü küresel rota geliştirme forumu; yeni hat kararlarının şekillendiği yer."
        ),
    ),
    AviationEvent(
        name="NBAA-BACE 2026",
        starts=date(2026, 10, 20),
        ends=date(2026, 10, 22),
        city="Las Vegas",
        country="ABD",
        region="north-america",
        url="https://nbaa.org/events/",
        summary="Kuzey Amerika'nın en büyük iş havacılığı fuarı ve konferansı.",
    ),
    AviationEvent(
        name="MRO Europe 2026",
        starts=date(2026, 10, 27),
        ends=date(2026, 10, 29),
        city="Amsterdam",
        country="Hollanda",
        region="europe",
        url="https://mroeurope.aviationweek.com/",
        summary=(
            "Avrupa'nın en büyük bakım-onarım (MRO) etkinliği: 500'ü aşkın katılımcı ve "
            "11.000'den fazla ziyaretçi."
        ),
    ),
    AviationEvent(
        name="Bahrain International Airshow 2026",
        starts=date(2026, 11, 18),
        ends=date(2026, 11, 20),
        city="Sakhir",
        country="Bahreyn",
        region="middle-east",
        url="https://www.bahraininternationalairshow.com/",
        summary="Körfez bölgesinin iki yılda bir düzenlenen havacılık fuarı, Sakhir Hava Üssü'nde.",
    ),
    AviationEvent(
        name="Aircraft Interiors Expo 2027",
        starts=date(2027, 4, 6),
        ends=date(2027, 4, 8),
        city="Hamburg",
        country="Almanya",
        region="europe",
        url="https://www.aircraftinteriorsexpo.com/",
        summary=(
            "Kabin içi ürün ve yolcu deneyimi fuarı; koltuk, kabin ve ek gelir ürünlerinin "
            "tanıtıldığı ana etkinlik."
        ),
    ),
    AviationEvent(
        name="IATA 83. Yıllık Genel Kurulu (AGM) 2027",
        starts=date(2027, 5, 30),
        ends=date(2027, 6, 1),
        city="Xiamen",
        country="Çin",
        region="asia",
        url="https://www.iata.org/en/events/agm/",
        summary=(
            "IATA Yıllık Genel Kurulu ve Dünya Hava Taşımacılığı Zirvesi, Xiamen Airlines "
            "ev sahipliğinde. Sektörün finansal görünümünün açıklandığı toplantı."
        ),
    ),
    AviationEvent(
        name="Paris Air Show (SIAE) 2027",
        starts=date(2027, 6, 14),
        ends=date(2027, 6, 20),
        city="Paris Le Bourget",
        country="Fransa",
        region="europe",
        url="https://www.siae.fr/en/",
        summary="56. Uluslararası Paris Hava Show'u, Le Bourget Fuar Merkezi'nde.",
    ),
    AviationEvent(
        name="Dubai Airshow 2027",
        starts=date(2027, 11, 15),
        ends=date(2027, 11, 19),
        city="Dubai",
        country="Birleşik Arap Emirlikleri",
        region="middle-east",
        url="https://www.dubaiairshow.aero/",
        summary=(
            "Orta Doğu'nun en büyük havacılık fuarı, Dubai World Central'da; Körfez "
            "havayollarının büyük sipariş duyurularıyla bilinir."
        ),
    ),
    AviationEvent(
        name="Singapore Airshow 2028",
        starts=date(2028, 2, 15),
        ends=date(2028, 2, 20),
        city="Singapur",
        country="Singapur",
        region="southeast-asia",
        url="https://www.singaporeairshow.com/",
        summary="Asya-Pasifik'in en büyük havacılık fuarı, iki yılda bir düzenleniyor.",
    ),
]

def _headline(event: AviationEvent) -> str:
    return f"{event.name} · {format_date_range(event.starts, event.ends)} · {event.city}"


async def _get_or_create_source(db: AsyncSession) -> Source:
    from sqlalchemy import select

    existing = await db.execute(select(Source).where(Source.name == SOURCE_NAME))
    source = existing.scalar_one_or_none()
    if source is not None:
        return source

    source = Source(
        name=SOURCE_NAME,
        url=SOURCE_URL,
        source_type="curated",
        category="org",
        trust_weight=0.9,  # organiser-published dates, not reporting
    )
    db.add(source)
    await db.flush()
    return source


async def seed_events(db: AsyncSession) -> int:
    """Insert each calendar entry as an article in the events category. Idempotent."""
    source = await _get_or_create_source(db)
    repo = ArticleRepository(db)
    now = datetime.now(timezone.utc)
    inserted = 0

    for event in EVENTS:
        if await repo.url_exists(event.url):
            continue

        body = f"{event.summary} {event.city}, {event.country}."
        article = Article(
            source_id=source.id,
            url=event.url,
            title=_headline(event),
            raw_content=body,
            author=None,
            # Dated to the seed run, not the event: `published_at` drives the
            # newspaper's recency window, and an event announced for 2027 still
            # belongs in today's calendar view.
            published_at=now,
            fetched_at=now,
            content_hash=content_hash(event.name, body),
            status="enriched",  # curated: nothing for the AI pipeline to add
        )
        db.add(article)
        await db.flush()

        db.add(
            ArticleEnrichment(
                article_id=article.id,
                headline=_headline(event),
                summary=event.summary,
                # Already Turkish -- written, not machine-translated, so it's
                # marked as such and the UI shows no "untranslated" tag.
                headline_tr=_headline(event),
                summary_tr=event.summary,
                translated_at=now,
                translation_provider="curated",
                category="events",
                subcategory="regional" if event.region else "general",
                region=event.region,
                importance_score=0.6,
                sentiment="neutral",
                confidence_score=0.9,
                corroborating_source_count=1,
                verified_at=now,
                llm_provider_used="curated",
                tags="event",
            )
        )
        await index_article_text(db, article.id, f"{article.title} {body}")
        inserted += 1

    await db.commit()
    logger.info("events_seeded", inserted=inserted, total=len(EVENTS))
    return inserted
