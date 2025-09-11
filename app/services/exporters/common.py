# app/services/exporters/common.py
"""Common helpers for export writers (TXT, DOCX, BibTeX, JSON).

Centralized utilities:
- Coercing incoming objects to a normalized citation dict
- Filename suggestions
- Style-based headings
- Ensuring formatted_text via FormatService if missing
- BibTeX-safe helpers (ASCII, pages normalization, author formatting)

Normalized citation dict shape expected by writers:
{
    "id": int | None,
    "type": str,
    "facts": dict,
    "style": str | None,
    "formatted_text": str | None
}
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional


def coerce_citation_dict(obj: Any) -> Dict[str, Any]:
    """Coerce various object shapes (ORM/dataclass/dict) into a normalized dict.

    Tries common attribute names first, then falls back to mapping-like access.
    Missing keys default to None or {}.

    Args:
        obj: ORM entity, dataclass, or dict-like citation.

    Returns:
        Normalized citation dictionary.
    """
    if isinstance(obj, dict):
        return {
            "id": obj.get("id"),
            "type": obj.get("type") or obj.get("source_type") or "",
            "facts": obj.get("facts") or obj.get("facts_jsonb") or {},
            "style": obj.get("style"),
            "formatted_text": obj.get("formatted_text"),
        }

    # Attribute-based access (ORM/dataclass)
    type_val = getattr(obj, "type", None) or getattr(obj, "source_type", "")
    facts_val = getattr(obj, "facts_jsonb", None) or getattr(obj, "facts", None) or {}
    return {
        "id": getattr(obj, "id", None),
        "type": str(type_val or ""),
        "facts": dict(facts_val) if isinstance(facts_val, dict) else {},
        "style": getattr(obj, "style", None),
        "formatted_text": getattr(obj, "formatted_text", None),
    }


def heading_for_style(style: Optional[str]) -> str:
    """Return the bulk-export heading for a given style.

    MLA → "Works Cited", others → "References".
    """
    if not style:
        return "References"
    if str(style).lower() == "mla":
        return "Works Cited"
    return "References"


def ensure_formatted_text(
    citation: Dict[str, Any],
    format_service: Any,
    *,
    default_style: str = "apa",
) -> str:
    """Ensure `formatted_text` exists on a normalized citation dict.

    If missing, formats via `format_service.preview(style, source_type, facts)`.

    Args:
        citation: Normalized citation dict (will be mutated with formatted_text).
        format_service: An object exposing `.preview(style, source_type, facts)`.
        default_style: Style to use when citation['style'] is absent.

    Returns:
        The formatted string.

    Raises:
        ValueError: If citation lacks a valid 'type' or 'facts'.
    """
    if citation.get("formatted_text"):
        return str(citation["formatted_text"])

    source_type = str(citation.get("type") or "").strip()
    facts = citation.get("facts") or {}
    if not source_type or not isinstance(facts, dict):
        raise ValueError("Citation must include 'type' (str) and 'facts' (dict).")

    style = str(citation.get("style") or default_style)
    rendered = format_service.preview(style=style, source_type=source_type, facts=facts)
    text = rendered["formatted"] if isinstance(rendered, dict) else str(rendered)
    citation["formatted_text"] = text
    return text


# ------------------------ #
# Filename helper routines #
# ------------------------ #


def suggest_filename_single(citation: Dict[str, Any], ext: str) -> str:
    """Suggest a filename for single-citation export."""
    facts = citation.get("facts") or {}
    author = _first_author_lastname(facts) or "citation"
    year = str(facts.get("year") or "n.d.")
    short = _short_title(facts.get("title") or facts.get("work_title") or "untitled")
    base = f"{_safe_ascii(author)}_{_safe_ascii(year)}_{_safe_ascii(short)}".strip("_")
    return f"{base}.{ext}"


def suggest_filename_library(library_name: str, ext: str) -> str:
    """Suggest a filename for library-level export."""
    base = _safe_ascii(library_name or "library")
    return f"{base}.{ext}"


# ---------------------- #
# BibTeX helper routines #
# ---------------------- #


def normalize_pages(pages: str) -> str:
    """Normalize pages to BibTeX-friendly 'start--end' (double hyphen) if range."""
    if not pages:
        return ""
    s = str(pages).strip()
    # Replace en/em dashes with double hyphen for BibTeX
    s = s.replace("–", "--").replace("—", "--")
    # Single hyphen ranges → double
    s = re.sub(r"(\d)-(\d)", r"\1--\2", s)
    return s


def format_authors_bibtex(facts: Dict[str, Any]) -> str:
    """Return authors in 'Last, First and Last, First' BibTeX format."""
    authors = facts.get("authors") or []
    parts = []
    for a in authors:
        if isinstance(a, dict):
            first = str(a.get("first") or "").strip()
            last = str(a.get("last") or "").strip()
            if last and first:
                parts.append(f"{last}, {first}")
            elif last:
                parts.append(last)
            elif first:
                parts.append(first)
        elif isinstance(a, str):
            parts.append(a)
    return " and ".join(parts)


def bib_key_from(facts: Dict[str, Any], fallback: str) -> str:
    """Generate a simple BibTeX key like 'Doe2025Practical' (ASCII only)."""
    last = _first_author_lastname(facts) or fallback
    year = str(facts.get("year") or "n.d.")
    title_first = ""
    title = str(facts.get("title") or facts.get("work_title") or "").strip()
    if title:
        title_first = title.split()[0]
    key = f"{last}{year}{title_first}"
    return _safe_ascii(key).replace("-", "")


# ---------------- #
# Utility routines #
# ---------------- #


def _first_author_lastname(facts: Dict[str, Any]) -> Optional[str]:
    """Extract first author's last name from facts in common shapes."""
    authors = facts.get("authors") or []
    if not isinstance(authors, list) or not authors:
        return None

    first = authors[0]
    if isinstance(first, dict):
        return (first.get("last") or None) and str(first.get("last"))
    if isinstance(first, str):
        if "," in first:
            return first.split(",", 1)[0].strip()
        parts = first.split()
        return parts[-1] if parts else None
    return None


def _short_title(title: str, max_len: int = 24) -> str:
    """Shorten a title for filenames; trims and adds ellipsis if necessary."""
    t = str(title or "").strip()
    if not t:
        return "untitled"
    t = re.sub(r"\s+", " ", t)
    if len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return t


def _safe_ascii(s: str) -> str:
    """ASCII-safe, filename-friendly string (lowercase, hyphenated)."""
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-") or "file"
