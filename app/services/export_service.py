# app/services/export_service.py
"""Export service for single and bulk citation exports (M7).

This module implements an OOP service that streams exports in multiple formats:
TXT, DOCX, BibTeX, and JSON. It is intentionally self-contained so that routes
can call `ExportService.export_single(...)` or `ExportService.export_library(...)`
and return a `StreamingResponse` with appropriate headers.

Integration points
------------------
- Repositories:
    * CitationRepository: load one citation (owned) and list by library (owned).
    * LibraryRepository: load a library (owned) for metadata/filename generation.
- Format service:
    * Used to render `formatted_text` on-demand if missing in the DB.

Design notes
------------
- ExportService does not know about FastAPI; it only returns an `ExportArtifact`
  (bytes content, media type, and filename).
- For DOCX, this service tries to import `python-docx` on-demand. If unavailable,
  an explicit `RuntimeError` is raised with an actionable message.
- For BibTeX export, the mapping is pragmatic (book, journal_article, website).
  You can extend mappings without touching route code.

Usage (in a route)
------------------
    artifact = export_service.export_single(user_id, citation_id, "txt")
    return StreamingResponse(
        content=io.BytesIO(artifact.content),
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Literal, Optional

from sqlalchemy.orm import Session

# Local imports (repos, services, models)
from app.services.format_service import FormatService
from app.repos.citation_repository import CitationRepository
from app.repos.library_repository import LibraryRepository

# If your models define specific ORM classes you need here, import them:
# from app.models.citation import Citation
# from app.models.library import Library

ExportType = Literal["txt", "docx", "bib", "json"]


@dataclass(frozen=True)
class ExportArtifact:
    """Result container for an export operation."""

    filename: str
    media_type: str
    content: bytes


@dataclass
class _CitationBundle:
    """Normalized, format-friendly snapshot for a citation."""

    source_type: str
    facts: Dict
    style: Optional[str]
    formatted_text: Optional[str]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ExportService:
    """Service that provides streaming exports for single and bulk citations."""

    # ----------------------------- #
    # Public API
    # ----------------------------- #

    def __init__(
        self,
        db: Session,
        *,
        format_service: FormatService,
        citation_repo: Optional[CitationRepository] = None,
        library_repo: Optional[LibraryRepository] = None,
    ) -> None:
        """Initialize the export service with its dependencies.

        Args:
            db: SQLAlchemy session (scoped for the request).
            format_service: Citation formatting service (M6).
            citation_repo: Repository to access citations.
            library_repo: Repository to access libraries.
        """
        self._db = db
        self._format_service = format_service
        self._citations = citation_repo or CitationRepository(db)
        self._libraries = library_repo or LibraryRepository(db)

    def export_single(
        self,
        user_id: int,
        citation_id: int,
        export_type: ExportType,
    ) -> ExportArtifact:
        """Export a single citation in the requested format.

        Args:
            user_id: ID of the requesting user (ownership enforced).
            citation_id: Target citation ID.
            export_type: One of "txt", "docx", "bib", or "json".

        Returns:
            ExportArtifact with filename, media type, and bytes content.

        Raises:
            ValueError: If export_type is unsupported.
            LookupError: If the citation is not found or not owned by user_id.
            RuntimeError: If DOCX export is requested without python-docx.
        """
        entity = self._load_owned_citation(user_id, citation_id)
        bundle = self._normalize_entity(entity)
        self._ensure_formatted_text(bundle)

        if export_type == "txt":
            content = self._write_txt_single(bundle)
            filename = self._suggest_filename_single(bundle, "txt")
            media = "text/plain; charset=utf-8"
        elif export_type == "json":
            content = self._write_json_single(bundle)
            filename = self._suggest_filename_single(bundle, "json")
            media = "application/json"
        elif export_type == "bib":
            content = self._write_bib_single(bundle)
            filename = self._suggest_filename_single(bundle, "bib")
            media = "application/x-bibtex"
        elif export_type == "docx":
            content = self._write_docx_single(bundle)
            filename = self._suggest_filename_single(bundle, "docx")
            media = (
                "application/"
                "vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        else:
            raise ValueError(f"Unsupported export type: {export_type}")

        return ExportArtifact(filename=filename, media_type=media, content=content)

    def export_library(
        self,
        user_id: int,
        library_id: int,
        export_type: ExportType,
        *,
        style_for_heading: Optional[str] = None,
    ) -> ExportArtifact:
        """Export all citations in a library (bulk) with style-specific heading.

        Args:
            user_id: ID of the requesting user (ownership enforced).
            library_id: Target library ID.
            export_type: One of "txt", "docx", "bib", or "json".
            style_for_heading: Optional style to decide heading text
                ("References" vs "Works Cited"). If omitted, will try to infer
                from citations or default to "apa".

        Returns:
            ExportArtifact with filename, media type, and bytes content.

        Raises:
            ValueError: If export_type is unsupported.
            LookupError: If the library is not found or not owned by user_id.
            RuntimeError: If DOCX export is requested without python-docx.
        """
        library = self._libraries.get_by_id_owned(user_id=user_id, library_id=library_id)
        if library is None:
            raise LookupError("Library not found or not owned by user.")

        entities = self._citations.list_by_library(user_id=user_id, library_id=library_id)
        bundles = [self._normalize_entity(e) for e in entities]

        # Ensure each bundle has formatted_text; infer a "dominant" style if missing.
        dominant_style = self._resolve_dominant_style(
            bundles, fallback=style_for_heading or "apa"
        )
        for bdl in bundles:
            # If style missing for preview, use dominant_style for consistent output
            if not bdl.style:
                bdl.style = dominant_style
            self._ensure_formatted_text(bdl)

        if export_type == "txt":
            heading = self._heading_for_style(dominant_style)
            content = self._write_txt_bulk(bundles, heading=heading)
            filename = self._suggest_filename_library(library.name, "txt")
            media = "text/plain; charset=utf-8"
        elif export_type == "json":
            content = self._write_json_bulk(bundles)
            filename = self._suggest_filename_library(library.name, "json")
            media = "application/json"
        elif export_type == "bib":
            content = self._write_bib_bulk(bundles)
            filename = self._suggest_filename_library(library.name, "bib")
            media = "application/x-bibtex"
        elif export_type == "docx":
            heading = self._heading_for_style(dominant_style)
            content = self._write_docx_bulk(bundles, heading=heading)
            filename = self._suggest_filename_library(library.name, "docx")
            media = (
                "application/"
                "vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        else:
            raise ValueError(f"Unsupported export type: {export_type}")

        return ExportArtifact(filename=filename, media_type=media, content=content)

    # ----------------------------- #
    # Internals: loading & shaping
    # ----------------------------- #

    def _load_owned_citation(self, user_id: int, citation_id: int):
        """Fetch a single citation ensuring row-level ownership."""
        entity = self._citations.get_by_id_owned(user_id=user_id, citation_id=citation_id)
        if entity is None:
            raise LookupError("Citation not found or not owned by user.")
        return entity

    @staticmethod
    def _normalize_entity(entity) -> _CitationBundle:
        """Map ORM entity to a normalized snapshot for export.

        This mapping is defensive to tolerate minor field naming changes
        (`type` vs `source_type`, `facts_jsonb` vs `facts`).
        """
        source_type = getattr(entity, "type", None) or getattr(entity, "source_type", "")
        facts = (
            getattr(entity, "facts_jsonb", None)
            or getattr(entity, "facts", None)
            or {}
        )
        style = getattr(entity, "style", None)
        formatted_text = getattr(entity, "formatted_text", None)
        created_at = getattr(entity, "created_at", None)
        updated_at = getattr(entity, "updated_at", None)

        return _CitationBundle(
            source_type=str(source_type or ""),
            facts=dict(facts) if isinstance(facts, dict) else {},
            style=str(style) if style else None,
            formatted_text=str(formatted_text) if formatted_text else None,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _ensure_formatted_text(self, bundle: _CitationBundle) -> None:
        """Ensure bundle.formatted_text is present (render via FormatService if missing)."""
        if bundle.formatted_text:
            return

        # Choose a style: prefer the bundle's style; else default to APA.
        style = bundle.style or "apa"
        rendered = self._format_service.preview(
            style=style,
            source_type=bundle.source_type,
            facts=bundle.facts,
        )
        # Expected to return dict with "formatted" key; accept plain string fallback.
        if isinstance(rendered, dict) and "formatted" in rendered:
            bundle.formatted_text = str(rendered["formatted"])
        else:
            bundle.formatted_text = str(rendered)

    @staticmethod
    def _resolve_dominant_style(
        bundles: List[_CitationBundle], fallback: str = "apa"
    ) -> str:
        """Pick the dominant style from bundles, or return a fallback."""
        counts: Dict[str, int] = {}
        for bdl in bundles:
            if bdl.style:
                key = str(bdl.style).lower()
                counts[key] = counts.get(key, 0) + 1
        if not counts:
            return fallback
        # Return the most frequent style.
        return max(counts.items(), key=lambda kv: kv[1])[0]

    # ----------------------------- #
    # Internals: formatting helpers
    # ----------------------------- #

    @staticmethod
    def _heading_for_style(style: Optional[str]) -> str:
        """Return the heading text for a given style."""
        if not style:
            return "References"
        style_l = style.lower()
        if style_l == "mla":
            return "Works Cited"
        # Chicago/Turabian/APA/Harvard → "References"
        return "References"

    @staticmethod
    def _suggest_filename_single(bundle: _CitationBundle, ext: str) -> str:
        """Suggest a filename for a single-citation export."""
        first_author = _safe_str(_first_author_lastname(bundle.facts) or "citation")
        year = _safe_str(str(bundle.facts.get("year") or "n.d."))
        short_title = _safe_str(_short_title(bundle.facts.get("title") or "untitled"))
        base = f"{first_author}_{year}_{short_title}".strip("_")
        return f"{base}.{ext}"

    @staticmethod
    def _suggest_filename_library(library_name: str, ext: str) -> str:
        """Suggest a filename for a library export."""
        base = _safe_str(library_name or "library")
        return f"{base}.{ext}"

    # ----------------------------- #
    # Writers: TXT / JSON / BIB / DOCX
    # ----------------------------- #

    @staticmethod
    def _write_txt_single(bundle: _CitationBundle) -> bytes:
        """Generate a TXT payload for a single citation."""
        text = (bundle.formatted_text or "").strip()
        return (text + "\n").encode("utf-8")

    def _write_txt_bulk(
        self, bundles: List[_CitationBundle], *, heading: str
    ) -> bytes:
        """Generate a TXT payload for a library export with heading."""
        lines: List[str] = [heading, ""]
        for bdl in bundles:
            text = (bdl.formatted_text or "").strip()
            if text:
                lines.append(text)
        # Blank line between citations for readability.
        payload = "\n\n".join(lines) + "\n"
        return payload.encode("utf-8")

    @staticmethod
    def _write_json_single(bundle: _CitationBundle) -> bytes:
        """Generate JSON payload for a single citation."""
        obj = {
            "type": bundle.source_type,
            "facts": bundle.facts,
            "style": bundle.style,
            "formatted_text": bundle.formatted_text,
            "created_at": _iso(bundle.created_at),
            "updated_at": _iso(bundle.updated_at),
        }
        return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")

    @staticmethod
    def _write_json_bulk(bundles: List[_CitationBundle]) -> bytes:
        """Generate JSON payload for a list of citations."""
        arr = [
            {
                "type": b.source_type,
                "facts": b.facts,
                "style": b.style,
                "formatted_text": b.formatted_text,
                "created_at": _iso(b.created_at),
                "updated_at": _iso(b.updated_at),
            }
            for b in bundles
        ]
        return json.dumps(arr, ensure_ascii=False, indent=2).encode("utf-8")

    @staticmethod
    def _write_bib_single(bundle: _CitationBundle) -> bytes:
        """Generate BibTeX payload for a single citation."""
        entry = _to_bibtex_entry(bundle)
        return (entry + "\n").encode("utf-8")

    @staticmethod
    def _write_bib_bulk(bundles: List[_CitationBundle]) -> bytes:
        """Generate BibTeX payload for multiple citations."""
        entries = [_to_bibtex_entry(b) for b in bundles]
        return ("\n\n".join(entries) + "\n").encode("utf-8")

    @staticmethod
    def _write_docx_single(bundle: _CitationBundle) -> bytes:
        """Generate DOCX payload for a single citation."""
        try:
            # Imported on demand so environments without DOCX can still use other formats.
            from docx import Document  # type: ignore  # pylint: disable=import-outside-toplevel
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError(
                "DOCX export requires 'python-docx'. Install it in your environment."
            ) from exc

        doc = Document()
        doc.add_paragraph((bundle.formatted_text or "").strip())
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    @staticmethod
    def _write_docx_bulk(
        bundles: List[_CitationBundle], *, heading: str
    ) -> bytes:
        """Generate DOCX payload for multiple citations with a heading."""
        try:
            from docx import Document  # type: ignore  # pylint: disable=import-outside-toplevel
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError(
                "DOCX export requires 'python-docx'. Install it in your environment."
            ) from exc

        doc = Document()
        doc.add_heading(heading, level=1)
        for bdl in bundles:
            text = (bdl.formatted_text or "").strip()
            if text:
                para = doc.add_paragraph(text)
                # Add spacing after each paragraph to mimic common style guides.
                para.paragraph_format.space_after = 200  # ~ 10pt
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()


# =============================================================================
# Pure helper functions (isolated for testability)
# =============================================================================


def _iso(dt: Optional[datetime]) -> Optional[str]:
    """Return ISO-8601 string with 'Z' for UTC (if available)."""
    if not dt:
        return None
    try:
        # If tz-aware UTC, normalize to 'Z'; otherwise just isoformat.
        iso = dt.isoformat()
        return iso.replace("+00:00", "Z") if iso.endswith("+00:00") else iso
    except Exception:  # pylint: disable=broad-except
        return None


def _first_author_lastname(facts: Dict) -> Optional[str]:
    """Extract the first author's last name from facts (supports two shapes)."""
    # Common shapes:
    #  - facts["authors"] = [{"first": "Jane", "last": "Doe"}, ...]
    #  - facts["authors"] = ["Doe, Jane", ...]
    authors = facts.get("authors") or []
    if not isinstance(authors, list) or not authors:
        return None

    first = authors[0]
    if isinstance(first, dict):
        last = first.get("last")
        return str(last) if last else None

    if isinstance(first, str):
        # Attempt to split "Last, First"
        if "," in first:
            return first.split(",", 1)[0].strip()
        # Otherwise, pick last token as a pragmatic default
        parts = first.split()
        return parts[-1] if parts else None
    return None


