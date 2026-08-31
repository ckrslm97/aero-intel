"""A curated calendar of the industry's major events.

RSS feeds only report an event once it makes news -- usually the week it opens,
and only if an outlet we follow covers it. That left the Etkinlik category
nearly empty and biased toward whatever Simple Flying happened to write about.
A calendar is the right shape for this data: events are scheduled, known months
ahead, and published on the organisers' own sites.

Every entry below was verified against the organiser's site or a trade report
at the time of writing (rounds 1-8 July 2026, round 9 August 2026), with the
official URL kept as the citation. Dates move: re-run
`python -m app.cli seed-events` after updating this file, or add next year's
editions as they're announced. Idempotent -- keyed on URL, so every event needs
a distinct one; where an organiser publishes a single page for a recurring
event, the second edition cites the page that actually lists it (RSNA's
future-meetings table) rather than a made-up per-year slug.

The calendar deliberately reaches well outside aviation. A revenue desk already
knows when Farnborough is; what it misses is the oncology congress, the trade
fair and the football tournament that fill the same aircraft. Round 9 is mostly
that: consumer, medical, industrial and sporting events, each with the demand
line that says why it is here.
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
    # How hard this moves traffic and fares into the host market:
    #   high   -- reprices the market; capacity decisions get made around it
    #   medium -- visible in the booking curve, absorbed by normal inventory
    #   low    -- newsworthy, not a demand event
    # Judged from headcount and how concentrated the travel is, and written by
    # hand next to the dates. Never inferred: a guessed impact level reads
    # exactly like a measured one, which is what makes it dangerous.
    impact_level: str = "medium"
    # Organiser-published headcount, where there is one. None = not published,
    # which the calendar shows as a dash rather than an estimate.
    attendance: int | None = None
    # One line: what to expect on the routes into that city, and when.
    demand_effect: str = ""


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
        impact_level="high",
        attendance=80000,
        demand_effect=(
            "Fuar haftasında Londra bölgesine iş seyahati talebi sıçrar; LHR ve LGW'de son dakika "
            "ücretleri sertleşir, oteller erken dolar. Etki fuardan iki hafta önce başlar."
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
        impact_level="low",
        attendance=None,
        demand_effect=(
            "Nairobi'ye sınırlı ama üst düzey bir talep; hat bazında kapasite kararı gerektirmez, "
            "iş sınıfı doluluğunda iki günlük hareket beklenir."
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
        impact_level="medium",
        attendance=7000,
        demand_effect=(
            "Lizbon'a Avrupa içi iş trafiğinde üç günlük yoğunlaşma. Kısa mesafe hatlarda son "
            "hafta rezervasyonları öne çekilir."
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
        impact_level="high",
        attendance=3000,
        demand_effect=(
            "Ağ planlama ekiplerinin toplandığı hafta: Riyad'a talep artışının ötesinde, burada "
            "duyurulan yeni hatlar sonraki sezonun rekabet haritasını değiştirir."
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
        impact_level="medium",
        attendance=25000,
        demand_effect=(
            "Las Vegas'a iş jeti ve kurumsal havacılık trafiği; tarifeli hatlarda premium kabin "
            "talebi belirgin şekilde artar."
        ),
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
        impact_level="medium",
        attendance=9000,
        demand_effect=(
            "Amsterdam'a teknik ve tedarik zinciri trafiği. AMS bağlantılı Avrupa hatlarında üç "
            "günlük iş seyahati yoğunlaşması."
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
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Körfez içi kısa mesafe trafiğinde artış; bölgesel taşıyıcılar için kapasite değil "
            "fiyat konusu."
        ),
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
        impact_level="medium",
        attendance=18000,
        demand_effect=(
            "Hamburg'a kabin ürünü ve tedarikçi trafiği. Almanya içi ve Avrupa kısa mesafede üç "
            "günlük talep sıçraması."
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
        impact_level="high",
        attendance=1200,
        demand_effect=(
            "Sektörün en üst düzey buluşması. Xiamen'e doğrudan talep sınırlı ama Çin bağlantılı "
            "premium trafik ve basın ilgisi zirve yapar; duyurular fiyat beklentisini etkiler."
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
        impact_level="high",
        attendance=320000,
        demand_effect=(
            "Sektörün en büyük fuarı. Paris'e giden tüm hatlarda iki hafta boyunca talep ve fiyat "
            "yükselir; CDG ve ORY'de kapasite planlaması gerektirir."
        ),
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
        impact_level="high",
        attendance=100000,
        demand_effect=(
            "Körfez'in en büyük fuarı. DXB'ye uzun menzilli iş trafiği ve otel fiyatları zirveye "
            "çıkar; Emirates ve bölgesel taşıyıcılar için yılın en yoğun premium haftası."
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
        event_type="airshow",
        impact_level="high",
        attendance=60000,
        demand_effect=(
            "Asya-Pasifik'in en büyük fuarı. SIN'e bölgesel ve uzun menzilli iş trafiğinde "
            "belirgin artış; Güneydoğu Asya hatlarında kapasite konusu."
        ),
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
        impact_level="high",
        attendance=6000000,
        demand_effect=(
            "Münih'e on altı gün boyunca yoğun turistik talep. MUC hatlarında ekonomi sınıfı "
            "erken dolar, son dakika ücretleri en yüksek seviyeye çıkar."
        ),
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Çin'in en büyük iki seyahat dalgasından biri. Çin çıkışlı uluslararası talep patlar; "
            "kapasite kararlarının aylar önceden verilmesi gerekir."
        ),
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Hindistan'ın en büyük seyahat dönemi. Hindistan bağlantılı hatlarda hem iç hem "
            "diaspora talebi zirve yapar; iki yönlü dengesizlik belirgindir."
        ),
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
        impact_level="high",
        attendance=1400,
        demand_effect=(
            "Bir sonraki sezonun slotları burada dağıtılır. Budapeşte'ye talep etkisi küçük, ama "
            "konferansın çıktısı tüm ağın gelecek sezon kapasitesini belirler."
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
        impact_level="low",
        attendance=3000,
        demand_effect=(
            "Singapur'a yolcu deneyimi ve teknoloji trafiği; bölgesel hatlarda sınırlı hareket."
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "ABD'nin yılın en yoğun iç hat dönemi. Kuzey Amerika bağlantılı hatlarda doluluk "
            "tavan yapar; aktarma trafiği için de kritik hafta."
        ),
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Küresel ölçekte yılın en uzun talep zirvesi. Neredeyse tüm pazarlarda iki haftalık "
            "yüksek doluluk ve en yüksek ücret seviyeleri."
        ),
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Dünyanın en büyük insan hareketi. Çin ve Güneydoğu Asya hatlarında haftalar süren "
            "talep zirvesi; dönüş yönü ayrı planlanmalı."
        ),
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
        impact_level="low",
        attendance=75000,
        demand_effect=(
            "Melbourne'e ağırlıklı iç hat talebi; uluslararası hatlarda etkisi sınırlı."
        ),
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Türkiye ve İslam dünyasında en yoğun seyahat dönemlerinden biri. İç hat ve gurbetçi "
            "trafiğinde bayram öncesi/sonrası çift zirve oluşur."
        ),
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
        impact_level="medium",
        attendance=1200,
        demand_effect=(
            "Asya ağ planlama buluşması. Yeni Delhi'ye iş trafiği artar; bölgedeki hat duyuruları "
            "bu hafta yoğunlaşır."
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Avrupa'nın ilk büyük tatil dalgası. Kısa mesafe tatil hatlarında doluluk ve ücretler "
            "sezon açılışını belirler."
        ),
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
        impact_level="medium",
        attendance=17000,
        demand_effect=(
            "Orlando'ya teknik ve tedarik trafiği; ABD iç hatlarında üç günlük iş seyahati "
            "artışı."
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Tayland'ın en büyük tatil dönemi. Bangkok ve Phuket hatlarında hem gelen turist hem "
            "iç seyahat talebi zirve yapar."
        ),
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Japonya'nın en yoğun tatil haftası. Japonya çıkışlı uluslararası talep patlar; dönüş "
            "yönünde de yüksek doluluk."
        ),
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
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Türkiye, Orta Doğu ve Kuzey Afrika'da yoğun seyahat dönemi. Hac öncesi trafikle "
            "birleştiğinde Suudi Arabistan hatlarında ayrı bir zirve oluşur."
        ),
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
        # Raised from medium in round 9: a 32-team tournament running a full
        # month across eight cities reprices those markets rather than being
        # absorbed by normal inventory, which is what "high" means here.
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Brezilya'nın sekiz şehrine bir ay boyunca dağılmış talep. Etki tek bir zirve değil, "
            "maç takvimine göre şehirler arası dalgalanma olarak görünür."
        ),
    ),
    # ------------------------------------------------------------------
    # Round-9 additions: the calendar past the aviation trade circuit.
    #
    # The first eight rounds covered airshows, MRO and route-development
    # events -- the weeks a network planner already has in their head. What
    # actually fills a widebody is the calendar nobody in aviation is
    # watching: a consumer electronics show, an oncology congress, a climate
    # summit, a football tournament. Those are added here, each against the
    # organiser's own page rather than an aggregator, because the aggregators
    # are demonstrably wrong -- Airshow China 2026 is listed as November on
    # several of them and the organiser says 7-13 December.
    #
    # Deliberately NOT added, and the reason is always the same one: no
    # organiser source. Oktoberfest 2027 (Munich publishes one year at a
    # time), COP32 (host undecided), ATM 2027, Routes World 2027, Aero India
    # 2027 (sources still conflict, dropped in round 5 for the same reason),
    # the 161st slot conference (dates published, city not), ICC Cricket
    # World Cup 2027 (ICC says only "October-November"), Rugby League World
    # Cup 2027 (does not exist -- the edition moved to 2026), FIFA Club World
    # Cup 2027 (next is 2029), FIFA Arab Cup 2027, U-20 World Cup 2027 dates
    # and Parapan Lima 2027. A date we cannot cite is a date we do not ship.
    # ------------------------------------------------------------------
    # --- Türkiye: the four that move IST/SAW/AYT directly ---
    AviationEvent(
        name="COP31 İklim Zirvesi 2026",
        starts=date(2026, 11, 9),
        ends=date(2026, 11, 20),
        city="Antalya",
        country="Türkiye",
        region="middle-east",
        url="https://cop31.tr/",
        summary=(
            "BM İklim Değişikliği Konferansı'nın 31. taraflar toplantısı Antalya'da. "
            "İki hafta boyunca ülke delegasyonları, sivil toplum ve uluslararası basın "
            "şehirde; Türkiye'nin ağırladığı en büyük ölçekli diplomatik etkinlik."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Antalya'ya on iki gün boyunca delegasyon ve basın trafiği; AYT hatlarında kasım ayı "
            "düşük sezonu tersine döner, iş sınıfı ve otel kapasitesi aylar öncesinden dolar."
        ),
    ),
    AviationEvent(
        name="4. Avrupa Oyunları 2027",
        starts=date(2027, 6, 16),
        ends=date(2027, 6, 27),
        city="İstanbul",
        country="Türkiye",
        region="middle-east",
        url="https://www.istanbul2027.org/",
        summary=(
            "Avrupa Olimpiyat Komiteleri'nin dört yılda bir düzenlediği çok sporlu "
            "organizasyon ilk kez İstanbul'da; kıta genelinden sporcu kafileleri, "
            "federasyon heyetleri ve seyirci akını."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "İstanbul'a on iki gün boyunca çok uluslu sporcu, kafile ve seyirci trafiği. IST ve "
            "SAW'da haziran doluluğu zaten yüksekken ek baskı gelir; kapasite kararı gerektirir."
        ),
    ),
    AviationEvent(
        name="IATA Dünya Güvenlik ve Operasyon Konferansı 2026",
        starts=date(2026, 10, 6),
        ends=date(2026, 10, 8),
        city="İstanbul",
        country="Türkiye",
        region="middle-east",
        url="https://www.iata.org/en/events/all/wsoc/",
        summary=(
            "IATA'nın uçuş emniyeti, yer operasyonu ve kabin güvenliği gündemini tek "
            "çatı altında toplayan yıllık konferansı, Hilton İstanbul Bomonti'de."
        ),
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "İstanbul'a üç günlük operasyon ve emniyet yöneticisi trafiği; iş sınıfında görülür "
            "ama IST ölçeğinde kapasite değil fiyat konusu."
        ),
    ),
    AviationEvent(
        name="IATA Dünya Hukuk Sempozyumu 2027",
        starts=date(2027, 3, 16),
        ends=date(2027, 3, 18),
        city="İstanbul",
        country="Türkiye",
        region="middle-east",
        url="https://www.iata.org/en/events/all/world-legal-symposium/",
        summary=(
            "Havacılık hukukunun yıllık buluşması: havayolu baş hukuk müşavirleri, "
            "düzenleyiciler ve uluslararası hukuk firmaları İstanbul'da."
        ),
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "İstanbul'a küçük ama tamamı premium bir delegasyon; mart ortasında iş sınıfı "
            "doluluğunda üç günlük hareket."
        ),
    ),
    AviationEvent(
        name="Routes Europe 2027",
        starts=date(2027, 4, 20),
        ends=date(2027, 4, 22),
        city="Antalya",
        country="Türkiye",
        region="middle-east",
        url="https://www.routesonline.com/events/290/routes-europe-2027/",
        summary=(
            "Avrupa'nın rota geliştirme forumu Antalya'da, Fraport TAV Antalya "
            "ev sahipliğinde; havayolu ağ planlama ekipleriyle havalimanlarının "
            "yeni hat görüşmelerini yürüttüğü üç gün."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Antalya'ya sezon açılmadan ağ planlama trafiği. Asıl etki talep değil karar: burada "
            "görüşülen hatlar Türkiye'nin gelecek yaz tarifesini şekillendirir."
        ),
    ),
    AviationEvent(
        name="TEKNOFEST 2026",
        starts=date(2026, 9, 30),
        ends=date(2026, 10, 4),
        city="Şanlıurfa",
        country="Türkiye",
        region="middle-east",
        url="https://www.teknofest.org/",
        summary=(
            "Havacılık, uzay ve teknoloji festivali bu yıl Şanlıurfa'da; yarışma "
            "takımları, aileler ve gösteri uçuşları için beş günlük program."
        ),
        event_type="festival",
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Şanlıurfa'ya beş gün boyunca yoğun iç hat talebi. GAP bölgesi hatlarında kapasite "
            "sınırlı olduğu için etki doluluktan çok ücrete yansır."
        ),
    ),
    # --- Sonbahar 2026: Avrupa ve Asya fuar takvimi ---
    AviationEvent(
        name="IFA Berlin 2026",
        starts=date(2026, 9, 4),
        ends=date(2026, 9, 8),
        city="Berlin",
        country="Almanya",
        region="europe",
        url="https://www.ifa-berlin.com/",
        summary=(
            "Avrupa'nın en büyük tüketici elektroniği fuarı, Messe Berlin'de; "
            "yaklaşık 220.000 ziyaretçi."
        ),
        impact_level="medium",
        attendance=220000,
        demand_effect=(
            "Berlin'e beş günlük karma iş ve ziyaretçi trafiği. BER hatlarında eylül başında "
            "doluluk yükselir, otel fiyatları uçak biletinden önce sertleşir."
        ),
    ),
    AviationEvent(
        name="FIFA U-20 Kadınlar Dünya Kupası 2026",
        starts=date(2026, 9, 5),
        ends=date(2026, 9, 27),
        city="Polonya geneli",
        country="Polonya",
        region="europe",
        url="https://www.fifa.com/en/tournaments/womens/u20womensworldcup/poland-2026",
        summary=(
            "24 takımlı turnuva Polonya'nın birkaç şehrine yayılıyor; üç haftalık "
            "maç takvimi boyunca taraftar ve kafile trafiği."
        ),
        event_type="sports",
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Polonya'ya üç hafta boyunca dağılmış taraftar trafiği. Tek bir zirve değil, maç "
            "takvimine göre şehir şehir dalgalanan bir talep."
        ),
    ),
    AviationEvent(
        name="Automechanika Frankfurt 2026",
        starts=date(2026, 9, 8),
        ends=date(2026, 9, 12),
        city="Frankfurt",
        country="Almanya",
        region="europe",
        url="https://automechanika.messefrankfurt.com/frankfurt/en.html",
        summary=(
            "Otomotiv yan sanayi ve satış sonrası hizmetlerin dünya fuarı; "
            "yaklaşık 108.000 ziyaretçi, ağırlıklı olarak uluslararası."
        ),
        impact_level="medium",
        attendance=108000,
        demand_effect=(
            "Frankfurt'a beş günlük yoğun tedarikçi trafiği. FRA zaten aktarma merkezi olduğu için "
            "etki ekonomi sınıfı doluluğunda ve otel fiyatlarında görünür."
        ),
    ),
    AviationEvent(
        name="IBC 2026",
        starts=date(2026, 9, 11),
        ends=date(2026, 9, 14),
        city="Amsterdam",
        country="Hollanda",
        region="europe",
        url="https://show.ibc.org/",
        summary=(
            "Medya ve yayıncılık teknolojilerinin Avrupa fuarı, RAI Amsterdam'da; "
            "organizatörün açıkladığı 2025 katılımı 43.858 kişi."
        ),
        impact_level="medium",
        attendance=43858,
        demand_effect=(
            "Amsterdam'a dört günlük yoğun sektör trafiği. AMS hatlarında eylül ortası doluluğu "
            "yükselir; şehirdeki otel kapasitesi biletlerden önce tükenir."
        ),
    ),
    AviationEvent(
        name="Arabian Travel Market 2026",
        starts=date(2026, 9, 14),
        ends=date(2026, 9, 17),
        city="Dubai",
        country="Birleşik Arap Emirlikleri",
        region="middle-east",
        url="https://www.wtm.com/atm/en-gb.html",
        summary=(
            "Orta Doğu'nun en büyük turizm ticaret fuarı, Dubai World Trade "
            "Centre'da; bölgedeki tur operatörü ve havayolu satış ekiplerinin "
            "sezon anlaşmalarını yaptığı hafta."
        ),
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Dubai'ye dört günlük turizm ve satış trafiği. DXB ölçeğinde kapasite konusu değil, "
            "ama burada yapılan kontratlar kış sezonu Körfez talebini belirler."
        ),
    ),
    AviationEvent(
        name="20. Asya Oyunları (Aichi-Nagoya 2026)",
        starts=date(2026, 9, 19),
        ends=date(2026, 10, 4),
        city="Aichi-Nagoya",
        country="Japonya",
        region="asia",
        url="https://www.aichi-nagoya2026.org/en/",
        summary=(
            "Asya'nın en büyük çok sporlu organizasyonu, yaklaşık 11.000 sporcuyla "
            "Aichi ve Nagoya'da. Resmî açılış 19 Eylül, ancak bazı branşlarda "
            "yarışmalar 10 Eylül'de başlıyor -- talep penceresi açılıştan geniştir."
        ),
        event_type="sports",
        impact_level="high",
        attendance=11000,
        demand_effect=(
            "Nagoya'ya iki hafta boyunca kafile, federasyon ve seyirci trafiği. Japonya iç "
            "hatlarında ve Asya bağlantılarında belirgin doluluk artışı."
        ),
    ),
    AviationEvent(
        name="MRO Asia-Pacific 2026",
        starts=date(2026, 9, 22),
        ends=date(2026, 9, 24),
        city="Singapur",
        country="Singapur",
        region="southeast-asia",
        url="https://mroasia.aviationweek.com/",
        summary=(
            "Aviation Week'in Asya-Pasifik bakım-onarım fuarı; bölgedeki filo "
            "büyümesinin teknik tedarik tarafının toplandığı üç gün."
        ),
        impact_level="medium",
        attendance=7500,
        demand_effect=(
            "Singapur'a teknik ve tedarik zinciri trafiği; Güneydoğu Asya kısa mesafe hatlarında "
            "üç günlük iş seyahati yoğunlaşması."
        ),
    ),
    AviationEvent(
        name="Canton Fair 140. dönem",
        starts=date(2026, 10, 15),
        ends=date(2026, 11, 4),
        city="Guangzhou",
        country="Çin",
        region="asia",
        url="https://www.cantonfair.org.cn/en-US",
        summary=(
            "Çin İthalat ve İhracat Fuarı'nın üç fazlı sonbahar dönemi; "
            "organizatörün açıkladığı ölçekte 314.000'i aşkın yabancı alıcı."
        ),
        impact_level="high",
        attendance=314000,
        demand_effect=(
            "Guangzhou'ya üç hafta süren alıcı akını. Çin'e giden uzun menzilli hatlarda ekonomi "
            "sınıfı doluluğu ve ücretler üç faz boyunca yüksek kalır."
        ),
    ),
    AviationEvent(
        name="Ragbi Lig Dünya Kupası 2026",
        starts=date(2026, 10, 15),
        ends=date(2026, 11, 15),
        city="Avustralya, Yeni Zelanda ve PNG geneli",
        country="Avustralya",
        region="oceania",
        url="https://www.rlwc2026.com/",
        summary=(
            "Turnuva Avustralya, Yeni Zelanda ve Papua Yeni Gine'ye yayılıyor. "
            "Organizatör yalnız başlangıç tarihini yayımladı; buradaki bitiş "
            "tarihi geçicidir ve final takvimi açıklandığında güncellenmelidir."
        ),
        event_type="sports",
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Okyanusya içi hatlarda bir ay boyunca dağılmış taraftar trafiği; uzun menzilli "
            "hatlarda etkisi sınırlı kalır."
        ),
    ),
    AviationEvent(
        name="ESMO Kongresi 2026",
        starts=date(2026, 10, 23),
        ends=date(2026, 10, 27),
        city="Madrid",
        country="İspanya",
        region="europe",
        url="https://www.esmo.org/meeting-calendar/esmo-congress-2026",
        summary=(
            "Avrupa Tıbbi Onkoloji Derneği'nin yıllık kongresi, yaklaşık 37.000 "
            "katılımcıyla Madrid'de; Avrupa'nın en büyük tıp kongrelerinden biri."
        ),
        impact_level="high",
        attendance=37000,
        demand_effect=(
            "Madrid'e beş gün boyunca kıta ve okyanus ötesi hekim trafiği. MAD hatlarında ekim "
            "sonunda doluluk tavan yapar; kongre otelleri altı ay önceden dolar."
        ),
    ),
    # --- Kasım-Aralık 2026 ---
    AviationEvent(
        name="WTM Londra 2026",
        starts=date(2026, 11, 3),
        ends=date(2026, 11, 5),
        city="Londra",
        country="Birleşik Krallık",
        region="europe",
        url="https://www.wtm.com/london/en-gb.html",
        summary=(
            "World Travel Market, ExCeL Londra'da: yaklaşık 46.000 turizm "
            "profesyoneli, havayolu ve destinasyon temsilcisi."
        ),
        impact_level="high",
        attendance=46000,
        demand_effect=(
            "Londra'ya kasım başında üç günlük yoğun turizm sektörü trafiği. LHR ve LGW'de iş "
            "sınıfı erken dolar; burada yapılan kontratlar gelecek yaz kapasitesini etkiler."
        ),
    ),
    AviationEvent(
        name="Web Summit 2026",
        starts=date(2026, 11, 9),
        ends=date(2026, 11, 12),
        city="Lizbon",
        country="Portekiz",
        region="europe",
        url="https://websummit.com/",
        summary=(
            "Avrupa'nın en büyük teknoloji konferansı, Altice Arena ve FIL'de; "
            "organizatörün açıkladığı 2025 katılımı 71.386 kişi."
        ),
        impact_level="high",
        attendance=71386,
        demand_effect=(
            "Lizbon'a dört gün boyunca kıta çapında talep dalgası. LIS hatlarında düşük sezon "
            "ortasında yüksek sezon ücretleri görülür; konaklama şehir dışına taşar."
        ),
    ),
    AviationEvent(
        name="FIFA U-17 Dünya Kupası 2026",
        starts=date(2026, 11, 19),
        ends=date(2026, 12, 13),
        city="Doha",
        country="Katar",
        region="middle-east",
        url="https://www.fifa.com/en/tournaments/mens/u17worldcup/qatar-2026",
        summary=(
            "48 takımlı turnuvanın tamamı tek şehirde, Doha'da oynanıyor; "
            "dört haftaya yayılan yoğun maç takvimi."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "48 takımın tamamı tek şehre geliyor: Doha'ya dört hafta boyunca kesintisiz kafile ve "
            "taraftar trafiği. DOH hatlarında kapasite planlaması gerektirir."
        ),
    ),
    AviationEvent(
        name="RSNA 2026",
        starts=date(2026, 11, 29),
        ends=date(2026, 12, 3),
        city="Şikago",
        country="ABD",
        region="north-america",
        url="https://www.rsna.org/annual-meeting",
        summary=(
            "Kuzey Amerika Radyoloji Derneği'nin yıllık toplantısı, McCormick "
            "Place'te; dünyanın en büyük tıbbi görüntüleme etkinliği."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Şikago'ya Şükran Günü dalgasının hemen ardından uluslararası hekim trafiği. ORD "
            "hatlarında iki yoğun pencere üst üste biner."
        ),
    ),
    AviationEvent(
        name="Airshow China 2026 (Zhuhai)",
        starts=date(2026, 12, 7),
        ends=date(2026, 12, 13),
        city="Zhuhai",
        country="Çin",
        region="asia",
        url="https://www.airshow.com.cn/",
        summary=(
            "Çin Uluslararası Havacılık ve Uzay Fuarı'nın 16. edisyonu. Tarihler "
            "organizatörün kendi sitesinden alındı: birçok fuar takvimi bu "
            "edisyonu hâlâ kasımda gösteriyor, doğrusu 7-13 Aralık."
        ),
        event_type="airshow",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Zhuhai'ye ve Guangzhou/Macau bağlantılarına bir hafta boyunca yoğun sektör trafiği; "
            "Çin sipariş duyurularının yoğunlaştığı hafta."
        ),
    ),
    AviationEvent(
        name="GITEX Global 2026",
        starts=date(2026, 12, 7),
        ends=date(2026, 12, 11),
        city="Dubai",
        country="Birleşik Arap Emirlikleri",
        region="middle-east",
        url="https://www.gitex.com/global",
        summary=(
            "Orta Doğu'nun en büyük teknoloji fuarı. Bu edisyonda iki değişiklik "
            "var: takvim ekimden aralığa kaydı ve etkinlik Dubai World Trade "
            "Centre'dan Expo City Dubai'ye taşındı."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Dubai'ye beş gün boyunca küresel teknoloji trafiği. Aralığa kayması Körfez'in zaten "
            "yüksek kış sezonuyla çakışıyor; DXB hatlarında çift baskı."
        ),
    ),
    # --- 2027 ilk yarı ---
    AviationEvent(
        name="CES 2027",
        starts=date(2027, 1, 6),
        ends=date(2027, 1, 9),
        city="Las Vegas",
        country="ABD",
        region="north-america",
        url="https://www.ces.tech/",
        summary=(
            "Dünyanın en büyük tüketici teknolojisi fuarı; organizatörün "
            "açıkladığı 2026 katılımı 148.392 kişi, 160'tan fazla ülkeden."
        ),
        impact_level="high",
        attendance=148392,
        demand_effect=(
            "Las Vegas'a yılın ilk büyük talep şoku. LAS'a giden tüm hatlarda ücretler ocak "
            "başında zirveye çıkar, otel fiyatları katlanır; kapasite kararı gerektirir."
        ),
    ),
    AviationEvent(
        name="AFC Asya Kupası 2027",
        starts=date(2027, 1, 7),
        ends=date(2027, 2, 5),
        city="Riyad, Cidde ve El Hobar",
        country="Suudi Arabistan",
        region="middle-east",
        url="https://www.the-afc.com/en/national/afc_asian_cup.html",
        summary=(
            "Asya'nın milli takım turnuvası Suudi Arabistan'da; maçlar Riyad, "
            "Cidde ve El Hobar arasında paylaşılıyor."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Suudi Arabistan'a bir ay boyunca Asya çıkışlı taraftar trafiği. Körfez içi ve Asya "
            "bağlantılı hatlarda maç takvimine bağlı dalgalı talep."
        ),
    ),
    AviationEvent(
        name="FISU Kış Üniversite Oyunları 2027",
        starts=date(2027, 1, 15),
        ends=date(2027, 1, 25),
        city="Changchun",
        country="Çin",
        region="asia",
        url="https://www.fisu.net/fisu-events/fisu-winter-world-university-games/",
        summary=(
            "Üniversite sporcularının kış oyunları Changchun'da; on bir günlük "
            "program boyunca kafile ve federasyon trafiği."
        ),
        event_type="sports",
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Changchun'a Çin iç hatları üzerinden kafile trafiği; uluslararası hatlarda etkisi "
            "sınırlı, Pekin aktarmalarında görünür."
        ),
    ),
    AviationEvent(
        name="Dünya Ekonomik Forumu Yıllık Toplantısı 2027",
        starts=date(2027, 1, 18),
        ends=date(2027, 1, 22),
        city="Davos",
        country="İsviçre",
        region="europe",
        url="https://www.davos.ch/",
        summary=(
            "Devlet başkanları, merkez bankacıları ve büyük şirket yönetimlerinin "
            "yıllık Davos toplantısı."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Zürih ve Cenevre'ye yılın en yoğun premium haftası. Tarifeli iş sınıfı kadar özel "
            "havacılık talebi de zirve yapar; ZRH slot baskısı belirginleşir."
        ),
    ),
    AviationEvent(
        name="FITUR 2027",
        starts=date(2027, 1, 20),
        ends=date(2027, 1, 24),
        city="Madrid",
        country="İspanya",
        region="europe",
        url="https://www.ifema.es/en/fitur",
        summary=(
            "IFEMA Madrid'in uluslararası turizm fuarı; İspanya ve Latin Amerika "
            "pazarının sezon anlaşmalarını yaptığı hafta."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Madrid'e ocak sonunda beş günlük turizm sektörü akını. MAD hatlarında düşük sezon "
            "ortasında doluluk sıçraması; Latin Amerika bağlantılarında da görünür."
        ),
    ),
    AviationEvent(
        name="Rio Karnavalı 2027",
        starts=date(2027, 2, 7),
        ends=date(2027, 2, 9),
        city="Rio de Janeiro",
        country="Brezilya",
        region="south-america",
        url="https://liesa.org.br/",
        summary=(
            "Sambadrome'daki özel grup geçit törenleri; Rio'nun yılın en yoğun "
            "turistik talep penceresinin merkezi üç günü."
        ),
        event_type="festival",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Rio'ya uluslararası talebin yıllık zirvesi. GIG hatlarında ücretler haftalar öncesinden "
            "sertleşir; dönüş yönü ayrı planlanmalı."
        ),
    ),
    AviationEvent(
        name="Ramazan 2027",
        starts=date(2027, 2, 8),
        ends=date(2027, 3, 8),
        city="İslam dünyası geneli",
        country="Küresel",
        region="middle-east",
        url="https://www.moonsighting.com/",
        summary=(
            "Ramazan ayı (hilal gözlemine göre ±1 gün kayabilir). Ay boyunca "
            "Körfez ve Kuzey Afrika hatlarında talep düşer, umre trafiği ise "
            "özellikle son on günde yoğunlaşır."
        ),
        event_type="holiday",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Bir aylık ters etki: Körfez içi iş trafiği zayıflarken Suudi Arabistan hatlarında umre "
            "talebi son on günde zirve yapar. İki yönü ayrı planlamak gerekir."
        ),
    ),
    AviationEvent(
        name="MWC Barcelona 2027",
        starts=date(2027, 3, 1),
        ends=date(2027, 3, 4),
        city="Barselona",
        country="İspanya",
        region="europe",
        url="https://www.mwcbarcelona.com/",
        summary=(
            "Mobil sektörün dünya kongresi, Fira Gran Via'da; organizatörün "
            "açıkladığı ölçekte 105.000'i aşkın katılımcı, 200'den fazla ülkeden."
        ),
        impact_level="high",
        attendance=105000,
        demand_effect=(
            "Barselona'ya yılın en sert talep şoku. BCN hatlarında ücretler dört kata kadar çıkar, "
            "otel fiyatları aylar öncesinden katlanır; ek sefer kararı gerektirir."
        ),
    ),
    AviationEvent(
        name="IATA Dünya Kargo Sempozyumu 2027",
        starts=date(2027, 3, 9),
        ends=date(2027, 3, 11),
        city="Calgary",
        country="Kanada",
        region="north-america",
        url="https://www.iata.org/en/events/all/world-cargo-symposium/",
        summary=(
            "Hava kargo sektörünün yıllık buluşması Calgary'de; 2026 Lima "
            "edisyonu yaklaşık 1.200 delege ağırlamıştı."
        ),
        impact_level="medium",
        attendance=1200,
        demand_effect=(
            "Calgary'ye üç günlük kargo ve lojistik yöneticisi trafiği. Yolcu tarafında küçük bir "
            "etki, ama kargo kapasitesi kararlarının konuşulduğu hafta."
        ),
    ),
    AviationEvent(
        name="ITB Berlin 2027",
        starts=date(2027, 3, 16),
        ends=date(2027, 3, 18),
        city="Berlin",
        country="Almanya",
        region="europe",
        url="https://www.itb.com/",
        summary=(
            "Dünyanın en büyük turizm ticaret fuarı, Messe Berlin'de; yaz sezonu "
            "kontratlarının bağlandığı hafta."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Berlin'e mart ortasında üç günlük yoğun turizm trafiği. BER hatlarında doluluk "
            "yükselir; burada bağlanan kontratlar yaz kapasitesini belirler."
        ),
    ),
    AviationEvent(
        name="Uluslararası Bahçecilik Expo 2027 Yokohama",
        starts=date(2027, 3, 19),
        ends=date(2027, 9, 26),
        city="Yokohama",
        country="Japonya",
        region="asia",
        url="https://expo2027yokohama.or.jp/en/",
        summary=(
            "BIE onaylı A1 sınıfı bahçecilik sergisi, altı ay boyunca Yokohama'da. "
            "Ticari fuar değil halka açık bir sergi olduğu için takvimde festival "
            "olarak sınıflandırıldı."
        ),
        event_type="festival",
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Altı aya yayıldığı için tek bir zirve yaratmaz; Japonya'ya gelen turist talebine "
            "sezon boyunca sabit bir taban ekler."
        ),
    ),
    AviationEvent(
        name="Hannover Messe 2027",
        starts=date(2027, 4, 5),
        ends=date(2027, 4, 8),
        city="Hannover",
        country="Almanya",
        region="europe",
        url="https://www.hannovermesse.de/en/",
        summary=(
            "Endüstriyel teknolojinin dünya fuarı; yaklaşık 110.000 ziyaretçinin "
            "yarısından fazlası Almanya dışından geliyor."
        ),
        impact_level="high",
        attendance=110000,
        demand_effect=(
            "Hannover'in kendi havalimanı kapasitesi yetmez: talep HAJ kadar FRA, DUS ve HAM'a "
            "taşar. Bölge genelinde dört günlük ücret sertleşmesi."
        ),
    ),
    AviationEvent(
        name="HIMSS27",
        starts=date(2027, 4, 5),
        ends=date(2027, 4, 8),
        city="Şikago",
        country="ABD",
        region="north-america",
        url="https://www.himssconference.com/",
        summary=(
            "Sağlık bilişiminin yıllık küresel konferansı, yaklaşık 24.000 "
            "katılımcıyla Şikago'da."
        ),
        impact_level="medium",
        attendance=24000,
        demand_effect=(
            "Şikago'ya dört günlük kurumsal sağlık teknolojisi trafiği; ORD ölçeğinde doluluğa "
            "yansır, kapasite kararı gerektirmez."
        ),
    ),
    AviationEvent(
        name="Passenger Terminal EXPO 2027",
        starts=date(2027, 4, 6),
        ends=date(2027, 4, 8),
        city="Amsterdam",
        country="Hollanda",
        region="europe",
        url="https://www.passengerterminal-expo.com/",
        summary=(
            "Havalimanı terminal tasarımı, yolcu akışı ve teknolojilerinin fuarı; "
            "havalimanı işletmecileriyle tedarikçileri buluşturuyor."
        ),
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Amsterdam'a üç günlük havalimanı işletmeciliği trafiği. AIX ile aynı haftaya "
            "denk geldiği için Avrupa içi iş seyahatinde çift yoğunlaşma."
        ),
    ),
    AviationEvent(
        name="Salone del Mobile 2027",
        starts=date(2027, 4, 13),
        ends=date(2027, 4, 18),
        city="Milano",
        country="İtalya",
        region="europe",
        url="https://www.salonemilano.it/en",
        summary=(
            "Milano mobilya fuarı; organizatörün açıkladığı 2025 katılımı 316.342 "
            "kişi, üçte ikisi İtalya dışından."
        ),
        impact_level="high",
        attendance=316342,
        demand_effect=(
            "Milano'ya altı gün boyunca uluslararası tasarım ve satın alma trafiği. MXP ve LIN'de "
            "ücretler zirveye çıkar, otel fiyatları şehir çapında katlanır."
        ),
    ),
    AviationEvent(
        name="Eurovision Şarkı Yarışması 2027",
        starts=date(2027, 5, 11),
        ends=date(2027, 5, 15),
        city="Burgas",
        country="Bulgaristan",
        region="europe",
        url="https://www.ebu.ch/",
        summary=(
            "İki yarı final ve final; yarışma haftası boyunca delegasyonlar, "
            "basın ve taraftarlar ev sahibi şehirde toplanıyor."
        ),
        event_type="festival",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Burgas gibi küçük bir pazar için orantısız büyük bir talep: yarışma haftasında "
            "bölgedeki tüm hatlar dolar, talep İstanbul ve Sofya aktarmalarına taşar."
        ),
    ),
    AviationEvent(
        name="Hac 2027",
        starts=date(2027, 5, 14),
        ends=date(2027, 5, 19),
        city="Mekke",
        country="Suudi Arabistan",
        region="middle-east",
        url="https://www.officeholidays.com/holidays/saudi-arabia/eid-al-adha",
        summary=(
            "Hac dönemi (hilal gözlemine göre ±1 gün kayabilir). Asıl trafik bu "
            "beş güne değil, öncesindeki ve sonrasındaki haftalara yayılır."
        ),
        event_type="holiday",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Cidde ve Medine hatlarında yılın en yoğun dönemi; talep hac günlerine değil, "
            "öncesindeki ve sonrasındaki üçer haftaya yayılır ve tek yönlü doluluk yaratır."
        ),
    ),
    AviationEvent(
        name="Expo 2027 Belgrad",
        starts=date(2027, 5, 15),
        ends=date(2027, 8, 15),
        city="Belgrad",
        country="Sırbistan",
        region="europe",
        url="https://expo2027belgrade.rs/",
        summary=(
            "BIE onaylı uzmanlık expo'su, üç ay boyunca Belgrad'da. Ev sahibi "
            "4 milyonu aşkın ziyaretçi öngörüyor; bu bir projeksiyon olduğu için "
            "katılım alanına yazılmadı."
        ),
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Belgrad'a üç ay boyunca yayılmış ziyaretçi talebi. Tek zirve değil, yaz sezonu "
            "boyunca BEG hatlarında yükselmiş bir taban."
        ),
    ),
    # --- 2027 yaz istifi: Haziran sonu - Temmuz ortası ---
    AviationEvent(
        name="ASCO Yıllık Toplantısı 2027",
        starts=date(2027, 6, 4),
        ends=date(2027, 6, 8),
        city="Şikago",
        country="ABD",
        region="north-america",
        url="https://www.asco.org/annual-meeting",
        summary=(
            "Amerikan Klinik Onkoloji Derneği'nin yıllık toplantısı, yaklaşık "
            "35.000 katılımcıyla McCormick Place'te."
        ),
        impact_level="high",
        attendance=35000,
        demand_effect=(
            "Şikago'ya haziran başında uluslararası hekim akını. ORD hatlarında beş günlük "
            "doluluk ve ücret zirvesi; otel kapasitesi aylar öncesinden tükenir."
        ),
    ),
    AviationEvent(
        name="160. IATA Slot Konferansı",
        starts=date(2027, 6, 15),
        ends=date(2027, 6, 17),
        city="Viyana",
        country="Avusturya",
        region="europe",
        url="https://www.iata.org/en/events/all/iata-slot-conference-160/",
        summary=(
            "Havayolları ile slot koordinatörlerinin 2028 yaz tarifesi slotlarını "
            "pazarlık ettiği toplantı, Viyana'da."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Viyana'ya talep etkisi küçük; önemi çıktısında. Bir sonraki yaz sezonunun slotları "
            "burada dağıtılır ve tüm ağın kapasitesini belirler."
        ),
    ),
    AviationEvent(
        name="VivaTech 2027",
        starts=date(2027, 6, 16),
        ends=date(2027, 6, 19),
        city="Paris",
        country="Fransa",
        region="europe",
        url="https://vivatech.com/",
        summary=(
            "Avrupa'nın en büyük teknoloji ve girişimcilik etkinliği, Porte de "
            "Versailles'da; yaklaşık 200.000 katılımcı."
        ),
        impact_level="high",
        attendance=200000,
        demand_effect=(
            "Paris'e dört günlük yoğun teknoloji ve yatırımcı trafiği. CDG ve ORY'de haziran "
            "doluluğu zaten yüksekken ek baskı; ücretler belirgin sertleşir."
        ),
    ),
    AviationEvent(
        name="Afrika Uluslar Kupası 2027",
        starts=date(2027, 6, 19),
        ends=date(2027, 7, 17),
        city="Kenya, Tanzanya ve Uganda geneli",
        country="Kenya",
        region="africa",
        url="https://www.cafonline.com/caf-africa-cup-of-nations/",
        summary=(
            "Turnuva ilk kez üç ülke ortaklığında: Kenya, Tanzanya ve Uganda. "
            "Açılış ve final şehirleri henüz açıklanmadı, dolayısıyla talebin "
            "hangi havalimanında yoğunlaşacağı belirsiz."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Doğu Afrika'ya bir ay boyunca kıta çapında taraftar trafiği. NBO, DAR ve EBB "
            "arasındaki bölgesel hatlarda kapasite darboğazı beklenir."
        ),
    ),
    AviationEvent(
        name="Glastonbury 2027",
        starts=date(2027, 6, 23),
        ends=date(2027, 6, 27),
        city="Pilton",
        country="Birleşik Krallık",
        region="europe",
        url="https://www.glastonburyfestivals.co.uk/",
        summary=(
            "Worthy Farm'daki müzik festivali; biletler aylar önce tükeniyor ve "
            "katılımcıların önemli bölümü yurt dışından geliyor."
        ),
        event_type="festival",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Bristol ve Londra hatlarında festival öncesi ve sonrası iki günlük keskin talep; "
            "gidiş ve dönüş yönleri farklı günlerde zirve yapar."
        ),
    ),
    AviationEvent(
        name="Dünya Su Sporları Şampiyonası 2027",
        starts=date(2027, 6, 26),
        ends=date(2027, 7, 18),
        city="Budapeşte",
        country="Macaristan",
        region="europe",
        url="https://www.worldaquatics.com/competitions/1112/world-aquatics-championships-budapest-2027",
        summary=(
            "Yüzme, atlama, su topu ve açık su branşlarının dünya şampiyonası "
            "üç haftaya yayılıyor; Budapeşte'nin üçüncü ev sahipliği."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Budapeşte'ye üç hafta boyunca sporcu, federasyon ve seyirci trafiği. BUD hatlarında "
            "yaz sezonunun üstüne binen ek doluluk baskısı."
        ),
    ),
    AviationEvent(
        name="Wimbledon 2027",
        starts=date(2027, 6, 28),
        ends=date(2027, 7, 11),
        city="Londra",
        country="Birleşik Krallık",
        region="europe",
        url="https://www.wimbledon.com/",
        summary=(
            "Yılın üçüncü tenis grand slam'i, All England Club'da; iki hafta "
            "boyunca uluslararası seyirci ve kurumsal misafir trafiği."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Londra'ya iki hafta boyunca premium ağırlıklı seyirci trafiği. LHR'de yaz zirvesinin "
            "üstüne biner; ikinci hafta finallere doğru yoğunlaşır."
        ),
    ),
    AviationEvent(
        name="Tour de France 2027 Grand Départ (Britanya etapları)",
        starts=date(2027, 7, 2),
        ends=date(2027, 7, 4),
        city="Edinburgh",
        country="Birleşik Krallık",
        region="europe",
        url="https://letourgb.com/",
        summary=(
            "Turun açılışı Britanya'da yapılıyor. Yalnızca Britanya etaplarının "
            "tarihleri doğrulandı; tam rota ve bitiş takvimi açıklanmadığı için "
            "kayıt bu pencereyle sınırlı tutuldu."
        ),
        event_type="sports",
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Edinburgh ve kuzey İngiltere hatlarında üç günlük seyirci ve ekip trafiği; "
            "İskoçya'ya temmuz başı talebi öne çeker."
        ),
    ),
    # --- 2027 ikinci yarı ---
    AviationEvent(
        name="Pan Amerikan Oyunları 2027",
        starts=date(2027, 7, 23),
        ends=date(2027, 8, 8),
        city="Lima",
        country="Peru",
        region="south-america",
        url="https://www.panamsports.org/lima-2027/",
        summary=(
            "Kıtanın çok sporlu organizasyonu Lima'da, yaklaşık 6.900 sporcuyla. "
            "Takvim bir hafta ertelendi: daha önce duyurulan 16 Temmuz başlangıcı "
            "geçerli değil."
        ),
        event_type="sports",
        impact_level="high",
        attendance=6900,
        demand_effect=(
            "Lima'ya iki hafta boyunca kıta çapında kafile ve seyirci trafiği. LIM hatlarında "
            "Güney Amerika içi bağlantılarda belirgin doluluk artışı."
        ),
    ),
    AviationEvent(
        name="FISU Yaz Üniversite Oyunları 2027",
        starts=date(2027, 8, 1),
        ends=date(2027, 8, 12),
        city="Chungcheong",
        country="Güney Kore",
        region="asia",
        url="https://www.fisu.net/fisu-events/fisu-summer-world-university-games/",
        summary=(
            "Üniversite sporcularının yaz oyunları Güney Kore'nin Chungcheong "
            "bölgesinde; on iki günlük program."
        ),
        event_type="sports",
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Seul ve Incheon aktarmaları üzerinden kafile trafiği; ağustos yoğunluğunun üstüne "
            "sınırlı ama görünür bir ek talep."
        ),
    ),
    AviationEvent(
        name="Dünya Atletizm Şampiyonası 2027",
        starts=date(2027, 9, 11),
        ends=date(2027, 9, 19),
        city="Pekin",
        country="Çin",
        region="asia",
        url="https://worldathletics.org/competitions/world-athletics-championships/beijing27",
        summary=(
            "Atletizmin dünya şampiyonası Pekin'de; 2015'ten sonra şehrin ikinci "
            "ev sahipliği, dokuz günlük program."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Pekin'e dokuz gün boyunca federasyon, sporcu ve seyirci trafiği. PEK ve PKX "
            "hatlarında eylül ortasında belirgin doluluk artışı."
        ),
    ),
    AviationEvent(
        name="Ryder Cup 2027",
        starts=date(2027, 9, 13),
        ends=date(2027, 9, 19),
        city="Adare Manor (Limerick)",
        country="İrlanda",
        region="europe",
        url="https://www.rydercup.com/",
        summary=(
            "Avrupa-ABD golf karşılaşması İrlanda'da. Pencere hazırlık günlerini "
            "de kapsıyor: seyirci trafiği turnuva maçlarından günler önce başlar."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Shannon ve Dublin hatlarında bir hafta boyunca ABD çıkışlı yoğun talep. Bölgedeki "
            "konaklama kapasitesi yetersiz kaldığı için talep geniş bir alana yayılır."
        ),
    ),
    AviationEvent(
        name="Special Olympics Dünya Yaz Oyunları 2027",
        starts=date(2027, 10, 16),
        ends=date(2027, 10, 24),
        city="Santiago",
        country="Şili",
        region="south-america",
        url="https://www.santiago2027.org/en",
        summary=(
            "Oyunlar ilk kez Güney Amerika'da. Organizatör sporcu, antrenör, "
            "gönüllü ve refakatçi dahil yaklaşık 35.000 katılımcı bekliyor."
        ),
        event_type="sports",
        impact_level="high",
        attendance=35000,
        demand_effect=(
            "Santiago'ya dokuz gün boyunca dünya çapında kafile ve refakatçi trafiği. SCL "
            "hatlarında uzun menzilli bağlantılarda kapasite konusu."
        ),
    ),
    AviationEvent(
        name="Seoul ADEX 2027",
        starts=date(2027, 10, 19),
        ends=date(2027, 10, 24),
        city="Seul",
        country="Güney Kore",
        region="asia",
        url="https://www.seouladex.com/",
        summary=(
            "Kore'nin iki yılda bir düzenlenen havacılık ve savunma fuarı, "
            "Seongnam'daki askerî havaalanında."
        ),
        event_type="airshow",
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Seul'e savunma ve havacılık delegasyonu trafiği; ICN hatlarında premium kabinlerde "
            "bir haftalık yoğunlaşma."
        ),
    ),
    AviationEvent(
        name="NBAA-BACE 2027",
        starts=date(2027, 10, 19),
        ends=date(2027, 10, 21),
        city="Las Vegas",
        country="ABD",
        region="north-america",
        url="https://nbaa.org/events/2027-nbaa-business-aviation-convention-exhibition-nbaa-bace/",
        summary=(
            "Kuzey Amerika'nın en büyük iş havacılığı fuarı ve konferansının "
            "2027 edisyonu, yine Las Vegas'ta."
        ),
        impact_level="medium",
        attendance=None,
        demand_effect=(
            "Las Vegas'a iş jeti ve kurumsal havacılık trafiği; tarifeli hatlarda premium kabin "
            "talebi belirgin şekilde artar."
        ),
    ),
    AviationEvent(
        name="Ragbi Dünya Kupası 2027",
        starts=date(2027, 10, 1),
        ends=date(2027, 11, 13),
        city="Avustralya geneli",
        country="Avustralya",
        region="oceania",
        url="https://www.rugbyworldcup.com/2027",
        summary=(
            "İlk kez 24 takımla oynanacak turnuva altı haftaya yayılıyor; "
            "maçlar Avustralya'nın birçok şehrinde."
        ),
        event_type="sports",
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Avustralya'ya altı hafta boyunca Avrupa ve Güney Afrika çıkışlı uzun menzilli talep. "
            "Tek zirve değil, maç takvimine göre şehirler arası dalgalanma."
        ),
    ),
    AviationEvent(
        name="RSNA 2027",
        starts=date(2027, 11, 14),
        ends=date(2027, 11, 18),
        city="Şikago",
        country="ABD",
        region="north-america",
        url="https://www.rsna.org/annual-meeting/future-and-past-meetings",
        summary=(
            "RSNA'nın 2027 toplantısı, alışılmış Şükran Günü sonrası yerine iki "
            "hafta erkene alındı; organizatör kendi takviminde bu edisyonu "
            "istisna olarak işaretliyor."
        ),
        impact_level="high",
        attendance=None,
        demand_effect=(
            "Şikago'ya kasım ortasında uluslararası hekim trafiği. Bu edisyon Şükran Günü "
            "dalgasıyla çakışmıyor, dolayısıyla etkisi tek ve net bir pencere."
        ),
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
                    impact_level=event.impact_level,
                    attendance=event.attendance,
                    demand_effect_tr=event.demand_effect,
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
            existing.impact_level = event.impact_level
            existing.attendance = event.attendance
            existing.demand_effect_tr = event.demand_effect
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
            word_count=len(body.split()),
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
