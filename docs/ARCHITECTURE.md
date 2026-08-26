# AeroIntel — mimari

Bu belge hedef mimariyi ve ona giden yolu anlatır. Faz 7 yeniden yapılanmasıyla
birlikte yazıldı; her faz kendi bölümünü günceller.

## Yönetici ilke

> Daha fazla veri değil, daha kaliteli ve anlamlı veri.

ve bunun uygulanabilir hâli:

> Emin olmadığın haberi, kampanyayı, riski, tahmini kullanıcıya gösterme.

İkincisi bir slogan değil, bir kısıt: düşük güvenli kayıtlar veritabanında
denetim için durur, üretim arayüzüne çıkmaz.

## Bugünkü hat (v1) ve neden değişiyor

```
RSS  →  alım  →  tekilleştirme  →  zenginleştirme  →  sayı/API  →  arayüz
```

Ölçülen sorun tek bir kök nedene iniyor: **sınıflandırmayı yapması gereken
model production'da çalışmıyor.** `BudgetedProvider` başlık, özet, duygu ve
varlık çıkarımını yerel sezgisele yönlendiriyor; `classify_risk` hiçbir
sarmalayıcı tarafından iletilmediği için hiçbir konfigürasyonda erişilebilir
değil. Sonuç: gördüğünüz her sınıflandırma anahtar kelime sayımı.

Daha kötüsü, model açılsa bile bir yanlış pozitifi **kaldıramıyor**:

```python
# app/pipeline/enrich.py
if not result or not result.get("risk_type"):
    result = classify_risk_heuristic(title, content, entities)
```

Modelin "bu bir risk değil" cevabı (`risk_type: null`) başarısız çağrıdan
ayırt edilemiyor, dolayısıyla sezgisel devreye giriyor. **Model yeniden
sınıflandırabiliyor ama asla veto edemiyor.**

## Hedef hat (v2)

```
Konu ajanı
    ↓  kaynak keşfi (periyodik, insan onaylı)
    ↓  içerik çıkarımı
    ↓  normalleştirme
    ↓  tekilleştirme  →  olay kümesi (birincil + ikincil kaynaklar)
    ↓  sınıflandırma  →  ÜÇ DURUM
    ↓  güven puanlaması
    ↓  kaynak doğrulama
    ↓  iş alakası doğrulama
    ↓  nihai veri
    ↓  arayüz
```

### Üç durumlu sonuç

Her sınıflandırıcı — risk, kampanya, iş alakası — üç şeyden birini döndürür:

| Durum | Anlamı | Sonuç |
|---|---|---|
| `CLASSIFIED` | Sonuç var | Yayına aday |
| `NOT_APPLICABLE` | Model açıkça "hayır" dedi | Kalıcı yazılır, bir daha sorulmaz, **hiçbir şey ezemez** |
| `FAILED` | Çağrı hatası, bozuk JSON, taksonomi dışı etiket | Beklemede kalır, tekrar denenir, **asla yayınlanmaz** |

Sezgisel sınıflandırıcı artık başarısız çağrının yedeği değildir. "Cevap yok"
demek "gösterme" demektir.

### Güven modeli

Ağırlıklı toplam, bileşenler [0,1] aralığında:

| Bileşen | Ağırlık |
|---|---|
| Kaynak güvenilirlik katmanı | 0,30 |
| Sınıflandırıcı kesinliği | 0,25 |
| Alan tamlığı | 0,20 |
| Sinyal uyumu (deterministik çıkarıcı ile) | 0,15 |
| Doğrulama (küme büyüklüğü) | 0,10 |

Bantlar: **yüksek ≥ 0,75 · orta 0,50–0,74 · düşük < 0,50**. API uç noktaları
varsayılan olarak düşük bandı filtreler. Eksik zorunlu alan tamlığı düşürür ve
kaydı düşük banda iter — sistemin "bilmiyorum" deme mekanizması budur.

### Kaynak öncelik merdiveni

Resmî havayolu/havalimanı duyurusu → devlet/düzenleyici → IATA/ICAO/EASA →
havayolu basın odası → havalimanı → büyük ajanslar → havacılık/finans yayınları.

Katman doğrudan güven puanını besler.

