"""Shared enums used across the app (models, schemas, services).

These enums provide canonical string values for source types and fetch sources.
They are used consistently across schemas, database models, and services to
avoid magic strings.
"""

from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    """Supported citation source types.

    Member names are lowercase and match their string values. This ensures
    consistency across API payloads, DB enum values, and comparisons.
    """

    # pylint: disable=invalid-name
    book = "book"
    journal_article = "journal_article"
    magazine_newspaper = "magazine_newspaper"
    encyclopedia = "encyclopedia"
    website = "website"


class FetchSource(StrEnum):
    """Origin/provider used to auto-fetch citation facts."""

    # pylint: disable=invalid-name
    crossref = "crossref"
    openlibrary = "openlibrary"
    url = "url"
    arxiv = "arxiv"
    pubmed = "pubmed"


__all__ = ["SourceType", "FetchSource"]
