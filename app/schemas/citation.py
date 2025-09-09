"""Pydantic schemas for citation validation I/O and per-type field catalogs (M2).

Goals:
- Canonical field names for each source type.
- Strict input (extra fields forbidden) so clients see mistakes early.
- Friendly input aliases so we can accept common variants without DB changes.
- I/O wrappers for /citations endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.core.enums import SourceType


# ---------------------------------------------------------------------
# Per-type field catalogs (inputs from client)
# ---------------------------------------------------------------------
class BookDetails(BaseModel):
    """Input details for a book citation.

    Canonical fields:
      - authors: list[str] (e.g., ["Doe, Jane", "Roe, John A."])
      - title: str
      - publisher: str
      - year: str  (4-digit string; format checked in service)
      - city_of_publication: Optional[str]
    """

    model_config = ConfigDict(extra="forbid")

    authors: List[str] = Field(..., description="List of author names as strings.")
    title: str = Field(..., description="Title of the work.")
    publisher: str = Field(..., description="Publisher name.")
    year: str = Field(..., description="4-digit publication year (string).")
    city_of_publication: Optional[str] = Field(
        default=None,
        description="City where the work was published.",
        validation_alias=AliasChoices("city_of_publication", "city"),
    )


class JournalArticleDetails(BaseModel):
    """Input details for a journal article citation.

    Canonical fields:
      - authors: list[str]
      - title: str
      - journal: str
      - year: str
      - volume?: str
      - issue?: str
      - pages?: str     (validated: '12-19', '12–19', '12, 25-27', etc.)
      - doi?: str
      - url?: str       (http/https required)
    """

    model_config = ConfigDict(extra="forbid")

    authors: List[str] = Field(default_factory=list, description="List of author names.")
    title: str = Field(..., description="Article title.")
    journal: str = Field(
        ...,
        description="Journal title.",
        validation_alias=AliasChoices("journal", "journal_title"),
    )
    year: str = Field(..., description="4-digit publication year (string).")
    volume: Optional[str] = Field(default=None, description="Volume number (string).")
    issue: Optional[str] = Field(default=None, description="Issue number (string).")
    pages: Optional[str] = Field(
        default=None,
        description="Page(s) or range ('12-19', '12–19', '12, 25-27').",
    )
    doi: Optional[str] = Field(default=None, description="DOI string.")
    url: Optional[str] = Field(
        default=None,
        description="Link to the article (must be http/https).",
    )


class MagazineNewspaperDetails(BaseModel):
    """Input details for a magazine/newspaper citation.

    Canonical fields:
      - authors?: list[str]
      - title: str
      - publication: str
      - year?: str
      - date?: str         (free-form / ISO per client choice)
      - pages?: str        (validated if present)
      - url?: str          (http/https required if present)
    """

    model_config = ConfigDict(extra="forbid")

    authors: List[str] = Field(default_factory=list, description="List of author names.")
    title: str = Field(..., description="Article title.")
    publication: str = Field(
        ...,
        description="Magazine or newspaper title.",
        validation_alias=AliasChoices("publication", "publication_title"),
    )
    year: Optional[str] = Field(default=None, description="4-digit year if provided.")
    date: Optional[str] = Field(
        default=None,
        description="Publication date (free-form or ISO per client choice).",
    )
    pages: Optional[str] = Field(
        default=None,
        description="Page(s) or range ('12-19', '12–19', '12, 25-27').",
    )
    url: Optional[str] = Field(
        default=None,
        description="Link to the article (must be http/https if provided).",
    )


class EncyclopediaDetails(BaseModel):
    """Input details for an encyclopedia/dictionary citation.

    Canonical fields:
      - title: str                 (entry/article title)
      - encyclopedia_title?: str   (work title)
      - year?: str
      - volume?: str
      - publisher?: str
      - city_of_publication?: str
      - url?: str                  (http/https required if present)
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., description="Article/entry title.")
    encyclopedia_title: Optional[str] = Field(
        default=None,
        description="Name of the encyclopedia/dictionary.",
        validation_alias=AliasChoices("encyclopedia_title", "encyclopedia"),
    )
    year: Optional[str] = Field(default=None, description="4-digit year if provided.")
    volume: Optional[str] = Field(default=None, description="Volume identifier.")
    publisher: Optional[str] = Field(default=None, description="Publisher name.")
    city_of_publication: Optional[str] = Field(
        default=None,
        description="City where the work was published.",
        validation_alias=AliasChoices("city_of_publication", "city"),
    )
    url: Optional[str] = Field(
        default=None,
        description="Link to the entry (must be http/https if provided).",
    )


class WebsiteDetails(BaseModel):
    """Input details for a website/webpage citation.

    Canonical fields:
      - title: str
      - url: str              (http/https)
      - year?: str
      - accessed_date?: str
      - authors?: list[str]
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., description="Page or article title.")
    url: str = Field(..., description="Link to the page (must be http/https).")
    year: Optional[str] = Field(default=None, description="4-digit year if provided.")
    accessed_date: Optional[str] = Field(
        default=None,
        description="Accessed/visited date.",
        validation_alias=AliasChoices("accessed_date", "accessed"),
    )
    authors: List[str] = Field(default_factory=list, description="List of author names.")


# ---------------------------------------------------------------------
# API I/O wrappers
# ---------------------------------------------------------------------
class CitationValidateIn(BaseModel):
    """Payload for /citations/validate (dry-run normalization + checks)."""

    type: SourceType
    details: Dict[str, Any]


class ValidationIssue(BaseModel):
    """Single validation issue item."""

    field: str
    code: str
    message: str


class ValidationResponse(BaseModel):
    """Response for /citations/validate."""

    is_valid: bool
    issues: List[ValidationIssue] = Field(default_factory=list)
    normalized_facts: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------
# CRUD I/O for /citations
# ---------------------------------------------------------------------
class CitationCreateIn(BaseModel):
    """Create a citation (validates + persists normalized facts)."""

    type: SourceType
    details: Dict[str, Any]
    style: Optional[str] = None
    library_id: Optional[int] = None


class CitationUpdateIn(BaseModel):
    """Patch a citation (re-validates details if provided)."""

    details: Optional[Dict[str, Any]] = None
    style: Optional[str] = None
    library_id: Optional[int] = None


class CitationOut(BaseModel):
    """Serialized citation object returned by CRUD endpoints."""

    id: int
    # Accept either `type` or `source_type` from the ORM, but output `type`
    type: SourceType = Field(validation_alias=AliasChoices("type", "source_type"))
    # Accept either `details` or `normalized_facts` from the ORM, but output `details`
    details: Dict[str, Any] = Field(
        validation_alias=AliasChoices("details", "normalized_facts")
    )
    style: Optional[str] = None
    formatted_text: Optional[str] = None
    library_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


__all__ = [
    "SourceType",
    # per-type detail payloads
    "BookDetails",
    "JournalArticleDetails",
    "MagazineNewspaperDetails",
    "EncyclopediaDetails",
    "WebsiteDetails",
    # validation I/O
    "CitationValidateIn",
    "ValidationIssue",
    "ValidationResponse",
    # CRUD I/O
    "CitationCreateIn",
    "CitationUpdateIn",
    "CitationOut",
]
