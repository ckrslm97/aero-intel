"""Scraper kayıt defteri (registry).

Havayolu koduna göre doğru scraper sınıfını otomatik seçer. Yeni bir
havayolu eklemek için: `scrapers/xx.py` içinde `BaseScraper`ten türeyen
bir sınıf yaz ve aşağıya kaydet (ya da `register` dekoratörünü kullan).
"""
from __future__ import annotations

from typing import Type

from config import AppConfig
from scrapers.base import BaseScraper

# Kod -> sınıf eşlemesi
_REGISTRY: dict[str, Type[BaseScraper]] = {}


def register(cls: Type[BaseScraper]) -> Type[BaseScraper]:
    """Bir scraper sınıfını kaydeden dekoratör.

    Kullanım:
        @register
        class TKScraper(BaseScraper):
            airline_code = "TK"
    """
    code = cls.airline_code.upper().strip()
    if not code:
        raise ValueError(f"{cls.__name__} için airline_code tanımlı değil")
    _REGISTRY[code] = cls
    return cls


def get_scraper(airline_code: str, config: AppConfig) -> BaseScraper:
    """Havayolu kodu için scraper örneği döndürür.

    - `config.demo_mode` açıksa her havayolu için `DemoScraper` döndürülür
      (canlı istek atılmaz; Playwright gerekmez).
    - Aksi halde kayıtlı gerçek scraper döndürülür; kayıt yoksa yine
      `DemoScraper`e düşülür (uygulama çökmesin diye).
    """
    from scrapers.demo import DemoScraper

    code = airline_code.upper().strip()
    cls = None if getattr(config, "demo_mode", False) else _REGISTRY.get(code)
    if cls is None:
        scraper = DemoScraper(config)
        scraper.airline_code = code
        return scraper
    return cls(config)


def registered_airlines() -> list[str]:
    """Kayıtlı havayolu kodlarının listesi."""
    return sorted(_REGISTRY.keys())


def has_real_scraper(airline_code: str) -> bool:
    """Havayolu için kayıtlı (gerçek) bir scraper var mı?"""
    return airline_code.upper().strip() in _REGISTRY


def load_all_scrapers() -> None:
    """`scrapers` paketindeki tüm scraper modüllerini içe aktarır.

    Import edilmeleri, `@register` dekoratörlerinin çalışmasını ve
    böylece registry'nin dolmasını sağlar.
    """
    import importlib
    import pkgutil

    import scrapers

    for mod in pkgutil.iter_modules(scrapers.__path__):
        if mod.name in {"base", "registry"}:
            continue
        importlib.import_module(f"scrapers.{mod.name}")
