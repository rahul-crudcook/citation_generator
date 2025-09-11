# app/services/exporters/txt.py
"""TXT exporter for citations.

Provides:
- write_single(citation) -> bytes
- write_bulk(citations, style) -> bytes

Notes:
- Uses existing `formatted_text` if present,
  else formats on the fly (defaults to APA) via the provided FormatService.
- Bulk includes a style-based heading ("References" / "Works Cited") and
  blank-line spacing between entries for readability.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from app.services.exporters.common import (
    coerce_citation_dict,
    ensure_formatted_text,
    heading_for_style,
)


def write_single(
    citation: Any,
    *,
    format_service: Optional[Any] = None,
    default_style: str = "apa",
) -> bytes:
    """Generate TXT bytes for a single citation.

    Args:
        citation: ORM/dict-like citation. Will be normalized internally.
        format_service: FormatService with `.preview(...)` (required when
            `formatted_text` is missing).
        default_style: Style to use if citation lacks `style`.

    Returns:
        UTF-8 encoded bytes with a single trailing newline.

    Raises:
        ValueError: If formatting is required but `format_service` is not provided.
    """
    c = coerce_citation_dict(citation)
    if not c.get("formatted_text"):
        if format_service is None:
            raise ValueError("format_service is required to render formatted_text.")
        ensure_formatted_text(c, format_service, default_style=default_style)

    text = (c.get("formatted_text") or "").strip()
    return (text + "\n").encode("utf-8")


def write_bulk(
    citations: Iterable[Any],
    style: Optional[str],
    *,
    format_service: Optional[Any] = None,
    default_style: str = "apa",
) -> bytes:
    """Generate TXT bytes for a library export.

    Args:
        citations: Iterable of ORM/dict-like citations.
        style: Preferred style for heading and formatting fallback.
        format_service: FormatService for on-the-fly formatting.
        default_style: Default style if neither citation nor `style` provides one.

    Returns:
        UTF-8 encoded bytes with heading, blank lines between citations, and
        trailing newline at the end.
    """
    style_for_heading = style or default_style
    lines = [heading_for_style(style_for_heading), ""]

    for obj in citations:
        c = coerce_citation_dict(obj)
        if not c.get("formatted_text"):
            if format_service is None:
                raise ValueError("format_service is required to render formatted_text.")
            # Use citation style if set; else use bulk `style` or default.
            c.setdefault("style", style or default_style)
            ensure_formatted_text(c, format_service, default_style=default_style)

        text = (c.get("formatted_text") or "").strip()
        if text:
            lines.append(text)

    payload = "\n\n".join(lines) + "\n"
    return payload.encode("utf-8")
