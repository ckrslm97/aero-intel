"""Async çok-sekme toplama motoru.

Aynı **taşıyıcı + tarih** için birden çok rotayı (OND) **tek bir tarayıcı
bağlamında** ve **eşzamanlı sekmelerle** çeker. Böylece:

- Çerez/onay bir kez (bağlam düzeyinde) kabul edilir; sonraki sekmelerde banner
  çıkmaz (consent cookie bağlam boyunca paylaşılır).
- N rota, `config.pages_per_browser` kadar sekmeyle aynı anda sorgulanır — her
  OND için ayrı tarayıcı açmaya göre çok daha hızlı ve hafiftir.

Tasarım: motor **yalnızca tarayıcı sürüşünü** async'e taşır (goto/çerez/fill/
click/DOM). Taşıyıcıya özel `parse_api` (yakalanan JSON → fare) **saf ve
motor-bağımsız** olduğundan doğrudan yeniden kullanılır; `parse_price`,
`_feature_state_from_text`, `_finalize` de sync olarak paylaşılır.

Bu motor gerçek havayolu scraper'ları (TK/AF/LH gibi, paylaşımlı arama şablonunu
kullananlar) içindir. OTA yedeği `core/runner.py` içinde sync yolda kalır.
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any

from config import AppConfig
from core.logging_config import get_logger
from core.models import Cabin, FareBrand
from core.ond import OND
from core.selectors import consent_candidates
from scrapers.base import BaseScraper, CaptchaError, NotFoundError

log = get_logger("async_engine")

#: Çerez banner'ı için üst sınır (yoksa uzun süre bloklamamak için kısa tutulur).
_CONSENT_TIMEOUT_MS = 3500
_CONSENT_ROLE_PATTERN = re.compile(r"accept all|accept|agree|allow all|kabul", re.I)


async def scrape_group(
    scraper: BaseScraper,
    onds: list[OND],
    travel_date: str,
    config: AppConfig,
) -> dict[str, list[FareBrand] | Exception]:
    """Bir taşıyıcının OND grubunu tek bağlamda, çok sekmeyle eşzamanlı çeker.

    Returns:
        ``ond.key`` → ``list[FareBrand]`` (başarı) veya ``Exception`` (başarısız)
        sözlüğü. Bir sekmedeki hata diğerlerini etkilemez.
    """
    results: dict[str, list[FareBrand] | Exception] = {}
    if not onds:
        return results

    from playwright.async_api import async_playwright

    max_tabs = max(1, min(config.pages_per_browser, len(onds)))
    log.info(
        "%s: %d OND, tek tarayıcıda %d eşzamanlı sekme ile çekilecek",
        scraper.airline_code, len(onds), max_tabs,
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)
        context = await browser.new_context(
            user_agent=config.user_agent,
            locale="en-US",
            viewport={"width": 1440, "height": 900},
        )
        context.set_default_timeout(config.page_timeout_ms)
        context.set_default_navigation_timeout(config.navigation_timeout_ms)
        try:
            # Isınma: çerezi bağlam düzeyinde bir kez kabul et.
            await _warmup_consent(scraper, context, config)

            sem = asyncio.Semaphore(max_tabs)

            async def worker(ond: OND) -> tuple[str, list[FareBrand] | Exception]:
                async with sem:
                    page = await context.new_page()
                    try:
                        fares = await _scrape_one(scraper, page, ond, travel_date, config)
                        return ond.key, fares
                    except Exception as exc:  # noqa: BLE001 - sekme bazında izole
                        return ond.key, exc
                    finally:
                        try:
                            await page.close()
                        except Exception:  # noqa: BLE001
                            pass

            pairs = await asyncio.gather(*(worker(o) for o in onds))
            results.update(dict(pairs))
        finally:
            try:
                await context.close()
            finally:
                await browser.close()

    return results


# --------------------------------------------------------------------------- #
# Tek OND (tek sekme)
# --------------------------------------------------------------------------- #
async def _scrape_one(
    scraper: BaseScraper, page: Any, ond: OND, travel_date: str, config: AppConfig
) -> list[FareBrand]:
    """Tek bir OND'yi kendi sekmesinde çeker (API → HTML)."""
    pattern = scraper.selectors.get("api_pattern")
    matched: list[Any] = []

    def on_response(response: Any) -> None:
        # Callback sync; response.json() (async) burada beklenmez — eşleşen
        # yanıtlar saklanır, JSON gövdesi networkidle sonrası okunur.
        try:
            if pattern and re.search(pattern, response.url):
                if "json" in response.headers.get("content-type", ""):
                    matched.append(response)
        except Exception:  # noqa: BLE001
            pass

    page.on("response", on_response)

    await _open_search(scraper, page, ond, travel_date, config)

    try:
        await page.wait_for_load_state("networkidle", timeout=config.page_timeout_ms)
    except Exception:  # noqa: BLE001 - networkidle her sitede tetiklenmeyebilir
        pass

    await _check_captcha(scraper, page)

    # Yakalanan yanıtların JSON gövdesini oku.
    captured: list[dict[str, Any]] = []
    for resp in matched:
        try:
            captured.append({"url": resp.url, "json": await resp.json()})
        except Exception:  # noqa: BLE001 - bazı yanıtlar okunamaz
            pass

    fares = scraper.parse_api(captured, ond) or []
    if fares:
        log.info("%s %s: API yanıtından %d paket", scraper.airline_code, ond, len(fares))
    else:
        fares = await _parse_dom(scraper, page, ond, config)
        if fares:
            log.info("%s %s: HTML DOM'dan %d paket", scraper.airline_code, ond, len(fares))

    if not fares:
        raise NotFoundError(
            f"{scraper.airline_code} {ond}: ne API yanıtında ne de HTML'de fare bulundu"
        )
    return scraper._finalize(fares, ond, travel_date)


