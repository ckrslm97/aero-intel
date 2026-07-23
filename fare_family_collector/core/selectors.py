"""Merkezi CSS selector / XPath kaydı.

Site tasarımları sık değişir. Tüm seçiciler tek bir yerde, havayolu
koduna göre saklanır; böylece bir site güncellendiğinde yalnızca bu
dosyadaki ilgili blok düzenlenir, scraper mantığına dokunulmaz.

Kullanım:
    sel = SELECTORS["TK"]
    page.click(sel["search_button"])
"""
from __future__ import annotations

from typing import TypedDict


class SiteSelectors(TypedDict, total=False):
    """Bir havayolu sitesi için beklenen seçici anahtarları.

    Tüm anahtarlar opsiyoneldir; bir scraper yalnızca ihtiyaç duyduklarını
    kullanır. API tabanlı çalışan scraper'lar HTML seçicilerine ihtiyaç
    duymayabilir.
    """

    base_url: str            # Arama başlangıç URL'i (şablon)
    api_pattern: str         # Yakalanacak network response URL deseni (regex)
    consent_button: str      # Çerez/onay butonu (tek seçici; geriye dönük uyum)
    consent_buttons: list    # Çerez/onay için sıralı yedek seçici listesi
    origin_input: str
    destination_input: str
    date_input: str
    search_button: str
    fare_card: str           # Her fare paketini saran öğe
    fare_name: str           # Paket adı
    fare_price: str          # Fiyat
    cabin_tab: str           # Kabin sekmesi
    feature_row: str         # Özellik satırı
    captcha_marker: str      # Captcha tespiti için işaret


# Sık kullanılan çerez/onay (CMP) sağlayıcılarının "hepsini kabul et"
# butonları. Site-özel seçiciler tutmazsa bu ortak yedekler denenir; böylece
# OneTrust / Didomi / Usercentrics / Cookiebot / Quantcast gibi yaygın banner'lar
# ekstra kod yazmadan atlatılır. Sıra önemlidir (en yaygın → en genel).
COMMON_CONSENT_FALLBACKS: tuple[str, ...] = (
    "#onetrust-accept-btn-handler",                       # OneTrust
    "#didomi-notice-agree-button",                        # Didomi
    "button#didomi-notice-agree-button",
    "[data-testid='uc-accept-all-button']",               # Usercentrics
    "button[data-testid='uc-accept-all-button']",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # Cookiebot
    "#CybotCookiebotDialogBodyButtonAccept",
    ".qc-cmp2-summary-buttons button[mode='primary']",    # Quantcast
    "button#accept-recommended-btn-handler",
    "button[aria-label*='accept' i]",
    "button[aria-label*='agree' i]",
    "button[title*='accept' i]",
    "button.cookie-accept, button.accept-cookies, button#accept, #accept-cookies",
)


