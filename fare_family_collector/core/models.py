"""Veri modelleri.

Bu modül uygulamanın merkezi veri yapılarını tanımlar. Her `FareBrand`
örneği tek bir ücret paketini (fare family / fare brand) temsil eder ve
Excel/CSV çıktısında tek bir satıra karşılık gelir.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from enum import Enum
from typing import Any, Optional


class Cabin(str, Enum):
    """Standart kabin sınıfları. Scraper'lar site metnini bu değerlere eşler."""

    ECONOMY = "Economy"
    PREMIUM_ECONOMY = "Premium Economy"
    BUSINESS = "Business"
    FIRST = "First"
    UNKNOWN = "Unknown"


class FeatureState(str, Enum):
    """Bir fare özelliğinin durumu.

    Ücretsiz/dahil, ücretli, dahil değil ya da bilinmiyor ayrımını
    net biçimde taşımak için string enum kullanılır. Böylece Excel'de
    ``Included`` / ``Paid`` / ``Not Included`` / ``Unknown`` okunur.
    """

    INCLUDED = "Included"
    PAID = "Paid"
    NOT_INCLUDED = "Not Included"
    UNKNOWN = "Unknown"


# Fare özellik sütunlarının merkezi listesi. Yeni bir özellik eklemek için
# yalnızca bu listeye eklemek yeterlidir; export ve arayüz otomatik uyum sağlar.
FEATURE_FIELDS: tuple[str, ...] = (
    "baggage_cabin",       # El bagajı
    "checked_baggage",     # Check-in bagajı
    "seat_selection",      # Koltuk seçimi
    "meal",                # Yemek
    "refund",              # İade
    "change",              # Değişiklik
    "miles",               # Mil kazanımı
    "priority_boarding",   # Öncelikli biniş
    "lounge",              # Lounge
    "fast_track",          # Fast Track
    "upgrade_eligible",    # Upgrade hakkı
    "wifi",                # WiFi
    "sport_equipment",     # Spor ekipmanı
    "pet",                 # Evcil hayvan
    "extra_baggage",       # Ekstra bagaj
    "child_advantage",     # Çocuk avantajı
)


@dataclass
class FareFeature:
    """Bir özelliğin durumu ve serbest metin detayı.

    Örn. ``checked_baggage`` için ``state=INCLUDED, detail="20kg"``.
    """

    state: FeatureState = FeatureState.UNKNOWN
    detail: str = ""

    def to_cell(self) -> str:
        """Excel/CSV hücresi için insan-okur bir metin döndürür."""
        if self.detail and self.state != FeatureState.UNKNOWN:
            return f"{self.state.value} ({self.detail})"
        if self.detail:
            return self.detail
        return self.state.value