# --------------------------------------------------------------------------- #
# Arama akışı (async, paylaşımlı şablon)
# --------------------------------------------------------------------------- #
async def _open_search(
    scraper: BaseScraper, page: Any, ond: OND, travel_date: str, config: AppConfig
) -> None:
    """Siteyi açar, çerezi kabul eder (bağlamda zaten kabul edildiyse hızlı geçer),
    formun hazır olmasını bekler ve aramayı tetikler."""
    sel = scraper.selectors
    await _goto(page, sel["base_url"], config)
    await _accept_cookies(scraper, page, config)
    await _wait_ready(scraper, page, config)
    await _human_pause(config)
    await _fill(page, sel.get("origin_input"), ond.origin)
    await _human_pause(config)
    await _fill(page, sel.get("destination_input"), ond.destination)
    await _human_pause(config)
    await _fill(page, sel.get("date_input"), travel_date)
    await _human_pause(config)
    await _click(page, sel.get("search_button"))


async def _goto(page: Any, url: str, config: AppConfig) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=config.navigation_timeout_ms)


async def _fill(page: Any, selector: str | None, value: str) -> None:
    if not selector:
        return
    try:
        await page.fill(selector, value)
    except Exception as exc:  # noqa: BLE001 - alan bulunamazsa akış yine denenir
        log.debug("fill atlandı (%s): %s", selector, exc)


async def _click(page: Any, selector: str | None) -> None:
    if not selector:
        return
    try:
        await page.click(selector)
    except Exception as exc:  # noqa: BLE001
        log.debug("click atlandı (%s): %s", selector, exc)


async def _wait_ready(scraper: BaseScraper, page: Any, config: AppConfig) -> None:
    """Arama formu (ya da sonuç kartları) görünene kadar bekler — erken fill'i önler."""
    selector = scraper.selectors.get("origin_input") or scraper.selectors.get("fare_card")
    if not selector:
        return
    try:
        await page.wait_for_selector(selector, state="visible", timeout=config.page_timeout_ms)
    except Exception:  # noqa: BLE001 - görünmezse yine de devam et
        pass


async def _human_pause(config: AppConfig) -> None:
    await asyncio.sleep(random.uniform(config.human_delay_min_s, config.human_delay_max_s))


