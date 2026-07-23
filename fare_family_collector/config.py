"""Uygulama yapılandırması.

Tüm ayarlar tek bir `AppConfig` dataclass'ında toplanır. Değerler
``.env`` dosyasından (varsa) okunabilir. Kod içinde "magic number"
kullanılmaz; her sabit burada isimlendirilir.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv opsiyonel; yoksa sistem env kullanılır
    pass


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on", "evet"}


def _env_list(key: str, default: list[str]) -> list[str]:
    """Virgülle ayrılmış ortam değişkenini listeye çevirir (boşsa default)."""
    val = os.getenv(key)
    if val is None:
        return list(default)
    items = [x.strip().lower() for x in val.split(",") if x.strip()]
    return items or list(default)


@dataclass
class AppConfig:
    """Çalışma zamanı ayarları."""

    # Playwright
    headless: bool = field(default_factory=lambda: _env_bool("HEADLESS", True))
    page_timeout_ms: int = field(default_factory=lambda: _env_int("PAGE_TIMEOUT_MS", 30_000))
    navigation_timeout_ms: int = field(default_factory=lambda: _env_int("NAV_TIMEOUT_MS", 45_000))
    user_agent: str = field(default_factory=lambda: os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    ))

    # İnsan davranışı taklidi (min/max saniye)
    human_delay_min_s: float = field(default_factory=lambda: _env_float("HUMAN_DELAY_MIN", 0.4))
    human_delay_max_s: float = field(default_factory=lambda: _env_float("HUMAN_DELAY_MAX", 1.8))

    # Retry
    max_retries: int = field(default_factory=lambda: _env_int("MAX_RETRIES", 3))
    retry_backoff_s: float = field(default_factory=lambda: _env_float("RETRY_BACKOFF", 2.0))

    # Eşzamanlılık
    # max_workers: canlı modda kaç taşıyıcı grubunun paralel işleneceği (her grup
    #   kendi tarayıcısında). Demo modda OND başına thread sayısı.
    max_workers: int = field(default_factory=lambda: _env_int("MAX_WORKERS", 3))
    # pages_per_browser: aynı taşıyıcı+tarih için tek tarayıcıda kaç sekmenin
    #   AYNI ANDA sorgu atacağı (async çok-sekme). Yüksek değer daha hızlıdır ama
    #   sitenin anti-bot eşiğini tetikleyebilir.
    pages_per_browser: int = field(default_factory=lambda: _env_int("PAGES_PER_BROWSER", 4))

    # Demo / çevrimdışı mod: True ise HİÇBİR canlı istek atılmaz; tüm
    # havayolları (kayıtlı gerçek scraper'ı olsa bile) DemoScraper'a düşer.
    # Böylece Playwright kurulu olmasa da uygulama uçtan uca hatasız çalışır.
    demo_mode: bool = field(default_factory=lambda: _env_bool("DEMO_MODE", False))

    # OTA yedeği: Havayolunun kendi sitesinden veri alınamazsa (erişim/anti-bot/
    # boş sonuç) sırayla OTA kaynakları denenir; ilk veri dönen kullanılır.
    use_ota_fallback: bool = field(default_factory=lambda: _env_bool("USE_OTA_FALLBACK", True))
    ota_sources: list[str] = field(default_factory=lambda: _env_list("OTA_SOURCES", ["google", "kayak"]))

    # Çıktı
    output_dir: Path = field(default_factory=lambda: Path(os.getenv("OUTPUT_DIR", "output")))
    export_excel: bool = field(default_factory=lambda: _env_bool("EXPORT_EXCEL", True))
    export_csv: bool = field(default_factory=lambda: _env_bool("EXPORT_CSV", True))
    export_sqlite: bool = field(default_factory=lambda: _env_bool("EXPORT_SQLITE", True))
    export_json: bool = field(default_factory=lambda: _env_bool("EXPORT_JSON", True))

    # Resume / dedup
    resume: bool = field(default_factory=lambda: _env_bool("RESUME", True))
    skip_existing: bool = field(default_factory=lambda: _env_bool("SKIP_EXISTING", True))

    # Varsayılan uçuş tarihi (boşsa scraper bugünden N gün sonrasını kullanır)
    default_travel_date: str = field(default_factory=lambda: os.getenv("TRAVEL_DATE", ""))
    default_days_ahead: int = field(default_factory=lambda: _env_int("DAYS_AHEAD", 30))

    # Logging
    log_dir: Path = field(default_factory=lambda: Path(os.getenv("LOG_DIR", "logs")))

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.log_dir = Path(self.log_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Değer akıl sınırları
        self.max_workers = max(1, min(self.max_workers, 16))
        self.pages_per_browser = max(1, min(self.pages_per_browser, 12))
        if self.human_delay_max_s < self.human_delay_min_s:
            self.human_delay_max_s = self.human_delay_min_s


# Uygulama genelinde tek örnek
CONFIG = AppConfig()