@dataclass
class FareBrand:
    """Tek bir ücret paketi = çıktı tablosunda tek satır.

    Alanlar prompttaki "Çekilecek bilgiler" listesiyle birebir örtüşür.
    Zorunlu olmayan alanlar için makul varsayılanlar verilir; bir scraper
    bir veriyi bulamazsa alan boş/UNKNOWN kalır ama satır yine üretilir.
    """

    # Rota kimliği
    airline: str = ""
    origin: str = ""
    destination: str = ""
    travel_date: str = ""

    # Paket kimliği
    cabin: str = Cabin.UNKNOWN.value
    fare_brand: str = ""          # Görünen paket adı, örn. "EcoFly"
    booking_class: str = ""       # Rezervasyon sınıfı, örn. "K"
    brand_code: str = ""          # Havayolu iç kodu, örn. "LT"

    # Fiyat
    price: Optional[float] = None
    currency: str = ""

    # Özellikler (FareFeature nesneleri)
    features: dict[str, FareFeature] = field(default_factory=dict)

    # Kural / açıklama alanları
    refund_rules: str = ""
    change_rules: str = ""
    cancellation_rules: str = ""
    flexibility: str = ""
    package_description: str = ""

    # Sıralama ve meta
    package_order: int = 0        # En düşükten en yükseğe (1,2,3,...)
    collection_time: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    source_url: str = ""
    source: str = ""              # Veri kaynağı: "TK-site", "ota:google", "demo" vb.

    # Platform alanları (core.enrich tarafından doldurulur)
    coll_date: str = ""           # Collection Date (YYYY-MM-DD)
    season: str = ""              # Summer / Winter (otomatik)
    ond_type: str = ""            # Local / Beyond (otomatik)
    region: str = ""              # Rota bölgesi (otomatik)
    carrier_type: str = ""        # Legacy / Low Cost (otomatik)
    price_usd: Optional[float] = None  # USD karşılığı (orijinal fiyat korunur)

    def set_feature(self, name: str, state: FeatureState, detail: str = "") -> None:
        """Bir özelliği güvenli biçimde ayarlar (bilinmeyen isimleri reddeder)."""
        if name not in FEATURE_FIELDS:
            raise KeyError(f"Bilinmeyen özellik alanı: {name!r}")
        self.features[name] = FareFeature(state=state, detail=detail)

    def to_row(self) -> dict[str, Any]:
        """pandas DataFrame için düz bir sözlük üretir.

        Her özellik ayrı bir sütuna açılır (prompt gereği).
        """
        row: dict[str, Any] = {
            "CollDate": self.coll_date,
            "Airline": self.airline,
            "Origin": self.origin,
            "Destination": self.destination,
            "Travel Date": self.travel_date,
            "Region": self.region,
            "OND Type": self.ond_type,
            "Season": self.season,
            "Carrier Type": self.carrier_type,
            "Cabin": self.cabin,
            "Fare Brand": self.fare_brand,
            "Class": self.booking_class,
            "Brand Code": self.brand_code,
            "Price USD": self.price_usd,
            "Price (Original)": self.price,
            "Currency (Original)": self.currency,
        }
        for name in FEATURE_FIELDS:
            feat = self.features.get(name, FareFeature())
            row[_human_label(name)] = feat.to_cell()
        row.update({
            "Refund Rules": self.refund_rules,
            "Change Rules": self.change_rules,
            "Cancellation Rules": self.cancellation_rules,
            "Flexibility": self.flexibility,
            "Package Description": self.package_description,
            "Package Order": self.package_order,
            "Collection Time": self.collection_time,
            "Source": self.source,
            "Source URL": self.source_url,
        })
        return row

    def to_json(self) -> dict[str, Any]:
        """HTML paneli için JSON uyumlu sözlük."""
        data = asdict(self)
        data["features"] = {
            name: {"state": f.state.value, "detail": f.detail}
            for name, f in self.features.items()
        }
        return data


def _human_label(field_name: str) -> str:
    """Özellik alanı adını okunur sütun başlığına çevirir."""
    labels = {
        "baggage_cabin": "Baggage Cabin",
        "checked_baggage": "Checked Baggage",
        "seat_selection": "Seat Selection",
        "meal": "Meal",
        "refund": "Refund",
        "change": "Change",
        "miles": "Miles",
        "priority_boarding": "Priority Boarding",
        "lounge": "Lounge",
        "fast_track": "Fast Track",
        "upgrade_eligible": "Upgrade Eligible",
        "wifi": "WiFi",
        "sport_equipment": "Sport Equipment",
        "pet": "Pet",
        "extra_baggage": "Extra Baggage",
        "child_advantage": "Child Advantage",
    }
    return labels.get(field_name, field_name.replace("_", " ").title())


@dataclass
class RunSummary:
    """Bir çalışmanın özet raporu."""

    total_ond: int = 0
    success: int = 0
    failed: int = 0
    total_fares: int = 0
    duration_seconds: float = 0.0
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def as_text(self) -> str:
        """Log/arayüz için çok satırlı özet metni."""
        return (
            f"Toplam OND    : {self.total_ond}\n"
            f"Başarılı      : {self.success}\n"
            f"Başarısız     : {self.failed}\n"
            f"Toplam Fare   : {self.total_fares}\n"
            f"Toplam Süre   : {self.duration_seconds:.1f} sn"
        )
