"""Pydantic schemas for the formatting preview API (M6).

Endpoints that use these schemas:
- POST /format/preview → { style, source_type, facts } ⇒ { formatted }

Design
------
- Strict input (extra fields forbidden) so clients catch mistakes early.
- Uses shared enums: `Style` and `SourceType` to keep contracts consistent.
- Facts are accepted as a generic mapping; style-specific formatters
  will validate required keys at render time.
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import SourceType, Style


class FormatPreviewIn(BaseModel):
    """Request payload for `/format/preview`.

    Attributes:
        style: Citation style (APA, MLA, Chicago, Turabian, Harvard).
        source_type: Citation source type (book, journal_article, etc.).
        facts: Normalized facts payload used by the formatter.
    """

    model_config = ConfigDict(extra="forbid")

    style: Style = Field(..., description="Citation style to render.")
    source_type: SourceType = Field(..., description="Kind of source to format.")
    facts: Dict[str, Any] = Field(
        ...,
        description=(
            "Normalized facts for the source (e.g., authors, title, journal, year, pages). "
            "Exact keys depend on source_type and style templates."
        ),
    )


class FormatPreviewOut(BaseModel):
    """Response payload for `/format/preview`."""

    formatted: str = Field(..., description="The formatted citation string.")


__all__ = ["FormatPreviewIn", "FormatPreviewOut", "Style", "SourceType"]
