"""
Async cache abstractions and implementations for M4.

We expose a small protocol (`AsyncCacheProtocol`) used by services/fetchers.
Two implementations are provided:
- `InMemoryCache`: default, simple TTL dictionary (good for dev/tests).
- `RedisCache`: optional, uses `redis.asyncio` when REDIS_URL is configured.

All methods are `async` to keep a consistent interface.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

# Try to import redis.asyncio lazily, but without using broad exceptions.
try:
    import redis.asyncio as REDIS_ASYNCIO  # type: ignore
except (ModuleNotFoundError, ImportError):
    REDIS_ASYNCIO = None  # type: ignore


class AsyncCacheProtocol(Protocol):
    """Minimal async cache protocol for dependency inversion."""

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a JSON-serializable value by key."""

    async def set_json(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        """Set a JSON-serializable value with TTL."""

    async def close(self) -> None:
        """Close underlying connections/resources."""


class InMemoryCache(AsyncCacheProtocol):
    """Simple in-memory TTL cache (per-process)."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._exp: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            now = time.time()
            exp = self._exp.get(key, 0.0)
            if exp and exp < now:
                self._store.pop(key, None)
                self._exp.pop(key, None)
                return None
            value = self._store.get(key)
            # Return a shallow copy to avoid accidental mutation by callers.
            return dict(value) if value is not None else None

    async def set_json(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        async with self._lock:
            self._store[key] = dict(value)
            self._exp[key] = time.time() + max(0, int(ttl_seconds))

    async def close(self) -> None:
        async with self._lock:
            self._store.clear()
            self._exp.clear()


@dataclass(frozen=True)
class RedisConfig:
    """Configuration needed to create a Redis cache."""

    url: str
    decode_responses: bool = True
    health_check_interval: int = 30


class RedisCache(AsyncCacheProtocol):
    """Redis-backed cache using redis.asyncio."""

    def __init__(self, cfg: RedisConfig) -> None:
        if REDIS_ASYNCIO is None:
            msg = "redis-py (redis.asyncio) not installed; cannot create RedisCache."
            raise RuntimeError(msg)
        # from_url may raise ValueError for bad URLs; network errors occur on use.
        self._client = REDIS_ASYNCIO.from_url(  # type: ignore[union-attr]
            cfg.url,
            decode_responses=cfg.decode_responses,
            health_check_interval=cfg.health_check_interval,
        )

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    async def set_json(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        await self._client.set(name=key, value=json.dumps(value), ex=int(ttl_seconds))

    async def close(self) -> None:
        await self._client.close()


def build_cache(redis_url: Optional[str]) -> AsyncCacheProtocol:
    """Factory producing a cache instance based on configuration.

    Args:
        redis_url: Redis connection URL. If falsy, returns an in-memory cache.

    Returns:
        An `AsyncCacheProtocol` implementation.
    """
    if redis_url:
        try:
            return RedisCache(RedisConfig(url=redis_url))
        except (RuntimeError, ValueError):
            # - RuntimeError: redis library not installed
            # - ValueError: malformed URL or invalid parameters
            return InMemoryCache()
    return InMemoryCache()
