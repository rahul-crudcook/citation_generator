"""Shared enums used across the app (models, schemas, services).

These enums provide canonical string values for source types, fetch sources,
and validation issue codes. They are used consistently across schemas,
database models, and services to avoid magic strings.
"""

from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    """Supported citation source types.

    Member names are lowercase and match their string values. This ensures
    consistency across API payloads, DB enum values, and comparisons.

    Notes:
        Keep these synchronized with Pydantic schemas and formatter rules.
    """

    # pylint: disable=invalid-name
    book = "book"
    journal_article = "journal_article"
    magazine_newspaper = "magazine_newspaper"
    encyclopedia = "encyclopedia"
    website = "website"


class FetchSource(StrEnum):
    """Origin/provider used to auto-fetch citation facts.

    These values identify which external integration produced the facts.
    """

    # pylint: disable=invalid-name
    crossref = "crossref"
    openlibrary = "openlibrary"
    url = "url"
    arxiv = "arxiv"
    pubmed = "pubmed"


class ValidationIssueCode(StrEnum):
    """Standardized validation issue codes for M5 UX helpers.

    These codes are mapped to localized messages via the i18n layer and
    are included in the `/citations/validate` response under `format_issues`.
    Keep this list small and generic—schemas/services can map their specific
    checks to these canonical codes.

    Common patterns:
        - Format issues (shape/content): ``not_4_digits``, ``invalid_url``,
          ``bad_pages_range``
        - Structure issues (person/name): ``name_not_split``
        - Generic sanity checks: ``empty_string``
    """

    # pylint: disable=invalid-name
    not_4_digits = "not_4_digits"
    invalid_url = "invalid_url"
    bad_pages_range = "bad_pages_range"
    name_not_split = "name_not_split"
    empty_string = "empty_string"


__all__ = ["SourceType", "FetchSource", "ValidationIssueCode"]
