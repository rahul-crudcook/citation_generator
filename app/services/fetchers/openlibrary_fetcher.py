# pylint: disable=W0718
"""
OpenLibrary fetcher: resolve an ISBN to book facts.

Queries OpenLibrary's ISBN endpoint and maps the response to your internal
book fields (title, authors, publisher, city, year).
"""

from __future__ import annotations

import re
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import Settings
from app.core.enums import FetchSource
from app.core.http import AsyncHttpClientProtocol  # type: ignore
from app.services.fetchers.base import BaseFetcher, FetchResult

_ISBN_DIGITS = re.compile(r"[0-9Xx]+")
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_RETRY_AFTER_RE = re.compile(r"Retry-After=(\d+)")


def _digits_only(isbn: str) -> str:
    """Strip non-ISBN characters, keep digits and X (for ISBN-10)."""
    return "".join(_ISBN_DIGITS.findall(isbn))


def _split_author_name(name: str) -> Tuple[str, str]:
    """Split a full name into (last, first) conservatively."""
    clean = (name or "").strip()
    if not clean:
        return ("", "")
    if "," in clean:
        last, first = [part.strip() for part in clean.split(",", 1)]
        return (last, first)
    parts = clean.split()
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[-1], " ".join(parts[:-1]))


def _get_header_value(resp: Any, name: str) -> Optional[str]:
    """Best-effort header accessor that works with multiple client responses.

    Tries (in order):
      - resp.headers (mapping-like)
      - resp.get_header(name) (method)
      - resp.raw_headers (list[tuple[bytes, bytes]]) as in some ASGI clients

    Returns the first matching value (case-insensitive) or None.
    """
    # 1) mapping-like headers attribute
    hdrs = getattr(resp, "headers", None)
    if hdrs is not None:
        try:
            # dict-like
            val = hdrs.get(name) or hdrs.get(
                name.lower()) or hdrs.get(name.title())  # type: ignore[attr-defined]
            if val:
                return str(val)
        except Exception:
            pass

    # 2) get_header method
    get_header = getattr(resp, "get_header", None)
    if callable(get_header):
        try:
            val = get_header(name)
            if val:
                return str(val)
        except Exception:
            pass

    # 3) raw_headers list of tuples
    raw = getattr(resp, "raw_headers", None)
    if raw:
        try:
            for k, v in raw:
                if isinstance(k, bytes):
                    k = k.decode("latin-1")
                if isinstance(v, bytes):
                    v = v.decode("latin-1")
                if str(k).lower() == name.lower():
                    return str(v)
        except Exception:
            pass

    return None


async def _resolve_authors(
    http: AsyncHttpClientProtocol, settings: Settings, author_keys: List[str]
) -> List[Dict[str, str]]:
    """Resolve author keys (/authors/OLxxxA.json) to names.

    Best-effort: if a particular author request fails or returns bad JSON,
    we skip that author and continue without failing the whole fetch.
    """
    results: List[Dict[str, str]] = []
    base = settings.OPENLIBRARY_BASE_URL.rstrip("/")
    for key in author_keys:
        url = (
            f"{base}{key}.json"
            if key.startswith("/authors/")
            else f"{base}/authors/{key}.json"
        )
        try:
            resp = await http.get(
                url,
                headers={"User-Agent": settings.USER_AGENT, "Accept": "application/json"},
                timeout=settings.FETCH_TIMEOUT_SECONDS,
            )
        except (TimeoutError, OSError):
            # Network/timeout: skip this author and continue.
            continue

        # Respect rate-limit/temporary failures for author lookups by skipping (best-effort).
        if resp.status_code != 200:
            # On 429 or any non-200, just skip this particular author to remain best-effort.
            continue

        try:
            data = resp.json()
        except ValueError:
            # Malformed JSON for this author; skip.
            continue

        name = (data.get("personal_name") or data.get("name") or "").strip()
        last, first = _split_author_name(name)
        if last or first:
            results.append({"last": last, "first": first})
    return results


