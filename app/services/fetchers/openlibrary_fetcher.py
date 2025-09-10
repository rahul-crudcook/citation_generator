"""
OpenLibrary fetcher: resolve an ISBN to book facts.

Queries OpenLibrary's ISBN endpoint and maps the response to your internal
book fields (title, authors, publisher, city, year).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import Settings
from app.core.enums import FetchSource
from app.core.http import AsyncHttpClientProtocol  # type: ignore
from app.services.fetchers.base import BaseFetcher, FetchResult

_ISBN_DIGITS = re.compile(r"[0-9Xx]+")


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
                headers={"User-Agent": settings.USER_AGENT},
                timeout=settings.FETCH_TIMEOUT_SECONDS,
            )
        except (TimeoutError, OSError):
            # Network/timeout: skip this author and continue.
            continue

        if resp.status_code != 200:
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

        base = self._settings.OPENLIBRARY_BASE_URL.rstrip("/")
        work_url = f"{base}/isbn/{isbn}.json"

        try:
            resp = await self._http.get(
                work_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self._settings.USER_AGENT,
                },
                timeout=self._settings.FETCH_TIMEOUT_SECONDS,
            )
        except (TimeoutError, OSError) as exc:
            # Network/timeout issues surface as retriable server-side failures.
            raise RuntimeError(f"OpenLibrary request failed: {exc}") from exc

        if resp.status_code == 404:
            raise RuntimeError("OpenLibrary: ISBN not found.")
        if resp.status_code != 200:
            raise RuntimeError(f"OpenLibrary HTTP {resp.status_code}")

        try:
            data: Dict[str, Any] = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"OpenLibrary JSON parse error: {exc}") from exc

        # Map fields
        title = (data.get("title") or "").strip()
        publishers = data.get("publishers") or []
        publish_places = data.get("publish_places") or []
        publish_date = (data.get("publish_date") or "").strip()

        # Extract year from publish_date (e.g., "2017", "June 2017")
        year: Optional[int] = None
        for token in re.findall(r"\d{4}", publish_date):
            maybe = int(token)
            if 1000 <= maybe <= 9999:
                year = maybe
                break

        # Resolve authors if present
        author_objs = data.get("authors") or []
        author_keys: List[str] = []
        for a in author_objs:
            key = a.get("key")
            if key:
                author_keys.append(key)

        authors = await _resolve_authors(self._http, self._settings, author_keys)

        facts: Dict[str, Any] = {
            "authors": authors,
            "title": title,
            "publisher": (publishers[0] if publishers else "").strip(),
            "city_of_publication": (publish_places[0] if publish_places else "").strip(),
            "year": year,
            "isbn": isbn,
        }

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
