"""The named premium/restricted sources called out in the spec. Each is a stub
until real credentials + an implementation are added -- see base.py."""
from app.ingest.premium.base import PremiumSourceAdapter

PREMIUM_ADAPTERS: list[PremiumSourceAdapter] = [
    PremiumSourceAdapter("IATA", ["IATA_API_KEY"]),
    PremiumSourceAdapter("OAG", ["OAG_API_KEY"]),
    PremiumSourceAdapter("Cirium", ["CIRIUM_API_KEY"]),
    PremiumSourceAdapter("LinkedIn", ["LINKEDIN_ACCESS_TOKEN"]),
]
