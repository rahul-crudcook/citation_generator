"""
Link/identifier detection and normalization utilities for M4.

Detect whether a string is a DOI, ISBN, or URL and return a canonical form:
- DOI → bare "10.xxxx/..." without a doi.org prefix (case-insensitive match).
- ISBN → digits-only (validate checksum for ISBN-10/13).
- URL → canonicalized http/https URL (trimmed).

All functions are pure and easy to unit test.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

# DOI patterns: practical and permissive for real-world cases.
_DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

# ISBN patterns/utilities
_ISBN_CHARS_RE = re.compile(r"[0-9Xx]+")


def detect_doi(raw: str) -> Optional[str]:
    """Detect and normalize a DOI.

    Returns the DOI in bare form (no https://doi.org/ prefix) if valid.

    Args:
        raw: Raw link or identifier string.

    Returns:
        Bare DOI string or None if not a DOI.
    """
    candidate = (raw or "").strip()
    if not candidate:
        return None
    # Strip any doi.org prefix
    candidate = _DOI_PREFIX_RE.sub("", candidate).strip()
    return candidate if _DOI_RE.match(candidate) else None


def _digits_only_isbn(raw: str) -> str:
    """Keep only digits and 'X'/'x' from an ISBN-like string."""
    return "".join(_ISBN_CHARS_RE.findall(raw))


def _valid_isbn10(isbn10: str) -> bool:
    """Validate ISBN-10 checksum (X allowed as 10)."""
    if len(isbn10) != 10:
        return False
    total = 0
    for idx, ch in enumerate(isbn10, start=1):
        if ch in ("X", "x"):
            val = 10
        elif ch.isdigit():
            val = int(ch)
        else:
            return False
        total += val * (11 - idx)
    return total % 11 == 0


def _valid_isbn13(isbn13: str) -> bool:
    """Validate ISBN-13 checksum."""
    if len(isbn13) != 13 or not isbn13.isdigit():
        return False
    total = 0
    for idx, ch in enumerate(isbn13):
        n = int(ch)
        total += n if idx % 2 == 0 else 3 * n
    return total % 10 == 0


def detect_isbn(raw: str) -> Optional[str]:
    """Detect and normalize an ISBN (digits-only) if valid.

    Accepts ISBN-10/13 with hyphens/spaces and returns digits-only on success.

    Args:
        raw: Raw identifier.

    Returns:
        Digits-only ISBN string or None if not a valid ISBN.
    """
    s = (raw or "").strip()
    if not s:
        return None
    digits = _digits_only_isbn(s)
    if len(digits) == 10 and _valid_isbn10(digits):
        return digits
    if len(digits) == 13 and _valid_isbn13(digits):
        return digits
    return None


def detect_url(raw: str) -> Optional[str]:
    """Detect a valid HTTP/HTTPS URL and return its canonical trimmed form.

    Args:
        raw: Raw input string.

    Returns:
        Canonical URL (trimmed) or None if invalid.
    """
    s = (raw or "").strip()
    try:
        parsed = urlparse(s)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.netloc:
        return None
    return s
