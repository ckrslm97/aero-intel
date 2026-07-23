"""Resmi API sağlayıcılarının şema eşleme testleri (canlı istek yok).

Duffel/Amadeus'un belgelenmiş JSON yanıt yapısına benzer örneklerle `_offers_to_fares`
doğrulanır; ağ çağrısı yapılmaz.
"""
from __future__ import annotations

from apis.amadeus import AmadeusProvider
from apis.base import get_api_providers, registered_apis
from apis.duffel import DuffelProvider
from config import AppConfig
from core.models import Cabin, FeatureState
from core.ond import OND


def test_apis_registered():
    assert "duffel" in registered_apis()
    assert "amadeus" in registered_apis()


def test_providers_skipped_without_credentials():
    cfg = AppConfig()
    cfg.duffel_access_token = ""
    cfg.amadeus_client_id = ""
    cfg.amadeus_client_secret = ""
    # Kimlik bilgisi yoksa hiçbir sağlayıcı etkin değildir.
    assert get_api_providers(cfg) == []


# ---- Duffel ---- #
_DUFFEL_OFFERS = [
    {
        "id": "off_light",
        "total_amount": "180.00", "total_currency": "EUR",
        "owner": {"iata_code": "TK", "name": "Turkish Airlines"},
        "conditions": {
            "refund_before_departure": {"allowed": False},
            "change_before_departure": {"allowed": True, "penalty_amount": "40.00", "penalty_currency": "EUR"},
        },
        "slices": [{
            "fare_brand_name": "EcoFly",
            "segments": [{
                "operating_carrier": {"iata_code": "TK"},
                "passengers": [{"cabin_class": "economy",
                                "baggages": [{"type": "carry_on", "quantity": 1},
                                             {"type": "checked", "quantity": 0}]}],
            }],
        }],
    },
    {
        "id": "off_flex",
        "total_amount": "360.00", "total_currency": "EUR",
        "owner": {"iata_code": "TK", "name": "Turkish Airlines"},
        "conditions": {
            "refund_before_departure": {"allowed": True, "penalty_amount": "0.00", "penalty_currency": "EUR"},
            "change_before_departure": {"allowed": True, "penalty_amount": "0.00", "penalty_currency": "EUR"},
        },
        "slices": [{
            "fare_brand_name": "ExtraFly",
            "segments": [{
                "operating_carrier": {"iata_code": "TK"},
                "passengers": [{"cabin_class": "business",
                                "baggages": [{"type": "checked", "quantity": 2}]}],
            }],
        }],
    },
    # Başka taşıyıcı — süzülmeli.
    {
        "id": "off_other", "total_amount": "150.00", "total_currency": "EUR",
        "owner": {"iata_code": "LH", "name": "Lufthansa"},
        "slices": [{"fare_brand_name": "Light", "segments": [
            {"passengers": [{"cabin_class": "economy"}]}]}],
    },
]


def test_duffel_maps_offers_and_filters_by_carrier():
    p = DuffelProvider(AppConfig())
    fares = p._offers_to_fares(_DUFFEL_OFFERS, OND("TK", "IST", "LHR"))
    # Yalnızca TK; iki marka.
    assert {f.fare_brand for f in fares} == {"EcoFly", "ExtraFly"}
    assert all(f.airline == "TK" and f.source == "api:duffel" for f in fares)

    eco = next(f for f in fares if f.fare_brand == "EcoFly")
    assert eco.cabin == Cabin.ECONOMY.value
    assert eco.price == 180.0 and eco.currency == "EUR"
    assert eco.features["baggage_cabin"].state == FeatureState.INCLUDED
    assert eco.features["checked_baggage"].state == FeatureState.NOT_INCLUDED
    assert eco.features["refund"].state == FeatureState.NOT_INCLUDED   # allowed=False
    assert eco.features["change"].state == FeatureState.PAID           # penalty>0

    flex = next(f for f in fares if f.fare_brand == "ExtraFly")
    assert flex.cabin == Cabin.BUSINESS.value
    assert flex.features["refund"].state == FeatureState.INCLUDED      # allowed, penalty 0
    assert flex.features["checked_baggage"].state == FeatureState.INCLUDED


def test_duffel_dedups_cheapest_per_brand():
    offers = [
        {"id": "a", "total_amount": "220.00", "total_currency": "EUR",
         "owner": {"iata_code": "TK"},
         "slices": [{"fare_brand_name": "EcoFly", "segments": [
             {"passengers": [{"cabin_class": "economy"}]}]}]},
        {"id": "b", "total_amount": "180.00", "total_currency": "EUR",
         "owner": {"iata_code": "TK"},
         "slices": [{"fare_brand_name": "EcoFly", "segments": [
             {"passengers": [{"cabin_class": "economy"}]}]}]},
    ]
    fares = DuffelProvider(AppConfig())._offers_to_fares(offers, OND("TK", "IST", "LHR"))
    assert len(fares) == 1 and fares[0].price == 180.0


# ---- Amadeus ---- #
_AMADEUS_OFFERS = [
    {
        "type": "flight-offer", "id": "1",
        "validatingAirlineCodes": ["TK"],
        "itineraries": [{"segments": [{"carrierCode": "TK", "id": "1"}]}],
        "price": {"currency": "EUR", "grandTotal": "180.00", "total": "180.00"},
        "travelerPricings": [{
            "fareOption": "STANDARD",
            "fareDetailsBySegment": [{
                "segmentId": "1", "cabin": "ECONOMY", "class": "K",
                "brandedFare": "ECOLIGHT", "brandedFareLabel": "ECO LIGHT",
                "includedCheckedBags": {"quantity": 0},
            }],
        }],
    },
    {
        "type": "flight-offer", "id": "2",
        "validatingAirlineCodes": ["TK"],
        "itineraries": [{"segments": [{"carrierCode": "TK", "id": "1"}]}],
        "price": {"currency": "EUR", "grandTotal": "300.00"},
        "travelerPricings": [{
            "fareDetailsBySegment": [{
                "segmentId": "1", "cabin": "BUSINESS", "class": "J",
                "brandedFareLabel": "BUSINESS FLEX",
                "includedCheckedBags": {"quantity": 2},
            }],
        }],
    },
]


def test_amadeus_maps_branded_fares():
    fares = AmadeusProvider(AppConfig())._offers_to_fares(_AMADEUS_OFFERS, OND("TK", "IST", "LHR"))
    assert {f.fare_brand for f in fares} == {"ECO LIGHT", "BUSINESS FLEX"}
    assert all(f.airline == "TK" and f.source == "api:amadeus" for f in fares)

    eco = next(f for f in fares if f.fare_brand == "ECO LIGHT")
    assert eco.cabin == Cabin.ECONOMY.value and eco.booking_class == "K"
    assert eco.price == 180.0 and eco.currency == "EUR"
    assert eco.features["checked_baggage"].state == FeatureState.NOT_INCLUDED

    biz = next(f for f in fares if f.fare_brand == "BUSINESS FLEX")
    assert biz.cabin == Cabin.BUSINESS.value
    assert biz.features["checked_baggage"].state == FeatureState.INCLUDED
