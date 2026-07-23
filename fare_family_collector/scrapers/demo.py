"""Demo (mock) scraper.

Canlı siteye bağlanmadan, gerçekçi örnek fare paketleri üretir. Amaç:
- Uygulamayı uçtan uca (arayüz, export, HTML paneli) test edebilmek
- Kayıtlı gerçek scraper'ı olmayan havayolları için güvenli varsayılan

ÖNEMLİ: Bu scraper GERÇEK VERİ ÇEKMEZ. Üretim için ilgili havayolunun
kendi scraper'ını (`scrapers/tk.py` gibi) yazın.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from core.models import Cabin, FareBrand, FeatureState
from core.ond import OND
from scrapers.base import BaseScraper


# Kabin bazlı tipik paket şablonları (düşükten yükseğe)
_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    Cabin.ECONOMY.value: [
        {"brand": "Eco Light", "code": "LT", "base": 180, "flex": "Non-refundable"},
        {"brand": "Eco Standard", "code": "ST", "base": 260, "flex": "Change with fee"},
        {"brand": "Eco Flex", "code": "FX", "base": 360, "flex": "Fully flexible"},
    ],
    Cabin.PREMIUM_ECONOMY.value: [
        {"brand": "Premium Standard", "code": "PS", "base": 520, "flex": "Change with fee"},
        {"brand": "Premium Flex", "code": "PF", "base": 690, "flex": "Fully flexible"},
    ],
    Cabin.BUSINESS.value: [
        {"brand": "Business Saver", "code": "BS", "base": 1200, "flex": "Change with fee"},
        {"brand": "Business Flex", "code": "BF", "base": 1650, "flex": "Fully flexible"},
    ],
}

# Paket kademesine göre özellik zenginliği (index arttıkça daha çok dahil)
_FEATURE_LADDER = [
    # (özellik, en düşük kademede durum, detay)
    ("baggage_cabin", FeatureState.INCLUDED, "8kg"),
    ("checked_baggage", FeatureState.NOT_INCLUDED, ""),
    ("seat_selection", FeatureState.PAID, ""),
    ("meal", FeatureState.PAID, ""),
    ("refund", FeatureState.NOT_INCLUDED, ""),
    ("change", FeatureState.PAID, ""),
    ("miles", FeatureState.INCLUDED, "25%"),
    ("priority_boarding", FeatureState.NOT_INCLUDED, ""),
    ("lounge", FeatureState.NOT_INCLUDED, ""),
    ("fast_track", FeatureState.NOT_INCLUDED, ""),
    ("upgrade_eligible", FeatureState.NOT_INCLUDED, ""),
    ("wifi", FeatureState.PAID, ""),
    ("sport_equipment", FeatureState.PAID, ""),
    ("pet", FeatureState.PAID, ""),
    ("extra_baggage", FeatureState.PAID, ""),
    ("child_advantage", FeatureState.NOT_INCLUDED, ""),
]


class DemoScraper(BaseScraper):
    """Gerçekçi ama sahte veri üreten scraper.

    Aynı OND için deterministik sonuç verir (hash tabanlı seed), böylece
    tekrar çalıştırıldığında tutarlı kalır.
    """

    airline_code = "DEMO"
    source_label = "demo"

    def run(self, ond: OND, travel_date: str | None = None) -> list[FareBrand]:
        """Tarayıcı açmadan doğrudan örnek veri üretir."""
        travel_date = travel_date or self._resolve_date()
        self.log.info("%s işleniyor (DEMO modu)", ond)
        self.human_pause()  # gerçekçi gecikme hissi
        fares = self._generate(ond, travel_date)
        return self._finalize(fares, ond, travel_date)

    def scrape(self, page: Any, ond: OND, travel_date: str) -> list[FareBrand]:
        # Demo modunda tarayıcı kullanılmaz; run() override edildi.
        return self._generate(ond, travel_date)

    def _generate(self, ond: OND, travel_date: str) -> list[FareBrand]:
        seed = int(hashlib.md5(ond.key.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        currency = rng.choice(["EUR", "USD", "GBP"])
        distance_factor = 1.0 + (len(ond.origin + ond.destination) % 5) * 0.15

        fares: list[FareBrand] = []
        tier_index = 0
        for cabin, templates in _TEMPLATES.items():
            for t in templates:
                price = round(t["base"] * distance_factor * rng.uniform(0.9, 1.25), 2)
                fb = FareBrand(
                    airline=ond.airline,
                    origin=ond.origin,
                    destination=ond.destination,
                    travel_date=travel_date,
                    cabin=cabin,
                    fare_brand=t["brand"],
                    brand_code=t["code"],
                    booking_class=rng.choice(list("YBMKLQEWTVGSNP")),
                    price=price,
                    currency=currency,
                    flexibility=t["flex"],
                    refund_rules=t["flex"],
                    change_rules=t["flex"],
                    cancellation_rules=t["flex"],
                    package_description=f"{cabin} · {t['brand']} fare family",
                    source_url=f"https://demo.local/{ond.airline}/{ond.origin}-{ond.destination}",
                )
                self._apply_features(fb, tier_index)
                fares.append(fb)
                tier_index += 1
        return fares

    def _apply_features(self, fb: FareBrand, tier: int) -> None:
        """Kademe (tier) arttıkça özellikleri kademeli olarak açar."""
        for i, (name, low_state, detail) in enumerate(_FEATURE_LADDER):
            # Yüksek kademelerde önce PAID sonra INCLUDED'a döner
            threshold_paid = i % 4
            threshold_inc = i % 4 + 3
            if tier >= threshold_inc:
                fb.set_feature(name, FeatureState.INCLUDED, detail or ("20kg" if name == "checked_baggage" else ""))
            elif tier >= threshold_paid:
                fb.set_feature(name, FeatureState.PAID, detail)
            else:
                fb.set_feature(name, low_state, detail)
