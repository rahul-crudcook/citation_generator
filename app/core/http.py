# app/core/http.py
# pylint: disable= W0611
# pylint: disable=W0718
"""
Async HTTP client abstraction for fetchers/services.

We expose:
- `AsyncHttpClientProtocol`: tiny protocol used by code to perform HTTP calls.
- `HttpResponse`: a lightweight wrapper with the attributes we need.
- `AsyncHttpClient`: httpx-based implementation with simple retries & backoff,
  plus an optional per-host token-bucket rate limiter.
- `build_http_client`: small factory for DI.

This keeps the rest of the code decoupled from any specific HTTP library.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Protocol, Sequence, Tuple, cast
from urllib.parse import urlsplit

# Optional dependency: httpx. We alias to `_HTTPX` to satisfy pylint naming.
try:
    import httpx as _HTTPX  # type: ignore
except (ModuleNotFoundError, ImportError):  # pragma: no cover - imported at runtime
    _HTTPX = None  # type: ignore

# Optional lightweight, in-process rate limiter (token bucket).
# Safe to import; the module provides a no-IO coroutine.
try:
    from app.utils.rate_limit import acquire as _rate_acquire  # type: ignore
except Exception:  # pylint: disable=broad-except
    _rate_acquire = None  # type: ignore  # pylint: disable=invalid-name


@dataclass(frozen=True)
class HttpResponse:
    """Lightweight HTTP response shape consumed by fetchers.

    Attributes:
        status_code: Integer HTTP status (e.g., 200, 404, 429).
        text: Raw response body as text.
        _json: Optional pre-parsed JSON (if detected and parsed successfully).
        headers: **Normalized** response headers as a plain dict with
                 **lowercase keys** (e.g., "content-type", "retry-after").
                 Exposing headers allows callers to read upstream hints like
                 rate-limiting ("Retry-After") without depending on the
                 underlying HTTP client's response type.
    """

    status_code: int
    text: str
    _json: Optional[Any] = None
    headers: Dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        """Return cached JSON if present, else attempt to parse from text.

        Raises:
            ValueError: When the body cannot be decoded as JSON.
        """
        if self._json is not None:
            return self._json
        try:
            return json.loads(self.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"JSON decode error: {exc}") from exc


class AsyncHttpClientProtocol(Protocol):
    """Tiny async HTTP client protocol for dependency inversion.

    Implementations must return `HttpResponse` so callers can access
    `status_code`, `headers`, and `json()` uniformly, regardless of the
    underlying HTTP library.
    """

    async def get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        """HTTP GET, returning a `HttpResponse`."""

    async def post(
        self,
        url: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        """HTTP POST with JSON body, returning a `HttpResponse`."""

    async def close(self) -> None:
        """Close underlying resources."""


class AsyncHttpClient(AsyncHttpClientProtocol):
    """`httpx`-based client implementing `AsyncHttpClientProtocol`.

    Features:
        * Simple retries with backoff on 5xx and timeouts (default 3 attempts,
          backoffs 0.25/0.5/1.0 seconds).
        * Optional per-host token-bucket rate limit (in-process), used before
          issuing each request.

    The behavior is intentionally minimal and dependency-free beyond `httpx`.
    """

    def __init__(
        self,
        *,
        base_headers: Optional[Dict[str, str]] = None,
        retries: int = 3,
        backoffs: Sequence[float] = (0.25, 0.5, 1.0),
        rate_limit: Optional[Tuple[float, int]] = None,
    ) -> None:
        """Initialize the async HTTP client.

        Args:
            base_headers: Headers to apply to all requests (e.g., User-Agent).
            retries: Number of additional attempts after the first try.
            backoffs: Sleep durations (seconds) between attempts. If shorter
                      than needed, the last value is reused.
            rate_limit: Optional tuple `(rate_per_sec, burst)` to enable
                        per-host token-bucket limiting (in-process).
        """
        if _HTTPX is None:
            msg = "httpx is not installed; cannot create AsyncHttpClient."
            raise RuntimeError(msg)
        self._client = _HTTPX.AsyncClient(headers=base_headers or {}, follow_redirects=True)

        if retries < 0:
            raise ValueError("`retries` must be >= 0")
        if not backoffs or any(b < 0 for b in backoffs):
            raise ValueError("`backoffs` must be non-empty and >= 0")

        self._retries = int(retries)
        self._backoffs = tuple(float(b) for b in backoffs)
        self._rate = float(rate_limit[0]) if rate_limit else None
        self._burst = int(rate_limit[1]) if rate_limit else None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        """HTTP GET with retry/backoff and optional rate-limit."""
        await self._rate_limit_if_enabled(url)
        resp = await self._with_retries(
            lambda: self._client.get(url, headers=headers, timeout=timeout)
        )
        return self._to_http_response(resp)

    async def post(
        self,
        url: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        """HTTP POST with retry/backoff and optional rate-limit."""
        await self._rate_limit_if_enabled(url)
        resp = await self._with_retries(
            lambda: self._client.post(url, json=json_body, headers=headers, timeout=timeout)
        )
        return self._to_http_response(resp)

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _rate_limit_if_enabled(self, url: str) -> None:
        """Apply a per-host token-bucket rate limit if configured.

        This is a best-effort throttle; if the rate limiter utility is not
        available, this method becomes a no-op.
        """
        if self._rate is None or self._burst is None or _rate_acquire is None:
            return
        host = urlsplit(url).hostname or "unknown"
        # Sleep asynchronously if budget not available.
        await _rate_acquire(host=host, rate_per_sec=self._rate, burst=self._burst)

    async def _with_retries(self, call):
        """Execute an httpx call with basic retry/backoff policy.

        Retries on:
            * httpx.TimeoutException
            * HTTP 5xx status codes

        Does NOT retry on:
            * 4xx client errors
            * Other httpx errors (connection errors are not retried to avoid
              accidental hammering when DNS/host is misconfigured).
        """
        attempts = self._retries + 1
        attempt = 0
        while True:
            try:
                resp = await call()
            except _HTTPX.TimeoutException:  # type: ignore[attr-defined]
                attempt += 1
                if attempt >= attempts:
                    raise
                await asyncio.sleep(self._backoff_for_attempt(attempt - 1))
                continue

            # Retry on 5xx; otherwise return immediately.
            if 500 <= int(resp.status_code) < 600:
                attempt += 1
                if attempt >= attempts:
                    return resp
                await asyncio.sleep(self._backoff_for_attempt(attempt - 1))
                continue

            return resp

    def _backoff_for_attempt(self, attempt_index: int) -> float:
        """Return the backoff (seconds) for the given attempt index (0-based)."""
        if attempt_index < len(self._backoffs):
            return self._backoffs[attempt_index]
        return self._backoffs[-1]

    @staticmethod
    def _to_http_response(resp: Any) -> HttpResponse:
        """Convert an httpx response to our lightweight HttpResponse.

        Notes:
            * We normalize headers to a dict **with lowercase keys** to make
              callers' header lookups case-insensitive and library-agnostic.
            * We opportunistically cache parsed JSON into `_json` when the
              server declares `application/json`. Callers may still call
              `json()` which will return the cached value or parse on demand.
        """
        content_text = resp.text

        # Opportunistic JSON parsing (only when content-type advertises JSON).
        parsed_json: Optional[Any]
        try:
            if "application/json" in (resp.headers.get("content-type") or ""):
                parsed_json = resp.json()
            else:
                parsed_json = None
        except ValueError:
            parsed_json = None

        # Normalize headers to a plain dict[str, str] with lowercase keys.
        try:
            headers_dict = {str(k).lower(): str(v) for k, v in resp.headers.items()}
        except Exception:
            headers_dict = {}

        return HttpResponse(
            status_code=cast(int, resp.status_code),
            text=content_text,
            _json=parsed_json,
            headers=headers_dict,
        )


def build_http_client(
    user_agent: Optional[str] = None,
    *,
    retries: int = 3,
    backoffs: Iterable[float] = (0.25, 0.5, 1.0),
    rate_per_host: Optional[float] = None,
    burst: Optional[int] = None,
) -> AsyncHttpClientProtocol:
    """Factory to build a shared async HTTP client.

    Args:
        user_agent: Optional default User-Agent header for all requests.
        retries: Number of additional attempts after the first try.
        backoffs: Iterable of backoff durations (seconds) between attempts.
        rate_per_host: Optional per-host rate (tokens per second) for the
            in-process token-bucket limiter.
        burst: Optional bucket size (max burst) for the per-host limiter.

    Returns:
        An `AsyncHttpClientProtocol` implementation.

    Examples:
        client = build_http_client(
            "my-app/1.0",
            retries=3,
            backoffs=(0.25, 0.5, 1.0),
            rate_per_host=5.0,
            burst=10,
        )
    """
    base_headers = {"User-Agent": user_agent} if user_agent else None
    rate_limit = (rate_per_host, burst) if (rate_per_host and burst) else None
    return AsyncHttpClient(
        base_headers=base_headers,
        retries=int(retries),
        backoffs=tuple(float(b) for b in backoffs),
        rate_limit=rate_limit,  # type: ignore[arg-type]
    )
