"""Placeholder for an Elasticsearch/OpenSearch-backed SearchBackend.

Not implemented in this build -- Postgres full-text search comfortably covers
the expected article volume. Swap in a real client here (and flip the
selection in factory.py) if/when ELASTICSEARCH_URL needs to back a much larger
corpus with fuzzier ranking than ts_rank provides.
"""
from app.core.logging import get_logger
from app.models.article import Article

logger = get_logger(__name__)


class ElasticsearchBackend:
    def __init__(self, url: str):
        self.url = url

    async def search(self, query: str, limit: int = 20) -> list[Article]:
        logger.warning("elasticsearch_backend_not_implemented", url=self.url)
        return []
