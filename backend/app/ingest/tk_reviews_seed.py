"""Curated Turkish Airlines passenger reviews for the BİZ page.

Collected 2026-07-19 from public sources (all excerpts verified against the
live pages at the time of writing):
- Skytrax (airlinequality.com), pages 1-2 of the TK review listing -- dated,
  scored /10 reviews from June-July 2026.
- Reddit r/TurkishAirlines top-of-year RSS -- unscored experience threads.
- Apple App Store customer-review RSS (US+GB storefronts) -- only reviews that
  talk about the *flight* experience; app-only complaints were skipped, as was
  one review that opened with "here's a draft in your voice" (obviously
  machine-written).
Inaccessible at collection time (honest gaps): TripAdvisor (bot protection),
FlyerTalk (not attempted after rate limits).

Excerpts are deliberately 1-2 sentences (quotation with attribution, not
reproduction); excerpt_tr is a human-quality Turkish rendering written at
curation time, not machine-translated. Sentiment mix is the real distribution
found, not a curated balance. Idempotent by sha256(url + excerpt).
"""
import hashlib
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.tk_review import TkReview

logger = get_logger(__name__)

_SKYTRAX1 = "https://www.airlinequality.com/airline-reviews/turkish-airlines/"
_SKYTRAX2 = "https://www.airlinequality.com/airline-reviews/turkish-airlines/page/2/"
_APPSTORE = "https://apps.apple.com/us/app/turkish-airlines-book-flights/id1283414961"
_APPSTORE_GB = "https://apps.apple.com/gb/app/turkish-airlines-book-flights/id1283414961"


@dataclass(frozen=True)
class TkReviewSeed:
    source_name: str
    url: str
    excerpt: str
    excerpt_tr: str
    sentiment: str  # positive | neutral | negative
    themes: tuple[str, ...]  # slugs from app.models.tk_review.REVIEW_THEMES
    review_date: date | None = None
    rating: float | None = None  # normalized /10
    author: str | None = None
    route: str | None = None
    extra: dict = field(default_factory=dict)