def _short_title(title: str, max_len: int = 24) -> str:
    """Generate a short title slug used in filenames."""
    title_norm = str(title or "").strip()
    if not title_norm:
        return "untitled"
    title_norm = re.sub(r"\s+", " ", title_norm)
    if len(title_norm) > max_len:
        title_norm = title_norm[: max_len - 1] + "…"
    return title_norm


def _safe_str(s: str) -> str:
    """ASCII-safe, filename-friendly string (lowercase, hyphenated)."""
    s = str(s or "").strip().lower()
    # Normalize unicode → ASCII where possible
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # Replace any non word/space character with space
    s = re.sub(r"[^\w\s-]", " ", s)
    # Collapse whitespace to single hyphen
    s = re.sub(r"\s+", "-", s)
    # Collapse multiple hyphens
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-") or "file"


def _to_bibtex_entry(bundle: _CitationBundle) -> str:
    """Convert a citation bundle to a BibTeX entry string.

    This is a pragmatic mapping that covers the common source types.
    Extend this mapping as needed for your domain.
    """
    source_type = (bundle.source_type or "").lower()
    facts = bundle.facts or {}

    # Decide BibTeX entry type
    if source_type == "book":
        entry_type = "book"
        fields = _bib_fields_book(facts)
        key = _bibtex_key_from(facts, fallback="book")
    elif source_type == "journal_article":
        entry_type = "article"
        fields = _bib_fields_article(facts)
        key = _bibtex_key_from(facts, fallback="article")
    elif source_type in {"website", "webpage"}:
        entry_type = "misc"
        fields = _bib_fields_website(facts)
        key = _bibtex_key_from(facts, fallback="web")
    else:
        # Reasonable fallback
        entry_type = "misc"
        fields = _bib_fields_generic(facts)
        key = _bibtex_key_from(facts, fallback="ref")

    # Assemble BibTeX text
    field_lines = [f'  {k} = {{{v}}}' for k, v in fields.items() if v]
    return f"@{entry_type}{{{key},\n" + ",\n".join(field_lines) + "\n}"