## Zamanlama

**Hiçbir şey süreç içinde zamanlanmaz.** Her yinelenen iş
`.github/workflows/` altında bir GitHub Actions cron'udur ve `app/cli.py`
komutlarını çağırır. Eskiden burada bir APScheduler de vardı; Vercel'de ölüydü
(fonksiyon istekler arasında donduruluyor) ve başka her yerde çift tetikliyordu,
çünkü iş akışları aynı veritabanına karşı koşuyor.

## Taksonomi: tek kaynak

`backend/app/taxonomy.py` slug'ların **ve** Türkçe etiketlerin tek kaynağıdır.
Etiketler eskiden dört yerde yazılıydı — öneriler servisi, e-posta şablonu,
gazete sayfası ve ön yüz taksonomisi — ve biri kaydığında bunu fark eden bir şey
yoktu.

Ön yüz bunları `backend/scripts/export_taxonomy.py` ile üretilen
`frontend/src/lib/taxonomy.gen.ts` üzerinden alır. Slug'lar TypeScript birleşim
tipi olarak dışa aktarılır, dolayısıyla bir tarafta olup diğerinde olmayan bir
slug **derleme hatasıdır**, üretimde boş kalan bir filtre değil. CI dosyanın
tazeliğini kontrol eder.

Renkler ve ikonlar ön yüzde kalır; arka uçta karşılıkları yok.

```bash
cd backend && python -m scripts.export_taxonomy
```

## Operatör uç noktaları

`/admin/status`, `GET /subscribers` ve sayı yeniden inşası `ADMIN_TOKEN`
taşıyıcı belirteciyle korunur (`app/api/deps.py`). Kullanıcı tablosu ve giriş
yoktur — bu tek masalı bir üründür, dolayısıyla tek bir dağıtım sırrı dürüst
olan şekildir.

**Belirteç ayarlanmamışsa uç noktalar her isteği reddeder, açılmaz.** Bir
değişken unutulduğunda kendini sessizce açan bir operatör uç noktası, bu
uç noktaların en baştan herkese açık olmasının sebebidir.

## Yayına alma

`main` otomatik olarak Vercel'e gider, dolayısıyla yeniden yapılanma **faz
başına bir PR** olarak ilerler:

1. Silmeler ve operatör koruması (küçülten, güvenli)
2. Yalnızca ekleyen göçler — eski kod yeni sütunları görmezden gelir
3. Yeni hat `PIPELINE_V2` bayrağı arkasında, yalnızca işlerde; arayüz değişmez.
   En az üç gün çift yazım ve karşılaştırma
4. Sayfa başına bir PR, her biri önizlemede onaylandıktan sonra
5. **Menü değişimi en sonda** — hiçbir menü girişi henüz çevrilmemiş bir sayfayı
   göstermesin

Geri dönüş yolu her adımda aynı: bayrağı kapat, önceki yayına dön.

## Bilinen riskler

- **Yahoo finans uç noktası** otomatik erişime resmî olarak kapalıdır
  (`robots.txt`: `Disallow: /`). Bu maruziyet Brent ve USD/TRY ile zaten
  mevcuttu. Frankfurter v2 (ücretsiz, ticari kullanıma açık, kotasız) yedek ve
  çapraz kontrol kaynağıdır.
- **USD/SAR günlük serisi Yahoo'da bozuktur** — sabitlenmiş bir kurda %4'e varan
  günlük hareket gösteriyor. Değer Frankfurter v2'den alınır ve sabit rozet
  olarak gösterilir; sparkline ve değişim sütunu yoktur.
- **Banka kur tahminleri** yeniden yayımlamaya kapalıdır (ING ve Danske açıkça
  yazılı izin şartı koyar, ING ayrıca veritabanı hakkı iddia eder). Bu yüzden
  bölüm insan onaylı, atıflı, kaynağa bağlantılı dar alıntıdır — kazıyıcı değil.
- **IATA tahminleri yılda ~2 kez** yayımlanır ve sayılar niteleyici taşıyan
  cümlelerin içindedir. Küratörlü veri kümesidir. Aylık trafik
  *gerçekleşmeleri* ayrı ve otomatiktir; ikisi asla aynı kartta gösterilmez.