REVIEWS: list[TkReviewSeed] = [
    # ---- Skytrax (airlinequality.com), /10 scores ----
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 7, 17), rating=9,
        author="Karim Fahim Fahim",
        excerpt="Onboard very clean cabin, friendly cabin crew, new A321 NEO, delicious catering, updated infotainment system.",
        excerpt_tr="Uçakta çok temiz bir kabin, güler yüzlü kabin ekibi, yeni A321neo, lezzetli ikram ve güncellenmiş eğlence sistemi.",
        sentiment="positive", themes=("cabin_crew", "food", "entertainment"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 7, 14), rating=1,
        author="Deane Nothard", route="JNB-IST",
        excerpt="Our flight to Istanbul from Durban/Johannesburg was delayed by over 12 hours and we missed our connecting flight.",
        excerpt_tr="Johannesburg-İstanbul uçuşumuz 12 saatten fazla rötar yaptı ve bağlantı uçuşumuzu kaçırdık.",
        sentiment="negative", themes=("delay", "ist_transfer"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 7, 3), rating=1,
        author="R Halsov",
        excerpt="Our flight was canceled by Turkish Airlines; the agent told us we either had to pay the fare difference or accept a full refund.",
        excerpt_tr="Uçuşumuz THY tarafından iptal edildi; temsilci ya fiyat farkı ödememizi ya da tam iade kabul etmemizi söyledi.",
        sentiment="negative", themes=("refund_service", "delay"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 7, 1), rating=8,
        author="Judy Hankin",
        excerpt="My return flights in business class were comfortable and service was attentive. My issue is entirely with the frequent flyer program.",
        excerpt_tr="Business dönüş uçuşlarım konforluydu, servis ilgiliydi. Tek sorunum sık uçan yolcu programıyla (Miles&Smiles).",
        sentiment="positive", themes=("cabin_crew", "miles_smiles"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 6, 23), rating=1,
        author="M Balinova", route="BUS-AMS",
        excerpt="They cancelled my original flight and moved it 12 hours earlier; their alternative created an impossible 15-hour layover in Istanbul.",
        excerpt_tr="Uçuşumu iptal edip 12 saat öne aldılar; önerdikleri alternatif İstanbul'da 15 saatlik imkânsız bir aktarma yarattı.",
        sentiment="negative", themes=("delay", "ist_transfer", "refund_service"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 6, 22), rating=1,
        author="N Tarzeni",
        excerpt="The cabin crew was not rude, but distant, inattentive and unhelpful. I am an older, visibly disabled passenger, yet no assistance was offered.",
        excerpt_tr="Kabin ekibi kaba değildi ama mesafeli, ilgisiz ve yardımsızdı. Yaşlı ve görünür engelli bir yolcuyum; kimse kendiliğinden yardım önermedi.",
        sentiment="negative", themes=("cabin_crew",),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 6, 16), rating=10,
        author="C Alper",
        excerpt="Amazing food, seats and crew. We got an upgrade from check in, and an amazing lounge experience as well.",
        excerpt_tr="Muhteşem yemek, koltuk ve ekip. Check-in'de upgrade aldık; lounge deneyimi de harikaydı.",
        sentiment="positive", themes=("food", "seat_comfort", "cabin_crew"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 6, 8), rating=10,
        author="Mahmud Noormohamed", route="ORD-IST",
        excerpt="Impressive business class product: 1-2-1 seating gives aisle access for each seat, the lie-flat seats are very comfortable, meals were excellent.",
        excerpt_tr="Etkileyici business ürünü: 1-2-1 düzen her koltuğa koridor erişimi veriyor, yataklı koltuklar çok rahat, yemekler mükemmeldi.",
        sentiment="positive", themes=("seat_comfort", "food"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX1, review_date=date(2026, 6, 8), rating=7,
        author="Mahmud Noormohamed",
        excerpt="Seating rather cramped on this high density route; since everyone boarded at the same time, the process was shambolic.",
        excerpt_tr="Bu yoğun hatta koltuklar epey dardı; herkes aynı anda bindiği için biniş süreci karman çormandı.",
        sentiment="neutral", themes=("seat_comfort",),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX2, review_date=date(2026, 6, 1), rating=7,
        author="Michael Little",
        excerpt="We needed to change the dates of our reward flights. The app and website experience was nightmarish; it took three hours -- longer than the flying time.",
        excerpt_tr="Ödül biletlerimizin tarihini değiştirmemiz gerekti. Uygulama ve site deneyimi kâbustu; üç saat sürdü — uçuş süresinden uzun.",
        sentiment="neutral", themes=("refund_service", "miles_smiles"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX2, review_date=date(2026, 6, 1), rating=1,
        author="Agne Gerasimaviciute",
        excerpt="My suitcase was damaged beyond repair. They first offered 21 EUR, then 40 EUR; my case was repeatedly closed without resolution.",
        excerpt_tr="Valizim onarılamayacak şekilde hasar gördü. Önce 21, sonra 40 euro önerdiler; dosyam defalarca çözümsüz kapatıldı.",
        sentiment="negative", themes=("baggage", "refund_service"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX2, review_date=date(2026, 5, 21), rating=3,
        author="E Nayanis", route="SIN-MUC",
        excerpt="My daughter's infotainment system did not work and was unable to be rebooted; on a long flight she was rather frustrated.",
        excerpt_tr="Kızımın eğlence sistemi çalışmadı ve yeniden başlatılamadı; uzun bir uçuşta epey moral bozucuydu.",
        sentiment="negative", themes=("entertainment",),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX2, review_date=date(2026, 5, 10), rating=1,
        author="See Ya Wanda Yuen", route="DBV-IST",
        excerpt="The ticketing staff told us 'you did not pay for your seats so you are not sitting together'.",
        excerpt_tr="Bilet gişesindeki görevli bize aynen 'koltuklarınıza ödeme yapmadınız, o yüzden yan yana oturmuyorsunuz' dedi.",
        sentiment="negative", themes=("value",),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX2, review_date=date(2026, 5, 6), rating=10,
        author="B Huang",
        excerpt="I accidentally left my watch behind after security; a senior Turkish Airlines staff member went out of their way to get it back to me before boarding.",
        excerpt_tr="Saatimi güvenlik sonrasında unutmuşum; kıdemli bir THY görevlisi biniş öncesi saatimi bana ulaştırmak için özel çaba gösterdi.",
        sentiment="positive", themes=("refund_service",),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX2, review_date=date(2026, 5, 3), rating=1,
        author="D Davis", route="IAH-ATH",
        excerpt="The food was not good, a flight attendant was rude and dismissive, and I paid $25 for Wi-Fi that didn't work.",
        excerpt_tr="Yemek iyi değildi, bir kabin görevlisi kaba ve umursamazdı; 25 dolar ödediğim Wi-Fi ise çalışmadı.",
        sentiment="negative", themes=("food", "cabin_crew", "entertainment"),
    ),
    TkReviewSeed(
        source_name="Skytrax", url=_SKYTRAX2, review_date=date(2026, 4, 24), rating=9,
        author="P Van", route="SYD-IST",
        excerpt="Overall, a great flying experience.",
        excerpt_tr="Genel olarak harika bir uçuş deneyimiydi.",
        sentiment="positive", themes=("cabin_crew",),
    ),
    # ---- Reddit r/TurkishAirlines (no scores) ----
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1s47y2e/spent_a_10hour_night_flight_standing_because_of_a/",
        review_date=date(2026, 3, 26), author="u/Radiant-Lobster-3681", route="JNB-IST",
        excerpt="I paid extra for seat 12G and spent almost the entire 10-hour flight standing in the galley and the aisles.",
        excerpt_tr="12G koltuğu için ekstra ödedim ama 10 saatlik uçuşun neredeyse tamamını galeride ve koridorlarda ayakta geçirdim.",
        sentiment="negative", themes=("seat_comfort", "cabin_crew"),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1op59ec/in_defence_of_turkish_airlines_from_a_loyal/",
        review_date=date(2025, 11, 5), author="u/Question_of_Surf",
        excerpt="Turkish Airlines is a fantastic company to fly with and I would recommend it to anyone. Business class on their modern aircraft is amazing.",
        excerpt_tr="THY uçmak için harika bir şirket, herkese tavsiye ederim. Modern uçaklarındaki business class muhteşem.",
        sentiment="positive", themes=("seat_comfort", "miles_smiles"),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1su3nul/turkish_airlines_made_economy_feel_premium_again/",
        review_date=date(2026, 4, 24), author="u/North_Rip4791", route="NCE-IST-MRU",
        excerpt="The real surprise was onboard, like old times: warm wet napkin, an actual amenity kit with a toothbrush.",
        excerpt_tr="Asıl sürpriz uçaktaydı, eski günlerdeki gibi: sıcak ıslak havlu, içinde diş fırçası olan gerçek bir seyahat kiti.",
        sentiment="positive", themes=("food", "seat_comfort"),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1pzkopt/my_experience_with_turkish_airlines_compensation/",
        review_date=date(2025, 12, 30), author="u/serpiente", route="CDG-IST-HKG",
        excerpt="Got EUR 1,200 (600 x 2 passengers) in about 3 weeks, but they made me work for it.",
        excerpt_tr="Yaklaşık 3 haftada 1.200 euro (yolcu başı 600) tazminat aldım ama epey uğraştırdılar.",
        sentiment="neutral", themes=("refund_service", "delay"),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1p60jvp/why_does_turkish_airlines_insist_on_dehydrating/",
        review_date=date(2025, 11, 25), author="u/ginjabeer", route="IST-SIN",
        excerpt="You're always given one 330ml bottle of water, and then spend the rest of the flight begging for more.",
        excerpt_tr="Hep tek bir 330 ml su veriliyor; uçuşun kalanını su isteyerek geçiriyorsunuz.",
        sentiment="negative", themes=("food",),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1shgqsy/42_calls_or_15h_11m_on_the_phone_to_get_turkish/",
        review_date=date(2026, 4, 10), author="u/seargeantcouscous",
        excerpt="42 calls or 15h 11m on the phone to get Turkish Airlines to rebook a cancelled flight. They closed my complaint without resolution.",
        excerpt_tr="İptal edilen uçuşun yeniden düzenlenmesi 42 telefon görüşmesi, toplam 15 saat 11 dakika sürdü. Şikayetimi de çözümsüz kapattılar.",
        sentiment="negative", themes=("refund_service",),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1sgxjc6/why_turkish_airlines_crew_is_borderline_rude/",
        review_date=date(2026, 4, 9), author="u/Overall-Concept6938",
        excerpt="I flew business class twice recently and both times the crew looked fed up and arrogant.",
        excerpt_tr="Son iki business uçuşumda da ekip bıkkın ve kibirli görünüyordu.",
        sentiment="negative", themes=("cabin_crew",),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1u6rd9r/turkish_in_flight_service/",
        review_date=date(2026, 6, 15), author="u/PlumMiddle9456",
        excerpt="The food in economy is wonderful -- compared to American and European airlines, Turkish comes in at number one.",
        excerpt_tr="Ekonomideki yemekler harika — Amerikan ve Avrupa havayollarıyla kıyaslayınca THY bir numara.",
        sentiment="positive", themes=("food", "cabin_crew"),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1ne9rdn/seat_43a_and_43c_a350_review/",
        review_date=date(2025, 9, 11), author="u/RepresentativeKick38", route="SIN-IST",
        excerpt="Only 2 seats so you don't have to worry about a random neighbour; recline is as good as any other standard economy seat.",
        excerpt_tr="Sadece 2 koltuk olduğundan rastgele bir komşu derdi yok; yatma açısı standart ekonomi koltukları kadar iyi.",
        sentiment="neutral", themes=("seat_comfort",),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1ttnrnt/layover_hotel_vouch_trip_report/",
        review_date=date(2026, 6, 1), author="u/Toolikethelightning",
        excerpt="I recently had a 20 hour layover in Istanbul and took up their offer for a free hotel night.",
        excerpt_tr="İstanbul'da 20 saatlik aktarmam vardı; ücretsiz otel gecesi teklifini kullandım.",
        sentiment="positive", themes=("ist_transfer",),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1r1bbjv/turkish_airlines_has_the_most_chaotic_boarding/",
        review_date=date(2026, 2, 10), author="u/Wild-Ad-2022",
        excerpt="One thing is so consistent at their home base: the worst possible boarding process. Lines aren't being respected.",
        excerpt_tr="Ana üslerinde değişmeyen tek şey var: olabilecek en kötü biniş süreci. Sıralara uyulmuyor.",
        sentiment="negative", themes=("ist_transfer",),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1uy6rt0/tk_istanbul_international_miles_and_smiles_lounge/",
        review_date=date(2026, 7, 16), author="u/fk067",
        excerpt="The renovated Miles&Smiles lounge area is freaking awesome -- plenty of room, new food like paninis, dedicated coffee stations.",
        excerpt_tr="Yenilenen Miles&Smiles lounge alanı harika olmuş — bol yer, panini gibi yeni yiyecekler, özel kahve istasyonları.",
        sentiment="positive", themes=("miles_smiles", "ist_transfer"),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1q2zoe2/never_flying_turkish_airlines_indigo_codeshare/",
        review_date=date(2026, 1, 3), author="u/No-Coconut-3700",
        excerpt="What should have been a manageable journey turned into a 54-hour nightmare, caused entirely by airline mismanagement and misinformation.",
        excerpt_tr="Yönetilebilir olması gereken yolculuk, tamamen havayolu kaynaklı yanlış yönetim ve yanlış bilgilendirme yüzünden 54 saatlik bir kâbusa döndü.",
        sentiment="negative", themes=("delay", "refund_service"),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1onu14n/forgot_laptop_on_plane_and_got_it_back_a_thank/",
        review_date=date(2025, 11, 4), author="u/lakedotcom", route="FCO-IST-JFK",
        excerpt="I left my laptop on board and got it back -- a thank you note for Turkish Airlines.",
        excerpt_tr="Dizüstü bilgisayarımı uçakta unuttum ve geri aldım — THY'ye bir teşekkür notu.",
        sentiment="positive", themes=("refund_service",),
    ),
    TkReviewSeed(
        source_name="Reddit r/TurkishAirlines",
        url="https://www.reddit.com/r/TurkishAirlines/comments/1mpzvdr/how_euro_business_should_be_done/",
        review_date=date(2025, 8, 14), author="u/DesperateVariation23",
        excerpt="First time flying TK in business. Loving the A321neo seat. European airlines take note -- this is how it's done!",
        excerpt_tr="TK ile ilk business uçuşum. A321neo koltuğuna bayıldım. Avrupa havayolları not alsın — bu iş böyle yapılır!",
        sentiment="positive", themes=("seat_comfort",),
    ),
    # ---- App Store (stars normalized x2 to /10) ----
    TkReviewSeed(
        source_name="App Store", url=_APPSTORE, rating=10, author="Malek Rabah",
        excerpt="I have been traveling with Turkish Airlines for years, taking long-haul flights across the seas. Your commitment to service is truly exceptional.",
        excerpt_tr="Yıllardır uzun menzilli uçuşlarımda THY ile seyahat ediyorum. Hizmete bağlılığınız gerçekten olağanüstü.",
        sentiment="positive", themes=("cabin_crew",),
    ),
    TkReviewSeed(
        source_name="App Store", url=_APPSTORE, rating=10, author="Meli2616",
        excerpt="It is more expensive than some similar airlines but the quality makes it worthwhile. Whenever I can afford it, I choose Turkish.",
        excerpt_tr="Benzer havayollarından biraz pahalı ama kalite buna değiyor. Gücüm yettiğinde hep THY'yi seçiyorum.",
        sentiment="positive", themes=("value",),
    ),
    TkReviewSeed(
        source_name="App Store", url=_APPSTORE_GB, rating=10, author="Dr Rastegar lari",
        excerpt="Turkish Airlines is my favorite airline in the world. The quality of service, comfort, reliability, and professionalism are truly exceptional.",
        excerpt_tr="THY dünyadaki favori havayolum. Hizmet kalitesi, konfor, güvenilirlik ve profesyonellik gerçekten olağanüstü.",
        sentiment="positive", themes=("cabin_crew", "value"),
    ),
    TkReviewSeed(
        source_name="App Store", url=_APPSTORE_GB, rating=10, author="emilsaa",
        excerpt="Yıllardan beri Türk Hava Yollarını kullanıyorum, hiç bir zaman mağduriyetim ve mutsuzluğum olmadı.",
        excerpt_tr="Yıllardan beri Türk Hava Yollarını kullanıyorum, hiç bir zaman mağduriyetim ve mutsuzluğum olmadı.",
        sentiment="positive", themes=("value",),
    ),
    TkReviewSeed(
        source_name="App Store", url=_APPSTORE, rating=10, author="Real Baba Agba",
        excerpt="Friendly crews and clean plane. Food so nice. Transit free hotel accommodation very smooth and easy.",
        excerpt_tr="Güler yüzlü ekipler, temiz uçak, çok iyi yemek. Ücretsiz transit otel konaklaması da çok kolay ve sorunsuzdu.",
        sentiment="positive", themes=("cabin_crew", "food", "ist_transfer"),
    ),
    TkReviewSeed(
        source_name="App Store", url=_APPSTORE_GB, rating=2, author="Andrea.B..",
        excerpt="Changing flights by days, not merely hours, is not acceptable. I've now incurred an extra 2 days of hotel costs.",
        excerpt_tr="Uçuşların saatlerle değil günlerle kaydırılması kabul edilemez. İki günlük ekstra otel masrafım oldu.",
        sentiment="negative", themes=("delay", "refund_service"),
    ),
    TkReviewSeed(
        source_name="App Store", url=_APPSTORE_GB, rating=2, author="Asuhel727",
        excerpt="Their website clearly states that passengers with over 20 hours of transit are eligible for a free hotel, but the staff completely ignored this policy.",
        excerpt_tr="Sitelerinde 20 saati aşan aktarmalarda ücretsiz otel hakkı yazıyor; ama personel bu kuralı tamamen görmezden geldi.",
        sentiment="negative", themes=("ist_transfer", "refund_service"),
    ),
    TkReviewSeed(
        source_name="App Store", url=_APPSTORE_GB, rating=2, author="TRK AM",
        excerpt="The airline blocks customers from using their miles as full or partial payment towards tickets. This is extremely disappointing.",
        excerpt_tr="Havayolu, millerin bilet ödemesinde tam ya da kısmi kullanılmasını engelliyor. Bu son derece hayal kırıklığı yaratıyor.",
        sentiment="negative", themes=("miles_smiles",),
    ),
]


