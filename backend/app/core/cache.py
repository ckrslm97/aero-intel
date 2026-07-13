"""Cache abstraction: uses Redis when REDIS_URL is set, otherwise an in-process TTL dict.

This keeps the app fully functional on a laptop with no Redis installed, while
letting production point at a real Redis with zero code changes.
"""
from __future__ import annotations

import time
from typing import Any, Protocol

from app.core.config import get_settings


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None: ...
    async def delete(self, key: str) -> None: ...


class InMemoryCache:
    """Single-process TTL cache. Not shared across workers -- fine for dev/small deployments."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class RedisCache:
    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as redis  # imported lazily; only needed when REDIS_URL is set

        self._client = redis.from_url(redis_url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        import json

        raw = await self._client.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        import json

        await self._client.set(key, json.dumps(value), ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)


_cache_instance: Cache | None = None


def get_cache() -> Cache:
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance

    settings = get_settings()
    if settings.redis_url:
        try:
            _cache_instance = RedisCache(settings.redis_url)
        except ImportError:
            _cache_instance = InMemoryCache()
    else:
        _cache_instance = InMemoryCache()
    return _cache_instance
