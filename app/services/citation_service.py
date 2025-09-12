# app/services/citation_service.py
"""Citation service: validate → normalize → persist (with partial update support).

Responsibilities
----------------
- Validate incoming citation details against per-type rules (via ValidationService).
- Normalize facts before persisting to the database.
- Support partial updates (PATCH) by:
    1) denormalizing current facts to a raw "validator" shape,
    2) deep-merging the incoming patch,
    3) re-validating, and
    4) re-normalizing before persist.
- Enforce row-level ownership for library moves and citation access.
- (M6) When requested, format and store `formatted_text` using the FormatService.
- (M7) Provide a stable mapper `to_export_dict(...)` for export services/writers.
- (M8) Advanced listing with free-text search/style filters, and bulk ops.

Notes
-----
This service is intentionally persistence-oriented. It delegates validation
and normalization to `ValidationService` to keep a single source of truth for
rules and messages. Minor key-aliasing is handled here to adapt historical
request payloads (e.g., "title" → "article_title") to validator expectations.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Iterable, List, MutableMapping, Optional

from sqlalchemy.orm import Session

from app.core.enums import SourceType
from app.repos.citation_repository import CitationRepository
from app.repos.library_repository import LibraryRepository
from app.services.format_service import FormatService
from app.services.validation_service import ValidationService


def _authors_norm_to_raw(authors: Any) -> list[str]:
    """Convert normalized authors into raw input strings.

    Expected normalized shape:
        [{"first": "First", "last": "Last"}, ...]

    Raw shape expected by validators:
        ["Last, First", ...]

    Unknown/partial shapes are ignored defensively.

    Args:
        authors: Any value; expected to be a list of dicts.

    Returns:
        A list of author strings suitable for validator input.
    """
    raw: list[str] = []
    if isinstance(authors, list):
        for item in authors:
            if isinstance(item, dict):
                first = (item.get("first") or "").strip()
                last = (item.get("last") or "").strip()
                if last and first:
                    raw.append(f"{last}, {first}")
                elif last:
                    raw.append(last)
                elif first:
                    raw.append(first)
    return raw


def _normalized_to_raw(source_type: SourceType, facts: Dict[str, Any]) -> Dict[str, Any]:
    """Build a *raw* details payload from stored normalized facts.

    Used during PATCH to:
        1) Convert the current (normalized) facts to a "raw" shape expected by
           the validator.
        2) Let the user's patch merge into that raw shape.
        3) Re-validate and re-normalize before persisting.

    Args:
        source_type: The citation source type.
        facts: The normalized facts as stored in the DB.

    Returns:
        A raw details dict suitable for passing into the validator.
    """
    facts = facts or {}

    if source_type == SourceType.book:
        return {
            "authors": _authors_norm_to_raw(facts.get("authors")),
            "title": facts.get("title") or "",
            "publisher": facts.get("publisher") or "",
            "year": facts.get("year") or "",
            "city_of_publication": facts.get("city_of_publication"),
        }

    if source_type == SourceType.journal_article:
        # Historical normalized keys: title / journal
        return {
            "title": facts.get("title") or "",
            "journal": facts.get("journal") or "",
            "authors": _authors_norm_to_raw(facts.get("authors")),
            "year": facts.get("year") or "",
            "volume": facts.get("volume"),
            "issue": facts.get("issue"),
            "pages": facts.get("pages"),
            "doi": facts.get("doi"),
            "url": facts.get("url"),
        }

    if source_type == SourceType.magazine_newspaper:
        # Historical normalized keys: title / publication
        return {
            "authors": _authors_norm_to_raw(facts.get("authors")),
            "title": facts.get("title") or "",
            "publication": facts.get("publication") or "",
            "year": facts.get("year"),
            "date": facts.get("date"),
            "pages": facts.get("pages"),
            "url": facts.get("url"),
        }

    if source_type == SourceType.encyclopedia:
        return {
            "title": facts.get("title") or "",
            "encyclopedia_title": facts.get("encyclopedia_title"),
            "year": facts.get("year"),
            "volume": facts.get("volume"),
            "publisher": facts.get("publisher"),
            "city_of_publication": facts.get("city_of_publication"),
            "url": facts.get("url"),
        }

    if source_type == SourceType.website:
        return {
            "title": facts.get("title") or "",
            "url": facts.get("url") or "",
            "year": facts.get("year"),
            "accessed_date": facts.get("accessed_date"),
            "authors": _authors_norm_to_raw(facts.get("authors")),
        }

    # Fallback (should not happen if enums are aligned).
    return {}


def _deep_merge(base: MutableMapping[str, Any], patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Deep-merge ``patch`` into ``base`` without modifying inputs.

    Rules:
        - If both sides are dicts -> recurse.
        - Otherwise -> patch value wins (replace).

    Args:
        base: The original mapping to merge into.
        patch: The patch mapping. If None, the base is returned (copied).

    Returns:
        A new dict representing the merged result.
    """
    out: Dict[str, Any] = deepcopy(base)
    for key, value in (patch or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)  # type: ignore[arg-type]
        else:
            out[key] = value
    return out


