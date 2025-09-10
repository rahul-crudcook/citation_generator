"""
Schemas for the Ingest (M4) API.

This module defines the request/response Pydantic models used by the
`/ingest/link` endpoint. These models encapsulate validation and typing for
production usage and are written to be pylint/black compliant.

Design notes
------------
- We keep models small and explicit; each has a single responsibility.
- `IngestLinkRequest` is the input contract; `IngestLinkResponse` is the
  output contract.
- `facts` is intentionally a flexible mapping (dict[str, Any]) because it can
  represent any of the supported source-type fact sets. Normalization into
  stricter per-type schemas happens in the service layer.
- Confidence is constrained to [0.0, 1.0].
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator
from typing_extensions import Annotated

from app.core.enums import FetchSource, SourceType

__all__ = [
    "IngestLinkRequest",
    "IngestLinkResponse",
]


class IngestLinkRequest(BaseModel):
    """Request payload for POST /ingest/link.

    Attributes:
        source_type: Optional hint to guide parsing/mapping of fetched fields
            into your internal schemas (e.g., book, journal_article, website).
            If omitted, the service will infer from the link and heuristics.
        link: A DOI, ISBN, or HTTP/HTTPS URL string to ingest.
    """

    source_type: SourceType | None = Field(
        default=None,
        description=(
            "Optional source type hint (book, journal_article, "
            "magazine_newspaper, encyclopedia, website)."
        ),
        examples=["journal_article"],
    )
    link: str = Field(
        ...,
        min_length=3,
        max_length=2048,
        description="The DOI/ISBN/URL to ingest (e.g., '10.1038/...' or 'https://...').",
        examples=[
            "https://doi.org/10.1038/s41586-020-2649-2",
            "9780134685991",
            "https://example.com/some-article",
        ],
    )

    @field_validator("link")
    @classmethod
    def _strip_and_check_not_empty(cls, value: str) -> str:
        """Normalize whitespace and ensure link is not empty.

        Args:
            value: Raw link string provided by the client.

        Returns:
            The trimmed link.

        Raises:
            ValueError: If the resulting link is empty.
        """
        trimmed = value.strip()
        if not trimmed:
            msg = "Link must not be empty."
            raise ValueError(msg)
        return trimmed

    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
        "use_enum_values": True,
        "json_schema_extra": {
            "examples": [
                {
                    "source_type": "journal_article",
                    "link": "https://doi.org/10.1038/s41586-020-2649-2",
                }
            ]
        },
    }


class IngestLinkResponse(BaseModel):
    """Response payload for POST /ingest/link.

    Attributes:
        facts: Normalized citation facts derived from the link. Exact keys
            depend on `source_type` (e.g., authors/title/year for books or
            journal_title/volume/pages for journal articles).
        confidence: A score in [0.0, 1.0] indicating how confident the system
            is in the fetched/normalized mapping.
        source: The upstream fetcher/source used to obtain the data.
    """

    facts: dict[str, Any] = Field(
        default_factory=dict,
        description="Normalized citation facts (shape depends on source_type).",
        examples=[
            {
                "authors": [{"last": "Doe", "first": "Jane"}],
                "article_title": "Great Discoveries",
                "journal_title": "Science",
                "year": 2021,
                "pages": "12–18",
            }
        ],
    )
    confidence: Annotated[
        float, Field(ge=0.0, le=1.0, description="Confidence score in [0.0, 1.0].")
    ] = 0.0
    source: FetchSource = Field(
        ...,
        description="Fetcher that produced the facts (e.g., crossref, openlibrary, url).",
        examples=["crossref"],
    )

    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
        "use_enum_values": True,
        "json_schema_extra": {
            "examples": [
                {
                    "facts": {
                        "authors": [{"last": "Doe", "first": "Jane"}],
                        "article_title": "Great Discoveries",
                        "journal_title": "Science",
                        "year": 2021,
                        "pages": "12–18",
                    },
                    "confidence": 0.87,
                    "source": "crossref",
                }
            ]
        },
    }
