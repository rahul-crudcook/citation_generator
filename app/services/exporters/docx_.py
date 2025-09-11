# app/services/exporters/docx_.py
"""DOCX exporter for citations (uses python-docx).

Provides:
- write_single(citation) -> BytesIO
- write_bulk(citations, style) -> BytesIO

Rules:
- Bulk adds a style-dependent heading ("References" / "Works Cited").
- Each citation is a paragraph with spacing after.
- No page breaks unless you add them later for very large libraries.
"""

from __future__ import annotations

import io
from typing import Any, Iterable, Optional, Type

from app.services.exporters.common import (
    coerce_citation_dict,
    ensure_formatted_text,
    heading_for_style,
)


def _require_docx() -> Type[Any]:
    """Import python-docx lazily; raise a helpful error if missing.

    Returns:
        The `docx.Document` class.

    Raises:
        RuntimeError: If `python-docx` is not installed.
    """
    try:
        # Lazy import to avoid hard dependency when not exporting.
        from docx import Document  # type: ignore  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # pylint: disable=broad-except
        raise RuntimeError(
            "DOCX export requires 'python-docx'. Install it in your environment."
        ) from exc
    return Document


def write_single(
    citation: Any,
    *,
    format_service: Optional[Any] = None,
    default_style: str = "apa",
) -> io.BytesIO:
    """Create an in-memory DOCX (BytesIO) for a single citation.

    Args:
        citation: ORM/dict-like citation.
        format_service: FormatService for on-demand formatting.
        default_style: Style fallback if none set.

    Returns:
        BytesIO containing a .docx file.
    """
    document_cls = _require_docx()

    c_dict = coerce_citation_dict(citation)
    if not c_dict.get("formatted_text"):
        if format_service is None:
            raise ValueError("format_service is required to render formatted_text.")
        ensure_formatted_text(c_dict, format_service, default_style=default_style)

    doc = document_cls()
    para = doc.add_paragraph((c_dict.get("formatted_text") or "").strip())
    # ~10pt spacing after each entry for visual separation
    para.paragraph_format.space_after = 200

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def write_bulk(
    citations: Iterable[Any],
    style: Optional[str],
    *,
    format_service: Optional[Any] = None,
    default_style: str = "apa",
) -> io.BytesIO:
    """Create an in-memory DOCX (BytesIO) for multiple citations.

    Args:
        citations: Iterable of ORM/dict-like citations.
        style: Style for heading and as default formatting style if needed.
        format_service: FormatService for on-demand formatting.
        default_style: Fallback style when neither citation nor `style` has one.

    Returns:
        BytesIO containing a .docx file with heading and per-citation paragraphs.
    """
    document_cls = _require_docx()

    doc = document_cls()
    # Heading depends on style (APA/Chicago/Turabian/Harvard → "References", MLA → "Works Cited")
    doc.add_heading(heading_for_style(style or default_style), level=1)

    for obj in citations:
        c_dict = coerce_citation_dict(obj)
        if not c_dict.get("formatted_text"):
            if format_service is None:
                raise ValueError("format_service is required to render formatted_text.")
            # Use provided style (for heading) as default if the citation lacks one
            c_dict.setdefault("style", style or default_style)
            ensure_formatted_text(c_dict, format_service, default_style=default_style)

        text = (c_dict.get("formatted_text") or "").strip()
        if text:
            para = doc.add_paragraph(text)
            para.paragraph_format.space_after = 200  # ~10pt

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