class OpenLibraryFetcher(BaseFetcher):
    """Fetcher that resolves ISBNs against OpenLibrary."""

    def __init__(self, http: AsyncHttpClientProtocol, settings: Settings) -> None:
        self._http = http
        self._settings = settings

    async def _get_json_or_raise(self, url: str) -> Dict[str, Any]:
        """GET a JSON URL and raise RuntimeError with clear upstream status.

        - Propagates 429 with a Retry-After hint if present.
        - Propagates 404 as not found.
        - Raises on any other non-200 status codes.
        """
        # Minimal retry for transient 5xx/timeouts (NOT for 429/404).
        attempts = 0
        while True:
            attempts += 1
            try:
                resp = await self._http.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": self._settings.USER_AGENT,
                    },
                    timeout=self._settings.FETCH_TIMEOUT_SECONDS,
                )
            except (TimeoutError, OSError) as exc:
                if attempts < 2:  # single retry on network hiccup
                    await asyncio.sleep(0.5)
                    continue
                raise RuntimeError(f"OpenLibrary request failed: {exc}") from exc

            if resp.status_code == 429:
                retry_after = _get_header_value(resp, "Retry-After") or "60"
                # Embed Retry-After so the API layer can expose it as a header.
                raise RuntimeError(f"OpenLibrary HTTP 429 (Retry-After={retry_after})")
            if resp.status_code == 404:
                raise RuntimeError("OpenLibrary: ISBN not found (HTTP 404).")
            if resp.status_code >= 500 and attempts < 2:
                # retry once on server errors
                await asyncio.sleep(0.5)
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"OpenLibrary HTTP {resp.status_code}")

            try:
                return resp.json() or {}
            except ValueError as exc:
                raise RuntimeError(f"OpenLibrary JSON parse error: {exc}") from exc

    async def _fetch_isbn_core(self, isbn: str) -> Dict[str, Any]:
        """Fetch the core ISBN JSON: /isbn/{isbn}.json"""
        base = self._settings.OPENLIBRARY_BASE_URL.rstrip("/")
        work_url = f"{base}/isbn/{isbn}.json"
        return await self._get_json_or_raise(work_url)

    async def _fetch_isbn_data_api(self, isbn: str) -> Dict[str, Any]:
        """Fetch the data-rich Books API response: 
        /api/books?bibkeys=ISBN:{isbn}&jscmd=data&format=json

        This often includes author names inline, reducing extra author lookups.
        """
        base = self._settings.OPENLIBRARY_BASE_URL.rstrip("/")
        url = f"{base}/api/books?bibkeys=ISBN:{isbn}&jscmd=data&format=json"
        data = await self._get_json_or_raise(url)
        return data.get(f"ISBN:{isbn}", {}) or {}

    async def fetch(self, identifier: str) -> FetchResult:
        """Fetch facts for an ISBN via OpenLibrary.

        Args:
            identifier: ISBN-10/13 (with or without hyphens/spaces).

        Returns:
            FetchResult with book facts.

        Raises:
            ValueError: If the ISBN is malformed.
            RuntimeError: If OpenLibrary returns errors or malformed JSON.
        """
        isbn = _digits_only(identifier)
        if len(isbn) not in (10, 13):
            raise ValueError("Malformed ISBN; expected 10 or 13 digits.")

        # 1) Try core ISBN JSON
        core: Dict[str, Any] = await self._fetch_isbn_core(isbn)

        # 2) Optionally fetch Books API (data-rich) for better authors/publishers if needed
        data_api: Dict[str, Any] = {}
        try:
            data_api = await self._fetch_isbn_data_api(isbn)
        except RuntimeError as exc:
            # If the data API is rate-limited/404/etc., we can still proceed with core JSON.
            # We only propagate errors from the *primary* core call above.
            # Keep the exception silent here to remain best-effort.
            _ = exc  # intentional no-op

        # Map fields (prefer richer data_api where possible)
        title = (data_api.get("title") or core.get("title") or "").strip()

        # Publishers: data_api → list[{"name": "..."}]; core → list[str] or list[dict]
        publisher: str = ""
        publishers_api = data_api.get("publishers") or []
        if isinstance(publishers_api, list) and publishers_api:
            first = publishers_api[0]
            if isinstance(first, dict) and "name" in first:
                publisher = (first.get("name") or "").strip()

        if not publisher:
            publishers_core = core.get("publishers") or []
            if isinstance(publishers_core, list) and publishers_core:
                first = publishers_core[0]
                if isinstance(first, dict):
                    publisher = (first.get("name") or "").strip()
                elif isinstance(first, str):
                    publisher = first.strip()

        # City: only in core (usually), as list[str]
        city = ""
        publish_places = core.get("publish_places") or []
        if isinstance(publish_places, list) and publish_places:
            first = publish_places[0]
            if isinstance(first, str):
                city = first.strip()

        # Year: prefer data_api.publish_date, fallback to core.publish_date
        year: Optional[int] = None
        publish_date = (
            data_api.get("publish_date")
            or core.get("publish_date")
            or data_api.get("publishDate")
            or ""
        )
        if isinstance(publish_date, str):
            m = _YEAR_RE.search(publish_date)
            if m:
                year = int(m.group(0))

        # Authors:
        authors: List[Dict[str, str]] = []
        # data_api authors are [{"name": "..."}] — easy path
        authors_api = data_api.get("authors") or []
        for a in authors_api:
            if isinstance(a, dict) and a.get("name"):
                last, first = _split_author_name(str(a["name"]))
                if last or first:
                    authors.append({"last": last, "first": first})

        # If none from data_api, fall back to resolving core author keys best-effort
        if not authors:
            author_objs = core.get("authors") or []
            author_keys: List[str] = []
            for a in author_objs:
                key = a.get("key") if isinstance(a, dict) else None
                if key:
                    author_keys.append(key)
            if author_keys:
                authors = await _resolve_authors(self._http, self._settings, author_keys)

        facts: Dict[str, Any] = {
            "authors": authors,  # e.g., [{"last": "Martin", "first": "Robert"}]
            "title": title,  # "Clean Code"
            "publisher": publisher,  # "Prentice Hall"
            "city_of_publication": city,  # e.g., "Upper Saddle River, NJ"
            "year": year,  # 2008
            "isbn": isbn,
        }

        # Confidence scoring (heuristic)
        confidence = 0.7
        if title:
            confidence += 0.1
        if authors:
            confidence += 0.05
        if year:
            confidence += 0.05
        confidence = min(confidence, 0.9)

        return FetchResult(
            facts=facts,
            confidence=confidence,
            source=FetchSource.openlibrary,
        )