def _apply_aliases_for_validator(source_type: SourceType, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt historical request keys to the validator's expected field names.

    This keeps the validator schemas stable while allowing older payload shapes.

    Mappings:
        - journal_article:
            title -> article_title
            journal -> journal_title
        - magazine_newspaper:
            title -> article_title
            publication -> periodical_title
        - website:
            title -> work_title
            # site_title might be missing in manual entry; leave as-is if absent.

    Args:
        source_type: Citation type.
        raw: Raw details (request-like) dict.

    Returns:
        A shallow-copied dict with aliases applied.
    """
    out = dict(raw)

    if source_type == SourceType.journal_article:
        if "article_title" not in out and "title" in out:
            out["article_title"] = out["title"]
        if "journal_title" not in out and "journal" in out:
            out["journal_title"] = out["journal"]

    elif source_type == SourceType.magazine_newspaper:
        if "article_title" not in out and "title" in out:
            out["article_title"] = out["title"]
        if "periodical_title" not in out and "publication" in out:
            out["periodical_title"] = out["publication"]

    elif source_type == SourceType.website:
        if "work_title" not in out and "title" in out:
            out["work_title"] = out["title"]

    # book / encyclopedia currently align well with validator fields.
    return out


class CitationService:
    """Coordinates validation and persistence for citations.

    The service composes a `ValidationService` for all rule checks and
    normalization, and optionally a `FormatService` (M6) to produce and store
    deterministic, style-specific `formatted_text`.

    It also exposes `to_export_dict(...)` (M7) to provide a stable, export-
    friendly mapping from ORM entities to normalized dicts.

    Args:
        validator: Optional custom validator instance (useful for tests).
        formatter: Optional custom formatter (useful for tests or advanced configs).
    """

    def __init__(
        self,
        validator: Optional[ValidationService] = None,
        formatter: Optional[FormatService] = None,
    ) -> None:
        self._validator = validator or ValidationService()
        self._formatter = formatter or FormatService()

    # ---------------------------------------------------------------------
    # M7: Export mapping helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def to_export_dict(entity: Any) -> Dict[str, Any]:
        """Return a normalized export snapshot for a citation ORM entity.

        Shape:
            {
                "id": int | None,
                "type": str,                # e.g. "book", "journal_article"
                "facts": dict,              # normalized facts
                "style": str | None,        # "apa" | "mla" | ...
                "formatted_text": str | None,
                "created_at": str | None,   # ISO-8601 string (UTC 'Z' normalized if tz-aware)
                "updated_at": str | None
            }

        This avoids leaking storage-specific names (e.g., `facts_jsonb`) and
        provides a clean interface for export services/writers.

        Args:
            entity: ORM instance (expected to have attributes: id, source_type/type,
                facts/facts_jsonb, style, formatted_text, created_at, updated_at).

        Returns:
            A normalized dict safe for export use.
        """
        source_type = getattr(entity, "type", None) or getattr(entity, "source_type", "")
        facts = (
            getattr(entity, "facts_jsonb", None)
            or getattr(entity, "facts", None)
            or {}
        )
        created = getattr(entity, "created_at", None)
        updated = getattr(entity, "updated_at", None)

        return {
            "id": getattr(entity, "id", None),
            "type": str(source_type or ""),
            "facts": dict(facts) if isinstance(facts, dict) else {},
            "style": getattr(entity, "style", None),
            "formatted_text": getattr(entity, "formatted_text", None),
            "created_at": _iso(created),
            "updated_at": _iso(updated),
        }

    @classmethod
    def to_export_dicts(cls, entities: Iterable[Any]) -> List[Dict[str, Any]]:
        """Vectorized convenience wrapper for `to_export_dict(...)`.

        Args:
            entities: Iterable of ORM entities.

        Returns:
            List of normalized export snapshots.
        """
        return [cls.to_export_dict(e) for e in entities]

    # ----------------------------
    # Create
    # ----------------------------
    def create(
        self,
        db: Session,
        *,
        user_id: int,
        source_type: SourceType,
        details: Dict[str, Any],
        style: Optional[str],
        library_id: Optional[int],
        format_now: bool = False,
    ) -> Any:
        """Validate details, then persist normalized facts (and optionally format).

        Steps:
            - If `library_id` is provided, ensure the library is owned by the user.
            - Apply key aliases to match validator expectations (backward-compat).
            - Validate raw `details` for the `source_type` using `ValidationService`.
            - Persist normalized facts.
            - (M6) If `format_now` is True and `style` is provided, compute and store
              `formatted_text` via the `FormatService`.

        Raises:
            LookupError: If the referenced library does not exist or is not owned by the user.
            ValueError: If validation fails.

        Returns:
            The persisted citation entity.
        """
        if library_id is not None:
            lib_repo = LibraryRepository(db)
            if lib_repo.get_owned(user_id, library_id) is None:
                raise LookupError("Library not found")

        aliased = _apply_aliases_for_validator(source_type, dict(details))
        result = self._validator.validate_with_helpers(source_type, aliased)
        if not result.get("is_valid", False):
            raise ValueError("Validation failed")

        normalized_facts: Dict[str, Any] = result.get("normalized_facts") or {}

        repo = CitationRepository(db)
        entity = repo.create(
            user_id=user_id,
            library_id=library_id,
            source_type=source_type,
            facts=normalized_facts,
            style=(style.strip() if style else None),
        )

        # Optionally format and persist the preview text.
        if format_now and style:
            formatted = self._formatter.format_preview(
                style=style, source_type=source_type, facts=normalized_facts
            )
            setattr(entity, "formatted_text", formatted)
            db.flush()

        return entity

    # ----------------------------
    # Read/List (M8: query/style filters)
    # ----------------------------
    def list_for_user(
        self,
        db: Session,
        *,
        user_id: int,
        library_id: Optional[int] = None,
        source_type: Optional[str] = None,
        style: Optional[str] = None,
        query: Optional[str] = None,
        page: Optional[int] = None,
        size: Optional[int] = None,
    ) -> list[Any]:
        """List citations for a user with optional filters/pagination (delegates to repo).

        Args:
            db: DB session.
            user_id: Owner user ID.
            library_id: Optional library filter.
            source_type: Optional source-type filter (string/enum value).
            style: Optional style filter (e.g., 'apa', 'mla').
            query: Optional free-text query (title/author/journal/publisher).
            page: Optional page number (1-based).
            size: Optional page size.

        Returns:
            A list of citation entities (repository handles ordering/paging/search).
        """
        repo = CitationRepository(db)
        return repo.list_for_user(
            user_id=user_id,
            library_id=library_id,
            source_type=source_type,
            style=style,
            query=query,
            page=page,
            size=size,
        )

    def get_owned(self, db: Session, *, user_id: int, citation_id: int) -> Any:
        """Get a citation if owned by the user; else raise 404.

        Raises:
            LookupError: If the citation is not found or not owned by the user.
        """
        repo = CitationRepository(db)
        entity = repo.get_owned(user_id, citation_id)
        if not entity:
            raise LookupError("Citation not found")
        return entity

    # ----------------------------
    # Update (partial)
    # ----------------------------
    def update(
        self,
        db: Session,
        *,
        user_id: int,
        citation_id: int,
        details: Optional[Dict[str, Any]] = None,
        style: Optional[str] = None,
        library_id: Optional[int] = None,
        format_now: bool = False,
    ) -> Any:
        """Partially update a citation (details/style/library) and optionally reformat.

        Behavior:
            - Library move: if `library_id` is provided, ensure target library is owned.
            - Details patch: denormalize current facts to a raw shape, deep-merge the patch,
              apply validator aliases, validate, then normalize and persist.
            - Style update: trimmed style string; empty -> None.
            - (M6) If `format_now` is True and a style is present (new or existing),
              update `formatted_text` using the latest facts/style.

        Raises:
            LookupError: If the citation or target library is not found or not owned by user.
            ValueError: If validation of merged details fails.

        Returns:
            The updated citation entity.
        """
        uid = user_id
        if hasattr(user_id, "id"):  # pragma: no cover - defensive
            uid = int(getattr(user_id, "id"))

        entity = self.get_owned(db, user_id=uid, citation_id=citation_id)

        # Library move (owner check only when provided)
        if library_id is not None:
            lib_repo = LibraryRepository(db)
            if lib_repo.get_owned(uid, library_id) is None:
                raise LookupError("Library not found")
            entity.library_id = library_id

        facts_changed = False

        # Details patch -> denormalize to raw -> merge -> alias -> validate -> normalize
        if details is not None:
            current_raw = _normalized_to_raw(entity.source_type, entity.facts or {})
            merged_raw = _deep_merge(current_raw, details)
            aliased = _apply_aliases_for_validator(entity.source_type, merged_raw)

            result = self._validator.validate_with_helpers(entity.source_type, aliased)
            if not result.get("is_valid", False):
                raise ValueError("Validation failed")

            entity.facts = result.get("normalized_facts") or {}
            facts_changed = True

        # Style update (only if provided)
        style_changed = False
        if style is not None:
            entity.style = style.strip() or None
            style_changed = True

        # Re-format if requested and possible (style present either newly or already stored).
        if format_now and (style_changed or facts_changed or entity.formatted_text is None):
            chosen_style = entity.style
            if chosen_style:
                formatted = self._formatter.format_preview(
                    style=chosen_style,
                    source_type=entity.source_type,
                    facts=entity.facts or {},
                )
                setattr(entity, "formatted_text", formatted)

        db.flush()
        return entity

    # ----------------------------
    # Delete
    # ----------------------------
    def delete(self, db: Session, *, user_id: int, citation_id: int) -> None:
        """Delete a citation owned by the user; raise 404 otherwise."""
        repo = CitationRepository(db)
        entity = repo.get_owned(user_id, citation_id)
        if not entity:
            raise LookupError("Citation not found")
        repo.delete(entity)

    # ----------------------------
    # M8: Bulk operations
    # ----------------------------
    def bulk_delete(self, db: Session, *, user_id: int, ids: List[int]) -> int:
        """Delete multiple citations owned by the user.

        Args:
            db: DB session.
            user_id: Owner user ID.
            ids: Non-empty list of citation IDs to delete.

        Returns:
            Number of rows deleted.

        Raises:
            ValueError: If `ids` is empty or contains invalid entries.
        """
        if not ids:
            raise ValueError("`ids` must be a non-empty list.")
        if any((not isinstance(x, int)) or x <= 0 for x in ids):
            raise ValueError("All `ids` must be positive integers.")

        repo = CitationRepository(db)
        return int(repo.bulk_delete_for_user(user_id=user_id, ids=ids))

    def bulk_move(
        self,
        db: Session,
        *,
        user_id: int,
        ids: List[int],
        library_id: int,
    ) -> int:
        """Move multiple citations to a target library (ownership enforced).

        Args:
            db: DB session.
            user_id: Owner user ID.
            ids: Non-empty list of citation IDs to move.
            library_id: Destination library (must be owned by the user).

        Returns:
            Number of rows moved.

        Raises:
            ValueError: If `ids` is empty/invalid or `library_id` is not positive.
            LookupError: If the library is not found or not owned by user.
        """
        if not ids:
            raise ValueError("`ids` must be a non-empty list.")
        if any((not isinstance(x, int)) or x <= 0 for x in ids):
            raise ValueError("All `ids` must be positive integers.")
        if not isinstance(library_id, int) or library_id <= 0:
            raise ValueError("`library_id` must be a positive integer.")

        # Ensure the target library is owned by the user.
        lib_repo = LibraryRepository(db)
        if lib_repo.get_owned(user_id, library_id) is None:
            raise LookupError("Library not found")

        repo = CitationRepository(db)
        return int(repo.bulk_move_for_user(user_id=user_id, ids=ids, library_id=library_id))


# ---------------------------------------------------------------------
# Local helper: ISO-8601 normalization (UTC 'Z' suffix if tz-aware)
# ---------------------------------------------------------------------
def _iso(dt: Optional[datetime]) -> Optional[str]:
    """Return ISO-8601 string with 'Z' for UTC (if available)."""
    if not dt:
        return None
    try:
        iso = dt.isoformat()
        return iso.replace("+00:00", "Z") if iso.endswith("+00:00") else iso
    except Exception:  # pylint: disable=broad-except
        return None


# Module-level singleton for app usage (tests may construct their own instance).
citation_service = CitationService()

__all__ = ["citation_service", "CitationService"]
