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
        # NOT: TK canlı formu dinamik ve sık değişir. Birden çok yedek seçici
        # verilir; fill `.first` ile ilk eşleşeni kullanır. Canlıda doğrulamak için:
        # `playwright codegen https://www.turkishairlines.com/en-int/flights/booking/`
        "origin_input": (
            "input[name='portChooserInput-origin'], "
            "input#fromPort, input#booking-origin, "
            "input[aria-label*='From' i], input[placeholder*='From' i], "
            "input[data-testid*='origin' i], input[data-test*='from' i]"
        ),
        "destination_input": (
            "input[name='portChooserInput-destination'], "
            "input#toPort, input#booking-destination, "
            "input[aria-label*='To' i], input[placeholder*='To' i], "
            "input[data-testid*='destination' i], input[data-test*='to' i]"
        ),
        "date_input": (
            "input[name='departureDate'], input#departureDate, "
            "input[aria-label*='Depart' i], input[placeholder*='Depart' i], "
            "input[data-testid*='depart' i]"
        ),
        "search_button": (
            "button[aria-label='Search flights'], button[aria-label*='Search' i], "
            "button[type='submit'], button[data-testid*='search' i]"
        ),
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
    "BA": {
        # British Airways — fare family ("Economy Basic/Plus", "Club" vb.) verisi
        # arama sonrası XHR ile döner; DOM'da da kabin/marka kartları bulunur.
        # UYARI: Seçiciler canlıda doğrulanmalı (playwright codegen).
        "base_url": "https://www.britishairways.com/travel/home/public/en_gb/",
        "api_pattern": r"availability|fare|farefamil|pricing|offers",
        "consent_button": "button#ensCloseBanner, #onetrust-accept-btn-handler",
        "consent_buttons": [
            "button#ensCloseBanner",
            "#onetrust-accept-btn-handler",
            "button[aria-label*='Accept all' i]",
        ],
        "origin_input": "input#planpanelmain\\:_id1:bookFlightModule:depAirport, input[name='departurePoint']",
        "destination_input": "input#planpanelmain\\:_id1:bookFlightModule:destAirport, input[name='destinationPoint']",
        "date_input": "input[name='outboundDate'], input#departureDate",
        "search_button": "button[type='submit'], button[data-test='search-flights']",
        "fare_card": "[data-test='fare-card'], .fare-family-card, .cabin-fare",
        "fare_name": "[data-test='fare-name'], .fare-family-card__title",
        "fare_price": "[data-test='fare-price'], .fare-family-card__price",
        "cabin_tab": "[role='tab'][data-cabin], .cabin-selector button",
        "feature_row": "[data-test='fare-feature'], .fare-family-card__benefit, li.benefit",
        "captcha_marker": "iframe[src*='captcha'], #px-captcha",
    },
    "PC": {
        # Pegasus (flypgs) — düşük maliyetli; "Essentials/Advantage/Extra" paketleri.
        # UYARI: Seçiciler canlıda doğrulanmalı.
        "base_url": "https://www.flypgs.com/en",
        "api_pattern": r"availability|fare|package|pricing|offers|search",
        "consent_button": "#onetrust-accept-btn-handler, button.cookie-accept",
        "consent_buttons": [
            "#onetrust-accept-btn-handler",
            "button[aria-label*='Accept' i]",
            "button.cookie-accept",
        ],
        "origin_input": "input#depPort, input[name='departurePort'], input[placeholder*='From' i]",
        "destination_input": "input#arrPort, input[name='arrivalPort'], input[placeholder*='To' i]",
        "date_input": "input#departureDate, input[name='departureDate']",
        "search_button": "button#flightSearchButton, button[type='submit']",
        "fare_card": ".package-card, .fare-package, [data-testid='package-card']",
        "fare_name": ".package-card__name, [data-testid='package-name']",
        "fare_price": ".package-card__price, [data-testid='package-price']",
        "cabin_tab": ".cabin-selector button",
        "feature_row": ".package-card__benefit, li.package-benefit, [data-testid='package-feature']",
        "captcha_marker": "iframe[src*='captcha'], #px-captcha",
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
