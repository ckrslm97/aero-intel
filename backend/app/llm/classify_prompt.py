"""The single consolidated classification prompt.

One call per surviving article answers everything: relevance, category,
subcategory, risk, entities, and the Turkish headline and summary. The version
this replaces made four to seven separate calls per article -- categorize,
subcategorize, translate x2, and, in the full-pipeline configuration, headline,
summary and sentiment -- each re-sending the article body.

Three things the prompt has to get right, because each one was a measured
production failure:

**It must be allowed to say no.** Every judgement below is optional. The model
is told explicitly that "not a risk", "not a campaign" and "not relevant" are
correct answers, and that guessing is worse than declining. The old risk prompt
had no way to express this: a null answer was indistinguishable from a failed
call, so the keyword heuristic overrode it, and a film review about the bombing
of Pan Am 103 was published as a high-severity attack.

**It must not translate aviation vocabulary.** "Business class" is Business
class in Turkish too; an earlier prompt rendered it "iş sınıfı". Airline and
airport names, IATA codes, aircraft designators and industry terms stay as
written.

**It must name the carrier that acted, not the one mentioned most.** Campaign
attribution was "whichever tracked carrier appears most often", which
attributed a Buy Alaska Points article to British Airways because BA appeared
in a comparison table, and an LNG pricing story to Emirates.
"""
from __future__ import annotations

from app.taxonomy import (
    CATEGORY_SLUGS,
    RISK_CATEGORY_SLUGS,
    RISK_SEVERITIES,
    SUBCATEGORY_KEYWORDS,
)

#: Body characters sent to the model. The lede carries the classification;
#: sending 3,000 words costs tokens and adds the boilerplate and related-links
#: noise that produced two of the measured risk false positives.
MAX_BODY_CHARS = 2400


def _subcategory_lines() -> str:
    return "\n".join(
        f"  {category}: {', '.join(sorted(subs))}"
        for category, subs in sorted(SUBCATEGORY_KEYWORDS.items())
    )


