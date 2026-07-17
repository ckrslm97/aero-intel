"""The named premium/restricted sources called out in the spec. Each is a stub
until real credentials + an implementation are added -- see base.py."""
from app.ingest.premium.base import PremiumSourceAdapter

PREMIUM_ADAPTERS: list[PremiumSourceAdapter] = [
    PremiumSourceAdapter("IATA", ["IATA_API_KEY"]),
    PremiumSourceAdapter("OAG", ["OAG_API_KEY"]),
    PremiumSourceAdapter("Cirium", ["CIRIUM_API_KEY"]),
    PremiumSourceAdapter("LinkedIn", ["LINKEDIN_ACCESS_TOKEN"]),
    PremiumSourceAdapter("CAPA", ["CAPA_API_KEY"]),
    PremiumSourceAdapter("FlightGlobal", ["FLIGHTGLOBAL_API_KEY"]),
    PremiumSourceAdapter("Skift Airline Weekly", ["SKIFT_AIRLINE_WEEKLY_API_KEY"]),
    PremiumSourceAdapter("ICAO Data+", ["ICAO_DATA_PLUS_API_KEY"]),
    PremiumSourceAdapter("ATPCO", ["ATPCO_API_KEY"]),
    PremiumSourceAdapter("Sabre", ["SABRE_API_KEY"]),
    PremiumSourceAdapter("Amadeus", ["AMADEUS_API_KEY"]),
    PremiumSourceAdapter("PROS", ["PROS_API_KEY"]),
    PremiumSourceAdapter("Accelya", ["ACCELYA_API_KEY"]),
    PremiumSourceAdapter("Lufthansa Systems", ["LUFTHANSA_SYSTEMS_API_KEY"]),
]
