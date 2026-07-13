from typing import Protocol

from app.models.article import Article


class SearchBackend(Protocol):
    async def search(self, query: str, limit: int = 20) -> list[Article]: ...
