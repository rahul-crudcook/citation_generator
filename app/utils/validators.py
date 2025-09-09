"""Reusable field-level validators (pure functions)."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse


_YEAR_RE = re.compile(r"^\d{4}$")
_PAGES_RE = re.compile(r"^\d+\s*[-–]\s*\d+$")
_DATE_RE = re.compile(r"^\d{4}(-\d{2}){0,2}$")  # YYYY or YYYY-MM or YYYY-MM-DD


def is_year(value: str | None) -> bool:
    """Return True if the value looks like a 4-digit year."""
    return bool(value and _YEAR_RE.fullmatch(value.strip()))


def is_pages_range(value: str | None) -> bool:
    """Return True if the value looks like a page range, e.g., '12-18' or '12–18'."""
    return bool(value and _PAGES_RE.fullmatch(value.strip()))


def is_http_url(value: str | None) -> bool:
    """Return True if the value is an http/https URL (basic check)."""
    if not value:
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_non_empty(value: Optional[str]) -> bool:
    """Return True if string is non-empty after trimming."""
    return bool(value and value.strip())


def is_ymd_date(value: Optional[str]) -> bool:
    """Return True if value is YYYY or YYYY-MM or YYYY-MM-DD (lenient)."""
    return bool(value and _DATE_RE.fullmatch(value.strip()))
