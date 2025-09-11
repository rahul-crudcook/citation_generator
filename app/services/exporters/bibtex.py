# app/services/exporters/bibtex.py
"""BibTeX exporter for citations.

Provides:
- to_bibtex_entry(citation) -> str
- write_single(citation) -> bytes
- write_bulk(citations) -> bytes

Mapping covers common types:
- "book"         -> @book
- "journal_article" -> @article
- "website"/"webpage" -> @misc
- Fallback       -> @misc
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from app.services.exporters.common import (
    bib_key_from,
    coerce_citation_dict,
    format_authors_bibtex,
    normalize_pages,
)


def to_bibtex_entry(citation: Any) -> str:
    """Convert a citation into a BibTeX entry string."""
    c = coerce_citation_dict(citation)
    source_type = (c.get("type") or "").lower()
    facts: Dict[str, Any] = c.get("facts") or {}

    if source_type == "book":
        entry_type = "book"
        fields = _fields_book(facts)
        key = bib_key_from(facts, fallback="book")
    elif source_type == "journal_article":
        entry_type = "article"
        fields = _fields_article(facts)
        key = bib_key_from(facts, fallback="article")
    elif source_type in {"website", "webpage"}:
        entry_type = "misc"
        fields = _fields_website(facts)
        key = bib_key_from(facts, fallback="web")
    else:
        entry_type = "misc"
        fields = _fields_generic(facts)
        key = bib_key_from(facts, fallback="ref")

    lines = [f"@{entry_type}{{{key},"]
    for k, v in fields.items():
        if v:
            lines.append(f"  {k} = {{{v}}},")
    # Remove trailing comma in last field line if present
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)


def write_single(citation: Any) -> bytes:
    """Return BibTeX bytes for a single citation."""
    return (to_bibtex_entry(citation) + "\n").encode("utf-8")


def write_bulk(citations: Iterable[Any]) -> bytes:
    """Return BibTeX bytes for multiple citations (two newlines between)."""
    entries = [to_bibtex_entry(c) for c in citations]
    return ("\n\n".join(entries) + "\n").encode("utf-8")


# ------------------ #
# Field mappers      #
# ------------------ #


def _fields_book(facts: Dict[str, Any]) -> Dict[str, str]:
    return {
        "author": format_authors_bibtex(facts),
        "title": str(facts.get("title") or ""),
        "publisher": str(facts.get("publisher") or ""),
        "year": str(facts.get("year") or ""),
        "address": str(facts.get("city_of_publication") or ""),
        "pages": normalize_pages(str(facts.get("pages") or "")),
    }


def _fields_article(facts: Dict[str, Any]) -> Dict[str, str]:
    return {
        "author": format_authors_bibtex(facts),
        "title": str(facts.get("title") or ""),
        "journal": str(facts.get("journal") or ""),
        "year": str(facts.get("year") or ""),
        "volume": str(facts.get("volume") or ""),
        "number": str(facts.get("issue") or ""),
        "pages": normalize_pages(str(facts.get("pages") or "")),
        "doi": str(facts.get("doi") or ""),
        "url": str(facts.get("url") or ""),
    }


def _fields_website(facts: Dict[str, Any]) -> Dict[str, str]:
    return {
        "author": format_authors_bibtex(facts),
        "title": str(facts.get("work_title") or facts.get("title") or ""),
        "howpublished": str(facts.get("site_title") or "Website"),
        "year": str(facts.get("year") or ""),
        "url": str(facts.get("url") or ""),
        "note": str(facts.get("date_accessed") or ""),
    }


def _fields_generic(facts: Dict[str, Any]) -> Dict[str, str]:
    return {
        "author": format_authors_bibtex(facts),
        "title": str(facts.get("title") or facts.get("work_title") or ""),
        "year": str(facts.get("year") or ""),
        "url": str(facts.get("url") or ""),
        "note": str(facts.get("publisher") or facts.get("site_title") or ""),
    }
