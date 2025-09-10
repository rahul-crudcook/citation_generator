"""
Crossref fetcher: resolve a DOI to journal-article facts.

This implementation calls the Crossref REST API and maps its response
to your internal journal article fields. It focuses on robust parsing
and conservative confidence scoring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.core.enums import FetchSource
from app.core.http import AsyncHttpClientProtocol  # type: ignore
from app.services.fetchers.base import BaseFetcher, FetchResult


def _extract_year(message: Dict[str, Any]) -> Optional[int]:
    """Get a 4-digit year from Crossref's date-parts."""
    issued = message.get("issued") or {}
    parts = issued.get("date-parts") or []
    if parts and parts[0] and isinstance(parts[0], list):
        year = parts[0][0]
        if isinstance(year, int) and 1000 <= year <= 9999:
            return year
    # Fallback: published-print or published-online
    for k in ("published-print", "published-online"):
        obj = message.get(k) or {}
        parts = obj.get("date-parts") or []
        if parts and parts[0] and isinstance(parts[0], list):
            year = parts[0][0]
            if isinstance(year, int) and 1000 <= year <= 9999:
                return year
    return None


def _map_authors(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Convert Crossref authors to {last, first} pairs."""
    results: List[Dict[str, str]] = []
    for a in items or []:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        if family or given:
            results.append({"last": family, "first": given})
    return results


class CrossrefFetcher(BaseFetcher):
    """Fetcher that resolves DOIs against Crossref."""

    def __init__(self, http: AsyncHttpClientProtocol, settings: Settings) -> None:
        """Initialize with shared HTTP client and settings."""
        self._http = http
        self._settings = settings

    async def fetch(self, identifier: str) -> FetchResult:
        """Fetch facts for a DOI via Crossref.

        Args:
            identifier: DOI string (e.g., "10.1038/s41586-020-2649-2").

        Returns:
            FetchResult with journal-article facts.

        Raises:
            ValueError: If the DOI appears malformed.
            RuntimeError: If Crossref returns an unexpected error/shape.
        """
        doi = identifier.strip()
        if not doi or "/" not in doi:
            raise ValueError("Malformed DOI.")

        base = self._settings.CROSSREF_BASE_URL.rstrip("/")
        url = f"{base}/{doi}"

        try:
            resp = await self._http.get(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self._settings.USER_AGENT,
                },
                timeout=self._settings.FETCH_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Crossref request failed: {exc}") from exc

        if resp.status_code != 200:
            raise RuntimeError(f"Crossref HTTP {resp.status_code}")

        try:
            data: Dict[str, Any] = resp.json()
            message = data.get("message") or {}
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Crossref JSON parse error: {exc}") from exc

        # Map into internal fields for journal articles.
        title_list = message.get("title") or []
        container_list = message.get("container-title") or []

        facts: Dict[str, Any] = {
            "authors": _map_authors(message.get("author") or []),
            "article_title": (title_list[0] if title_list else None) or "",
            "journal_title": (container_list[0] if container_list else None) or "",
            "journal_volume": (message.get("volume") or "").strip(),
            "journal_number": (message.get("issue") or "").strip(),
            "pages": (message.get("page") or "").strip(),
            "year": _extract_year(message) or None,
            "doi": doi,
        }

        # Confidence heuristic: base + increments for key fields present.
        confidence = 0.75
        if facts["authors"]:
            confidence += 0.05
        if facts["article_title"]:
            confidence += 0.05
        if facts["journal_title"]:
            confidence += 0.05
        if facts["year"]:
            confidence += 0.05

        confidence = min(confidence, 0.95)

        return FetchResult(
            facts=facts,
            confidence=confidence,
            source=FetchSource.crossref,
        )