def _dedupe_key(review: TkReviewSeed) -> str:
    return hashlib.sha256(f"{review.url}|{review.excerpt}".encode()).hexdigest()


async def seed_tk_reviews(db: AsyncSession) -> int:
    """Upsert the curated reviews. Idempotent by sha256(url+excerpt); existing
    rows get their curation fields refreshed so corrections propagate."""
    inserted = 0
    for review in REVIEWS:
        key = _dedupe_key(review)
        existing = (
            await db.execute(select(TkReview).where(TkReview.dedupe_key == key))
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                TkReview(
                    source_name=review.source_name,
                    url=review.url,
                    dedupe_key=key,
                    review_date=review.review_date,
                    rating=review.rating,
                    author=review.author,
                    route=review.route,
                    excerpt=review.excerpt,
                    excerpt_tr=review.excerpt_tr,
                    sentiment=review.sentiment,
                    themes=list(review.themes),
                )
            )
            inserted += 1
        else:
            existing.excerpt_tr = review.excerpt_tr
            existing.sentiment = review.sentiment
            existing.themes = list(review.themes)
            existing.rating = review.rating
            existing.review_date = review.review_date
            existing.route = review.route
    await db.commit()
    logger.info("tk_reviews_seeded", inserted=inserted, total=len(REVIEWS))
    return inserted
