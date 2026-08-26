"""Duffel Offers API sağlayıcısı (fare-family için birincil, güvenilir kaynak).

Akış (Duffel Air API, Duffel-Version: v2):
  POST /air/offer_requests?return_offers=true
    body: {"data": {"slices":[{origin,destination,departure_date}],
                     "passengers":[{"type":"adult"}]}}
  → yanıt: data.offers[] (fare brand + kabin + koşullar + bagaj + fiyat)

Her offer tek bir ücret paketini temsil eder; istenen taşıyıcıya (`ond.airline`)
göre süzülür ve (kabin, fare_brand_name) bazında en ucuz tutulur — böylece
paket merdiveni (Light/Standard/Flex …) çıkar.

Belge: https://duffel.com/docs/api/offers
"""
from __future__ import annotations

from typing import Any

from core.models import Cabin, FareBrand, FeatureState
from core.ond import OND
from apis.base import FareAPIProvider, register_api

_BASE_URL = "https://api.duffel.com"

_CABIN_MAP = {
    "economy": Cabin.ECONOMY.value,
    "premium_economy": Cabin.PREMIUM_ECONOMY.value,
    "business": Cabin.BUSINESS.value,
    "first": Cabin.FIRST.value,
}

# Duffel bagaj tipi → standart özellik alanı.
_BAGGAGE_MAP = {
    "checked": "checked_baggage",
    "carry_on": "baggage_cabin",
}


@register_api
class DuffelProvider(FareAPIProvider):
    """Duffel Offers API sağlayıcısı."""

    name = "duffel"

    def available(self) -> bool:
        return bool(self.config.duffel_access_token)

    def fetch(self, ond: OND, travel_date: str) -> list[FareBrand]:
        import requests

        headers = {
            "Authorization": f"Bearer {self.config.duffel_access_token}",
            "Duffel-Version": self.config.duffel_api_version,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = {
            "data": {
                "slices": [{
                    "origin": ond.origin,
                    "destination": ond.destination,
                    "departure_date": travel_date,
                }],
                "passengers": [{"type": "adult"}],
            }
        }
        url = f"{_BASE_URL}/air/offer_requests?return_offers=true"
        self.log.info("Duffel: %s %s isteniyor", ond, travel_date)
        resp = requests.post(url, json=body, headers=headers, timeout=self.config.api_timeout_s)
        resp.raise_for_status()
        offers = (resp.json().get("data") or {}).get("offers") or []
        return self._offers_to_fares(offers, ond)

    # ------------------------------------------------------------------ #
    # Eşleme (test edilebilir; canlı istekten bağımsız)
    # ------------------------------------------------------------------ #
    def _offers_to_fares(self, offers: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        by_key: dict[tuple[str, str], FareBrand] = {}
        for offer in offers:
            owner = (offer.get("owner") or {}).get("iata_code", "")
            if not self._airline_matches(owner, ond.airline):
                continue
            fb = self._offer_to_fare(offer, owner)
            if not fb:
                continue
            key = (fb.cabin, fb.fare_brand)
            # Aynı (kabin, marka) için en ucuzu tut.
            existing = by_key.get(key)
            if existing is None or (fb.price is not None and (existing.price is None or fb.price < existing.price)):
                by_key[key] = fb
        return list(by_key.values())

    def _offer_to_fare(self, offer: dict[str, Any], owner: str) -> FareBrand | None:
        slices = offer.get("slices") or []
        if not slices:
            return None
        sl = slices[0]
        cabin, baggages = self._cabin_and_baggage(sl)
        brand = sl.get("fare_brand_name") or offer.get("fare_brand_name") or _cabin_label(cabin)

        fb = FareBrand(
            airline=owner.upper(),
            cabin=cabin,
            fare_brand=str(brand),
            price=_to_float(offer.get("total_amount")),
            currency=str(offer.get("total_currency", "")),
            package_description="Duffel",
            source="api:duffel",
            source_url=f"{_BASE_URL}/air/offers/{offer.get('id', '')}",
        )

        # Bagaj
        for bag in baggages:
            field_name = _BAGGAGE_MAP.get(str(bag.get("type", "")))
            if not field_name:
                continue
            qty = bag.get("quantity", 0) or 0
            state = FeatureState.INCLUDED if qty else FeatureState.NOT_INCLUDED
            fb.set_feature(field_name, state, detail=(f"{qty}x" if qty else ""))

        # Koşullar (offer + slice birleşik)
        conditions = {**(offer.get("conditions") or {}), **(sl.get("conditions") or {})}
        state, text = _condition_state(conditions.get("refund_before_departure"))
        fb.set_feature("refund", state)
        fb.refund_rules = text
        state, text = _condition_state(conditions.get("change_before_departure"))
        fb.set_feature("change", state)
        fb.change_rules = text
        return fb

    @staticmethod
    def _cabin_and_baggage(sl: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        """İlk segment yolcusundan kabin ve bagaj bilgisini çıkarır."""
        cabin = Cabin.ECONOMY.value
        baggages: list[dict[str, Any]] = []
        for seg in sl.get("segments") or []:
            for pax in seg.get("passengers") or []:
                cabin = _CABIN_MAP.get(str(pax.get("cabin_class", "")).lower(), cabin)
                baggages = pax.get("baggages") or baggages
                if baggages:
                    return cabin, baggages
        return cabin, baggages


def _to_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _cabin_label(cabin: str) -> str:
    return cabin or "Economy"


def _condition_state(cond: Any) -> tuple[FeatureState, str]:
    """Duffel koşul nesnesini (allowed/penalty) FeatureState + açıklamaya çevirir."""
    if not isinstance(cond, dict):
        return FeatureState.UNKNOWN, ""
    if not cond.get("allowed", False):
        return FeatureState.NOT_INCLUDED, "İzin yok"
    penalty = _to_float(cond.get("penalty_amount"))
    if penalty and penalty > 0:
        cur = cond.get("penalty_currency", "")
        return FeatureState.PAID, f"Ceza: {penalty:g} {cur}".strip()
    return FeatureState.INCLUDED, "Ücretsiz"
