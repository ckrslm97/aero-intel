"""Amadeus Self-Service API sağlayıcısı (ikinci güvenilir API kaynağı).

Akış:
  1. OAuth2 (client_credentials) → erişim tokenı (örnek başına önbelleklenir).
  2. GET /v2/shopping/flight-offers?originLocationCode=..&destinationLocationCode=..
       &departureDate=..&adults=1&includedAirlineCodes=<taşıyıcı>
  → data[].travelerPricings[].fareDetailsBySegment[] içinden marka (brandedFare),
    kabin ve dahil bagaj; data[].price'tan fiyat.

(kabin, marka) bazında en ucuz tutulur → paket merdiveni.

Belge: https://developers.amadeus.com/self-service/category/flights
"""
from __future__ import annotations

import time
from typing import Any

from core.models import Cabin, FareBrand, FeatureState
from core.ond import OND
from apis.base import FareAPIProvider, register_api

_HOSTS = {
    "test": "https://test.api.amadeus.com",
    "production": "https://api.amadeus.com",
}

_CABIN_MAP = {
    "ECONOMY": Cabin.ECONOMY.value,
    "PREMIUM_ECONOMY": Cabin.PREMIUM_ECONOMY.value,
    "BUSINESS": Cabin.BUSINESS.value,
    "FIRST": Cabin.FIRST.value,
}


@register_api
class AmadeusProvider(FareAPIProvider):
    """Amadeus Flight Offers Search sağlayıcısı."""

    name = "amadeus"

    def __init__(self, config) -> None:  # type: ignore[no-untyped-def]
        super().__init__(config)
        self._token: str = ""
        self._token_exp: float = 0.0

    def available(self) -> bool:
        return bool(self.config.amadeus_client_id and self.config.amadeus_client_secret)

    @property
    def _host(self) -> str:
        return _HOSTS.get(self.config.amadeus_env.lower(), _HOSTS["test"])

    def _access_token(self) -> str:
        """OAuth2 client_credentials tokenı (süresi dolana dek önbelleklenir)."""
        import requests

        if self._token and time.time() < self._token_exp - 30:
            return self._token
        resp = requests.post(
            f"{self._host}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.amadeus_client_id,
                "client_secret": self.config.amadeus_client_secret,
            },
            timeout=self.config.api_timeout_s,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_exp = time.time() + float(payload.get("expires_in", 1799))
        return self._token

    def fetch(self, ond: OND, travel_date: str) -> list[FareBrand]:
        import requests

        params = {
            "originLocationCode": ond.origin,
            "destinationLocationCode": ond.destination,
            "departureDate": travel_date,
            "adults": 1,
            "includedAirlineCodes": ond.airline,
            "max": 50,
        }
        self.log.info("Amadeus: %s %s isteniyor", ond, travel_date)
        resp = requests.get(
            f"{self._host}/v2/shopping/flight-offers",
            params=params,
            headers={"Authorization": f"Bearer {self._access_token()}"},
            timeout=self.config.api_timeout_s,
        )
        resp.raise_for_status()
        return self._offers_to_fares(resp.json().get("data") or [], ond)

    # ------------------------------------------------------------------ #
    # Eşleme (test edilebilir)
    # ------------------------------------------------------------------ #
    def _offers_to_fares(self, offers: list[dict[str, Any]], ond: OND) -> list[FareBrand]:
        by_key: dict[tuple[str, str], FareBrand] = {}
        for offer in offers:
            carrier = _carrier_of(offer)
            if not self._airline_matches(carrier, ond.airline):
                continue
            fb = self._offer_to_fare(offer, carrier or ond.airline)
            if not fb:
                continue
            key = (fb.cabin, fb.fare_brand)
            existing = by_key.get(key)
            if existing is None or (fb.price is not None and (existing.price is None or fb.price < existing.price)):
                by_key[key] = fb
        return list(by_key.values())

    def _offer_to_fare(self, offer: dict[str, Any], carrier: str) -> FareBrand | None:
        tps = offer.get("travelerPricings") or []
        if not tps:
            return None
        segs = tps[0].get("fareDetailsBySegment") or []
        if not segs:
            return None
        seg = segs[0]
        cabin = _CABIN_MAP.get(str(seg.get("cabin", "")).upper(), Cabin.ECONOMY.value)
        brand = seg.get("brandedFareLabel") or seg.get("brandedFare") or _cabin_label(cabin)
        price = offer.get("price") or {}

        fb = FareBrand(
            airline=carrier.upper(),
            cabin=cabin,
            fare_brand=str(brand),
            booking_class=str(seg.get("class", "")),
            price=_to_float(price.get("grandTotal", price.get("total"))),
            currency=str(price.get("currency", "")),
            package_description="Amadeus",
            source="api:amadeus",
        )
        bags = seg.get("includedCheckedBags") or {}
        qty = bags.get("quantity")
        if qty is not None:
            state = FeatureState.INCLUDED if qty else FeatureState.NOT_INCLUDED
            fb.set_feature("checked_baggage", state, detail=(f"{qty}x" if qty else ""))
        return fb


def _carrier_of(offer: dict[str, Any]) -> str:
    codes = offer.get("validatingAirlineCodes") or []
    if codes:
        return str(codes[0])
    for it in offer.get("itineraries") or []:
        for seg in it.get("segments") or []:
            if seg.get("carrierCode"):
                return str(seg["carrierCode"])
    return ""


def _to_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _cabin_label(cabin: str) -> str:
    return cabin or "Economy"
