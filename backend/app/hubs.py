"""Reference data for the hubs this desk watches.

Two consumers, one table: the Hub Explorer page needs the facts (who is based
there, what the airport is for), and the world map needs the coordinates. They
were going to drift apart as two lists, so they are one.

Deliberately not a database table. These are geographic facts that change on
the scale of decades, they are needed to *render* a page rather than to filter
one, and putting them in Postgres would mean a migration and a seed job for
data that is more reliably reviewed in a diff.

Scope: Istanbul and the two Turkish airports first, then every main rival's
base, then the hubs that show up in connecting-traffic decisions. Adding one is
a four-line entry -- but only add hubs whose IATA code the gazetteer can
actually recognise in text (app/llm/gazetteer.py AIRPORTS), or the page will
render with a permanent zero.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Hub:
    code: str  # IATA
    name: str
    city: str
    country: str  # matches gazetteer COUNTRIES keys, title-cased
    region: str  # app/taxonomy.py region slug
    lat: float
    lon: float
    carriers: tuple[str, ...]  # IATA codes based here
    note_tr: str  # why a revenue-management desk cares


HUBS: tuple[Hub, ...] = (
    Hub(
        "IST", "İstanbul Havalimanı", "İstanbul", "Turkey", "europe", 41.275, 28.752,
        ("TK",),
        "Türk Hava Yolları'nın ana üssü ve aktarma modelinin merkezi. Avrupa, Orta Doğu "
        "ve Asya arasındaki bağlantı trafiğinin büyük bölümü buradan geçiyor.",
    ),
    Hub(
        "SAW", "Sabiha Gökçen", "İstanbul", "Turkey", "europe", 40.899, 29.309,
        ("PC",),
        "Pegasus'un üssü. İstanbul'un ikinci havalimanı olarak düşük maliyetli trafiğin "
        "fiyat tabanını belirliyor — iç hat ve kısa mesafe Avrupa'da doğrudan rakip.",
    ),
    Hub(
        "DXB", "Dubai Uluslararası", "Dubai", "United Arab Emirates", "middle-east",
        25.253, 55.365, ("EK",),
        "Emirates'in üssü ve IST'in aktarma trafiğindeki en büyük rakibi. Avrupa–Asya "
        "akışında doğrudan aynı yolcuyu hedefliyor.",
    ),
    Hub(
        "AUH", "Abu Dabi Zayed", "Abu Dabi", "United Arab Emirates", "middle-east",
        24.433, 54.651, ("EY",),
        "Etihad'ın üssü. Körfez'deki üçlü rekabetin (EK/QR/EY) bir ayağı.",
    ),
    Hub(
        "DOH", "Hamad Uluslararası", "Doha", "Qatar", "middle-east", 25.273, 51.608,
        ("QR",),
        "Qatar Airways'in üssü. Uzun menzilli tarifede IST ile en çok örtüşen ağ.",
    ),
    Hub(
        "LHR", "Londra Heathrow", "Londra", "United Kingdom", "europe", 51.470, -0.454,
        ("BA",),
        "British Airways'in üssü ve Kuzey Atlantik'in en yüksek getirili ucu. Slot "
        "kısıtı fiyatlamayı doğrudan etkiliyor.",
    ),
    Hub(
        "LGW", "Londra Gatwick", "Londra", "United Kingdom", "europe", 51.148, -0.190,
        (),
        "Londra'nın ikinci havalimanı; tatil ve düşük maliyetli trafiğin ağırlıkta "
        "olduğu, LHR'den ayrı bir fiyat seviyesi.",
    ),
    Hub(
        "CDG", "Paris Charles de Gaulle", "Paris", "France", "europe", 49.010, 2.548,
        ("AF",),
        "Air France'ın üssü, SkyTeam'in Avrupa merkezi. Afrika bağlantılarında güçlü.",
    ),
    Hub(
        "AMS", "Amsterdam Schiphol", "Amsterdam", "Netherlands", "europe", 52.309, 4.764,
        ("KL",),
        "KLM'in üssü. Aktarma odaklı yapısıyla IST'e en çok benzeyen Avrupa hub'ı.",
    ),
    Hub(
        "FRA", "Frankfurt", "Frankfurt", "Germany", "europe", 50.037, 8.562, ("LH",),
        "Lufthansa'nın üssü ve Avrupa'nın en yoğun kurumsal trafik merkezi. İş "
        "seyahatinde yüksek getiri.",
    ),
    Hub(
        "JFK", "New York JFK", "New York", "United States", "north-america",
        40.641, -73.778, (),
        "Kuzey Atlantik'in en rekabetçi ucu. TK'nın ABD ağındaki en büyük pazarı.",
    ),
    Hub(
        "ATL", "Atlanta Hartsfield-Jackson", "Atlanta", "United States", "north-america",
        33.640, -84.427, (),
        "Dünyanın en yoğun havalimanı; ABD iç hat besleme trafiğinin merkezi.",
    ),
    Hub(
        "ORD", "Chicago O'Hare", "Chicago", "United States", "north-america",
        41.978, -87.904, (),
        "ABD'nin ikinci büyük aktarma merkezi; Avrupa'ya doğrudan trafiğin ağırlıklı ucu.",
    ),
    Hub(
        "LAX", "Los Angeles", "Los Angeles", "United States", "north-america",
        33.942, -118.408, (),
        "Pasifik geçişinin batı ucu; uzun menzilli tarifede Asya bağlantılarını besliyor.",
    ),
    Hub(
        "SIN", "Singapur Changi", "Singapur", "Singapore", "southeast-asia",
        1.364, 103.991, (),
        "Güneydoğu Asya'nın aktarma merkezi; kabin ürünü karşılaştırmalarında referans.",
    ),
    Hub(
        "HKG", "Hong Kong", "Hong Kong", "China", "asia", 22.308, 113.918, (),
        "Kargo hacminde dünyanın en büyüklerinden; Çin trafiğinin dışa açılan kapısı.",
    ),
    Hub(
        "HND", "Tokyo Haneda", "Tokyo", "Japan", "asia", 35.549, 139.780, (),
        "Tokyo'nun şehre yakın havalimanı; slotları kısıtlı, iş trafiği yoğun.",
    ),
    Hub(
        "NRT", "Tokyo Narita", "Tokyo", "Japan", "asia", 35.772, 140.393, (),
        "Tokyo'nun uzun menzilli ve düşük maliyetli trafiği ağırlıklı ikinci havalimanı.",
    ),
    Hub(
        "SYD", "Sydney Kingsford Smith", "Sydney", "Australia", "oceania",
        -33.946, 151.177, (),
        "Okyanusya'nın ana kapısı; ultra uzun menzil tartışmalarının merkezinde.",
    ),
)

HUBS_BY_CODE: dict[str, Hub] = {hub.code: hub for hub in HUBS}
