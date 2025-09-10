"""
Base protocol and result model for ingest fetchers.

All concrete fetchers (Crossref, OpenLibrary, URL, etc.) must implement
`BaseFetcher.fetch()` and return a `FetchResult`. This keeps the ingest
service decoupled from concrete integrations and easy to test/mock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.enums import FetchSource


@dataclass(frozen=True)
class FetchResult:
    """Standard result returned by all fetchers.

    Attributes:
        facts: A mapping of normalized fields prior to final service-level
            normalization. Concrete fetchers should map external data into your
            internal field names (e.g., authors/title/year).
        confidence: The fetcher's confidence in the extracted/parsed facts,
            a float in [0.0, 1.0].
        source: A `FetchSource` enum identifying the upstream used.
    """

    facts: dict
    confidence: float
    source: FetchSource


class BaseFetcher(Protocol):
    """Protocol that all fetchers must implement."""

    async def fetch(self, identifier: str) -> FetchResult:
        """Fetch citation facts using a provider-specific identifier.

        Args:
            identifier: A normalized identifier for the provider:
                - Crossref: DOI ("10.XXXX/..."), no URL prefix.
                - OpenLibrary: Digits-only ISBN-10/13.
                - URL: An HTTP/HTTPS URL.

        Returns:
            A provider-specific `FetchResult`.

        Raises:
            ValueError: If the identifier is malformed or unsupported.
            RuntimeError: If the upstream service fails or times out.
        """
        raise NotImplementedError
