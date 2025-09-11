# app/services/format_service.py
# pylint: disable=W0718
"""Formatting service for rendering citation strings (M6).

This module exposes a single orchestration class, :class:`FormatService`,
which routes formatting requests to style-specific formatters. It is designed
to be testable and DI-friendly (instantiate once and reuse via a FastAPI
dependency).

Public API
----------
    FormatService.preview(style, source_type, facts) -> str
    FormatService.format_preview(style, source_type, facts) -> str   # alias

Exports (M7)
------------
- Exporters/routes should prefer existing `formatted_text`. If absent,
  they can call `FormatService.preview(...)` (or `format_preview(...)`)
  to render deterministically before writing TXT/DOCX/Bib.

Resolution
----------
- Style-specific formatters are resolved lazily via `_get_formatter`.
- If a concrete formatter module is not available yet, the service
  can fall back to a minimal APA implementation sufficient for smoke tests.
- Other styles raise a helpful ValueError until their modules are added.

Conventions
-----------
- Input `facts` are expected to be *normalized* (as produced by M5).
- Output is a plain string suitable for TXT/DOCX placement; italics are not
  represented here (rendering engine can style them if desired).

Extensibility
-------------
- Implement style modules under `app/services/formatters/` that export a
  `get_formatter()` function returning an object with per-type methods:
      format_book(facts) -> str
      format_journal_article(facts) -> str
      format_magazine_newspaper(facts) -> str
      format_encyclopedia(facts) -> str
      format_website(facts) -> str
- The minimal APA fallback in this file illustrates the interface.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Mapping, Protocol, Tuple, runtime_checkable

from app.core.enums import SourceType, Style


# -----------------------------------------------------------------------------
# Protocol for formatter implementations (duck-typed)
# -----------------------------------------------------------------------------
@runtime_checkable
class FormatterProtocol(Protocol):
    """Contract for style-specific formatter implementations."""

    def format_book(self, facts: Mapping[str, Any]) -> str:
        """Format a book citation given normalized facts."""

    def format_journal_article(self, facts: Mapping[str, Any]) -> str:
        """Format a journal article citation given normalized facts."""

    def format_magazine_newspaper(self, facts: Mapping[str, Any]) -> str:
        """Format a magazine/newspaper citation given normalized facts."""

    def format_encyclopedia(self, facts: Mapping[str, Any]) -> str:
        """Format an encyclopedia/dictionary citation given normalized facts."""

    def format_website(self, facts: Mapping[str, Any]) -> str:
        """Format a website/webpage citation given normalized facts."""


# -----------------------------------------------------------------------------
# Helper utilities (local, formatting-focused)
# -----------------------------------------------------------------------------
_STOP_WORDS: set[str] = {
    "a",
    "an",
    "the",
    "and",
    "but",
    "or",
    "nor",
    "for",
    "so",
    "yet",
    "as",
    "at",
    "by",
    "in",
    "of",
    "on",
    "per",
    "to",
    "via",
    "with",
    "from",
    "into",
    "over",
    "under",
    "off",
}


def _trim(value: Any) -> Any:
    """Trim strings; return other types unchanged."""
    if isinstance(value, str):
        return value.strip()
    return value


def _sentence_case(text: str) -> str:
    """Return a sentence-cased version of ``text`` (simple/deterministic)."""
    s = (text or "").strip()
    if not s:
        return ""
    s = s.lower()
    return s[0].upper() + s[1:]


def _title_case(text: str) -> str:
    """Return title case with a minimal stop-word list (deterministic)."""
    s = (text or "").strip()
    if not s:
        return ""
    words = s.split()
    out: list[str] = []
    for idx, w in enumerate(words):
        lower = w.lower()
        if idx not in (0, len(words) - 1) and lower in _STOP_WORDS:
            out.append(lower)
        else:
            out.append(lower.capitalize())
    return " ".join(out)


def _split_author(author: str) -> Tuple[str, str]:
    """Split an author string into (first, last) using simple heuristics."""
    s = (author or "").strip()
    if not s:
        return "", ""
    if "," in s:
        last, first = [p.strip() for p in s.split(",", 1)]
        return first, last
    parts = s.split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _initials(name: str) -> str:
    """Convert 'First Middle' -> 'F. M.' (no trailing space)."""
    parts = [p for p in name.split() if p]
    inits = [f"{p[0].upper()}." for p in parts]
    return " ".join(inits)


def _render_author_apa(author: Mapping[str, Any] | str) -> str:
    """Render one author in APA short form: 'Last, F. M.'."""
    first = ""
    last = ""
    if isinstance(author, dict):
        first = _trim(author.get("first"))
        last = _trim(author.get("last"))
    elif isinstance(author, str):
        first, last = _split_author(author)
    if not first and not last:
        return ""
    if not last:
        return _initials(str(first))
    if not first:
        return str(last)
    return f"{last}, {_initials(str(first))}"


def _render_authors_apa(authors: Any) -> str:
    """Render a list of authors with simplified APA punctuation rules."""
    if not authors:
        return ""
    rendered: list[str] = []

    if isinstance(authors, list):
        for a in authors:
            piece = _render_author_apa(a)
            if piece:
                rendered.append(piece)
    elif isinstance(authors, str):
        piece = _render_author_apa(authors)
        if piece:
            rendered.append(piece)

    n = len(rendered)
    if n == 0:
        return ""
    if n == 1:
        return rendered[0]
    if n == 2:
        return f"{rendered[0]}, & {rendered[1]}"
    return ", ".join(rendered[:-1]) + f", & {rendered[-1]}"


# -----------------------------------------------------------------------------
# Minimal APA formatter (fallback) — covers book, journal, website
# -----------------------------------------------------------------------------
class _APAFormatterFallback:
    """Small APA formatter sufficient for preview smoke tests.

    Implementations here are intentionally minimal and deterministic. Full
    stylistic parity (italics, DOIs vs URLs precedence, etc.) belongs in
    dedicated style modules in `app.services.formatters`.
    """

    # pylint: disable=unused-argument
    def format_magazine_newspaper(self, facts: Mapping[str, Any]) -> str:
        """Format a magazine/newspaper reference (not yet implemented)."""
        raise NotImplementedError("APA magazine/newspaper not implemented yet.")

    def format_encyclopedia(self, facts: Mapping[str, Any]) -> str:
        """Format an encyclopedia reference (not yet implemented)."""
        raise NotImplementedError("APA encyclopedia not implemented yet.")

    def format_website(self, facts: Mapping[str, Any]) -> str:
        """Format a website reference using a simplified APA layout."""
        # Author(s). (Year). Title. URL
        authors = _render_authors_apa(facts.get("authors"))
        year = str(facts.get("year") or "").strip()
        title = _sentence_case(str(facts.get("title") or ""))
        url = str(facts.get("url") or "").strip()

        parts = []
        if authors:
            parts.append(f"{authors}.")
        if year:
            parts.append(f"({year}).")
        if title:
            parts.append(f"{title}.")
        if url:
            parts.append(url)
        return " ".join(parts).strip()

    def format_book(self, facts: Mapping[str, Any]) -> str:
        """Format a book reference using a simplified APA layout."""
        # Author(s). (Year). Title. Publisher.
        authors = _render_authors_apa(facts.get("authors"))
        year = str(facts.get("year") or "").strip()
        title = _sentence_case(str(facts.get("title") or ""))
        publisher = str(facts.get("publisher") or "").strip()

        parts = []
        if authors:
            parts.append(f"{authors}.")
        if year:
            parts.append(f"({year}).")
        if title:
            parts.append(f"{title}.")
        if publisher:
            parts.append(f"{publisher}.")
        return " ".join(parts).strip()

    def format_journal_article(self, facts: Mapping[str, Any]) -> str:
        """Format a journal article reference using a simplified APA layout."""
        # Author(s). (Year). Title. Journal, volume(issue), pages. DOI/URL
        authors = _render_authors_apa(facts.get("authors"))
        year = str(facts.get("year") or "").strip()
        title = _sentence_case(str(facts.get("title") or ""))
        journal = _title_case(str(facts.get("journal") or ""))
        volume = str(facts.get("volume") or "").strip()
        issue = str(facts.get("issue") or "").strip()
        pages = str(facts.get("pages") or "").strip()
        doi = str(facts.get("doi") or "").strip()
        url = str(facts.get("url") or "").strip()

        vol_issue = ""
        if volume and issue:
            vol_issue = f"{volume}({issue})"
        elif volume:
            vol_issue = volume

        trailing = ""
        if pages and vol_issue:
            trailing = f"{vol_issue}, {pages}."
        elif vol_issue:
            trailing = f"{vol_issue}."
        elif pages:
            trailing = f"{pages}."

        link = doi or url

        parts = []
        if authors:
            parts.append(f"{authors}.")
        if year:
            parts.append(f"({year}).")
        if title:
            parts.append(f"{title}.")
        if journal:
            parts.append(f"{journal},")
        if trailing:
            parts.append(trailing)
        if link:
            parts.append(link)

        # Clean up stray commas/spaces if some parts were empty
        out = " ".join(p.strip() for p in parts if p).replace(" ,", ",")
        return out.strip()


# -----------------------------------------------------------------------------
# Format service (public entry point)
# -----------------------------------------------------------------------------
class FormatService:
    """Orchestrates style-specific formatting for citations.

    Usage:
        service = FormatService()
        text = service.preview(style="apa", source_type="book", facts={...})

    The service will:
        1) Coerce `style` and `source_type` to enums (accepts str values).
        2) Resolve an appropriate formatter object for the style.
        3) Dispatch to the per-type method on that formatter.
    """

    _STYLE_MODULES: Dict[Style, str] = {
        Style.apa: "app.services.formatters.apa",
        Style.mla: "app.services.formatters.mla",
        Style.chicago: "app.services.formatters.chicago",
        Style.turabian: "app.services.formatters.turabian",
        Style.harvard: "app.services.formatters.harvard",
    }

    def __init__(self) -> None:
        """Initialize the format service with an empty formatter cache."""
        self._cache: Dict[Style, FormatterProtocol] = {}

    # ----------------------------
    # Public API
    # ----------------------------
    def preview(
        self,
        *,
        style: Style | str,
        source_type: SourceType | str,
        facts: Mapping[str, Any],
    ) -> str:
        """Return a formatted citation string for the given inputs.

        Args:
            style: Citation style (enum or its string value).
            source_type: Source type (enum or its string value).
            facts: Normalized facts used by the formatter.

        Returns:
            A formatted, deterministic citation string.

        Raises:
            ValueError: If the style or source type is unsupported.
        """
        style_enum = self._coerce_style(style)
        type_enum = self._coerce_source_type(source_type)
        formatter = self._get_formatter(style_enum)

        # Dispatch per type
        if type_enum == SourceType.book:
            return formatter.format_book(facts)
        if type_enum == SourceType.journal_article:
            return formatter.format_journal_article(facts)
        if type_enum == SourceType.magazine_newspaper:
            return formatter.format_magazine_newspaper(facts)
        if type_enum == SourceType.encyclopedia:
            return formatter.format_encyclopedia(facts)
        if type_enum == SourceType.website:
            return formatter.format_website(facts)

        raise ValueError(f"Unsupported source type: {type_enum!s}")

    # Back-compat shim for callers that use `format_preview(...)` (e.g., M6 code paths)
    def format_preview(
        self,
        *,
        style: Style | str,
        source_type: SourceType | str,
        facts: Mapping[str, Any],
    ) -> str:
        """Alias to :meth:`preview` (non-breaking convenience).

        This keeps older code (e.g., M6 service calls) working without change.
        """
        return self.preview(style=style, source_type=source_type, facts=facts)

    # ----------------------------
    # Internals
    # ----------------------------
    def _coerce_style(self, value: Style | str) -> Style:
        """Coerce an arbitrary ``value`` into a :class:`Style` enum."""
        if isinstance(value, Style):
            return value
        try:
            return Style(value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Unsupported style: {value!r}") from exc

    def _coerce_source_type(self, value: SourceType | str) -> SourceType:
        """Coerce an arbitrary ``value`` into a :class:`SourceType` enum."""
        if isinstance(value, SourceType):
            return value
        try:
            return SourceType(value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Unsupported source type: {value!r}") from exc

    def _get_formatter(self, style: Style) -> FormatterProtocol:
        """Resolve (and cache) a formatter instance for the given style.

        Resolution order:
            1) If a concrete module is available (`app.services.formatters.<style>`),
               import it and call `get_formatter()`.
            2) Fallback for APA: use a minimal internal implementation.
            3) Otherwise raise a clear ValueError.

        Returns:
            An object implementing :class:`FormatterProtocol`.
        """
        if style in self._cache:
            return self._cache[style]

        # Try to import a real formatter module if present.
        module_path = self._STYLE_MODULES.get(style)
        if module_path:
            try:
                module = import_module(module_path)
                # Expect a factory function `get_formatter() -> FormatterProtocol`
                factory = getattr(module, "get_formatter", None)
                if callable(factory):
                    instance = factory()
                    if isinstance(instance, FormatterProtocol):
                        self._cache[style] = instance
                        return instance
            except Exception:  # noqa: BLE001
                # Fall through to built-in fallback (APA only), or error.
                pass

        # Minimal built-in fallback for APA
        if style == Style.apa:
            instance = _APAFormatterFallback()
            self._cache[style] = instance
            return instance

        raise ValueError(
            f"Formatter for style '{style.value}' is not available yet. "
            "Add a style module under app/services/formatters or switch to APA."
        )


__all__ = ["FormatService", "FormatterProtocol"]
