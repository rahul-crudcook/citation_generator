"""
Generic URL fetcher: extract facts from a web page.

Strategy (best-effort, never blocking manual entry):
1) Fetch HTML.
2) Prefer OpenGraph / Twitter meta tags.
3) Fall back to Readability (readability-lxml) and <title>.
4) Extract author and published date from common meta tags if available.

Produces minimal fields for a `website_webpage` source type:
- authors (if detectable)
- work_title
- site_title
- date_published (best-effort ISO date or YYYY-MM-DD)
- url
"""

from __future__ import annotations

import datetime as dt
import importlib
import re
from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.core.enums import FetchSource
from app.core.http import AsyncHttpClientProtocol  # type: ignore
from app.services.fetchers.base import BaseFetcher, FetchResult


def _first_non_empty(*values: Optional[str]) -> str:
    """Return the first non-empty stripped string."""
    for val in values:
        if val:
            stripped = val.strip()
            if stripped:
                return stripped
    return ""


def _parse_date(value: Optional[str]) -> Optional[str]:
    """Normalize common meta date strings to ISO YYYY-MM-DD when possible."""
    if not value:
        return None
    s = value.strip()

    # ISO-like: 2021-03-14 or 2021-03-14T12:00:00Z
    iso_candidate = s.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(iso_candidate)  # type: ignore[arg-type]
        return parsed.date().isoformat()
    except (ValueError, TypeError):
        pass

    # Slashes or dashes: YYYY[-|/]MM[-|/]DD
    match = re.match(r"(\d{4})[/-](\d{2})[/-](\d{2})", s)
    if match:
        try:
            year, month, day = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            return dt.date(year, month, day).isoformat()
        except (ValueError, TypeError):
            return None

    # Month name: "March 14, 2021"
    try:
        return dt.datetime.strptime(s, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def _split_author_name(name: str) -> Dict[str, str]:
    """Split an author string into {last, first} with basic heuristics."""
    clean = (name or "").strip()
    if not clean:
        return {"last": "", "first": ""}
    if "," in clean:
        last, first = [part.strip() for part in clean.split(",", 1)]
        return {"last": last, "first": first}
    parts = clean.split()
    if len(parts) == 1:
        return {"last": parts[0], "first": ""}
    return {"last": parts[-1], "first": " ".join(parts[:-1])}


def _try_import_bs4() -> Any:
    """Import bs4.BeautifulSoup via importlib; return None if unavailable."""
    try:
        module = importlib.import_module("bs4")
        return getattr(module, "BeautifulSoup", None)
    except (ModuleNotFoundError, ImportError):
        return None


def _try_import_readability() -> Any:
    """Import readability.Document via importlib; return None if unavailable."""
    try:
        module = importlib.import_module("readability")
        return getattr(module, "Document", None)
    except (ModuleNotFoundError, ImportError):
        return None


class UrlFetcher(BaseFetcher):
    """Fetcher that extracts metadata from arbitrary URLs."""

    def __init__(self, http: AsyncHttpClientProtocol, settings: Settings) -> None:
        self._http = http
        self._settings = settings

    async def fetch(self, identifier: str) -> FetchResult:
        """Fetch facts for an HTTP/HTTPS URL.

        Args:
            identifier: Canonical URL.

        Returns:
            FetchResult with website_webpage facts.

        Raises:
            ValueError: If the URL is not HTTP/HTTPS.
            RuntimeError: If the page is unreachable or parsing fails badly.
        """
        url = identifier.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")

        # 1) Download HTML
        try:
            resp = await self._http.get(
                url,
                headers={"User-Agent": self._settings.USER_AGENT},
                timeout=self._settings.FETCH_TIMEOUT_SECONDS,
            )
        except (TimeoutError, OSError) as exc:
            raise RuntimeError(f"URL fetch failed: {exc}") from exc

        if resp.status_code >= 400:
            raise RuntimeError(f"URL fetch HTTP {resp.status_code}")

        html = resp.text or ""

        # 2) Parse meta tags (prefer OG/Twitter) using BeautifulSoup if available
        og_title = ""
        og_site = ""
        meta_author = ""
        meta_date = ""

        bs4_beautiful_soup = _try_import_bs4()
        if bs4_beautiful_soup is not None:
            try:
                soup = bs4_beautiful_soup(html, "lxml")

                def _meta(name: str) -> Optional[str]:
                    tag = soup.find("meta", attrs={"name": name})
                    content = tag.get("content") if tag and tag.get("content") else None
                    return content

                def _prop(property_name: str) -> Optional[str]:
                    tag = soup.find("meta", attrs={"property": property_name})
                    content = tag.get("content") if tag and tag.get("content") else None
                    return content

                og_title = _first_non_empty(
                    _prop("og:title"),
                    _prop("twitter:title"),
                )
                og_site = _first_non_empty(
                    _prop("og:site_name"),
                    _meta("application-name"),
                )
                meta_author = _first_non_empty(
                    _meta("author"),
                    _prop("article:author"),
                )
                meta_date = _first_non_empty(
                    _meta("article:published_time"),
                    _prop("article:published_time"),
                    _meta("date"),
                )

                # Fallback to <title> if no OG title
                if not og_title:
                    title_tag = soup.find("title")
                    if title_tag and getattr(title_tag, "text", None):
                        og_title = title_tag.text.strip()
            except (ValueError, TypeError, AttributeError):
                # Any parser-level issue → skip; we will try readability next.
                pass

        # 3) Readability fallback for main content title if OG missing
        if not og_title:
            readability_document_cls = _try_import_readability()
            if readability_document_cls is not None:
                try:
                    doc = readability_document_cls(html)
                    og_title = (doc.short_title() or doc.title() or "").strip()
                except (ValueError, TypeError, AttributeError):
                    og_title = ""

        # Normalize authors list
        authors: List[Dict[str, str]] = []
        if meta_author:
            # Support comma-separated authors; split conservatively.
            parts = [part.strip() for part in meta_author.split(",") if part.strip()]
            for raw in parts:
                authors.append(_split_author_name(raw))

        facts: Dict[str, Any] = {
            "authors": authors,
            "work_title": og_title,
            "site_title": og_site,
            "date_published": _parse_date(meta_date),
            "url": url,
        }

        # Confidence heuristic based on extracted signals
        confidence = 0.55
        if og_title:
            confidence += 0.15
        if og_site:
            confidence += 0.1
        if authors:
            confidence += 0.05
        if facts["date_published"]:
            confidence += 0.05
        confidence = min(confidence, 0.85)

        return FetchResult(
            facts=facts,
            confidence=confidence,
            source=FetchSource.url,
        )
