"""In-process async token-bucket rate limiter keyed by host.

This module provides a tiny, dependency-free rate limiter intended for
client-side throttling of outbound HTTP calls to specific hosts.

Usage (simple functional API):
    await acquire("api.crossref.org", rate_per_sec=5.0, burst=10)

Usage (service-style, optional):
    limiter = RateLimiter()
    await limiter.acquire("openlibrary.org", rate_per_sec=2.0, burst=4)

Design
------
* Token bucket per host:
    - `rate_per_sec` tokens are added each second (fractional allowed).
    - Bucket capacity is `burst`.
    - Each acquire() consumes 1 token (configurable via `tokens`).
* Async-safe:
    - A per-bucket asyncio.Lock ensures correct updates under concurrency.
* Lightweight:
    - Pure Python; suitable for a single-process FastAPI app instance.

Notes
-----
This limiter is *per-process*. If you run multiple worker processes (e.g.,
gunicorn with multiple workers), each process maintains its own buckets.
For truly global limits, use a centralized store (e.g., Redis) instead.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from typing import MutableMapping, Optional

__all__ = ["RateLimiter", "acquire"]


@dataclass
class _TokenBucket:
    """Mutable token bucket state."""

    rate_per_sec: float
    burst: int
    tokens: float = field(default=0.0)
    last_ts: float = field(default_factory=monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def reconfigure(self, rate_per_sec: float, burst: int) -> None:
        """Update rate/burst safely; clamp tokens to new capacity."""
        self.rate_per_sec = rate_per_sec
        self.burst = burst
        if self.tokens > self.burst:
            self.tokens = float(self.burst)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last update."""
        now = monotonic()
        elapsed = now - self.last_ts
        if elapsed <= 0.0:
            return
        self.tokens = min(float(self.burst), self.tokens + elapsed * self.rate_per_sec)
        self.last_ts = now

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire `tokens` from the bucket, sleeping if needed.

        Args:
            tokens: Number of tokens to consume (default 1.0).
                    Non-positive values are treated as a no-op.

        Raises:
            ValueError: If tokens requested exceeds burst capacity (impossible to satisfy).
        """
        if tokens <= 0:
            return

        if tokens > self.burst:
            raise ValueError(
                f"Requested {tokens} tokens exceeds bucket capacity {self.burst}"
            )

        async with self.lock:
            while True:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                # Not enough tokens: compute precise sleep time.
                needed = tokens - self.tokens
                # Guard against zero/near-zero rate; division by zero is prevented
                # by constructor validation in RateLimiter.
                sleep_for = needed / self.rate_per_sec
                # Avoid busy-waiting on extremely small durations.
                await asyncio.sleep(max(0.001, sleep_for))


class RateLimiter:
    """Per-process registry of token buckets keyed by host.

    A single instance can be used application-wide (module-level singleton
    provided below), or you can instantiate one explicitly if desired.
    """

    def __init__(self) -> None:
        self._buckets: MutableMapping[str, _TokenBucket] = {}
        # Lock protects the _buckets dict itself (not per-bucket operations).
        self._dict_lock = asyncio.Lock()

    async def acquire(
        self,
        host: str,
        rate_per_sec: float,
        burst: int,
        tokens: float = 1.0,
    ) -> None:
        """Acquire tokens from the bucket corresponding to `host`.

        Args:
            host: Key for the bucket (typically a hostname).
            rate_per_sec: Token regeneration rate (tokens per second). Must be > 0.
            burst: Maximum bucket capacity (integer). Must be >= 1.
            tokens: Tokens to consume for this call (default 1.0).

        Raises:
            ValueError: If invalid parameters are provided or `tokens > burst`.
        """
        if not host:
            raise ValueError("`host` must be a non-empty string")
        if rate_per_sec <= 0:
            raise ValueError("`rate_per_sec` must be > 0")
        if burst < 1:
            raise ValueError("`burst` must be >= 1")

        bucket = await self._get_or_create_bucket(host, rate_per_sec, burst)
        await bucket.acquire(tokens=tokens)

    async def _get_or_create_bucket(
        self, host: str, rate_per_sec: float, burst: int
    ) -> _TokenBucket:
        """Return the bucket for `host`, creating or reconfiguring as needed."""
        async with self._dict_lock:
            bucket = self._buckets.get(host)
            if bucket is None:
                # New bucket starts "full" to avoid throttling the very first call.
                bucket = _TokenBucket(
                    rate_per_sec=rate_per_sec,
                    burst=burst,
                    tokens=float(burst),
                )
                self._buckets[host] = bucket
                return bucket

            # If parameters changed, update in place.
            if (
                bucket.rate_per_sec != rate_per_sec
                or bucket.burst != burst
            ):
                bucket.reconfigure(rate_per_sec=rate_per_sec, burst=burst)
            return bucket


# ---------------------------------------------------------------------------
# Module-level convenience singleton & functional API
# ---------------------------------------------------------------------------

_default_limiter: Optional[RateLimiter] = RateLimiter()


async def acquire(host: str, rate_per_sec: float, burst: int, tokens: float = 1.0) -> None:
    """Functional wrapper around the default :class:`RateLimiter`.

    This is convenient for call-sites that don't want to hold a RateLimiter
    instance. For advanced scenarios (custom lifetimes, testing), create and
    use your own `RateLimiter`.

    Args:
        host: Bucket key (typically a hostname).
        rate_per_sec: Tokens added per second (must be > 0).
        burst: Maximum capacity (must be >= 1).
        tokens: Tokens to consume (default 1.0).

    Raises:
        ValueError: If parameters are invalid or the request exceeds capacity.
    """
    assert _default_limiter is not None  # For type-checkers; module init ensures this.
    await _default_limiter.acquire(host, rate_per_sec, burst, tokens=tokens)
