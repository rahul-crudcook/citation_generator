"""
Ingest service (M4).

This module implements the orchestration for the "paste-a-link" experience:
given a DOI/ISBN/URL, it detects the link type, consults the appropriate
fetcher, performs caching, runs normalization, and returns a structured result.

Design goals
------------
- Pure service class with explicit dependencies injected (HTTP client, cache,
  settings, and concrete fetchers) to keep it testable and production-ready.
- Clear error boundaries:
  * ValueError → client errors (malformed/unsupported link)
  * RuntimeError → transient upstream errors (timeouts, bad gateways, etc.)
- No FastAPI-specific imports or side-effects here (keeps service portable).
- Lintable with pylint and formatted with black.

Usage
-----
The API layer should construct/resolve an `IngestService` (via DI) and call:

    await service.ingest_link(link="https://doi.org/10.1234/xyz", source_type=None)
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, List, Optional

from app.core.cache import AsyncCacheProtocol  # type: ignore
from app.core.config import Settings
from app.core.enums import FetchSource, SourceType
from app.core.http import AsyncHttpClientProtocol  # type: ignore
from app.services.citation_validation_service import (
    citation_validation_service,
)
from app.services.fetchers.base import BaseFetcher, FetchResult
from app.services.fetchers.crossref_fetcher import CrossrefFetcher
from app.services.fetchers.openlibrary_fetcher import OpenLibraryFetcher
from app.services.fetchers.url_fetcher import UrlFetcher
from app.utils.detect import detect_doi, detect_isbn, detect_url
from app.utils.merge import merge_facts

__all__ = ["IngestService", "IngestResult"]


@dataclass(frozen=True)
class IngestResult:
    """Final result returned by the ingest service.

    Attributes:
        facts: Normalized citation facts (shape depends on `source_type`).
        confidence: Confidence score in [0.0, 1.0].
        source: Upstream fetcher/source that produced the facts.
    """

    facts: Dict[str, Any]
    confidence: float
    source: FetchSource


class IngestService:
    """Ingest orchestration for DOI/ISBN/URL.

    Coordinates:
        1) Link-type detection (DOI/ISBN/URL).
        2) Cache lookup by a deterministic key for the link.
        3) Fetch via the appropriate fetcher (Crossref/OpenLibrary/URL).
        4) Normalization into internal fact structures (via validation service).
        5) Confidence scoring and response shaping.

    Dependencies are injected so that:
        - HTTP I/O and caching can be mocked in tests.
        - Fetchers can be swapped/toggled via settings without code changes.
    """

    def __init__(
        self,
        *,
        http: AsyncHttpClientProtocol,
        cache: Optional[AsyncCacheProtocol],
        settings: Settings,
        crossref_fetcher: Optional[BaseFetcher] = None,
        openlibrary_fetcher: Optional[BaseFetcher] = None,
        url_fetcher: Optional[BaseFetcher] = None,
    ) -> None:
        """Initialize the service with infrastructure and fetchers."""
        self._http = http
        self._cache = cache
        self._settings = settings

        # Feature toggles with safe defaults if settings are missing.
        enable_crossref = bool(getattr(settings, "ENABLE_CROSSREF", True))
        enable_openlib = bool(getattr(settings, "ENABLE_OPENLIBRARY", True))
        enable_url = bool(getattr(settings, "ENABLE_URL_SCRAPE", True))

        # Lazily construct defaults if toggles are enabled and fetchers are not supplied.
        self._crossref: Optional[BaseFetcher] = (
            crossref_fetcher
            if crossref_fetcher is not None
            else (CrossrefFetcher(http, settings) if enable_crossref else None)
        )
        self._openlibrary: Optional[BaseFetcher] = (
            openlibrary_fetcher
            if openlibrary_fetcher is not None
            else (OpenLibraryFetcher(http, settings) if enable_openlib else None)
        )
        self._url_fetcher: Optional[BaseFetcher] = (
            url_fetcher
            if url_fetcher is not None
            else (UrlFetcher(http, settings) if enable_url else None)
        )

    async def ingest_link(
        self, *, link: str, source_type: Optional[SourceType | str]
    ) -> IngestResult:
        """Ingest a DOI/ISBN/URL and return normalized facts.

        The service tries the following flow:
            - Detect DOI → use Crossref fetcher.
            - Detect ISBN → use OpenLibrary fetcher.
            - Detect URL → use URL fetcher (readability/OG/heuristics).
            - Otherwise → raise ValueError for unsupported/malformed link.

        Results are cached by a stable key derived from the canonical link.

        Args:
            link: A DOI ("10.XXXX/..."), ISBN-10/13 (digits/hyphens), or URL.
            source_type: Optional hint to inform normalization.

        Returns:
            IngestResult with normalized facts, confidence, and source.

        Raises:
            ValueError: If the link is empty, malformed, or unsupported.
            RuntimeError: If the upstream services fail in a retriable way.
        """
        trimmed = link.strip()
        if not trimmed:
            raise ValueError("Link must not be empty.")

        # 1) Detect type; also produce normalization-friendly forms.
        doi = detect_doi(trimmed)
        isbn = detect_isbn(trimmed)
        url = detect_url(trimmed)

        # 2) Build a cache key and attempt read-through cache.
        cache_key = self._cache_key(doi=doi, isbn=isbn, url=url)
        if self._cache is not None and cache_key is not None:
            cached = await self._cache.get_json(cache_key)
            if cached:
                return IngestResult(
                    facts=cached["facts"],
                    confidence=float(cached["confidence"]),
                    source=FetchSource(cached["source"]),
                )

        # 3) Select the right fetcher and get raw facts.
        fetch_result = await self._fetch_with_detection(doi=doi, isbn=isbn, url=url)

        # 4) Normalize via validation service (uses source_type hint if provided).
        normalized = self._normalize_facts(fetch_result.facts, source_type=source_type)

        # 5) Merge policy (user-facts-first). For /ingest/link we have no user facts.
        merged = merge_facts(user_facts=None, fetched_facts=normalized)

        result = IngestResult(
            facts=merged,
            confidence=float(fetch_result.confidence),
            source=fetch_result.source,
        )

        # 6) Cache the normalized result (best-effort).
        cache_ttl = int(getattr(self._settings, "INGEST_CACHE_TTL_SECONDS", 300))
        if self._cache is not None and cache_key is not None:
            await self._cache.set_json(
                cache_key,
                {
                    "facts": result.facts,
                    "confidence": result.confidence,
                    "source": result.source.value,
                },
                ttl_seconds=cache_ttl,
            )

        return result

    async def _fetch_with_detection(
        self, *, doi: Optional[str], isbn: Optional[str], url: Optional[str]
    ) -> FetchResult:
        """Select and call the appropriate fetcher based on detection.

        Raises:
            ValueError: When no supported link type is detected or the
                corresponding fetcher is disabled/missing.
        """
        if doi:
            if self._crossref is None:
                raise ValueError("DOI ingestion is disabled in settings.")
            return await self._crossref.fetch(doi)

        if isbn:
            if self._openlibrary is None:
                raise ValueError("ISBN ingestion is disabled in settings.")
            return await self._openlibrary.fetch(isbn)

        if url:
            if self._url_fetcher is None:
                raise ValueError("URL ingestion is disabled in settings.")
            return await self._url_fetcher.fetch(url)

        raise ValueError("Unsupported or malformed link. Provide a DOI, ISBN, or URL.")

    def _normalize_facts(
        self,
        facts: Dict[str, Any],
        *,
        source_type: Optional[SourceType | str],
    ) -> Dict[str, Any]:
        """Normalize fetched facts using the validation service.

        Accepts a `SourceType`, a string, or `None`. Strings are coerced to the
        enum; invalid strings fall back to inference. Then we adapt the fetcher
        output to the validator's expected shape and return normalized facts.
        """
        st = self._coerce_or_infer_source_type(facts, source_type)
        adapted = self._adapt_for_validator(st, facts)
        response = citation_validation_service.validate(st.value, adapted)
        # `normalized_facts` is already in your canonical internal shape.
        return dict(response.normalized_facts or {})

    @staticmethod
    def _author_dict_to_str(author: Dict[str, Any]) -> str:
        """Render {'last','first'} → 'Last, First' (best-effort)."""
        last = (author.get("last") or "").strip()
        first = (author.get("first") or "").strip()
        if last and first:
            return f"{last}, {first}"
        return last or first

    def _coerce_authors_to_strings(self, authors: Any) -> List[str]:
        """Convert authors into list[str] acceptable by the validator."""
        if not isinstance(authors, list):
            return []
        out: List[str] = []
        for item in authors:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
            elif isinstance(item, dict):
                rendered = self._author_dict_to_str(item)
                if rendered:
                    out.append(rendered)
        return out

    def _adapt_for_validator(self, st: SourceType, facts: Dict[str, Any]) -> Dict[str, Any]:
        """Map fetcher fields → validator fields and drop unknowns."""
        if st == SourceType.journal_article:
            year_val = facts.get("year")
            if isinstance(year_val, int):
                year_str = str(year_val)
            else:
                year_str = (year_val or "").strip() if isinstance(year_val, str) else ""
            adapted = {
                "authors": self._coerce_authors_to_strings(facts.get("authors")),
                "title": (facts.get("title") or facts.get("article_title") or "").strip(),
                "journal": (facts.get("journal") or facts.get("journal_title") or "").strip(),
                "year": year_str,
                "volume": (facts.get("volume") or facts.get(
                    "journal_volume") or "").strip() or None,
                "issue": (facts.get("issue") or facts.get("journal_number") or "").strip() or None,
                "pages": (facts.get("pages") or "").strip() or None,
                "doi": (facts.get("doi") or "").strip() or None,
                "url": (facts.get("url") or "").strip() or None,
            }
            return adapted

        if st == SourceType.book:
            year_val = facts.get("year")
            if isinstance(year_val, int):
                year_str = str(year_val)
            else:
                year_str = (year_val or "").strip() if isinstance(year_val, str) else ""
            adapted = {
                "authors": self._coerce_authors_to_strings(facts.get("authors")),
                "title": (facts.get("title") or "").strip(),
                "publisher": (facts.get("publisher") or "").strip(),
                "city_of_publication": (facts.get("city_of_publication") or "").strip() or None,
                "year": year_str,
            }
            return adapted

        if st == SourceType.website:
            # Optionally derive year from an ISO-ish date string if present.
            year_str = ""
            date_published = facts.get("date_published")
            if isinstance(date_published, str) and len(date_published) >= 4:
                year_str = date_published[:4]
            elif isinstance(facts.get("year"), str):
                year_str = (facts.get("year") or "").strip()
            elif isinstance(facts.get("year"), int):
                year_str = str(facts.get("year"))

            adapted = {
                "authors": self._coerce_authors_to_strings(facts.get("authors")),
                "title": (facts.get("work_title") or facts.get("title") or "").strip(),
                "url": (facts.get("url") or "").strip(),
                "year": year_str or None,
                "accessed_date": None,  # can be set by client later
            }
            return adapted

        # Default: pass through minimal keys
        return dict(facts)

    @staticmethod
    def _infer_source_type(facts: Dict[str, Any]) -> SourceType:
        """Infer a likely SourceType from fetched facts (best-effort)."""
        if facts.get("journal") or facts.get("journal_title") or facts.get("doi"):
            return SourceType.journal_article
        if facts.get("isbn") or (facts.get("publisher") and facts.get("authors")):
            return SourceType.book
        if facts.get("url"):
            return SourceType.website
        # Fallback to website as safest general type.
        return SourceType.website

    def _coerce_or_infer_source_type(
        self, facts: Dict[str, Any], source_type: Optional[SourceType | str]
    ) -> SourceType:
        """Coerce a string to enum or infer when missing/invalid."""
        if isinstance(source_type, SourceType):
            return source_type
        if isinstance(source_type, str) and source_type.strip():
            try:
                return SourceType(source_type)
            except ValueError:
                return self._infer_source_type(facts)
        return self._infer_source_type(facts)

    @staticmethod
    def _cache_key(
        *, doi: Optional[str], isbn: Optional[str], url: Optional[str]
    ) -> Optional[str]:
        """Create a stable cache key for the link, or None if not cacheable."""
        if doi:
            return f"ingest:doi:{doi}"
        if isbn:
            return f"ingest:isbn:{isbn}"
        if url:
            digest = sha256(url.encode("utf-8")).hexdigest()
            return f"ingest:url:{digest}"
        return None
