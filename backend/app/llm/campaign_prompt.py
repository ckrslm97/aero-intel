"""The prompt for an airline's OWN campaign page, which is not an article.

llm/classify_prompt.py asks one question about one story: is this news, and if
it is a campaign, which campaign. A carrier's offers page answers neither
shape. Emirates' verified page carries twenty-two offer cards in one document;
there is no headline, no lede, no single subject, and the copy is marketing
rather than reporting ("Fırsatı kaçırma!", "Book by 31 Aug"). Feeding that to
the article prompt would produce one campaign per page -- twenty-one silently
discarded -- attributed to whichever offer the model read first.

So this prompt asks for a *list*, and it asks the model to quote.

**The evidence requirement is the point.** Every non-null date, discount and
route field must come with a short verbatim quote from the page in
`source_text`. Two things follow from it. The reader gets a citation instead of
a number (promotions.evidence_json is rendered in the drawer). And the
extraction chain gets something it can check: pipeline/campaign_extract.py
re-reads every quoted date with the deterministic regex layer, and a date that
appears in no quote and nowhere on the page is dropped rather than published.
A model that has to quote is measurably less willing to invent.

**Years are never guessed here.** A page that says "30 Kasım'a kadar" with no
year is the single most common shape in campaign copy, and the temptation is to
let the model complete it. It must not: the model does not know when the page
was fetched, so its guess is arbitrary, while the chain knows the scan date and
records the completion as `date_flags_json.inferred_year` so the drawer can
warn. The contract is therefore explicit and narrow:

    booking_start / booking_end / travel_start / travel_end
        ISO YYYY-MM-DD, and ONLY when the year is written on the page.
    date_text.{booking_start, ...}
        the date exactly as the page writes it, whenever the year is missing
        (or the date is otherwise not expressible as ISO).

Either field may be null; both being null means the page does not state that
edge. The chain resolves `date_text` through pipeline/promotions.find_dates_flagged
with the scan year as the default, and flags what it had to infer.

The booking/travel split is spelled out in full because conflating the two is
the failure the whole four-column schema exists to prevent: booking is when a
ticket can be BOUGHT, travel is when it can be FLOWN, and "Book by 31 December
for travel until 31 March" is two windows, not one fifteen-month window.

**The ticketing and campaign windows are opt-in, not defaults.** Some copy
distinguishes a third and fourth window -- a ticketing deadline on a fare you
can hold and pay for later, an announced "kampanya dönemi" wider than the sale
itself. Rule 2b asks for those only when the page states them *separately and
explicitly*, and says outright that a page giving one window is giving the
booking window. The reason is the same one behind the year rule: a model that
is allowed to fill a field "because it is probably the same" produces a
deadline nobody wrote, and a deadline is drawn as the end of a bar.
"""
from __future__ import annotations

from app.taxonomy import CAMPAIGN_BUSINESS_CLASSES, CAMPAIGN_TYPES, ROUTE_SCOPES

#: Page characters sent to the model. An offers page is mostly navigation,
#: footer and legal boilerplate; the offer cards themselves are a few thousand
#: characters even when there are twenty of them, and deep_scan already narrows
#: to the campaign blocks where a carrier's selector is known
#: (carriers.py block_selector). Generous enough for the whole-body case,
#: bounded because the Groq free tier is a token ceiling before it is a request
#: ceiling.
MAX_PAGE_CHARS = 6000

#: Appended when the cap bites, so the model knows the page is cut rather than
#: finished -- otherwise a truncated last card reads as a campaign with missing
#: fields and gets extracted with half its dates.
TRUNCATION_MARKER = "\n\n[… sayfa metni bu noktada kesildi …]"


def _enum_list(values: tuple[str, ...]) -> str:
    return " | ".join(values)


