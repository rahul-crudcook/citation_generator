"""Shared enums used across the app (models, schemas, services)."""
from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    """Supported citation source types.

    We intentionally keep member *names* lowercase so they match their string values.
    This keeps API payloads, DB enum values, and comparisons consistent.
    """
    # pylint: disable=invalid-name
    book = "book"
    journal_article = "journal_article"
    magazine_newspaper = "magazine_newspaper"
    encyclopedia = "encyclopedia"
    website = "website"


__all__ = ["SourceType"]
