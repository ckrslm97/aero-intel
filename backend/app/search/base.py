from typing import Protocol

from app.models.article import Article


class SearchBackend(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 20,
        category: str | None = None,
        days: int | None = None,
    ) -> list[Article]: ...

    async def count(
        self, query: str, category: str | None = None, days: int | None = None
    ) -> int: ...
