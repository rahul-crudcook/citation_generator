# pylint: disable= W0611
"""
Async HTTP client abstraction for fetchers/services.

We expose:
- `AsyncHttpClientProtocol`: tiny protocol used by code to perform HTTP calls.
- `HttpResponse`: a lightweight wrapper with the attributes we need.
- `AsyncHttpClient`: httpx-based implementation.
- `build_http_client`: small factory for DI.

This keeps the rest of the code decoupled from any specific HTTP library.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, cast

# Optional dependency: httpx. We alias to `_HTTPX` to satisfy pylint naming.
try:
    import httpx as _HTTPX  # type: ignore
except (ModuleNotFoundError, ImportError):
    _HTTPX = None  # type: ignore


@dataclass(frozen=True)
class HttpResponse:
    """Lightweight HTTP response shape consumed by fetchers."""

    status_code: int
    text: str
    _json: Optional[Any] = None

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
    """Tiny async HTTP client protocol for dependency inversion."""

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
    """`httpx`-based client implementing `AsyncHttpClientProtocol`."""

    def __init__(self, *, base_headers: Optional[Dict[str, str]] = None) -> None:
        if _HTTPX is None:
            msg = "httpx is not installed; cannot create AsyncHttpClient."
            raise RuntimeError(msg)
        self._client = _HTTPX.AsyncClient(headers=base_headers or {}, follow_redirects=True)

    async def get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        resp = await self._client.get(url, headers=headers, timeout=timeout)
        content_text = resp.text
        # Pre-parse JSON once for efficiency if content-type hints.
        parsed_json: Optional[Any]
        try:
            if "application/json" in (resp.headers.get("content-type") or ""):
                parsed_json = resp.json()
            else:
                parsed_json = None
        except ValueError:
            parsed_json = None
        return HttpResponse(
            status_code=cast(int, resp.status_code),
            text=content_text,
            _json=parsed_json,
        )

    async def post(
        self,
        url: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        resp = await self._client.post(
            url, json=json_body, headers=headers, timeout=timeout
        )
        content_text = resp.text
        parsed_json: Optional[Any]
        try:
            if "application/json" in (resp.headers.get("content-type") or ""):
                parsed_json = resp.json()
            else:
                parsed_json = None
        except ValueError:
            parsed_json = None
        return HttpResponse(
            status_code=cast(int, resp.status_code),
            text=content_text,
            _json=parsed_json,
        )

    async def close(self) -> None:
        await self._client.aclose()


def build_http_client(user_agent: Optional[str] = None) -> AsyncHttpClientProtocol:
    """Factory to build a shared async HTTP client.

    Args:
        user_agent: Optional default User-Agent header for all requests.

    Returns:
        An `AsyncHttpClientProtocol` implementation.
    """
    base_headers = {"User-Agent": user_agent} if user_agent else None
    return AsyncHttpClient(base_headers=base_headers)