def _bibtex_key_from(facts: Dict, fallback: str) -> str:
    """Generate a BibTeX key: lastYearTitle (ASCII-safe)."""
    last = _first_author_lastname(facts) or fallback
    year = str(facts.get("year") or "n.d.")
    title = str(facts.get("title") or "").split()[0] if facts.get("title") else "title"
    key = f"{last}{year}{title}"
    return _safe_str(key).replace("-", "")


def _format_author_list_for_bibtex(facts: Dict) -> str:
    """Format authors as 'Last, First and Last, First' for BibTeX."""
    authors = facts.get("authors") or []
    parts: List[str] = []
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


def _bib_fields_book(facts: Dict) -> Dict[str, str]:
    """Map book facts to BibTeX fields."""
    return {
        "author": _format_author_list_for_bibtex(facts),
        "title": str(facts.get("title") or ""),
        "publisher": str(facts.get("publisher") or ""),
        "year": str(facts.get("year") or ""),
        "address": str(facts.get("city_of_publication") or ""),
        "pages": str(facts.get("pages") or ""),
    }


def _bib_fields_article(facts: Dict) -> Dict[str, str]:
    """Map journal article facts to BibTeX fields."""
    return {
        "author": _format_author_list_for_bibtex(facts),
        "title": str(facts.get("title") or ""),
        "journal": str(facts.get("journal") or ""),
        "year": str(facts.get("year") or ""),
        "volume": str(facts.get("volume") or ""),
        "number": str(facts.get("issue") or ""),
        "pages": str(facts.get("pages") or ""),
        "doi": str(facts.get("doi") or ""),
        "url": str(facts.get("url") or ""),
    }


def _bib_fields_website(facts: Dict) -> Dict[str, str]:
    """Map website facts to BibTeX fields."""
    return {
        "author": _format_author_list_for_bibtex(facts),
        "title": str(facts.get("work_title") or facts.get("title") or ""),
        "howpublished": str(facts.get("site_title") or "Website"),
        "year": str(facts.get("year") or ""),
        "url": str(facts.get("url") or ""),
        "note": str(facts.get("date_accessed") or ""),
    }


def _bib_fields_generic(facts: Dict) -> Dict[str, str]:
    """Fallback mapping for other/unknown types."""
    return {
        "author": _format_author_list_for_bibtex(facts),
        "title": str(facts.get("title") or facts.get("work_title") or ""),
        "year": str(facts.get("year") or ""),
        "url": str(facts.get("url") or ""),
        "note": str(facts.get("publisher") or facts.get("site_title") or ""),
    }