def build_campaign_page_prompt(
    carrier_code: str,
    carrier_name: str,
    page_url: str,
    page_text: str,
) -> str:
    """The full prompt for one carrier campaign page.

    `carrier_code`/`carrier_name` are stated rather than asked for: this page
    was fetched from that carrier's own domain (app/ingest/carriers.py), so the
    operator is a fact, not an inference. The chain still verifies the model did
    not name a different airline -- see campaign_extract's entity validation --
    but nothing is gained by making the model guess what the fetcher already
    knows.
    """
    body = (page_text or "").strip()
    if len(body) > MAX_PAGE_CHARS:
        body = body[:MAX_PAGE_CHARS] + TRUNCATION_MARKER

    return f"""Sen bir havayolu gelir yönetimi masası için çalışan bir kampanya
analistisin. Aşağıdaki metin {carrier_name} ({carrier_code}) havayolunun KENDİ
resmî kampanya sayfasından alınmıştır. Sayfada birden fazla kampanya olabilir.
SADECE geçerli JSON döndür. Açıklama, markdown veya kod bloğu ekleme.

EN ÖNEMLİ KURAL: Sayfada YAZMAYAN hiçbir şeyi yazma. Bir alan metinde açıkça
belirtilmemişse null bırak. Eksik bir alan, uydurulmuş bir alandan her zaman
iyidir. Tarih, indirim oranı, rota ve fiyat uydurmak bu görevdeki en ağır
hatadır.

JSON şeması:

{{
  "campaigns": [
    {{
      "campaign_name": "kampanyanın sayfada geçen adı/başlığı",
      "campaign_type": null | {_enum_list(CAMPAIGN_TYPES)},
      "is_fare_campaign": true|false,
      "business_class_hint": null | {_enum_list(CAMPAIGN_BUSINESS_CLASSES)},
      "booking_start": null | "YYYY-AA-GG",
      "booking_end": null | "YYYY-AA-GG",
      "travel_start": null | "YYYY-AA-GG",
      "travel_end": null | "YYYY-AA-GG",
      "ticketing_start": null | "YYYY-AA-GG",
      "ticketing_end": null | "YYYY-AA-GG",
      "campaign_start": null | "YYYY-AA-GG",
      "campaign_end": null | "YYYY-AA-GG",
      "date_text": {{
        "booking_start": null | "sayfada yazdığı gibi",
        "booking_end": null | "sayfada yazdığı gibi",
        "travel_start": null | "sayfada yazdığı gibi",
        "travel_end": null | "sayfada yazdığı gibi",
        "ticketing_start": null | "sayfada yazdığı gibi",
        "ticketing_end": null | "sayfada yazdığı gibi",
        "campaign_start": null | "sayfada yazdığı gibi",
        "campaign_end": null | "sayfada yazdığı gibi"
      }},
      "discount_pct": null | 1-100,
      "price_floor": null | sayı,
      "currency": null | "TRY" | "USD" | "EUR" | "AED" | ...,
      "promo_code": null | "promosyon kodu",
      "cabin": null | "Economy" | "Business" | "Premium Economy" | "First",
      "origin": null | "metinde YAZDIĞI gibi kalkış yeri",
      "destination": null | "metinde YAZDIĞI gibi varış yeri",
      "route_scope_hint": null | {_enum_list(ROUTE_SCOPES)},
      "eligibility": null | "kimler yararlanabilir (tek cümle)",
      "sales_channel": null | "web" | "mobil uygulama" | "çağrı merkezi" | ...,
      "source_text": {{
        "booking_start": "sayfadan kısa birebir alıntı",
        "booking_end": "...",
        "travel_start": "...",
        "travel_end": "...",
        "discount_pct": "...",
        "price_floor": "...",
        "origin": "...",
        "destination": "..."
      }}
    }}
  ]
}}

KURALLAR

1. LİSTE: Sayfadaki HER kampanya için bir nesne döndür. Sayfada hiç kampanya
   yoksa "campaigns": [] döndür — bu doğru bir cevaptır, uydurma.

2. SATIŞ (booking) ve SEYAHAT (travel) DÖNEMİ AYRI ŞEYLERDİR ve asla
   birbirinin yerine yazılmaz:
   - booking_start / booking_end: biletin SATIN ALINABİLECEĞİ dönem. "Son
     rezervasyon", "31 Ağustos'a kadar alın", "Book by 31 Aug", "satış dönemi".
   - travel_start / travel_end: biletle UÇULABİLECEĞİ dönem. "Seyahat dönemi",
     "1 Ekim - 30 Kasım arasında uçun", "travel between".
   "Book by 31 December for travel until 31 March" iki ayrı penceredir; tek bir
   pencere olarak birleştirme.

2b. BİLETLEME ve KAMPANYA DÖNEMİ: Bu iki alan çifti YALNIZCA sayfa bunları
   satış döneminden AYRI ve AÇIKÇA yazıyorsa doldurulur. Emin değilsen null.
   - ticketing_start / ticketing_end: biletin DÜZENLENMESİ / ödemenin
     tamamlanması gereken dönem. Yalnızca "biletleme dönemi", "biletlemenin
     ... tarihine kadar tamamlanması", "ticketing deadline", "tickets must be
     issued by" gibi açık bir ifade varsa yaz.
   - campaign_start / campaign_end: sayfanın kampanyanın kendi süresi olarak
     ilan ettiği dönem. Yalnızca "kampanya dönemi", "kampanya ... tarihleri
     arasında geçerlidir", "campaign period", "offer valid from ... to ..."
     gibi açık bir ifade varsa yaz.
   Sayfa tek bir tarih aralığı veriyorsa o aralık SATIŞ dönemidir
   (booking_start/booking_end) — bu dört alanı DOLDURMA, null bırak.
   Satış dönemini bu alanlara KOPYALAMA; "aynı olabilir" diye yazma. Bu dört
   alanın null olması normaldir ve sayfaların büyük çoğunluğunda doğru cevaptır.

3. YIL: Bir tarihi ISO alanına (booking_end vb.) YALNIZCA yılı sayfada
   yazıyorsa yaz. Yıl yazmıyorsa ISO alanını null bırak ve tarihi
   date_text içine sayfada yazdığı gibi kopyala ("30 Kasım'a kadar", "Book by
   28 Aug"). Yıl TAHMİN ETME — hangi yılda olduğumuzu bu metinden bilemezsin.

4. source_text: Null OLMAYAN her tarih, indirim, fiyat ve rota alanı için
   sayfadan kısa (en fazla bir cümle) BİREBİR alıntı ver. Alıntıyı kendi
   cümlenle yeniden yazma; kopyala. Alıntı veremiyorsan o alanı null bırak.

5. ROTA: origin ve destination'ı metinde YAZDIĞI gibi ver — havalimanı kodu
   ("IST"), şehir ("İstanbul", "London"), ülke ("Türkiye") veya bölge
   ("Avrupa") olabilir. Çeviri yapma, kod uydurma, şehir tahmin etme.
   - Görsel, afiş veya arka plan tasvirinden rota çıkarma. Kampanyada bir
     şehrin fotoğrafı olması o şehre uçuş kampanyası olduğu anlamına gelmez.
   - Metin "tüm uçuşlarda", "tüm hatlarda", "all destinations" diyorsa origin
     ve destination null, route_scope_hint = "NETWORK_WIDE".
   - Bölgesel bir kampanyayı ("Avrupa'ya") tek tek şehir çiftlerine AÇMA.

6. discount_pct: Yalnızca metinde açıkça yazan indirim oranı ("%40'a varan" ->
   40). Bir fiyat, bir yüzde artışı veya bir doluluk oranı indirim değildir.
   price_floor: yalnızca "9 Euro'dan başlayan" gibi açık bir taban fiyat;
   currency olmadan price_floor verme.

7. is_fare_campaign: Bilet ücretine yönelik bir kampanya mı? Bagaj, lounge,
   otel, araç kiralama, mil/puan kampanyaları ve öğrenci/kurumsal/65 yaş gibi
   SÜREKLİ geçerli standart teklifler ücret kampanyası DEĞİLDİR — bunları yine
   de listele, ama is_fare_campaign=false ve uygun business_class_hint ile.
   TEK İSTİSNA: ek hizmet teklifi açıkça bir UÇUŞ SATIN ALMA koşuluna
   bağlıysa ("bilet alana ücretsiz ekstra bagaj", "uçuşunuzu satın aldığınızda
   lounge hediye", "when you book a flight"), bu bir uçuş kampanyasının
   parçasıdır: campaign_type = "ANCILLARY_PROMOTION" ve is_fare_campaign=true
   yaz. Uçuş satın alma koşulu YOKSA (bağımsız lounge/otel/araç kampanyası)
   istisna geçerli değildir.

8. campaign_type: Yalnızca yukarıdaki listeden bir değer. Hiçbiri uymuyorsa
   "OTHER". Liste dışı bir değer uydurma.

KAYNAK: {page_url}

SAYFA METNİ:
{body}

JSON:"""
