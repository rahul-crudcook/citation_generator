"""Validation helpers service for citation details (M5).

This module implements a focused, testable OOP service that powers the
server-driven validation UX. It does not touch I/O or the database and can be
used from both:
- POST /citations/validate (dry-run)
- Citation create/update flows (validate → normalize → persist)

Outputs are designed to map directly onto the extended ValidationResponse
schema for M5:

{
    "is_valid": bool,
    "missing_required": ["year", "author"],
    "format_issues": [{"field": "year", "issue": "not_4_digits", "message": "..."}],
    "suggestions": [{"field": "pages", "example": "12–18", "note": "..."}],
    "normalized_facts": {...}
}

Notes
-----
- This service aims to be schema-agnostic and minimally opinionated. If your
  Pydantic schemas evolve (e.g., renames), update REQUIRED_FIELDS and simple
  format rules below.
- It’s safe to inject a message lookup (i18n) for localization; fallback
  English messages are included by default.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple

from app.core.enums import SourceType


class ValidationService:
    """Service that validates, normalizes, and suggests fixes for citation details."""

    # ---------------------------------------------------------------------
    # Required fields per source type (aligned with current Pydantic schemas)
    # ---------------------------------------------------------------------
    # NOTE:
    # - Keep this minimal and aligned with your *input* schemas in
    #   app/schemas/citation.py. Do not require optional fields here.
    REQUIRED_FIELDS: Mapping[SourceType, Tuple[str, ...]] = {
        SourceType.book: ("authors", "title", "publisher", "year"),
        SourceType.journal_article: ("authors", "title", "journal", "year"),
        SourceType.magazine_newspaper: ("title", "publication"),
        SourceType.encyclopedia: ("title",),
        SourceType.website: ("title", "url"),
    }

    # ----------------------------
    # Default message catalog (i18n-friendly)
    # ----------------------------
    DEFAULT_MESSAGES: Mapping[str, str] = {
        "not_4_digits": "Year must be four digits (e.g., 2021).",
        "invalid_url": "URL must start with http:// or https://.",
        "bad_pages_range": "Use page ranges like 12–18 or lists like 12, 25–27.",
        "name_not_split": "Provide author names as separate first/last fields.",
        "empty_string": "This field cannot be empty.",
    }

    # Pages examples for suggestions
    PAGES_EXAMPLES: Tuple[str, ...] = ("12–18", "12-18", "12, 25–27")

    # Regexes (compiled once)
    _RE_YEAR = re.compile(r"^\d{4}$")
    _RE_HTTP_URL = re.compile(r"^https?://", re.IGNORECASE)
    _RE_PAGES = re.compile(
        r"""^
        \d+                              # 12
        (?:[–-]\d+)?                     # 12–18
        (?:                              # , 12 or , 25–27 ...
            \s*,\s*\d+(?:[–-]\d+)?
        )*
        $""",
        re.VERBOSE,
    )

    def __init__(self, messages: Optional[Mapping[str, str]] = None) -> None:
        """Initialize the service.

        Args:
            messages: Optional override message catalog (for i18n). If provided,
                      it is used as a shallow overlay on DEFAULT_MESSAGES.
        """
        self._messages: Dict[str, str] = dict(self.DEFAULT_MESSAGES)
        if messages:
            self._messages.update(messages)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def validate_with_helpers(
        self, source_type: SourceType, details: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Validate and normalize details for a given source type.

        Args:
            source_type: The citation source type (book, journal_article, ...).
            details: Raw incoming details (usually request payload).

        Returns:
            A dict conforming to the M5 ValidationResponse payload:
            {
                "is_valid": bool,
                "missing_required": list[str],
                "format_issues": list[dict],
                "suggestions": list[dict],
                "normalized_facts": dict[str, Any],
            }
        """
        # 1) Normalize (trim strings, standardize shape)
        normalized = self._normalize(deepcopy(details))

        # 2) Compute missing required
        missing_required = self._find_missing_required(source_type, normalized)

        # 3) Format issues
        format_issues: List[Dict[str, str]] = []
        format_issues.extend(self._check_year(normalized))
        format_issues.extend(self._check_url(normalized))
        format_issues.extend(self._check_pages(normalized))
        format_issues.extend(self._check_authors(normalized))

        # 4) Suggestions (only when something is missing or malformed)
        suggestions: List[Dict[str, str]] = []
        suggestions.extend(self._suggest_pages(normalized))
        suggestions.extend(self._suggest_authors(normalized))

        is_valid = not missing_required and not format_issues

        return {
            "is_valid": is_valid,
            "missing_required": missing_required,
            "format_issues": format_issues,
            "suggestions": suggestions,
            "normalized_facts": normalized,
        }

    # ---------------------------------------------------------------------
    # Normalization helpers
    # ---------------------------------------------------------------------
    def _normalize(self, data: MutableMapping[str, Any]) -> Dict[str, Any]:
        """Return a normalized copy of details.

        - Trim strings.
        - Normalize authors person list (if present).
        """
        for key, value in list(data.items()):
            data[key] = self._trim_if_str(value)

        # Normalize authors: accept list of dicts or a single string
        if "authors" in data:
            data["authors"] = self._normalize_authors(data.get("authors"))

        return dict(data)

    @staticmethod
    def _trim_if_str(value: Any) -> Any:
        """Trim strings; leave other types as-is."""
        if isinstance(value, str):
            return value.strip()
        return value

    def _normalize_authors(self, authors_val: Any) -> List[Dict[str, str]]:
        """Normalize `authors` into a list of {first, last} dicts when possible.

        Accepts:
          - List[Dict]: already split, pass through (trimmed).
          - List[str]: best-effort split on 'Last, First' or space.
          - str: a single author string → best-effort split.
          - Anything else → empty list.

        Note:
            This function does *not* raise; it normalizes leniently.
        """
        if authors_val is None:
            return []

        result: List[Dict[str, str]] = []

        if isinstance(authors_val, list):
            for item in authors_val:
                if isinstance(item, dict):
                    first = self._trim_if_str(item.get("first", "")) or ""
                    last = self._trim_if_str(item.get("last", "")) or ""
                    if first or last:
                        result.append({"first": first, "last": last})
                elif isinstance(item, str):
                    result.append(self._split_author_string(item))
            return result

        if isinstance(authors_val, str):
            # Single string → best-effort split
            return [self._split_author_string(authors_val)]

        return []

    @staticmethod
    def _split_author_string(s: str) -> Dict[str, str]:
        """Split an author string into {first, last} using simple heuristics.

        Supported:
            - 'Last, First Middle' → {'first': 'First Middle', 'last': 'Last'}
            - 'First Middle Last'  → {'first': 'First Middle', 'last': 'Last'}
            - 'SingleName'         → {'first': '', 'last': 'SingleName'}
        """
        s = (s or "").strip()
        if not s:
            return {"first": "", "last": ""}

        if "," in s:
            # 'Last, First ...'
            last, first = [part.strip() for part in s.split(",", 1)]
            return {"first": first, "last": last}

        parts = s.split()
        if len(parts) == 1:
            return {"first": "", "last": parts[0]}
        return {"first": " ".join(parts[:-1]), "last": parts[-1]}

    # ---------------------------------------------------------------------
    # Required-field checks
    # ---------------------------------------------------------------------
    def _find_missing_required(
        self, source_type: SourceType, normalized: Mapping[str, Any]
    ) -> List[str]:
        """Return names of fields that are required but missing/empty."""
        required = self.REQUIRED_FIELDS.get(source_type, tuple())
        missing: List[str] = []
        for field in required:
            val = normalized.get(field)
            if self._is_missing(val):
                missing.append(field)
        return missing

    @staticmethod
    def _is_missing(val: Any) -> bool:
        """True if a value is considered missing for required-field purposes."""
        if val is None:
            return True
        if isinstance(val, str) and not val.strip():
            return True
        if isinstance(val, (list, tuple, set)) and len(val) == 0:
            return True
        return False

    # ---------------------------------------------------------------------
    # Format checks → format_issues
    # ---------------------------------------------------------------------
    def _check_year(self, normalized: Mapping[str, Any]) -> List[Dict[str, str]]:
        """Validate that 'year' is a 4-digit value when present."""
        issues: List[Dict[str, str]] = []
        year = normalized.get("year")
        if year is None:
            return issues
        # Accept strings or ints; stringify for regex
        year_str = str(year).strip()
        if not self._RE_YEAR.match(year_str):
            issues.append(
                {"field": "year", "issue": "not_4_digits", "message": self._msg("not_4_digits")}
            )
        return issues

    def _check_url(self, normalized: Mapping[str, Any]) -> List[Dict[str, str]]:
        """Validate that 'url' starts with http:// or https:// when present."""
        issues: List[Dict[str, str]] = []
        url = normalized.get("url")
        if url is None:
            return issues
        url_str = str(url).strip()
        if url_str and not self._RE_HTTP_URL.match(url_str):
            issues.append(
                {"field": "url", "issue": "invalid_url", "message": self._msg("invalid_url")}
            )
        return issues

    def _check_pages(self, normalized: Mapping[str, Any]) -> List[Dict[str, str]]:
        """Validate page ranges/lists if provided (e.g., '12–18', '12, 25–27')."""
        issues: List[Dict[str, str]] = []
        pages = normalized.get("pages")
        if pages is None:
            return issues
        pages_str = str(pages).strip()
        if pages_str and not self._RE_PAGES.match(pages_str):
            issues.append(
                {
                    "field": "pages",
                    "issue": "bad_pages_range",
                    "message": self._msg("bad_pages_range"),
                }
            )
        return issues

    def _check_authors(self, normalized: Mapping[str, Any]) -> List[Dict[str, str]]:
        """Detect author-name structure issues (e.g., not split into first/last)."""
        issues: List[Dict[str, str]] = []
        authors = normalized.get("authors")
        if not isinstance(authors, list) or not authors:
            return issues

        for idx, person in enumerate(authors):
            if not isinstance(person, dict):
                issues.append(
                    {
                        "field": f"authors[{idx}]",
                        "issue": "name_not_split",
                        "message": self._msg("name_not_split"),
                    }
                )
                continue
            first = str(person.get("first", "")).strip()
            last = str(person.get("last", "")).strip()
            # If both empty, or only one giant token suspected as unsplit name:
            if not first and not last:
                issues.append(
                    {
                        "field": f"authors[{idx}]",
                        "issue": "name_not_split",
                        "message": self._msg("name_not_split"),
                    }
                )
        return issues

    # ---------------------------------------------------------------------
    # Suggestions → suggestions
    # ---------------------------------------------------------------------
    def _suggest_pages(self, normalized: Mapping[str, Any]) -> List[Dict[str, str]]:
        """Suggest examples for pages when missing or malformed."""
        suggestions: List[Dict[str, str]] = []
        pages = normalized.get("pages")
        if pages is None or (isinstance(pages, str) and not pages.strip()):
            suggestions.append(
                {
                    "field": "pages",
                    "example": self.PAGES_EXAMPLES[0],
                    "note": self._msg("bad_pages_range"),
                }
            )
            return suggestions

        pages_str = str(pages).strip()
        if pages_str and not self._RE_PAGES.match(pages_str):
            # Provide a better example if user attempted something invalid
            suggestions.append(
                {
                    "field": "pages",
                    "example": self.PAGES_EXAMPLES[0],
                    "note": self._msg("bad_pages_range"),
                }
            )
        return suggestions

    def _suggest_authors(self, normalized: Mapping[str, Any]) -> List[Dict[str, str]]:
        """Suggest author formatting when names are not split."""
        suggestions: List[Dict[str, str]] = []
        authors = normalized.get("authors")
        if not isinstance(authors, list) or not authors:
            # If authors are required for this type, a suggestion may help.
            suggestions.append(
                {
                    "field": "authors",
                    "example": "Last, First M.",
                    "note": self._msg("name_not_split"),
                }
            )
            return suggestions

        # If any author is missing first/last, emit one suggestion for the list.
        for person in authors:
            if not isinstance(person, dict):
                suggestions.append(
                    {
                        "field": "authors",
                        "example": "Last, First M.",
                        "note": self._msg("name_not_split"),
                    }
                )
                break
            first = str(person.get("first", "")).strip()
            last = str(person.get("last", "")).strip()
            if not first or not last:
                suggestions.append(
                    {
                        "field": "authors",
                        "example": "Last, First M.",
                        "note": self._msg("name_not_split"),
                    }
                )
                break
        return suggestions

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------
    def _msg(self, code: str) -> str:
        """Lookup a message by code from the merged catalog."""
        return self._messages.get(code, code)
