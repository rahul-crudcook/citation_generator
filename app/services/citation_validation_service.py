"""Validation & normalization service for citation details by source type."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse

from app.core.enums import SourceType
from app.schemas.citation import (
    BookDetails,
    EncyclopediaDetails,
    JournalArticleDetails,
    MagazineNewspaperDetails,
    ValidationIssue,
    ValidationResponse,
    WebsiteDetails,
)

# Try to use the robust parser (you'll add in M2: app/utils/author.py).
# If it isn't available yet, fall back to a simple splitter here.
try:
    # expected signature: parse_person_name("Last, First M. Jr.") -> dict
    from app.utils.author import parse_person_name as _parse_person_name  # type: ignore
except Exception:  # pylint: disable=broad-except
    def _parse_person_name(name: str) -> Dict[str, str]:  # type: ignore
        """Fallback: Split 'Last, First' or 'First Last' → {first,last} (basic)."""
        s = (name or "").strip()
        if not s:
            return {"first": "", "last": ""}
        if "," in s:
            last, first = [p.strip() for p in s.split(",", 1)]
            return {"first": first, "last": last}
        parts = s.split()
        if len(parts) == 1:
            return {"first": "", "last": parts[0]}
        return {"first": " ".join(parts[:-1]), "last": parts[-1]}


# ----------------------------
# Generic helpers
# ----------------------------
_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "in",
    "nor",
    "of",
    "on",
    "or",
    "per",
    "the",
    "to",
    "vs",
    "via",
}

_PAGES_RE = re.compile(
    r"""^
    \s*
    (?:
        # a page or range
        \d+\s*(?:[-–]\s*\d+)?     # 12 or 12-19 (en dash allowed)
    )
    (?:\s*,\s*
        \d+\s*(?:[-–]\s*\d+)?
    )*                           # optional , 25-27, 30
    \s*$
    """,
    re.VERBOSE,
)


def _require(details: Dict[str, Any], fields: Iterable[str]) -> List[ValidationIssue]:
    """Check required fields exist and are non-empty."""
    issues: List[ValidationIssue] = []
    for fname in fields:
        val = details.get(fname)
        if val is None or (isinstance(val, str) and not val.strip()):
            issues.append(ValidationIssue(field=fname, code="missing", message="Field is required"))
        if isinstance(val, list) and not val:
            issues.append(ValidationIssue(
                field=fname, code="missing", message="At least one value"))
    return issues


def _is_year(value: str) -> bool:
    return isinstance(value, str) and value.isdigit() and len(value) == 4


def _check_year(details: Dict[str, Any], field: str, issues: List[ValidationIssue]) -> None:
    val = details.get(field)
    if val is None or val == "":
        return
    if not _is_year(val):
        issues.append(ValidationIssue(field=field, code="format", message="Year must be 4 digits"))


def _check_url_http_https(
        details: Dict[str, Any], field: str, issues: List[ValidationIssue]) -> None:
    val = (details.get(field) or "").strip()
    if not val:
        return
    parsed = urlparse(val)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        issues.append(ValidationIssue(field=field, code="format", message="URL must be http/https"))


def _check_pages(details: Dict[str, Any], field: str, issues: List[ValidationIssue]) -> None:
    """Validate page/range format like '12-19', '12–19', '12-19, 25-27', or '7, 10'."""
    val = (details.get(field) or "").strip()
    if not val:
        return
    if not _PAGES_RE.match(val):
        issues.append(
            ValidationIssue(
                field=field,
                code="format",
                message="Pages must be numbers/ranges like '12-19' or '12, 25-27'",
            )
        )


def _title_case(text: str) -> str:
    """Light title-case with small-word handling (first/last always capped)."""
    s = (text or "").strip()
    if not s:
        return s
    words = s.split()
    if not words:
        return s

    def cap(word: str) -> str:
        # keep ALLCAPS/acronyms (e.g., "NASA"), else capitalize first letter
        return word if (len(word) > 1 and word.isupper()) else word[:1].upper() + word[1:].lower()

    out: List[str] = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i not in (0, len(words) - 1) and lw in _SMALL_WORDS:
            out.append(lw)
        else:
            out.append(cap(w))
    return " ".join(out)


def _normalize_authors(authors: Any) -> List[Dict[str, Any]]:
    """Normalize authors list of strings → list of dicts via parser."""
    if not isinstance(authors, list):
        return []
    norm: List[Dict[str, Any]] = []
    for a in authors:
        if not isinstance(a, str):
            continue
        parsed = _parse_person_name(a)
        # Guarantee keys for downstream formatting
        norm.append(
            {
                "first": (parsed.get("first") or "").strip(),
                "middle": (parsed.get("middle") or "").strip() if isinstance(parsed, dict) else "",
                "last": (parsed.get("last") or "").strip(),
                "suffix": (parsed.get("suffix") or "").strip()
                if isinstance(parsed, dict)
                else "",
            }
        )
    return norm


# ----------------------------
# Service
# ----------------------------
class CitationValidationService:
    """Encapsulates per-type validation + normalization logic."""

    _LABELS: Dict[SourceType, str] = {
        SourceType.book: "Book",
        SourceType.journal_article: "Journal Article",
        SourceType.magazine_newspaper: "Magazine / Newspaper",
        SourceType.encyclopedia: "Encyclopedia",
        SourceType.website: "Website",
    }

    def supported_types(self) -> List[Tuple[str, str]]:
        """Return (value, label) pairs for UI dropdowns."""
        return [(t.value, self._LABELS[t]) for t in SourceType]

    def validate(self, source_type: SourceType | str, details: Dict[
        str, Any]) -> ValidationResponse:
        """Validate 'details' for a given source_type and produce normalized facts."""
        st = SourceType(source_type)
        issues: List[ValidationIssue] = []
        normalized: Dict[str, Any] = {"type": st.value}

        if st == SourceType.book:
            issues, normalized = self._validate_book(details)
        elif st == SourceType.journal_article:
            issues, normalized = self._validate_journal(details)
        elif st == SourceType.magazine_newspaper:
            issues, normalized = self._validate_magazine(details)
        elif st == SourceType.encyclopedia:
            issues, normalized = self._validate_encyclopedia(details)
        elif st == SourceType.website:
            issues, normalized = self._validate_website(details)

        return ValidationResponse(is_valid=not issues, issues=issues, normalized_facts=normalized)

    # ---------- Per-type implementations ----------

    def _validate_book(self, raw: Dict[str, Any]) -> Tuple[List[ValidationIssue], Dict[str, Any]]:
        issues = _require(raw, ("authors", "title", "publisher", "year"))
        _check_year(raw, "year", issues)
        _ = BookDetails.model_validate(raw)  # shape/sanity

        authors = raw.get("authors") or []
        normalized_authors = _normalize_authors(authors)

        normalized = {
            "type": SourceType.book.value,
            "authors": normalized_authors,
            "title": _title_case(raw.get("title") or ""),
            "city_of_publication": (raw.get("city_of_publication") or "").strip() or None,
            "publisher": (raw.get("publisher") or "").strip(),
            "year": (raw.get("year") or "").strip(),
        }
        return issues, normalized

    def _validate_journal(
        self, raw: Dict[str, Any]
    ) -> Tuple[List[ValidationIssue], Dict[str, Any]]:
        issues = _require(raw, ("authors", "title", "journal", "year"))
        _check_year(raw, "year", issues)
        _ = JournalArticleDetails.model_validate(raw)

        authors = raw.get("authors") or []
        normalized_authors = _normalize_authors(authors)

        normalized = {
            "type": SourceType.journal_article.value,
            "authors": normalized_authors,
            "title": _title_case(raw.get("title") or ""),
            "journal": (raw.get("journal") or "").strip(),
            "year": (raw.get("year") or "").strip(),
            "volume": (raw.get("volume") or "").strip() or None,
            "issue": (raw.get("issue") or "").strip() or None,
            "pages": (raw.get("pages") or "").strip() or None,
            "doi": (raw.get("doi") or "").strip() or None,
            "url": (raw.get("url") or "").strip() or None,
        }
        if normalized["pages"]:
            _check_pages(normalized, "pages", issues)
        if normalized["url"]:
            _check_url_http_https(normalized, "url", issues)
        return issues, normalized

    def _validate_magazine(
        self, raw: Dict[str, Any]
    ) -> Tuple[List[ValidationIssue], Dict[str, Any]]:
        issues = _require(raw, ("title", "publication"))
        if raw.get("year"):
            _check_year(raw, "year", issues)
        _ = MagazineNewspaperDetails.model_validate(raw)

        authors = raw.get("authors") or []
        normalized_authors = _normalize_authors(authors)

        normalized = {
            "type": SourceType.magazine_newspaper.value,
            "authors": normalized_authors,
            "title": _title_case(raw.get("title") or ""),
            "publication": (raw.get("publication") or "").strip(),
            "year": (raw.get("year") or "").strip() or None,
            "date": (raw.get("date") or "").strip() or None,
            "pages": (raw.get("pages") or "").strip() or None,
            "url": (raw.get("url") or "").strip() or None,
        }
        if normalized["pages"]:
            _check_pages(normalized, "pages", issues)
        if normalized["url"]:
            _check_url_http_https(normalized, "url", issues)
        return issues, normalized

    def _validate_encyclopedia(
        self, raw: Dict[str, Any]
    ) -> Tuple[List[ValidationIssue], Dict[str, Any]]:
        issues = _require(raw, ("title",))
        if raw.get("year"):
            _check_year(raw, "year", issues)
        _ = EncyclopediaDetails.model_validate(raw)

        normalized = {
            "type": SourceType.encyclopedia.value,
            "title": _title_case(raw.get("title") or ""),
            "encyclopedia_title": (raw.get("encyclopedia_title") or "").strip() or None,
            "year": (raw.get("year") or "").strip() or None,
            "volume": (raw.get("volume") or "").strip() or None,
            "publisher": (raw.get("publisher") or "").strip() or None,
            "city_of_publication": (raw.get("city_of_publication") or "").strip() or None,
            "url": (raw.get("url") or "").strip() or None,
        }
        if normalized["url"]:
            _check_url_http_https(normalized, "url", issues)
        return issues, normalized

    def _validate_website(
        self, raw: Dict[str, Any]
    ) -> Tuple[List[ValidationIssue], Dict[str, Any]]:
        issues = _require(raw, ("title", "url"))
        if raw.get("year"):
            _check_year(raw, "year", issues)
        _ = WebsiteDetails.model_validate(raw)

        authors = raw.get("authors") or []
        normalized_authors = _normalize_authors(authors)

        normalized = {
            "type": SourceType.website.value,
            "authors": normalized_authors,
            "title": _title_case(raw.get("title") or ""),
            "url": (raw.get("url") or "").strip(),
            "year": (raw.get("year") or "").strip() or None,
            "accessed_date": (raw.get("accessed_date") or "").strip() or None,
        }
        _check_url_http_https(normalized, "url", issues)
        return issues, normalized


# Singleton instance for DI-less usage
citation_validation_service = CitationValidationService()
