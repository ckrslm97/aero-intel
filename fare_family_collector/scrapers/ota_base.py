"""OTA (Online Travel Agency) yedek scraper altyapısı.

Havayolunun kendi sitesinden veri alınamazsa (erişim/anti-bot/boş sonuç),
`core/runner.py` sırayla OTA kaynaklarını dener. Her OTA scraper'ı, istenen
taşıyıcıya (`target_airline`) ait paketleri filtreleyerek döndürür.

OTA scraper'ları `BaseScraper`'ın otomatik (API → HTML) şablonunu kullanır;
tek fark, seçicilerin havayolu koduyla değil OTA adıyla (GOOGLE/KAYAK…)
`core/selectors.py`'den gelmesi ve sonuçların taşıyıcıya göre süzülmesidir.

NOT: OTA'lar çoğunlukla fiyat/kabin verir; fare-family özellik detayı sınırlı
olabilir. Kod eldeki alanları doldurur, bulunmayanları UNKNOWN bırakır — kayıt
yine üretilir ve `source` ile açıkça OTA olarak işaretlenir.
"""
from __future__ import annotations

from typing import Type

from config import AppConfig
from core.selectors import get_selectors
from scrapers.base import BaseScraper

# OTA adı ("google","kayak") -> scraper sınıfı
_OTA_REGISTRY: dict[str, Type["OTAScraper"]] = {}


def register_ota(cls: Type["OTAScraper"]) -> Type["OTAScraper"]:
    """Bir OTA scraper sınıfını kaydeden dekoratör."""
    name = cls.ota_name.lower().strip()
    if not name:
        raise ValueError(f"{cls.__name__} için ota_name tanımlı değil")
    _OTA_REGISTRY[name] = cls
    return cls


def get_ota_scraper(name: str, config: AppConfig, target_airline: str) -> "OTAScraper | None":
    """OTA adı için scraper örneği döndürür (yoksa None)."""
    cls = _OTA_REGISTRY.get(name.lower().strip())
    if cls is None:
        return None
    return cls(config, target_airline=target_airline)


def registered_otas() -> list[str]:
    return sorted(_OTA_REGISTRY.keys())


class OTAScraper(BaseScraper):
    """OTA yedek scraper'ları için temel sınıf.

    Attributes:
        ota_name: OTA anahtarı; seçici bloğu ve kaynak etiketi bundan türer.
        target_airline: Süzülecek taşıyıcı IATA kodu (örn. "TK").
    """

    ota_name: str = ""

    def __init__(self, config: AppConfig, target_airline: str = "") -> None:
        # airline_code'u hedef taşıyıcıya ayarla ki _finalize doğru doldursun.
        self.airline_code = target_airline.upper().strip()
        super().__init__(config)
        # Seçiciler havayolu koduyla değil OTA adıyla gelir.
        self.selectors = get_selectors(self.ota_name.upper())
        self.source_label = f"ota:{self.ota_name.lower()}"
        self.target_airline = self.airline_code

    def _airline_matches(self, code: str) -> bool:
        """OTA sonucundaki taşıyıcı kodunu hedefle karşılaştırır.

        Hedef boşsa (belirtilmemişse) tüm sonuçlar kabul edilir.
        """
        if not self.target_airline:
            return True
        return str(code).upper().strip() == self.target_airline
