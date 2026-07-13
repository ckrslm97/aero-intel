"""Adapter for a licensed or ToS-restricted source (IATA, OAG, Cirium, LinkedIn, ...).

These sources require paid credentials or violate scraping terms if accessed
without a proper data agreement, so this stub always returns no data -- it
exists as the integration point a real implementation drops into once
credentials are available, not a scraper.
"""
from app.core.logging import get_logger
from app.ingest.base import RawArticle

logger = get_logger(__name__)


class PremiumSourceAdapter:
    def __init__(self, source_name: str, required_env: list[str]):
        self.source_name = source_name
        self.required_env = required_env

    async def fetch(self) -> list[RawArticle]:
        logger.info(
            "premium_source_not_configured",
            source=self.source_name,
            required_env=self.required_env,
        )
        return []