def build_prompt(title: str, content: str, *, topic_fragment: str = "") -> str:
    body = (content or "").strip()[:MAX_BODY_CHARS]
    extra = f"\n\nKONUYA ÖZEL KURALLAR\n{topic_fragment.strip()}" if topic_fragment.strip() else ""

    return f"""Sen bir havayolu gelir yönetimi masası için çalışan bir haber analistisin.
Aşağıdaki haberi analiz et ve SADECE geçerli JSON döndür. Açıklama, markdown veya
kod bloğu ekleme.

EN ÖNEMLİ KURAL: Emin değilsen "hayır" de. Bir alanı boş bırakmak, uydurmaktan
her zaman iyidir. "Bu bir risk değil", "bu bir kampanya değil" ve "bu haber
havacılıkla ilgili değil" doğru cevaplardır ve öyle işaretlenmelidir.

JSON şeması:

{{
  "relevant": true|false,
  "not_relevant_reason": null | "kısa gerekçe",
  "category": {" | ".join(f'"{c}"' for c in CATEGORY_SLUGS)},
  "subcategory": null | "alt kategori slug",
  "confidence": 0.0-1.0,
  "title_tr": "Türkçe başlık",
  "summary_tr": "2-3 cümlelik Türkçe özet",
  "airlines": [{{"code": "TK", "name": "Turkish Airlines", "role": "subject|mentioned"}}],
  "airports": [{{"code": "IST", "name": "Istanbul Airport"}}],
  "countries": ["Türkiye"],
  "is_risk": true|false,
  "not_risk_reason": null | "kısa gerekçe",
  "risk": null | {{
    "category": {" | ".join(f'"{r}"' for r in RISK_CATEGORY_SLUGS)},
    "severity": {" | ".join(f'"{s}"' for s in RISK_SEVERITIES)},
    "probability": 0.0-1.0,
    "aviation_impact_score": 0.0-1.0,
    "country": "ülke adı",
    "city": null | "şehir adı",
    "aviation_impact_note": "havacılığa etkisi tek cümle"
  }},
  "is_campaign": true|false,
  "not_campaign_reason": null | "kısa gerekçe",
  "campaign": null | {{
    "airline_code": "kampanyayı YÜRÜTEN taşıyıcının IATA kodu",
    "discount_pct": null | 0-100,
    "sale_starts": null | "YYYY-AA-GG",
    "sale_ends": null | "YYYY-AA-GG",
    "travel_starts": null | "YYYY-AA-GG",
    "travel_ends": null | "YYYY-AA-GG",
    "markets": {{"regions": [], "countries": [], "cities": []}}
  }}
}}

Alt kategoriler (yalnızca kendi kategorisi altındakiler geçerlidir):
{_subcategory_lines()}

KURALLAR

1. relevant: Haber ticari havacılıkla mı ilgili? Kredi kartı incelemeleri, otel
   ve tatil köyü yazıları, demiryolu haberleri, spor ve genel ekonomi haberleri
   ilgili DEĞİLDİR -- havayolu adı geçse bile. İlgili değilse diğer alanları
   boş bırak.

2. category: Haberin ASIL konusu. Geçen bir kelimeye göre değil. Emin değilsen
   "general" seç; yanlış kategori boş kategoriden kötüdür.

3. title_tr ve summary_tr: Havacılık terimlerini ÇEVİRME. Havayolu ve
   havalimanı adları, IATA kodları, uçak tipleri ve sektör terimleri olduğu
   gibi kalır. "Business class" Türkçede de Business class'tır, "iş sınıfı"
   değildir. Aynı şekilde: load factor, yield, RASK, hub, slot, codeshare,
   no-show, upgrade, Economy, Premium Economy.

4. airlines: role="subject" haberin ASIL öznesi olan taşıyıcıdır. Karşılaştırma
   tablosunda veya yan cümlede geçen taşıyıcı "mentioned"dır.

5. is_risk: SADECE gerçek, olmuş veya olmakta olan bir olay için true.
   - Film, dizi, belgesel, kitap veya oyun içeriği risk DEĞİLDİR.
   - Tarihî bir olayın yıldönümü, anması, mahkemesi veya soruşturması risk
     DEĞİLDİR -- olay bugün olmuyor.
   - Askerî uçak adları hava olayı değildir: Typhoon, Hurricane, Tornado ve
     Storm birer savaş uçağıdır.
   - Haberin gövdesinde geçen ilgisiz tek bir kelime risk yapmaz. Riskin
     haberin konusu olması gerekir.
   Risk değilse is_risk=false ve not_risk_reason doldur.

6. risk.category: Sekiz ailenin altındaki 16 tipten biri olmalı --
   jeopolitik: conflict/sanctions; operasyonel: accident_incident/disruption;
   düzenleyici: restriction/policy_change; ekonomik: currency_crisis/macro_shock;
   yakıt-maliyet: fuel_price_spike/fuel_shortage; pazar-rekabet:
   capacity_shift/price_war; talep: demand_shock/demand_surge; altyapı:
   airport_disruption/atc_disruption. Hiçbiri uymuyorsa is_risk=false.

7. risk.country: Olayın GERÇEKTEN olduğu ülke. Metinde ilk geçen ülke değil.
   Emin değilsen null bırak.

8. risk.probability: Bu olayın gerçekten olduğuna/olmakta olduğuna ne kadar
   eminsin (0.0-1.0). Bir söylenti veya doğrulanmamış rapor düşük, resmî bir
   açıklama yüksek olmalı.

9. risk.aviation_impact_score: Bu olay ticari havacılığı ne kadar doğrudan
   etkiliyor (0.0-1.0). Bir havalimanı kapanışı veya hava sahası yasağı yüksek
   (0.8+); bir ülkedeki genel ekonomik haber ama havacılığa özel bir etkisi
   belirtilmemişse düşük (0.2 civarı).

10. is_campaign: SADECE bir havayolunun bilet satışına yönelik indirim,
   promosyon veya kampanyası için true.
   - Otel, tren, kredi kartı ve sadakat programı kampanyaları DEĞİLDİR.
   - Ücret ARTIŞI, hizmet kesintisi veya gelir DÜŞÜŞÜ kampanya değildir.
   - Başlığında "expired", "süresi doldu" yazan kampanya artık geçerli değildir.
   - discount_pct: yalnızca metinde açıkça yazan indirim oranı. Gelir düşüş
     yüzdesi indirim değildir.

11. confidence: Kendi kararına ne kadar güvendiğin. Haber kısa, belirsiz veya
   çelişkiliyse düşük ver. Bu değer düşükse kayıt kullanıcıya gösterilmez, bu
   yüzden dürüst ol.{extra}

BAŞLIK: {title}

METİN: {body}

JSON:"""
