"""Tüm scraper'ların türediği soyut temel sınıf.

`BaseScraper` ortak işleri üstlenir:
- Playwright tarayıcı/bağlam/sayfa yaşam döngüsü
- İnsan davranışı taklidi (rastgele beklemeler)
- Retry mekanizması
- Captcha / timeout / 404 tespiti
- Network response (JSON/API) yakalama altyapısı

Alt sınıflar yalnızca `scrape()` metodunu doldurur. Yeni bir havayolu
eklemek için: bu sınıftan türeyen yeni bir dosya + `registry`e kayıt.
"""
from __future__ import annotations

import random
import time
from abc import ABC
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any, Callable, Iterator, Optional

from config import AppConfig
from core.logging_config import get_logger
from core.models import Cabin, FareBrand
from core.ond import OND
from core.selectors import consent_candidates, get_selectors


class ScrapeError(Exception):
    """Kurtarılamayan scrape hatası (üst katman OND'yi başarısız sayar)."""


class CaptchaError(ScrapeError):
    """Captcha ile karşılaşıldı."""


class NotFoundError(ScrapeError):
    """Sayfa/uçuş bulunamadı (404 veya boş sonuç)."""


class BaseScraper(ABC):
    """Havayolu scraper'ları için temel sınıf.

    Attributes:
        airline_code: İki harfli IATA taşıyıcı kodu (örn. "TK").
        config: Uygulama yapılandırması.
    """

    #: Alt sınıf bunu ezmeli. Registry bu koda göre eşleştirir.
    airline_code: str = ""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.selectors = get_selectors(self.airline_code)
        self.log = get_logger(f"scraper.{self.airline_code.lower()}")
        self._captured_responses: list[dict[str, Any]] = []

    #: Bu kayıt için veri kaynağı etiketi (izlenebilirlik). Örn. "TK-site".
    #: Boşsa `_finalize` `"{airline_code}-site"` üretir.
    source_label: str = ""

    #: HTML DOM'daki özellik satırı metnini standart özellik alanına eşleyen
    #: sözlük (küçük harf anahtar → alan adı). Alt sınıflar doldurur; jenerik
    #: `parse_dom` bunu kullanır. Boşsa DOM'dan özellik çıkarılmaz.
    feature_keywords: dict[str, str] = {}

    #: DOM'dan fiyat okunurken kur bilgisi yoksa varsayılan para birimi.
    dom_currency: str = "EUR"

    # ------------------------------------------------------------------ #
    # Otomatik toplama şablonu (API → HTML). Alt sınıflar kancaları doldurur.
    # ------------------------------------------------------------------ #
    def scrape(self, page: Any, ond: OND, travel_date: str) -> list[FareBrand]:
        """Otomatik toplama: **önce network/JSON (API), sonra HTML DOM**.

        Bu bir şablon metottur; alt sınıflar `open_search`, `parse_api` ve
        `parse_dom` kancalarını doldurur, sıralamayı bu metot yönetir:

          1. ``open_search`` → siteyi aç, çerez onayı, formu doldur, aramayı tetikle.
          2. ``networkidle`` beklemesi + captcha kontrolü.
          3. ``parse_api`` (yakalanan JSON) — doluysa onu döndür.
          4. ``parse_dom`` (görünür kartlar) — API boşsa dene.
          5. İkisi de boşsa ``NotFoundError``.

        Raises:
            CaptchaError, NotFoundError, ScrapeError
        """
        self.open_search(page, ond, travel_date)
        try:
            page.wait_for_load_state("networkidle", timeout=self.config.page_timeout_ms)
        except Exception:  # noqa: BLE001 - networkidle her sitede tetiklenmeyebilir
            pass
        self.check_captcha(page)

        fares = self.parse_api(self._captured_responses, ond) or []
        if fares:
            self.log.info("%s: API yanıtından %d paket", ond, len(fares))
            return fares

        fares = self.parse_dom(page, ond) or []
        if fares:
            self.log.info("%s: HTML DOM'dan %d paket", ond, len(fares))
            return fares

        raise NotFoundError(
            f"{self.airline_code} {ond}: ne API yanıtında ne de HTML'de fare bulundu"
        )

    # ------------------------------------------------------------------ #
    # Alt sınıfların dolduracağı kancalar
    # ------------------------------------------------------------------ #
    def open_search(self, page: Any, ond: OND, travel_date: str) -> None:
        """Siteyi açar, çerezi kabul eder, formu doldurur ve aramayı tetikler.

        Bu **paylaşımlı şablon**, çoğu havayolu sitesi için yeterlidir; TK/AF/LH
        aynı akışı kullanır. Kritik iki adım burada tek yerde sağlamlaştırılmıştır:

        1. ``goto`` sonrası **çerez onayı** (`accept_cookies`): banner geç
           belirse veya bir iframe içinde (OneTrust/Didomi/Usercentrics) olsa
           bile atlatılır — aksi halde overlay input'ları kapatır.
        2. Form doldurulmadan önce **arama alanının görünür olmasını bekleme**
           (`wait_for_ready`): SPA render'ı tamamlanmadan `fill` çağrılmaz.

        Farklı bir akış gereken siteler (ör. derin bağlantı kullanan OTA'lar)
        bu metodu ezer ama yine `self.accept_cookies(page)`'i çağırmalıdır.
        """
        sel = self.selectors
        self.log.info("%s sayfası açılıyor: %s", self.airline_code, sel.get("base_url", ""))
        self._goto(page, sel["base_url"])
        self.accept_cookies(page)
        self.wait_for_ready(page)
        self.human_pause()
        self._fill(page, sel.get("origin_input"), ond.origin)
        self.human_pause()
        self._fill(page, sel.get("destination_input"), ond.destination)
        self.human_pause()
        self._fill(page, sel.get("date_input"), travel_date)
        self.human_pause()
        self._click(page, sel.get("search_button"))

    def parse_api(self, captured: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        """Yakalanan network/JSON yanıtlarından fare üretir (opsiyonel)."""
        return []

    def parse_dom(self, page: Any, ond: OND) -> list[FareBrand]:
        """Görünür DOM'dan (fare kartları) fare üretir.

        Jenerik uygulama: `fare_card` seçicisiyle kartları bulur, her karttan
        `fare_name`/`fare_price` okur ve `feature_row` satırlarını
        `self.feature_keywords` ile standart özelliklere eşler. Çoğu site bu
        akışa uyar; farklı DOM yapısı olan siteler (OTA'lar) bu metodu ezer.
        """
        sel = self.selectors
        card_sel = sel.get("fare_card")
        if not card_sel:
            return []
        try:
            page.wait_for_selector(card_sel, timeout=self.config.page_timeout_ms)
        except Exception:  # noqa: BLE001 - kart yoksa boş döneriz
            return []
        fares: list[FareBrand] = []
        for card in page.query_selector_all(card_sel):
            name_el = card.query_selector(sel["fare_name"]) if sel.get("fare_name") else None
            price_el = card.query_selector(sel["fare_price"]) if sel.get("fare_price") else None
            fb = FareBrand(
                cabin=Cabin.ECONOMY.value,
                fare_brand=(name_el.inner_text().strip() if name_el else ""),
                price=self.parse_price(price_el.inner_text() if price_el else ""),
                currency=self.dom_currency,
                source_url=getattr(page, "url", ""),
            )
            self._apply_dom_features(card, fb)
            if fb.fare_brand:
                fares.append(fb)
        return fares

    def _apply_dom_features(self, card: Any, fb: FareBrand) -> None:
        """Bir karttaki özellik satırlarını `feature_keywords` ile eşler."""
        feature_row = self.selectors.get("feature_row")
        if not feature_row or not self.feature_keywords:
            return
        for row in card.query_selector_all(feature_row):
            text = row.inner_text().strip()
            low = text.lower()
            for keyword, field_name in self.feature_keywords.items():
                if keyword in low:
                    fb.set_feature(field_name, self._feature_state_from_text(text), detail=text)
                    break

    # ------------------------------------------------------------------ #
    # Sayfa sürüşü yardımcıları (sync). Gerçek Playwright sayfası ve testlerdeki
    # sahte page nesneleri ile uyumlu olacak biçimde savunmacı yazılmıştır.
    # ------------------------------------------------------------------ #
    def _goto(self, page: Any, url: str) -> None:
        """Sayfaya gider; mümkünse yalnızca DOM hazır olana kadar bekler."""
        try:
            page.goto(url, wait_until="domcontentloaded")
        except TypeError:
            # Sahte/eski imza: kwargs desteklemiyor.
            page.goto(url)

    def _fill(self, page: Any, selector: str | None, value: str) -> None:
        """Alanı doldurur (Playwright `fill` öğe actionable olana dek bekler).

        Gerçek Playwright sayfasında (``input_value`` mevcutsa) girilen değeri
        oku-geri ile doğrular ve uyuşmazlıkta uyarı verir; testlerdeki sahte
        page'lerde bu adım güvenle atlanır.
        """
        if not selector:
            return
        # Gerçek Playwright'ta locator(...).first: virgülle ayrılmış yedek seçicilerde
        # ilk eşleşeni kullan (strict-mode hatasını önler) ve girilen değeri doğrula.
        locator = getattr(page, "locator", None)
        if callable(locator):
            loc = page.locator(selector).first
            loc.fill(value)
            from core.verify import input_matches

            try:
                actual = loc.input_value()
            except Exception:  # noqa: BLE001
                return
            if not input_matches(value, actual):
                self.log.warning(
                    "%s: '%s' girdisi doğrulanamadı — beklenen %r, alanda %r",
                    self.airline_code, selector, value, actual,
                )
            return
        # Sahte/basit page (testler): düz fill.
        page.fill(selector, value)

    def _click(self, page: Any, selector: str | None) -> None:
        if not selector:
            return
        page.click(selector)

    def wait_for_ready(self, page: Any) -> None:
        """Arama formu görünür olana kadar bekler (input'lara erken yazmayı önler).

        Hata sızdırmaz: seçici yoksa/geç gelirse akış yine denenir; bu, canlı
        sitede sağlamlık, testlerde sahte page uyumluluğu sağlar.
        """
        selector = self.selectors.get("origin_input") or self.selectors.get("fare_card")
        if not selector:
            return
        try:
            page.wait_for_selector(selector, state="visible", timeout=self.config.page_timeout_ms)
        except TypeError:
            try:
                page.wait_for_selector(selector)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 - görünmezse yine de devam et
            pass

    # ------------------------------------------------------------------ #
    # Çerez / onay (consent) — sağlam ve tolerant
    # ------------------------------------------------------------------ #
    def _consent_timeout_ms(self) -> int:
        """Çerez banner'ı için kısa bekleme (yoksa uzun süre bloklamamak için)."""
        return min(self.config.page_timeout_ms, 3500)

    def accept_cookies(self, page: Any) -> bool:
        """Çerez/onay banner'ını kabul eder (varsa). Hiç banner yoksa sessiz geçer.

        Sıra: (1) tüm aday CSS seçicileri tek bir birleşik locator ile ana
        çerçevede bekle/tıkla; (2) yaygın CMP'ler iframe kullandığından
        iframe'leri anlık tara; (3) rol/metin tabanlı son çare ("Accept all"
        vb.). Gerçek Playwright yoksa (test sahte page'i) basit
        `query_selector` yoluna düşer. Hiçbir istisna dışarı sızmaz.
        """
        candidates = consent_candidates(self.selectors)
        if not candidates:
            return False

        if not hasattr(page, "locator"):
            return self._accept_simple(page, candidates)

        timeout = self._consent_timeout_ms()
        combined = ", ".join(candidates)

        # 1) Ana çerçeve: banner belirene kadar (kısa) bekle, sonra tıkla.
        try:
            loc = page.locator(combined).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            self.log.info("%s: çerez onayı kabul edildi", self.airline_code)
            self._settle_after_consent(page, combined)
            return True
        except Exception:  # noqa: BLE001 - banner yok / seçici eşleşmedi
            pass

        # 2) iframe'ler (OneTrust/Didomi çoğu zaman iframe içindedir).
        for frame in list(getattr(page, "frames", []) or []):
            try:
                loc = frame.locator(combined).first
                if loc.count() and loc.is_visible():
                    loc.click()
                    self.log.info("%s: çerez onayı kabul edildi (iframe)", self.airline_code)
                    self._settle_after_consent(page, combined)
                    return True
            except Exception:  # noqa: BLE001
                continue

        # 3) Rol/metin tabanlı son çare.
        return self._accept_by_role(page, min(2000, timeout))

    def _accept_simple(self, page: Any, candidates: list[str]) -> bool:
        """Locator'ı olmayan basit/sahte page için query_selector tabanlı onay."""
        qs = getattr(page, "query_selector", None)
        if not callable(qs):
            return False
        for sel in candidates:
            try:
                if page.query_selector(sel):
                    page.click(sel)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _accept_by_role(self, page: Any, timeout: int) -> bool:
        """"Accept all/Agree/Kabul et" gibi buton metinlerini rol ile hedefler."""
        get_by_role = getattr(page, "get_by_role", None)
        if not callable(get_by_role):
            return False
        import re

        try:
            pattern = re.compile(r"accept all|accept|agree|allow all|kabul", re.I)
            btn = get_by_role("button", name=pattern).first
            btn.wait_for(state="visible", timeout=timeout)
            btn.click()
            self.log.info("%s: çerez onayı kabul edildi (rol/metin)", self.airline_code)
            self.human_pause()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _settle_after_consent(self, page: Any, combined: str) -> None:
        """Onay sonrası banner/overlay'in kaybolmasını bekler (kısa)."""
        try:
            page.locator(combined).first.wait_for(state="hidden", timeout=self._consent_timeout_ms())
        except Exception:  # noqa: BLE001 - gizlenmese de akışa devam
            pass
        self.human_pause()

    # ------------------------------------------------------------------ #
    # Ortak yardımcılar
    # ------------------------------------------------------------------ #
    def run(self, ond: OND, travel_date: str | None = None) -> list[FareBrand]:
        """Tek bir OND'yi retry mekanizmasıyla işler.

        Playwright tarayıcısını açar, `scrape()` çağırır, sonuçları
        package_order'a göre sıralar ve döndürür.
        """
        travel_date = travel_date or self._resolve_date()
        last_error: Optional[Exception] = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                with self._browser_page() as page:
                    self.log.info("%s işleniyor (deneme %d)", ond, attempt)
                    fares = self.scrape(page, ond, travel_date)
                    fares = self._finalize(fares, ond, travel_date)
                    self.log.info("%s: %d paket bulundu", ond, len(fares))
                    return fares
            except CaptchaError as exc:
                self.log.warning("Captcha (%s): %s", ond, exc)
                last_error = exc
            except NotFoundError as exc:
                self.log.warning("Bulunamadı (%s): %s", ond, exc)
                raise  # 404'te retry anlamsız
            except ImportError as exc:
                # Playwright kurulu değil: tekrar denemek anlamsız. Kullanıcıya
                # net yönlendirme ver (demo modu ya da 'pip install playwright').
                raise ScrapeError(
                    f"{self.airline_code} için Playwright gerekli ama bulunamadı ({exc}). "
                    "Kurulum: 'pip install playwright && playwright install chromium' "
                    "veya çevrimdışı test için demo modunu kullanın (--demo)."
                ) from exc
            except Exception as exc:  # noqa: BLE001 - geniş yakalama kasıtlı
                self.log.warning("Hata (%s, deneme %d): %s", ond, attempt, exc)
                last_error = exc

            if attempt < self.config.max_retries:
                self._backoff(attempt)

        raise ScrapeError(f"{ond} {self.config.max_retries} denemede başarısız: {last_error}")

    @contextmanager
    def _browser_page(self) -> Iterator[Any]:
        """Playwright sayfası açan context manager.

        Import'u burada tutarız ki Playwright kurulu olmasa da modül
        yüklenebilsin (örn. sadece demo scraper kullanılırken).
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.config.headless)
            context = browser.new_context(
                user_agent=self.config.user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 900},
            )
            context.set_default_timeout(self.config.page_timeout_ms)
            context.set_default_navigation_timeout(self.config.navigation_timeout_ms)
            page = context.new_page()
            self._captured_responses.clear()
            page.on("response", self._on_response)
            try:
                yield page
            finally:
                context.close()
                browser.close()

    def _on_response(self, response: Any) -> None:
        """Network response'ları yakalar (API/JSON yaklaşımı için).

        `api_pattern` ile eşleşen JSON yanıtları saklanır; scraper
        `self._captured_responses` üzerinden bunları okuyabilir.
        """
        import re

        pattern = self.selectors.get("api_pattern")
        if not pattern:
            return
        try:
            if re.search(pattern, response.url) and "json" in response.headers.get("content-type", ""):
                self._captured_responses.append({"url": response.url, "json": response.json()})
        except Exception:  # pragma: no cover - bazı response'lar okunamaz
            pass

    def human_pause(self) -> None:
        """İnsan davranışını taklit eden rastgele bekleme."""
        time.sleep(random.uniform(self.config.human_delay_min_s, self.config.human_delay_max_s))

    def check_captcha(self, page: Any) -> None:
        """Sayfada captcha varsa `CaptchaError` fırlatır."""
        marker = self.selectors.get("captcha_marker")
        if marker and page.query_selector(marker):
            raise CaptchaError(f"{self.airline_code}: captcha tespit edildi")

    def _backoff(self, attempt: int) -> None:
        """Üssel geri çekilme (retry arası bekleme)."""
        time.sleep(self.config.retry_backoff_s * attempt)

    @staticmethod
    def parse_price(raw: Any) -> Optional[float]:
        """Serbest metinden/nesneden sayısal fiyat çıkarır.

        '1.234,56 EUR', '€1,234.56', '1234' gibi biçimleri tolere eder; hem
        Avrupa (1.234,56) hem ABD (1,234.56) ondalık düzenini algılar.
        """
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        import re

        text = str(raw)
        m = re.search(r"[\d][\d.,\s]*", text)
        if not m:
            return None
        num = re.sub(r"\s", "", m.group()).strip(".,")
        if "," in num and "." in num:
            # Son görülen ayraç ondalık kabul edilir.
            if num.rfind(",") > num.rfind("."):
                num = num.replace(".", "").replace(",", ".")
            else:
                num = num.replace(",", "")
        elif "," in num:
            # Tek virgül: ondalık mı binlik mi? Son gruptaki hane sayısına bak.
            num = num.replace(",", ".") if len(num.split(",")[-1]) != 3 else num.replace(",", "")
        try:
            return float(num)
        except ValueError:
            return None

    @staticmethod
    def _feature_state_from_text(text: str) -> "FeatureState":
        """Özellik satırı metninden dahil/ücretli/yok durumu çıkarır."""
        from core.models import FeatureState

        t = text.lower()
        if any(k in t for k in ("✓", "included", "dahil", "free", "yes", "ücretsiz")):
            return FeatureState.INCLUDED
        if any(k in t for k in ("€", "$", "£", "fee", "paid", "chargeable", "ücretli", "extra")):
            return FeatureState.PAID
        if any(k in t for k in ("✕", "×", "not ", "yok", "n/a", "unavailable", "—", "-")):
            return FeatureState.NOT_INCLUDED
        return FeatureState.UNKNOWN

    def _resolve_date(self) -> str:
        """Yapılandırmadan uçuş tarihini çözer."""
        if self.config.default_travel_date:
            return self.config.default_travel_date
        return (date.today() + timedelta(days=self.config.default_days_ahead)).isoformat()

    def _finalize(self, fares: list[FareBrand], ond: OND, travel_date: str) -> list[FareBrand]:
        """Ortak alanları doldurur ve paketleri fiyata göre sıralar."""
        default_source = self.source_label or f"{self.airline_code}-site"
        for f in fares:
            f.airline = f.airline or ond.airline
            f.origin = f.origin or ond.origin
            f.destination = f.destination or ond.destination
            f.travel_date = f.travel_date or travel_date
            f.source = f.source or default_source
        # Fiyatı olan paketleri düşükten yükseğe sırala, package_order ata
        fares.sort(key=lambda f: (f.price is None, f.price if f.price is not None else 0))
        for idx, f in enumerate(fares, start=1):
            if not f.package_order:
                f.package_order = idx
        return fares
