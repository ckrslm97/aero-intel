/** The vocabulary this portal is written in.
 *
 * Every term here appears somewhere in the newspaper's headlines, summaries or
 * category names, so each entry carries the category slug it belongs to and
 * becomes a link into the archive: read the definition, then read the stories
 * that use it. Terms with no coverage are still worth defining -- that is what
 * a reference is for -- but the link tells you honestly when there is nothing
 * to read yet.
 *
 * English is kept alongside the Turkish because the sources are English and a
 * reader who only knows "birim gelir" will not recognise "RASK" in a headline.
 */
export interface Term {
  /** Turkish name, the entry's title. */
  tr: string;
  /** How it appears in the wires. */
  en: string;
  /** What it is, in one or two sentences. */
  definition: string;
  /** Why a revenue-management desk cares -- the part a dictionary leaves out. */
  matters: string;
  /** A category slug from lib/taxonomy.ts, for the "ilgili haberler" link. */
  category: string;
  /** Optional subcategory slug, when one narrows the link usefully. */
  subcategory?: string;
}

export interface TermGroup {
  slug: string;
  title: string;
  intro: string;
  terms: Term[];
}

export const KNOW_HOW: TermGroup[] = [
  {
    slug: "revenue_management",
    title: "Gelir Yönetimi",
    intro:
      "Doğru koltuğu, doğru yolcuya, doğru fiyattan satma disiplini. Bu sayfadaki " +
      "terimlerin çoğu günlük karar toplantılarının dili.",
    terms: [
      {
        tr: "Birim gelir",
        en: "RASK / RASM",
        definition:
          "Arz edilen koltuk-kilometre başına elde edilen gelir. RASK kilometre, RASM mil " +
          "tabanlıdır; ikisi de aynı soruyu sorar: uçurduğumuz her koltuk ne kazandırdı?",
        matters:
          "Doluluk ve fiyat aynı anda değiştiğinde performansı tek sayıda özetleyen ölçü budur. " +
          "Doluluk artarken birim gelir düşüyorsa, koltukları ucuzlatarak doldurmuşsunuz demektir.",
        category: "revenue_management",
      },
      {
        tr: "Birim maliyet",
        en: "CASK / CASM",
        definition:
          "Arz edilen koltuk-kilometre başına düşen maliyet. Yakıt hariç hesaplanan hâli " +
          "(CASK ex-fuel) taşıyıcılar arası karşılaştırmada tercih edilir.",
        matters:
          "Birim gelir ile birim maliyet arasındaki fark, uçuşun kâr marjıdır. Bir rakip " +
          "sürekli sizden ucuza satıyorsa, cevabı genellikle burada aramak gerekir.",
        category: "finance",
      },
      {
        tr: "Getiri",
        en: "Yield",
        definition:
          "Taşınan yolcu-kilometre başına gelir. Birim gelirden farkı: yield yalnızca satılan " +
          "koltukları sayar, doluluğu hesaba katmaz.",
        matters:
          "Yield yükselirken birim gelir düşüyorsa fiyatı yükseltip yolcu kaybetmişsinizdir. " +
          "İki ölçüyü birlikte okumak, tek başına ikisinden de doğrudur.",
        category: "revenue_management",
      },
      {
        tr: "Doluluk oranı",
        en: "Load factor",
        definition:
          "Satılan yolcu-kilometrenin arz edilen koltuk-kilometreye oranı. Uçağın ne kadarının " +
          "dolu uçtuğu.",
        matters:
          "Tek başına bir başarı ölçüsü değildir: bedava dağıtılan koltuklarla %100 doluluğa " +
          "ulaşılır. Birim gelirle birlikte anlam kazanır.",
        category: "revenue_management",
      },
      {
        tr: "Başabaş doluluk",
        en: "Break-even load factor",
        definition: "Uçuşun maliyetini tam karşıladığı doluluk seviyesi.",
        matters:
          "Bir hattın ne kadar kırılgan olduğunu gösterir. Başabaş doluluğu %85 olan bir hat, " +
          "talepteki küçük bir düşüşte zarara geçer.",
        category: "finance",
      },
      {
        tr: "Ücret sınıfı / kova",
        en: "Fare class / booking bucket",
        definition:
          "Aynı kabin içinde farklı fiyat ve koşullara sahip rezervasyon sınıfları. Harflerle " +
          "kodlanır (Y, B, M, K…) ve her birine ayrı koltuk kotası verilir.",
        matters:
          "Gelir yönetiminin asıl kaldıracı budur: fiyatı değiştirmeden, ucuz sınıfları kapatarak " +
          "ortalama bileti yükseltirsiniz.",
        category: "revenue_management",
        subcategory: "pricing",
      },
      {
        tr: "Teklif fiyatı",
        en: "Bid price",
        definition:
          "Bir koltuğun satılabilmesi için aşması gereken asgari gelir eşiği. Sistem, kalan " +
          "koltuğun ileride daha pahalıya satılma ihtimalini hesaplayarak belirler.",
        matters:
          "Bugün 200 euro'ya satmak mı, yarın 600 euro verecek iş yolcusu için saklamak mı " +
          "sorusunun sayısal cevabı.",
        category: "revenue_management",
        subcategory: "pricing",
      },
      {
        tr: "Taşma",
        en: "Spill",
        definition:
          "Uçak dolduğu ya da ilgili ücret sınıfı kapandığı için reddedilen talep.",
        matters:
          "Kaybedilen gelir görünmezdir: satılmayan bilet raporda yer almaz. Taşmayı ölçmeyen " +
          "bir ekip, kapasitesinin yetersiz olduğunu fark etmez.",
        category: "revenue_management",
      },
      {
        tr: "Fazla rezervasyon",
        en: "Overbooking",
        definition:
          "Uçuşa gelmeyen yolcuları (no-show) telafi etmek için koltuk sayısından fazla bilet " +
          "satmak.",
        matters:
          "Doğru ayarlanırsa boş uçan koltuğu sıfıra yaklaştırır; yanlış ayarlanırsa kapıda " +
          "tazminat ve itibar maliyeti doğurur. Denge tamamen tahmin kalitesine bağlı.",
        category: "revenue_management",
      },
      {
        tr: "Dinamik fiyatlama",
        en: "Dynamic pricing",
        definition:
          "Fiyatın sabit sınıf basamakları yerine talep, kalan gün ve yolcu profiline göre " +
          "sürekli hesaplanması.",
        matters:
          "Sektörün yöneldiği model. Sabit kovalardan çıkmak daha isabetli fiyat demek, ama " +
          "aynı zamanda dağıtım altyapısının bunu taşıyabilmesini gerektiriyor.",
        category: "revenue_management",
        subcategory: "pricing",
      },
      {
        tr: "Yan gelirler",
        en: "Ancillary revenue",
        definition:
          "Bilet fiyatı dışındaki gelirler: bagaj, koltuk seçimi, ekstra bacak mesafesi, " +
          "yemek, öncelikli biniş, mil programı satışları.",
        matters:
          "Birçok taşıyıcıda kârın belirleyici kısmı burada. Bilet fiyatını düşürüp yan " +
          "gelirle telafi etmek, bugünün en yaygın rekabet hamlesi.",
        category: "revenue_management",
        subcategory: "ancillary",
      },
      {
        tr: "NDC",
        en: "New Distribution Capability",
        definition:
          "IATA'nın, havayolunun kendi ürünlerini acentelere doğrudan ve zenginleştirilmiş " +
          "biçimde sunmasını sağlayan dağıtım standardı.",
        matters:
          "Klasik GDS kanalı yalnızca fiyat ve sınıf taşır. NDC, paketleri ve kişiselleştirilmiş " +
          "teklifleri acente ekranına taşıdığı için yan gelir stratejisinin altyapısı.",
        category: "revenue_management",
        subcategory: "ndc",
      },
      {
        tr: "GDS ve OTA",
        en: "GDS / OTA",
        definition:
          "GDS (Amadeus, Sabre, Travelport) acentelerin bilet sattığı küresel dağıtım " +
          "sistemleri; OTA ise Booking veya Expedia gibi çevrimiçi seyahat siteleri.",
        matters:
          "Her kanalın maliyeti farklı. Doğrudan satışı artırmak dağıtım maliyetini düşürür, " +
          "ama erişimden feragat etme riski taşır.",
        category: "revenue_management",
        subcategory: "ndc",
      },
    ],
  },
  {
    slug: "network",
    title: "Ağ ve Rota Planlama",
    intro:
      "Nereye, hangi sıklıkla ve hangi uçakla uçulacağı kararı. Gelir yönetiminin " +
      "üzerinde çalıştığı zemini bu ekip kuruyor.",
    terms: [
      {
        tr: "Toplayıcı-dağıtıcı ağ",
        en: "Hub and spoke",
        definition:
          "Yolcuların bir merkez havalimanında toplanıp oradan hedeflerine dağıtıldığı ağ " +
          "yapısı. Doğrudan uçuş modelinin (point-to-point) alternatifi.",
        matters:
          "Türk Hava Yolları'nın modeli budur: İstanbul'da birleşen trafik, tek başına " +
          "taşınamayacak ince hatları ayakta tutar.",
        category: "network",
      },
      {
        tr: "Aktarma dalgası",
        en: "Bank / wave",
        definition:
          "Hub'a kısa aralıkla inen ve hemen ardından kalkan uçuş kümesi; bağlantı süresini " +
          "kısaltmak için tarife bu dalgalar hâlinde kurulur.",
        matters:
          "Dalga yapısı bağlantı sayısını belirler. Dalgayı bir saat kaydırmak, yüzlerce " +
          "aktarma kombinasyonunu açar ya da kapatır.",
        category: "network",
      },
      {
        tr: "Kalkış-varış çifti",
        en: "O&D (origin and destination)",
        definition:
          "Yolcunun gerçek başlangıç ve bitiş noktası — uçuş bacakları değil, yolculuğun kendisi.",
        matters:
          "Gelir uçuşa değil yolculuğa aittir. İstanbul–Frankfurt uçağındaki yolcunun asıl " +
          "yolculuğu Bakü–Chicago olabilir; fiyatlama bu bütünü görmeli.",
        category: "network",
      },
      {
        tr: "Slot",
        en: "Slot",
        definition:
          "Kapasitesi kısıtlı bir havalimanında belirli bir zaman diliminde iniş ya da kalkış " +
          "hakkı.",
        matters:
          "Heathrow gibi doygun havalimanlarında slot, uçaktan değerli bir varlıktır. Yeni hat " +
          "açmanın önündeki engel çoğu zaman talep değil slot.",
        category: "airport",
      },
      {
        tr: "Hava serbestlikleri",
        en: "Freedoms of the air",
        definition:
          "Bir taşıyıcının başka ülkelerin hava sahasında ve pazarlarında ne yapabileceğini " +
          "tanımlayan, ikili anlaşmalarla verilen haklar dizisi.",
        matters:
          "Beşinci serbestlik (iki yabancı ülke arasında yolcu taşıma) yeni pazar açar; " +
          "kısıtlanması bir hattı bir gecede kapatabilir.",
        category: "regulatory",
      },
      {
        tr: "Ortak uçuş",
        en: "Codeshare",
        definition:
          "Bir uçuşun birden fazla havayolunun kodu ve bilet numarasıyla satılması.",
        matters:
          "Uçak koymadan ağ genişletmenin en ucuz yolu. Ancak gelir paylaşımı anlaşmaya bağlı; " +
          "koltuk sizin değilse marj da tamamen sizin değil.",
        category: "network",
      },
      {
        tr: "Ortak girişim",
        en: "Joint venture",
        definition:
          "İki ya da daha fazla taşıyıcının belirli bir pazarda tarifeyi, fiyatı ve geliri " +
          "birlikte yönettiği, düzenleyici muafiyet gerektiren derin iş birliği.",
        matters:
          "Codeshare'den bir seviye ötesi: rakip olmaktan çıkıp tek bir gelir havuzuna " +
          "dönüşürsünüz. Kuzey Atlantik'teki rekabetin şeklini bunlar belirliyor.",
        category: "network",
      },
    ],
  },
  {
    slug: "operations",
    title: "Filo ve Operasyon",
    intro:
      "Fiyat ve tarife kararlarının fiziksel sınırları: hangi uçak nereye gidebilir, " +
      "kaç koltukla ve hangi maliyetle.",
    terms: [
      {
        tr: "Koltuk yoğunluğu",
        en: "Seat density / configuration",
        definition:
          "Aynı uçak tipine yerleştirilen koltuk sayısı ve kabin sınıflarının dağılımı.",
        matters:
          "Aynı A321 ile 180 ya da 240 koltuk uçurabilirsiniz. Bu tercih hem birim maliyeti " +
          "hem hangi yolcuyu hedeflediğinizi belirler.",
        category: "fleet",
      },
      {
        tr: "ETOPS",
        en: "ETOPS",
        definition:
          "Çift motorlu uçakların en yakın alternatif havalimanından ne kadar uzakta " +
          "uçabileceğini belirleyen yetkilendirme.",
        matters:
          "Okyanus aşırı hatlarda hangi uçağın kullanılabileceğini doğrudan kısıtlar; " +
          "rota uzunluğu ile uçak seçimi bu kuralla bağlanır.",
        category: "fleet",
      },
      {
        tr: "Uçak kullanımı",
        en: "Aircraft utilisation",
        definition: "Bir uçağın günde kaç saat havada olduğu.",
        matters:
          "Uçak yerde para kazanmaz. Düşük maliyetli taşıyıcıların maliyet avantajının önemli " +
          "kısmı, aynı uçaktan günde daha fazla uçuş çıkarmalarından gelir.",
        category: "fleet",
      },
      {
        tr: "Yakıt korunması",
        en: "Fuel hedging",
        definition:
          "Gelecekteki yakıt maliyetini finansal sözleşmelerle önceden sabitleme.",
        matters:
          "Yakıt, maliyetin en oynak kalemi. Korunma, fiyat düştüğünde avantajdan feragat " +
          "etme pahasına bütçeyi öngörülebilir kılar.",
        category: "finance",
      },
    ],
  },
];

export const ALL_TERMS: Term[] = KNOW_HOW.flatMap((group) => group.terms);
