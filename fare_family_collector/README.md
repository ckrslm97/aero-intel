# ✈ Fare Family Collector

Havayolu **ücret paketlerini (Fare Family / Fare Brand)** OND (Origin-Destination)
listesi üzerinden otomatik toplayan, **hem masaüstü uygulaması hem paylaşılabilir
HTML paneli** olan profesyonel bir sistem.

- **Masaüstü:** Python · Playwright · CustomTkinter · pandas · Excel/CSV/SQLite
- **Panel:** Tek dosyalık, koyu temalı, canlı yenilenen HTML terminal (`web/index.html`)

---

## İçindekiler

- Fare Intelligence Platform Özellikleri (v2)

- [Mimari](#mimari)
- [Kurulum](#kurulum)
- [Kullanım](#kullanım)
- [HTML Paneli (paylaşımlı & canlı)](#html-paneli)
- [Yeni Havayolu Ekleme](#yeni-havayolu-ekleme)
- [Yapılandırma](#yapılandırma)
- [Önemli Not: Gerçek Scraper'lar](#önemli-not)

---

## Mimari

```
fare_family_collector/
├── main.py                 # Giriş noktası (GUI / CLI / demo)
├── config.py               # Tüm ayarlar + .env desteği (magic number yok)
├── core/
│   ├── models.py           # FareBrand, FareFeature, RunSummary (tek satır = tek paket)
│   ├── ond.py              # OND modeli + CSV/Excel yükleyici
│   ├── selectors.py        # Merkezi CSS/XPath kaydı + çerez (consent) aday seçicileri
│   ├── exporter.py         # Excel / CSV / SQLite / JSON çıktı
│   ├── async_engine.py     # Tek tarayıcı + çok sekme (async) toplama motoru + girdi doğrulama
│   ├── verify.py           # Form girdisi oku-geri doğrulama eşleştiricisi (input_matches)
│   ├── runner.py           # API → tarayıcı(çok-sekme) → OTA orkestrasyonu + resume
│   └── logging_config.py   # Dosya + canlı GUI log kuyruğu
├── apis/                    # Resmi HTTP/JSON API kaynakları (canlıda ÖNCE denenir)
│   ├── base.py             # FareAPIProvider + registry (token yoksa sessiz atla)
│   ├── duffel.py           # Duffel Offers API (fare brand + koşullar + bagaj)
│   └── amadeus.py          # Amadeus Flight Offers Search (branded fares)
├── scrapers/
│   ├── base.py             # BaseScraper — sağlam çerez onayı, form-hazır bekleme, ortak arama/DOM şablonu
│   ├── registry.py         # Kod → scraper otomatik eşleme
│   ├── demo.py             # Gerçekçi sahte veri (uçtan uca test için)
│   ├── tk.py af.py lh.py   # Turkish / Air France / Lufthansa (API→HTML)
│   ├── ba.py pc.py         # British Airways / Pegasus (paylaşımlı şablon)
│   └── ota_*.py            # Google Flights / Kayak (OTA yedeği)
├── gui/
│   ├── app.py              # CustomTkinter arayüz
│   └── theme.py            # Koyu tema paleti
├── web/
│   └── index.html          # Paylaşılabilir canlı panel (tek dosya)
├── data/
│   └── ond_example.csv     # Örnek OND listesi (prompttaki tablo)
└── output/                 # Excel/CSV/SQLite/JSON + data.json (panel bunu okur)
```

Her scraper `BaseScraper`'tan türer ve **bağımsızdır**. Yeni bir havayolu eklemek
yalnızca yeni bir dosya + registry kaydı gerektirir.

### Çerez onayı, form-hazır bekleme ve çok-sekme eşzamanlılık

Canlı toplamada iki yaygın hata `BaseScraper` + `async_engine` içinde tek yerde
çözülür:

- **Çerez/onay banner'ı** (`accept_cookies`): banner geç belirse veya bir
  **iframe** içinde (OneTrust/Didomi/Usercentrics/Cookiebot) olsa bile atlatılır.
  Aday seçiciler `core/selectors.py` içindeki site bloğu + ortak CMP yedeklerinden
  (`COMMON_CONSENT_FALLBACKS`) gelir; ayrıca "Accept all/Agree/Kabul et" gibi buton
  metinleri rol tabanlı son çare olarak denenir.
- **Sayfa yüklenmeden input'a yazma** (`wait_for_ready`): arama alanı görünür
  olmadan form doldurulmaz; böylece SPA render'ı beklenir ve overlay input'u
  kapatmaz.

**Çok-sekme motoru** (`core/async_engine.py`): aynı **taşıyıcı + tarih** için
birden çok rota, **tek tarayıcı bağlamında** ve **eşzamanlı sekmelerle** çekilir.
Çerez bir kez (bağlam düzeyinde) kabul edilir; sonraki sekmeler banner görmez.
Sekme sayısı `PAGES_PER_BROWSER` ile, paralel işlenen taşıyıcı grubu sayısı
`MAX_WORKERS` ile ayarlanır. Havayolu sitesinden veri gelmezse OTA yedeği devreye
girer. Demo modu bu motoru kullanmaz (sync, çevrimdışı).

### Resmi API kaynakları (Duffel / Amadeus) — önerilen

Fare-family verisi için en güvenilir yol tarayıcı değil **resmi API**'dir (anti-bot/
çerez/dinamik yükleme yok). Canlı modda kaynak sırası:

1. **Resmi API'ler** (`apis/`): kimlik bilgisi tanımlıysa OND başına denenir.
   - **Duffel** (`apis/duffel.py`): Offers API → fare brand, kabin, fiyat, iade/
     değişiklik koşulları, bagaj. `.env`: `DUFFEL_ACCESS_TOKEN` (+ `DUFFEL_API_VERSION`).
   - **Amadeus** (`apis/amadeus.py`): Flight Offers Search (branded fares) → marka,
     kabin, sınıf, dahil bagaj. `.env`: `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET`
     (+ `AMADEUS_ENV=test|production`).
   - Token yoksa sağlayıcı **sessizce atlanır** — akış bozulmaz.
2. Veri gelmezse **havayolu sitesi** (çok-sekme tarayıcı motoru).
3. O da olmazsa **OTA** (Google/Kayak).

Yeni API eklemek: `apis/xx.py` içinde `FareAPIProvider`'dan türet, `@register_api`
ile kaydet, `available()` ve `fetch()` doldur; `API_SOURCES` listesine adını ekle.

### Girdi doğruluğu kontrolü

Tarayıcı formuna girilen değerler **oku-geri** ile doğrulanır (`core/verify.py`,
`input_matches`): alan doldurulduktan sonra `input_value` okunur ve girilen kod/
tarih alanda yansıyor mu bakılır. Otomatik-tamamlama dönüşümleri (`IST` →
`Istanbul (IST)`, `2026-08-01` → `01 Aug 2026`) toleranslıdır. Boş kalan/uyuşmayan
alanlarda bir kez daha (temizle + karakter karakter yaz) denenir ve sonuç loglanır.
Arama sonrası sonuç sayfasının istenen rotayı yansıtıp yansıtmadığı da kontrol edilir.

### Canlı çalıştırma (örnek komutlar)

```bash
# Sadece resmi API (en güvenilir) — tarayıcı gerekmez:
export DUFFEL_ACCESS_TOKEN=duffel_test_xxx
python main.py --routes "TK:IST-LHR,TK:IST-CDG,TK:IST-FRA"

# API + tarayıcı (çok-sekme) + OTA zinciri (varsayılan canlı davranış):
python main.py --cli data/ond_example.csv

# Girdi doğrulama uyarılarını görmek için logs/ altındaki log dosyasına bakın.
```

---

## Kurulum

```bash
# 1) Bağımlılıklar
pip install -r requirements.txt

# 2) Playwright tarayıcısı (gerçek scraping için)
playwright install chromium

# 3) (Opsiyonel) ayarlar
cp .env.example .env
```

---

## Kullanım

### Masaüstü arayüz (GUI)

```bash
python main.py
```

Arayüzden:
1. **OND Listesini Yükle** → CSV/Excel seç (`AIRLINE | ORIGIN | DESTINATION`)
2. Filtreler, uçuş tarihi, headless/normal mod, thread sayısı, resume ayarla
3. **START** → tüm OND'ler paralel işlenir; sağda canlı log, altta ilerleme çubuğu
4. Bitince Excel/CSV/SQLite/JSON `output/`'a yazılır; **HTML Panelini Aç** ile görüntüle

### Komut satırı (arayüzsüz — sunucu/cron için)

```bash
python main.py --cli data/ond_example.csv              # verilen listeyi gerçek scraper'larla işle
python main.py --cli data/ond_example.csv --demo-mode  # canlı istek atmadan sahte veri üret
python main.py --demo                                   # örnek liste + sahte veri (tam çevrimdışı)
```

> **Çevrimdışı demo:** `--demo` (ve `--demo-mode`) hiçbir canlı istek atmaz;
> tüm havayolları için — kayıtlı gerçek scraper'ı olsa bile — `DemoScraper`
> devreye girer. Böylece Playwright kurulu olmasa dahi uygulama uçtan uca
> **hatasız** çalışır, tüm export biçimleri ve HTML paneli üretilir.
> Aynı davranış `.env` içinde `DEMO_MODE=true` veya GUI'deki "Demo modu"
> anahtarıyla da açılabilir.

### Canlı (gerçek) çalışma

Canlı modda (demo kapalı) her OND için sırayla:

1. **Havayolunun kendi sitesi** — kayıtlı gerçek scraper varsa (bugün **TK,
   AF, LH**). Her scraper **otomatik** çalışır: önce sitenin XHR/JSON (network)
   yanıtları yakalanır, bulunamazsa görünür fare kartları DOM'dan okunur.
2. **OTA yedeği** — havayolu sitesine erişilemezse (anti-bot/boş sonuç) ya da
   havayolunun kayıtlı scraper'ı yoksa, sırayla **OTA** kaynakları denenir
   (varsayılan: Google Flights → Kayak). İlk veri dönen kaynak kullanılır.

Her kayıtta veri kaynağı **`Source`** alanında saklanır (`TK-site`,
`ota:google`, `demo`…) ve hem çıktı tablolarında hem GUI'de görünür.

```bash
# Canlı, dosyadan:
python main.py --cli data/ond_example.csv
# Canlı, satır içi rota (dosyasız):
python main.py --routes "TK:IST-LHR,AF:CDG-JFK,TK/AF:IST-CDG"
# Dosya + satır içi birlikte, OTA yedeği kapalı:
python main.py --cli routes.xlsx --routes "LH:FRA-JFK" --no-ota
```

> Canlı scraping için: `pip install playwright && playwright install chromium`.
> Havayolu siteleri ve OTA'lar anti-bot koruması içerir; `core/selectors.py`
> içindeki seçici/URL desenleri `playwright codegen <site>` ile doğrulanmalıdır.

### Dinamik giriş — GUI ve Excel

- **GUI'de elle:** Sol panelde **Rota Oluşturucu** ile Taşıyıcı/Origin/Destination
  girip **➕ Rota Ekle**; liste satır satır düzenlenir (seç-sil, temizle).
  Taşıyıcı alanı çoklu olabilir (`TK,AF`). Yüklenen dosyalar da aynı listeye eklenir.
- **Excel/CSV'den:** `AIRLINE | ORIGIN | DESTINATION` tek tablo; **veya** rota ve
  taşıyıcı listesi ayrı: Excel'de **Routes** (ORIGIN|DESTINATION) + **Carriers**
  (CARRIER) sayfaları — taşıyıcısız rotalar taşıyıcı listesiyle **çaprazlanır**
  (rota × taşıyıcı). Örnek şablon: `python tools/make_ond_template.py`.
- **Canlı panel yayını:** GUI'de **📡 Paneli Canlı Yayınla** ile `output/`
  klasörü basit bir HTTP sunucusundan yayınlanır; panel canlı modda `data.json`'u
  periyodik yeniler, ağdaki herkes son veriyi görür.

### OND dosya formatı

```
AIRLINE,ORIGIN,DESTINATION
TK,IST,LHR
LH,FRA,JFK
```
Bir rotada virgülle çoklu taşıyıcı da yazılabilir (`AF,JL,NH | CDG | HND`);
yükleyici her taşıyıcı için ayrı OND üretir.

---

## HTML Paneli

`web/index.html` **tek dosyalık**, koyu temalı bir terminaldir. İki modu vardır:

- **Koşullar:** Paketler yan yana sütunlarda; her özellik ayrı satırda
  (✓ dahil · € ücretli · — yok), kabin renk kodlu.
- **Ücretler:** Paket paket fiyatlar, fiyat kademesi çubukları ve
  **paketler arası geçişkenlik** (bir üst pakete geçiş maliyeti + kazanılan avantajlar).

**Canlı & paylaşımlı çalıştırma** (localhost değil):

```bash
cd output           # data.json burada üretiliyor
# panel dosyasını da buraya kopyalayıp basit bir sunucu ile yayınlayın:
cp ../web/index.html .
python -m http.server 8080
```
Ağdaki herkes `http://<sunucu-ip>:8080/` adresinden erişir. Paneldeki **canlı**
göstergesini açınca `data.json` 10 saniyede bir yeniden okunur — masaüstü uygulaması
yeni veri yazdıkça herkesin ekranı güncellenir. (GitHub Pages / Netlify gibi statik
barındırma da olur.) Dosyayı doğrudan çift tıklayarak açarsanız **JSON Yükle**
butonuyla elle de veri yükleyebilirsiniz; hiçbir şey yüklemezseniz gömülü örnek gösterilir.

---

## Fare Intelligence Platform Özellikleri (v2)

Uygulama artık yalnızca bir scraper değil, **Airline Fare Intelligence Platform**'dur.

**Collection Date (CollDate).** Her kayıt CollDate ile saklanır; tüm filtre, analiz
ve grafik ekranlarında kullanılır. Aynı OND'nin farklı CollDate'lerdeki değişimi
Line Chart ve Paket Evrimi ekranlarında karşılaştırılır. `output/data.json`
kümülatiftir: her çekim geçmişin üzerine eklenir, zaman serisi kaybolmaz.

**Ham veri ve TSV.** Her çekim otomatik olarak TSV dahil tüm biçimlerde yazılır ve
`output/archive/run_*/` altında kalıcı arşivlenir (raw.tsv, fares.xlsx, fares.db,
fares.json). GUI'de "TSV Export" düğmesi tek tıkla kayıt yerini sorarak yazar;
HTML panelinde üstteki "⬇ TSV" düğmesi o an filtreli veriyi indirir.

**Archive.** Hem GUI'de (sol menü → Archive) hem HTML panelinde Archive sekmesi:
CollDate, çekim zamanı, havayolları, OND ve kayıt sayısı, durum; TSV/Excel/SQLite
indirme ve ham veri görüntüleme.

**Otomatik çekim frekansı.** `core/scheduler.py`: Local OND (TR çıkışlı/varışlı)
haftalık, Beyond OND aylık. GUI'de "Sadece zamanı gelenler" anahtarı, CLI'de
`--due` bayrağı. Cron örneği: `0 6 * * * python main.py --cli data/ond_example.csv --due`

**TK referanslı gösterim.** Ücretler modunda her paketin altında aynı OND'deki TK
eşleniği (kabin + kademe eşleşmesi) ve fark gösterilir; TK'da eşdeğer yoksa boş
bırakılır. Analytics'te TK Karşılaştırmalı Bar Chart ve Heatmap'te "TK farkı" metriği.

**Beyaz tema.** Masaüstü ve HTML arayüz tamamen beyaz temaya geçirildi
(okunabilirlik + sadelik + modern ikonlar). Filtre çubuğu sayfa kaydırılsa da
üstte sabit kalır.

**Paket ikonları.** 14 fare özelliği (el bagajı, check-in bagajı, koltuk, yemek,
lounge, priority, fast track, refund, change, wifi, extra baggage, spor ekipmanı,
pet, mil) çizgi ikonlarla gösterilir; üzerine gelince açıklama tooltip'i çıkar.

**Know How.** Havayolu başına bilgi bankası: paket yapısı farklılıkları, bölgesel
uygulamalar, kampanyalar, istisnalar madde madde tutulur. Akıllı Bilgilendirme
Sistemi uyarıları otomatik not olarak eklenir; elle not eklenebilir, notlar JSON
indirilir / içe aktarılır.

**Akıllı Bilgilendirme Sistemi.** Ardışık CollDate'ler karşılaştırılır: yeni paket,
kaldırılan paket, fiyat anomalisi (≥%25 artış), olası kampanya (≥%12 düşüş).
İlgili taşıyıcı+OND kartında ⭐/❗ ikonu belirir; üzerine gelince açıklama,
tıklanınca ilgili Know How kaydı açılır.

**Filtreler.** Region, Carrier, CollDate, Ay, Yıl, Sezon (Summer=Nisan-Eylül,
Winter=Ekim-Mart, otomatik), Local/Beyond (otomatik), Legacy/Low Cost, Cabin,
Fare Family, Fare Brand + serbest arama.

**Para birimi.** Tüm ücretler USD gösterilir; farklı para birimleri
`core/enrich.py` içindeki kur tablosuyla çevrilir (`.env` içinde `FX_EUR=1.10`
gibi değerlerle güncellenebilir). Orijinal fiyat ve para birimi korunur,
panelde tooltip'te görünür.

**Analytics.** KPI kartları ve trend göstergeleri; boyutları seçilebilir dinamik
Heatmap (satır: OND/Region/Carrier, sütun: Fare Package/Carrier/Cabin, renk:
ortalama/min/fark/TK farkı); TK karşılaştırmalı Bar Chart; CollDate bazlı Line
Chart (ortalama/min/max); Paket Evrimi timeline'ı (eklenen +, kaldırılan ×);
Radar (özellik karşılaştırması vs TK); fiyat dağılım histogramı; Scatter (rakip
fiyat konumlandırması). Tüm grafikler bağımsız SVG'dir, harici kütüphane yoktur.

**Veri kalitesi.** `core/enrich.check_quality`: eksik kayıt, tutarsız fiyat
(üst paketin alttan ucuz olması), duplicate, para birimi hatası otomatik tespit
edilip log + arayüzde raporlanır.

**Demo geçmişi.** `python tools/make_demo_history.py --embed` 8 haftalık Local +
3 aylık Beyond çekim simülasyonu üretir ve panele gömer (yeni paket, kaldırılan
paket, anomali ve kampanya olayları dahil) — tüm zaman serisi ekranlarını gerçek
veri gelmeden test etmenizi sağlar.

## Kokpit Ekranı Revizyonları (v3)

**Kokpit Ekranı.** "Panel" adı kaldırıldı; ana ekran artık Kokpit Ekranı.

**Ücret Özeti (sticky).** Ücretler modunun en üstünde, seçili filtreye göre
otomatik oluşan özet matris: satırlar taşıyıcı, sütunlar kademe geçişleri
(Eco 0-1 = giriş fiyatı, Eco 1-2 / Bus 1-2 = kademeler arası USD farkı) ve
kabin başına paket sayısı. Tablo kaydırmada üstte sabit kalır; tüm taşıyıcılar
tek bakışta karşılaştırılır.

**Paket geçişkenliği (yeniden tasarım).** Kabin başına dikey zincir: paket
kartı → ok → +USD farkı → kazanılan özellik rozetleri → sonraki paket kartı.

**Scatter kaldırıldı; histogram yerine Violin.** Fiyat Yoğunluğu — Violin:
taşıyıcı başına KDE tabanlı dağılım, medyan çizgisi ve çeyrekler arası kutu;
taşıyıcılar medyana göre sıralanır.

**OND filtresi.** Ana filtrelere arama destekli, çoklu seçimli OND alanı
eklendi. Ayrıca Origin Bölge / Destination Bölge, Origin Ülke / Destination
Ülke ve Origin / Destination ayrı ayrı filtrelenebilir.

**Global filtre sistemi.** Üst filtre çubuğu uygulamadaki BÜTÜN grafikleri
etkiler: heatmap, TK bar, line chart, paket evrimi, radar, violin, KPI'lar,
Ücret Özeti ve kart listesi aynı filtre kümesinden beslenir; grafik içi
Carrier/OND seçicileri de filtrelenmiş kümeden dolar.

**Veri seti.** Dashboard şu an yalnızca şu 7 rota çiftini (14 yönlü OND)
içerir: CDG↔IST (TK, AF, BJ, JU, LO) · MAD↔IST (TK, PC, VF, LH) ·
DXB↔MAD (EK, QR, TK, RJ, PC) · ATH↔JFK (DL, N0, AA, BA, TK) ·
CDG↔PEK (CA, AF, HU, EK, KL, TK) · FCO↔HND (AZ, LH, MU, EK, CA, TK) ·
BKK↔CDG (AF, TG, QR, EK, EY, TK). 22 taşıyıcının fare brand yapıları
(marka adları, dahil/ücretli özellikler) resmi ve yayımlanmış fare family
bilgilerinden derlenmiştir; `tools/make_real_dataset.py` üretir.

**Önemli — fiyatlar hakkında:** Bu ortamda havayolu rezervasyon sistemlerine
canlı sorgu atılamadığından fiyat SEVİYELERİ piyasa araştırmasına dayalı
temsili değerlerdir (marka yapıları gerçektir). Gerçek canlı fiyatlar için
masaüstü uygulamayı gerçek scraper'larla çalıştırın; data.json her çekimde
otomatik güncellenir ve panel canlı modda yeniler.

## FPI · YDUS — Geçişkenlik Odaklı Yeniden Tasarım (v4)

Uygulamanın adı **FARE PACKAGE INTELLIGENCE (FPI · YDUS)** olarak güncellendi.
Nihai/son bilet ücreti hiçbir ekranda gösterilmez; tüm değerlendirme ve
mukayeseler **paket geçişkenliği** (kademeler arası USD maliyet + kazanılan
haklar) üzerinden okunur.

**Kokpit (yönetici / makro analiz).** Yeni ana sekme. (1) *Makro Akış
Matrisi*: Bölge→Bölge, Ülke→Ülke veya OND kırılımında tüm taşıyıcılar tek
matriste; hücre = ortalama kademe geçiş maliyeti + paket sayısı, TK sütunu
vurgulu, hücreye tıklayınca o akışın Paket İndeksi açılır. (2) *Paket
İndeksi*: seçili akışta TK (sabit üstte) ve diğer taşıyıcıların paketleri
içerik skorlarıyla (0-100), aralarındaki geçiş maliyetleri ve kazanılan
haklarla tek kompakt ekranda mukayese edilir.

**Detay Analiz (eski Kokpit/Panel).** Koşullar matrisine No-Show Refund,
No-Show Change ve Aynı Gün Erken Uçuş hakları eklendi (17 özellik). Geçiş
Özeti tablosu artık sabit değildir ve iki görünümü vardır: *Geçiş Maliyeti*
(USD; 0-1 giriş geçişi, k-(k+1) kademe farkı) ve *Paket İçeriği* (ilk paket
skoru + geçişte kazanılan hak sayısı). Zincir kartlarında paket düğümleri
fiyat yerine içerik skoru taşır.

**Analitik Analiz.** KPI'larda ort/min/max ücret yerine ortalama kademe
geçişi ile en yüksek/en düşük geçiş (taşıyıcı + paket bilgisiyle) gösterilir.
Heatmap satır/sütunlarına OND Ülke ve OND Bölge eklendi; paketler içerik
skoruna göre kabin bazında küçükten büyüğe **standart kademelere** (Eco-1,
Eco-2, Bus-1…) segmentlenir, marka bazlı görünüm de korunur; metrikler
geçişkenlik tabanlıdır ve TK satır/sütunları kalın-kırmızı ayrıştırılır.
CollDate line chart, Radar ve Fiyat Yoğunluğu kaldırıldı; TK karşılaştırmalı
geçişkenlik analizi tam genişlikte, solda Economy sağda Business panelli,
OND / Ülke→Ülke / Bölge→Bölge kırılımlı (Asya→Avrupa, Almanya→Çin gibi) hale
getirildi — her kademede iki taşıyıcının kaç USD ödeyip hangi hakları
eklediği eş zamanlı okunur. Paket Evrimi büyütüldü; son iki çekim arasındaki
farklar satır bazlı koşullu renklendirme + ⚠ ve Değişim sütunu ile raporlanır.

**Filtreler.** Üstteki bütün filtreler OND gibi çoklu seçimlidir (ortak,
taşmayan kompakt bileşen); Region ve Ay filtreleri kaldırıldı; Origin/
Destination Bölge-Ülke-Havalimanı ayrı ayrı filtrelenir. Global filtre tüm
ekranları besler.

**Standart sezonsal çekim.** Veri çekim zamanları standardize edildi: her
dönem için Winter (Eki-Mar) ve Summer (Nis-Eyl) sezonlarının ORTASINDA iki
çekim yapılır (`tools/make_real_dataset.py` bunu bugünün tarihinden dinamik
hesaplar). CollDate yıl-ay bazında tutulur; ham veri ve Arşiv'de sezon ve
sorgu atılan seyahat tarihi yer alır; Arşiv'de tümünü TSV/Excel indirme vardır.

**Bilgi Bankası (eski Know How).** Global filtreye duyarlıdır (örn. Carrier=
LH + Destination Bölge=Europe yalnızca kapsamdaki taşıyıcı ve notları getirir)
ve 📖 Metrik Sözlüğü tüm metrik/kırılım tanımlarını içerir.

### Canlı veri — HTML'i paylaştığınız herkes son veriyi görsün

1. `output/data.json` dosyasını herkese açık bir adreste yayınlayın
   (GitHub raw / GitHub Pages, S3, şirket içi statik sunucu…). Örn:
   `https://raw.githubusercontent.com/<kullanici>/<repo>/main/data.json`
2. `web/index.html` dosyasının en üstündeki `REMOTE_DATA_URL = ""` satırına
   bu adresi yazın ve HTML'i ekibinizle paylaşın — **veya** HTML'i hiç
   değiştirmeden `dosya.html?data=<URL>` parametresiyle paylaşın.
3. Panel açılışta bu adresi okur; sağ üstteki **canlı** modu açık olan
   herkes 10 saniyede bir yeniden okur. Siz data.json'u her
   güncellediğinizde (yeni çekim sonrası dosyayı aynı adrese yüklediğinizde)
   paneli açık tutan tüm kullanıcılar son güncel veriyi görür.
   Okuma sırası: `?data=URL` → `REMOTE_DATA_URL` → `./data.json` →
   `./output/data.json` → gömülü veri.

## Yeni Havayolu Ekleme

1. `core/selectors.py` içine ilgili havayolu bloğunu ekleyin (`_TEMPLATE`'i kopyalayın).
2. `scrapers/xx.py` oluşturun. `BaseScraper` otomatik **API → HTML** akışını
   yönetir; siz üç kancayı doldurursunuz:

```python
from scrapers.base import BaseScraper
from scrapers.registry import register

@register
class XXScraper(BaseScraper):
    airline_code = "XX"
    source_label = "XX-site"

    def open_search(self, page, ond, travel_date):
        # siteyi aç, çerez onayı, formu doldur, aramayı tetikle
        ...

    def parse_api(self, captured, ond):
        # yakalanan XHR/JSON yanıtlarından FareBrand listesi (tercih edilen)
        return []

    def parse_dom(self, page, ond):
        # API boşsa görünür fare kartlarını DOM'dan oku
        return []
```

Şablon önce `parse_api`, boşsa `parse_dom` sonucunu döndürür; ikisi de boşsa
`NotFoundError` verir (üst katman OTA yedeğine düşer). Kayıt otomatiktir
(`load_all_scrapers` tüm modülleri tarar). Her scraper `pytest` ile bağımsız
test edilebilir (bkz. `tests/test_auto_scrape.py`).

**OTA yedeği eklemek** benzer: `scrapers/ota_xx.py` içinde `OTAScraper`'dan
türetip `@register_ota` ile kaydedin, `ota_name` verin ve aynı üç kancayı
doldurun; `config.ota_sources` listesine adını ekleyin.

---

## Yapılandırma

Tüm ayarlar `config.py` içindedir ve `.env` ile ezilebilir:

| Anahtar | Açıklama | Varsayılan |
|---|---|---|
| `HEADLESS` | Tarayıcı görünmez mi | `true` |
| `MAX_WORKERS` | Paralel işlenen taşıyıcı grubu sayısı (her grup kendi tarayıcısı) | `3` |
| `PAGES_PER_BROWSER` | Aynı taşıyıcı+tarih için tek tarayıcıda eşzamanlı sekme sayısı | `4` |
| `MAX_RETRIES` | Deneme sayısı | `3` |
| `HUMAN_DELAY_MIN/MAX` | İnsan davranışı beklemesi (sn) | `0.4 / 1.8` |
| `RESUME` / `SKIP_EXISTING` | Kaldığı yerden devam / tekrar çekme | `true` |
| `EXPORT_*` | Excel/CSV/SQLite/JSON | hepsi `true` |
| `TRAVEL_DATE` / `DAYS_AHEAD` | Uçuş tarihi | boş / `30` |
| `DEMO_MODE` | Çevrimdışı sahte veri (canlı istek yok) | `false` |
| `USE_OTA_FALLBACK` | Havayolu sitesi başarısızsa OTA'dan dene | `true` |
| `OTA_SOURCES` | OTA yedek sırası | `google,kayak` |
| `USE_API_SOURCES` | Canlıda önce resmi API'leri dene | `true` |
| `API_SOURCES` | API kaynak sırası | `duffel,amadeus` |
| `DUFFEL_ACCESS_TOKEN` | Duffel API tokenı (yoksa atlanır) | boş |
| `AMADEUS_CLIENT_ID` / `_SECRET` | Amadeus kimlik bilgisi (yoksa atlanır) | boş |
| `AMADEUS_ENV` | Amadeus ortamı (`test`/`production`) | `test` |

---

## Önemli Not

Havayolu siteleri **anti-bot koruması**, dinamik içerik ve sık tasarım değişimi
içerir. `tk.py` ve `af.py` dosyaları **çalışan şablonlardır** — sınıf yapısını,
HTML-parse ve network/API yaklaşımlarını gösterirler; ancak seçicilerin canlı sitede
doğrulanması gerekir:

```bash
playwright codegen https://www.turkishairlines.com
```

Kayıtlı gerçek scraper'ı olmayan her havayolu otomatik olarak **DemoScraper**'a
düşer ve gerçekçi örnek veri üretir; böylece arayüz, export ve HTML paneli daima
uçtan uca çalışır ve yeni bir havayolunu geliştirirken sistemin geri kalanı hazır olur.

Bu araç yalnızca ilgili sitelerin kullanım şartlarına uygun ve yasal biçimde
kullanılmalıdır.