# --------------------------------------------------------------------------- #
# Çerez / onay (async)
# --------------------------------------------------------------------------- #
async def _warmup_consent(scraper: BaseScraper, context: Any, config: AppConfig) -> None:
    """Bir kez siteye gidip çerezi kabul eder; cookie bağlamda paylaşıldığından
    sonraki sekmeler banner görmez."""
    base = scraper.selectors.get("base_url")
    if not base:
        return
    page = await context.new_page()
    try:
        await _goto(page, base, config)
        await _accept_cookies(scraper, page, config)
    except Exception as exc:  # noqa: BLE001 - ısınma başarısızsa sekmeler kendi başına dener
        log.info("%s: ısınma/çerez adımı atlandı: %s", scraper.airline_code, exc)
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass


async def _accept_cookies(scraper: BaseScraper, page: Any, config: AppConfig) -> bool:
    """Çerez/onay banner'ını kabul eder (varsa). Ana çerçeve → iframe → rol/metin.

    Banner yoksa kısa bir bekleme sonrası sessizce döner; hiçbir istisna sızmaz.
    """
    candidates = consent_candidates(scraper.selectors)
    if not candidates:
        return False
    timeout = min(config.page_timeout_ms, _CONSENT_TIMEOUT_MS)
    combined = ", ".join(candidates)

    # 1) Ana çerçeve.
    try:
        loc = page.locator(combined).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click()
        log.info("%s: çerez onayı kabul edildi", scraper.airline_code)
        try:
            await loc.wait_for(state="hidden", timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001 - banner yok / eşleşmedi
        pass

    # 2) iframe'ler (OneTrust/Didomi çoğu zaman iframe içindedir).
    for frame in page.frames:
        try:
            loc = frame.locator(combined).first
            if await loc.count() and await loc.is_visible():
                await loc.click()
                log.info("%s: çerez onayı kabul edildi (iframe)", scraper.airline_code)
                return True
        except Exception:  # noqa: BLE001
            continue

    # 3) Rol/metin tabanlı son çare.
    try:
        btn = page.get_by_role("button", name=_CONSENT_ROLE_PATTERN).first
        await btn.wait_for(state="visible", timeout=min(2000, timeout))
        await btn.click()
        log.info("%s: çerez onayı kabul edildi (rol/metin)", scraper.airline_code)
        return True
    except Exception:  # noqa: BLE001
        return False


async def _check_captcha(scraper: BaseScraper, page: Any) -> None:
    marker = scraper.selectors.get("captcha_marker")
    if not marker:
        return
    try:
        found = await page.query_selector(marker)
    except Exception:  # noqa: BLE001
        return
    if found:
        raise CaptchaError(f"{scraper.airline_code}: captcha tespit edildi")


# --------------------------------------------------------------------------- #
# HTML DOM ayrıştırma (async, jenerik — feature_keywords ile)
# --------------------------------------------------------------------------- #
async def _parse_dom(
    scraper: BaseScraper, page: Any, ond: OND, config: AppConfig
) -> list[FareBrand]:
    sel = scraper.selectors
    card_sel = sel.get("fare_card")
    if not card_sel:
        return []
    try:
        await page.wait_for_selector(card_sel, timeout=config.page_timeout_ms)
    except Exception:  # noqa: BLE001 - kart yoksa boş döneriz
        return []

    fares: list[FareBrand] = []
    feature_row = sel.get("feature_row")
    for card in await page.query_selector_all(card_sel):
        name = await _inner_text(card, sel.get("fare_name"))
        price_text = await _inner_text(card, sel.get("fare_price"))
        fb = FareBrand(
            cabin=Cabin.ECONOMY.value,
            fare_brand=name.strip(),
            price=scraper.parse_price(price_text),
            currency=scraper.dom_currency,
            source_url=page.url,
        )
        if feature_row and scraper.feature_keywords:
            for row in await card.query_selector_all(feature_row):
                text = (await row.inner_text()).strip()
                low = text.lower()
                for keyword, field_name in scraper.feature_keywords.items():
                    if keyword in low:
                        fb.set_feature(field_name, scraper._feature_state_from_text(text), detail=text)
                        break
        if fb.fare_brand:
            fares.append(fb)
    return fares


async def _inner_text(card: Any, selector: str | None) -> str:
    if not selector:
        return ""
    try:
        el = await card.query_selector(selector)
        if not el:
            return ""
        return await el.inner_text()
    except Exception:  # noqa: BLE001
        return ""
