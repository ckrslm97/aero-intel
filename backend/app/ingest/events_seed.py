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
    # One of app.models.event.EVENT_TYPES; drives the calendar page's type filter.
    event_type: str = "conference"


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
        event_type="airshow",
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
        event_type="airshow",
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
        event_type="airshow",
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
        event_type="airshow",
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
        event_type="airshow",
    ),
    # ------------------------------------------------------------------
    # Round-5 additions. Conference/airshow/sports dates verified against the
    # organiser (or FIFA/IATA) sites via web search at build time; holiday
    # dates follow the civil calendar, and lunar-calendar holidays (Ramazan/
    # Kurban bayramları, Çin Yeni Yılı) carry a ±1 day moon-sighting caveat in
    # their summaries. Aero India 2027 was researched and DROPPED: sources
    # conflict on its dates (Feb 8-12 vs 17-21), so it doesn't ship.
    # ------------------------------------------------------------------
    AviationEvent(
        name="Oktoberfest 2026",
        starts=date(2026, 9, 19),
        ends=date(2026, 10, 4),
        city="Münih",
        country="Almanya",
        region="europe",
        url="https://www.oktoberfest.de/en",
        summary=(
            "191. Oktoberfest, Theresienwiese'de. Münih'e yönelik talebin ve uçak "
            "doluluklarının yılın zirvesine çıktığı iki hafta."
        ),
        event_type="festival",
    ),
    AviationEvent(
        name="Çin Ulusal Günü Altın Haftası 2026",
        starts=date(2026, 10, 1),
        ends=date(2026, 10, 7),
        city="Çin geneli",
        country="Çin",
        region="asia",
        url="https://www.timeanddate.com/holidays/china/national-day",
        summary=(
            "Çin'in en büyük iki seyahat dalgasından biri: yurt içi ve uluslararası "
            "talebin hafta boyunca tavan yaptığı ulusal tatil."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="Diwali 2026",
        starts=date(2026, 11, 6),
        ends=date(2026, 11, 10),
        city="Hindistan geneli",
        country="Hindistan",
        region="asia",
        url="https://www.timeanddate.com/holidays/india/diwali",
        summary=(
            "Işık Bayramı (Lakshmi Puja 8 Kasım). Hindistan iç hatlarında ve "
            "diaspora rotalarında yılın en yoğun talep haftalarından."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="159. IATA Slot Konferansı",
        starts=date(2026, 11, 17),
        ends=date(2026, 11, 19),
        city="Budapeşte",
        country="Macaristan",
        region="europe",
        url="https://www.iata.org/en/events/all/iata-slot-conference-159/",
        summary=(
            "Havayolları ile slot koordinatörlerinin 2027 yaz tarifesi slotlarını "
            "pazarlık ettiği toplantı; ağ planlama ve kapasitenin kalbi."
        ),
    ),
    AviationEvent(
        name="APEX FTE EXPO Asia 2026",
        starts=date(2026, 11, 18),
        ends=date(2026, 11, 19),
        city="Singapur",
        country="Singapur",
        region="southeast-asia",
        url="https://expo2026.apex.aero/",
        summary=(
            "APEX ve Future Travel Experience'ın ortak fuarı Marina Bay Sands'te: "
            "kabin içi eğlence, bağlantı ve yolcu deneyimi teknolojileri."
        ),
    ),
    AviationEvent(
        name="Şükran Günü seyahat dalgası 2026",
        starts=date(2026, 11, 25),
        ends=date(2026, 11, 30),
        city="ABD geneli",
        country="ABD",
        region="north-america",
        url="https://www.timeanddate.com/holidays/us/thanksgiving-day",
        summary=(
            "Şükran Günü (26 Kasım) çevresi, ABD iç hatlarının yılın en yoğun "
            "günlerini yaşadığı pencere."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="Noel & Yılbaşı dönemi 2026-27",
        starts=date(2026, 12, 24),
        ends=date(2027, 1, 3),
        city="Küresel",
        country="Küresel",
        region=None,
        url="https://www.timeanddate.com/holidays/common/christmas-day",
        summary=(
            "Yıl sonu tatil dalgası: uzun mesafe ve güneş destinasyonlarında doluluk "
            "ve ücretlerin zirve yaptığı dönem."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="Çin Yeni Yılı (Bahar Bayramı) 2027",
        starts=date(2027, 2, 6),
        ends=date(2027, 2, 12),
        city="Çin geneli",
        country="Çin",
        region="asia",
        url="https://www.timeanddate.com/holidays/china/spring-festival",
        summary=(
            "Koyun Yılı 6 Şubat'ta başlıyor; dünyanın en büyük yıllık insan "
            "hareketliliği olan chunyun seyahat dalgasının merkezi haftası."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="Avalon Australian International Airshow 2027",
        starts=date(2027, 2, 23),
        ends=date(2027, 2, 28),
        city="Avalon (Melbourne)",
        country="Avustralya",
        region="oceania",
        url="https://airshow.com.au/",
        summary=(
            "Avustralya'nın en büyük uluslararası havacılık fuarı: üç ticari gün, "
            "ardından halka açık gösteri programı."
        ),
        event_type="airshow",
    ),
    AviationEvent(
        name="Ramazan Bayramı 2027",
        starts=date(2027, 3, 10),
        ends=date(2027, 3, 12),
        city="Türkiye ve İslam dünyası",
        country="Türkiye",
        region="middle-east",
        url="https://www.timeanddate.com/holidays/turkey/ramadan-feast",
        summary=(
            "Ramazan Bayramı (hilale bağlı, ±1 gün): Türkiye iç hatları ve gurbetçi "
            "rotalarında yoğun talep penceresi."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="Routes Asia 2027",
        starts=date(2027, 3, 16),
        ends=date(2027, 3, 18),
        city="Yeni Delhi",
        country="Hindistan",
        region="asia",
        url="https://www.routesonline.com/events/289/routes-asia-2027/",
        summary=(
            "Asya'nın rota geliştirme forumu ilk kez Yeni Delhi'de; bölgeye yeni hat "
            "kararlarının şekillendiği buluşma."
        ),
    ),
    AviationEvent(
        name="Paskalya seyahat dalgası 2027",
        starts=date(2027, 3, 26),
        ends=date(2027, 3, 29),
        city="Avrupa geneli",
        country="Küresel",
        region="europe",
        url="https://www.timeanddate.com/holidays/common/easter-sunday",
        summary=(
            "Batı Paskalyası 28 Mart (2027'de erken); Avrupa'da uzun hafta sonu "
            "talep zirvesi. Ortodoks Paskalyası 2 Mayıs'ta ayrıca izlenmeli."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="MRO Americas 2027",
        starts=date(2027, 4, 13),
        ends=date(2027, 4, 15),
        city="Orlando",
        country="ABD",
        region="north-america",
        url="https://mroamericas.aviationweek.com/",
        summary=(
            "Aviation Week'in Amerika kıtası MRO fuarı: 19.000+ katılımcı, 1.000+ "
            "stant, 93+ ülke."
        ),
    ),
    AviationEvent(
        name="Songkran (Tay Yeni Yılı) 2027",
        starts=date(2027, 4, 13),
        ends=date(2027, 4, 15),
        city="Tayland geneli",
        country="Tayland",
        region="southeast-asia",
        url="https://www.timeanddate.com/holidays/thailand/songkran",
        summary=(
            "Tay Yeni Yılı su festivali; Tayland'a gelen turizm talebinin yıl içi "
            "zirvelerinden biri."
        ),
        event_type="festival",
    ),
    AviationEvent(
        name="Japonya Altın Haftası 2027",
        starts=date(2027, 4, 29),
        ends=date(2027, 5, 5),
        city="Japonya geneli",
        country="Japonya",
        region="asia",
        url="https://www.timeanddate.com/holidays/japan/",
        summary=(
            "Ardışık ulusal tatiller: Japonya çıkışlı uluslararası seyahatin yıllık "
            "zirve haftası."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="Kurban Bayramı 2027",
        starts=date(2027, 5, 16),
        ends=date(2027, 5, 19),
        city="Türkiye ve İslam dünyası",
        country="Türkiye",
        region="middle-east",
        url="https://www.timeanddate.com/holidays/turkey/sacrifice-feast",
        summary=(
            "Kurban Bayramı (hilale bağlı, ±1 gün) ve hac dönemi: Türkiye, Körfez ve "
            "Suudi Arabistan rotalarında yoğun trafik."
        ),
        event_type="holiday",
    ),
    AviationEvent(
        name="FIFA Kadınlar Dünya Kupası 2027",
        starts=date(2027, 6, 24),
        ends=date(2027, 7, 25),
        city="Brezilya (8 şehir)",
        country="Brezilya",
        region="south-america",
        url="https://www.fifa.com/en/tournaments/womens/womensworldcup/brazil-2027",
        summary=(
            "32 takımlı turnuva ilk kez Güney Amerika'da: Rio, São Paulo, Brasília "
            "dahil 8 şehirde; Brezilya'ya uluslararası talep dalgası yaratacak."
        ),
        event_type="sports",
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


async def _upsert_calendar_rows(db: AsyncSession) -> int:
    """Write EVENTS into the structured aviation_events table (idempotent by
    URL, dates/summary refreshed on re-run so corrections propagate)."""
    from sqlalchemy import select

    from app.models.event import AviationEvent as AviationEventRow

    inserted = 0
    for event in EVENTS:
        existing = (
            await db.execute(select(AviationEventRow).where(AviationEventRow.url == event.url))
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                AviationEventRow(
                    name=event.name,
                    starts=event.starts,
                    ends=event.ends,
                    city=event.city,
                    country=event.country,
                    region=event.region,
                    url=event.url,
                    summary_tr=event.summary,
                    event_type=event.event_type,
                )
            )
            inserted += 1
        else:
            # Dates move ("Dates move: re-run seed-events") -- refresh in place.
            existing.name = event.name
            existing.starts = event.starts
            existing.ends = event.ends
            existing.city = event.city
            existing.country = event.country
            existing.region = event.region
            existing.summary_tr = event.summary
            existing.event_type = event.event_type
    await db.flush()
    return inserted


async def seed_events(db: AsyncSession) -> int:
    """Seed the calendar: structured rows for the /events page AND an article
    per event for the Gazete's Etkinlik tab -- one source list, two shapes,
    so they can't drift apart. Idempotent."""
    source = await _get_or_create_source(db)
    repo = ArticleRepository(db)
    now = datetime.now(timezone.utc)
    inserted = 0

    await _upsert_calendar_rows(db)

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
