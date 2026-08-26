"""Resmi uçuş API sağlayıcıları için ortak altyapı.

Tarayıcı scraper'larının aksine bu sağlayıcılar **doğrudan HTTP/JSON API**
kullanır (Duffel, Amadeus, …). Anti-bot/çerez/dinamik yükleme derdi yoktur;
fare-family (marka + koşullar) verisi için en güvenilir kaynaktır.

`core/runner.py`, canlı modda **önce** yapılandırılmış API sağlayıcılarını dener
(kimlik bilgisi mevcutsa); veri gelmezse havayolu sitesi tarayıcı scraper'ına ve
son olarak OTA'ya düşer.

Yeni bir API eklemek için: bu sınıftan türeyen bir dosya (`apis/xx.py`) yaz,
`@register_api` ile kaydet, `available()` (kimlik bilgisi var mı) ve
`fetch(ond, travel_date)` metodlarını doldur.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Type

from config import AppConfig
from core.logging_config import get_logger
from core.models import FareBrand
from core.ond import OND

# Ad ("duffel","amadeus") -> sağlayıcı sınıfı
_API_REGISTRY: dict[str, Type["FareAPIProvider"]] = {}


def register_api(cls: Type["FareAPIProvider"]) -> Type["FareAPIProvider"]:
    """Bir API sağlayıcı sınıfını kaydeden dekoratör."""
    name = cls.name.lower().strip()
    if not name:
        raise ValueError(f"{cls.__name__} için name tanımlı değil")
    _API_REGISTRY[name] = cls
    return cls


def load_all_apis() -> None:
    """`apis` paketindeki tüm sağlayıcı modüllerini içe aktarır (registry'yi doldurur)."""
    import importlib
    import pkgutil

    import apis

    for mod in pkgutil.iter_modules(apis.__path__):
        if mod.name in {"base"}:
            continue
        importlib.import_module(f"apis.{mod.name}")


def registered_apis() -> list[str]:
    return sorted(_API_REGISTRY.keys())


def get_api_providers(config: AppConfig) -> list["FareAPIProvider"]:
    """Yapılandırmada seçili ve **kimlik bilgisi mevcut** sağlayıcıları sırayla döndürür.

    `config.api_sources` sırası korunur. Kimlik bilgisi olmayan (``available()``
    False dönen) sağlayıcılar sessizce atlanır; böylece token yoksa akış bozulmaz.
    """
    load_all_apis()
    providers: list[FareAPIProvider] = []
    for name in config.api_sources:
        cls = _API_REGISTRY.get(name.lower().strip())
        if cls is None:
            continue
        provider = cls(config)
        if provider.available():
            providers.append(provider)
    return providers


class FareAPIProvider(ABC):
    """Uçuş fare-family API sağlayıcıları için temel sınıf."""

    #: Alt sınıf ezmeli; `config.api_sources` bu ada göre eşleşir. Örn. "duffel".
    name: str = ""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.log = get_logger(f"api.{self.name.lower()}")

    @abstractmethod
    def available(self) -> bool:
        """Kimlik bilgisi (token/anahtar) mevcut mu? Değilse sağlayıcı atlanır."""

    @abstractmethod
    def fetch(self, ond: OND, travel_date: str) -> list[FareBrand]:
        """Verilen OND + tarih için fare paketlerini döndürür (istenen taşıyıcıya süzülü)."""

    # ------------------------------------------------------------------ #
    # Ortak yardımcılar
    # ------------------------------------------------------------------ #
    def _airline_matches(self, code: str, target: str) -> bool:
        """API sonucundaki taşıyıcı kodunu hedefle karşılaştırır (hedef boşsa hepsi geçer)."""
        if not target:
            return True
        return str(code).upper().strip() == target.upper().strip()