# Havayolu koduna göre seçici sözlüğü. Buraya yeni havayolu eklemek,
# ilgili scraper dosyasıyla birlikte yeni bir blok eklemek kadar basittir.
SELECTORS: dict[str, SiteSelectors] = {
    "TK": {
        "base_url": "https://www.turkishairlines.com/en-int/flights/booking/",
        "api_pattern": r"availability|fare|pricing",
        "consent_button": "#cookie-accept, button[aria-label='Accept']",
        "consent_buttons": [
            "#cookie-accept",
            "button[aria-label='Accept']",
            "button[aria-label='Accept all']",
            "#onetrust-accept-btn-handler",
        ],
        "origin_input": "input[name='portChooserInput-origin']",
        "destination_input": "input[name='portChooserInput-destination']",
        "date_input": "input[name='departureDate']",
        "search_button": "button[aria-label='Search flights']",
        "fare_card": "div.fare-brand-card",
        "fare_name": ".fare-brand-name",
        "fare_price": ".fare-price .amount",
        "cabin_tab": ".cabin-selector button",
        "feature_row": ".fare-feature-row",
        "captcha_marker": "iframe[src*='captcha'], #px-captcha",
    },
    "AF": {
        "base_url": "https://www.airfrance.com/search/",
        "api_pattern": r"availability|offers|fare-families",
        "consent_button": "#didomi-notice-agree-button",
        "consent_buttons": [
            "#didomi-notice-agree-button",
            "button#didomi-notice-agree-button",
            "button[aria-label*='Agree' i]",
        ],
        "origin_input": "input#originCity",
        "destination_input": "input#destinationCity",
        "date_input": "input#departureDate",
        "search_button": "button[type='submit'][data-testid='search']",
        "fare_card": "div[data-testid='fare-family-card']",
        "fare_name": "[data-testid='fare-family-name']",
        "fare_price": "[data-testid='fare-price']",
        "cabin_tab": "[role='tab'][data-cabin]",
        "feature_row": "li[data-testid='fare-feature']",
        "captcha_marker": "iframe[title*='captcha']",
    },
    "LH": {
        # Lufthansa — Continue.com/lufthansa.com akışı. Fare family verisi
        # arama sonrası XHR ile (offers/fare-families) döner; DOM'da da
        # "Choose your fare" kartları bulunur.
        "base_url": "https://www.lufthansa.com/de/en/flight-search",
        "api_pattern": r"offers|fare-?famil|pricing|availability|farefinder",
        "consent_button": "#cm-acceptAll, button[data-testid='accept-all-button']",
        "consent_buttons": [
            "#cm-acceptAll",
            "button[data-testid='accept-all-button']",
            "button[aria-label*='Accept all' i]",
        ],
        "origin_input": "input#flight-origin, input[name='originCity']",
        "destination_input": "input#flight-destination, input[name='destinationCity']",
        "date_input": "input[name='outboundDate'], input#departureDate",
        "search_button": "button[data-testid='flight-search-submit'], button[type='submit']",
        "fare_card": "[data-testid='fare-family-card'], .fare-family, .o-fare-card",
        "fare_name": "[data-testid='fare-family-name'], .fare-family__name, .o-fare-card__title",
        "fare_price": "[data-testid='fare-price'], .fare-family__price, .o-fare-card__price",
        "cabin_tab": "[role='tab'][data-cabin], .cabin-class-selector button",
        "feature_row": "[data-testid='fare-feature'], .fare-family__benefit, li.o-fare-card__benefit",
        "captcha_marker": "iframe[src*='captcha'], #distilCaptchaForm, iframe[title*='captcha']",
    },
    # ---- OTA (Online Travel Agency) kaynakları — havayolu sitesi yedeği ---- #
    "GOOGLE": {
        # Google Flights — branded fares/price verisini XHR (GetShoppingResults
        # / rpc) ile döndürür; DOM'da uçuş kartları ve "fare options" bulunur.
        "base_url": "https://www.google.com/travel/flights",
        "api_pattern": r"GetShoppingResults|travel/flights|batchexecute|rpc",
        "consent_button": "button[aria-label*='Accept'], button[jsname='higCR']",
        "consent_buttons": [
            "button[jsname='higCR']",
            "button[aria-label*='Accept all' i]",
            "button[aria-label*='Accept' i]",
            "form[action*='consent'] button",
        ],
        "origin_input": "input[aria-label='Where from?'], input[placeholder='Where from?']",
        "destination_input": "input[aria-label='Where to?'], input[placeholder='Where to?']",
        "date_input": "input[aria-label*='Departure']",
        "search_button": "button[aria-label='Search'], button[jsname='vLv7Lb']",
        "fare_card": "li.pIav2d, div[role='listitem']",
        "fare_name": "div.sSHqwe, .JMc5Xc",
        "fare_price": "div.YMlIz, span[data-gs] , .BVAVmf",
        "cabin_tab": "div[jsname='oYxtQd'] button",
        "feature_row": ".Xj7YFd, .MX5RWe",
        "captcha_marker": "form#captcha-form, iframe[src*='recaptcha']",
    },
    "KAYAK": {
        # Kayak — fiyat/kabin/marka. Sonuçlar XHR (flights/results/…) ile döner;
        # DOM'da result kartları (data-resultid) bulunur.
        "base_url": "https://www.kayak.com/flights",
        "api_pattern": r"flights/results|FlightResultDelta|/s/horizon|poll",
        "consent_button": "button[aria-label*='Accept'], div.RxNS-button",
        "consent_buttons": [
            "button[aria-label*='Accept all' i]",
            "button[aria-label*='Accept' i]",
            "div.RxNS-button",
        ],
        "origin_input": "input[aria-label*='Flight origin'], input[placeholder*='From']",
        "destination_input": "input[aria-label*='Flight destination'], input[placeholder*='To']",
        "date_input": "div[aria-label*='Departure']",
        "search_button": "button[aria-label='Search'], button.RxNS-button-content",
        "fare_card": "div[class*='resultInner'], div[data-resultid]",
        "fare_name": "div[class*='fareFamily'], div[class*='brand']",
        "fare_price": "div[class*='price-text'], span.price",
        "cabin_tab": "div[class*='cabin'] button",
        "feature_row": "div[class*='amenit'], li[class*='feature']",
        "captcha_marker": "div#px-captcha, iframe[src*='captcha']",
    },
    # Diğer havayolları için şablon. Kopyala, kodu değiştir, seçicileri doldur.
    "_TEMPLATE": {
        "base_url": "https://example-airline.com/booking/",
        "api_pattern": r"fare|availability",
        "consent_button": "button.cookie-accept",
        "origin_input": "input[name='origin']",
        "destination_input": "input[name='destination']",
        "date_input": "input[name='date']",
        "search_button": "button.search",
        "fare_card": ".fare-card",
        "fare_name": ".fare-name",
        "fare_price": ".price",
        "cabin_tab": ".cabin-tab",
        "feature_row": ".feature",
        "captcha_marker": "#captcha",
    },
}


def get_selectors(airline_code: str) -> SiteSelectors:
    """Havayolu kodu için seçicileri döndürür; yoksa şablonu döndürür."""
    return SELECTORS.get(airline_code.upper(), SELECTORS["_TEMPLATE"])


def consent_candidates(selectors: SiteSelectors) -> list[str]:
    """Çerez/onay için denenecek seçicileri sıralı ve tekilleştirilmiş döndürür.

    Sıra: önce site-özel seçiciler (``consent_buttons`` listesi ya da tek
    ``consent_button``, virgülle ayrılmış olabilir), sonra sık kullanılan CMP
    yedekleri (`COMMON_CONSENT_FALLBACKS`). Böylece site kendi butonunu
    tanımlamasa bile OneTrust/Didomi/Usercentrics gibi yaygın banner'lar
    otomatik denenir.
    """
    ordered: list[str] = []

    site_list = selectors.get("consent_buttons") or []
    for sel in site_list:
        if sel:
            ordered.append(str(sel).strip())

    single = selectors.get("consent_button") or ""
    for part in str(single).split(","):
        part = part.strip()
        if part:
            ordered.append(part)

    ordered.extend(COMMON_CONSENT_FALLBACKS)

    # Sırayı koruyarak tekilleştir.
    seen: set[str] = set()
    result: list[str] = []
    for sel in ordered:
        if sel and sel not in seen:
            seen.add(sel)
            result.append(sel)
    return result
