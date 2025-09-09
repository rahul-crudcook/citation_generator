"""Citation service: validate -> normalize -> persist (with partial update support).

Responsibilities:
- Validate incoming citation details against per-type rules (via validation service).
- Normalize facts before persisting to the database.
- Support partial updates (PATCH) by denormalizing current facts to a raw shape,
  deep-merging the incoming patch, re-validating, and re-normalizing.
- Enforce row-level ownership for library moves and citation access.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, MutableMapping

from sqlalchemy.orm import Session

from app.core.enums import SourceType
from app.repos.citation_repository import CitationRepository
from app.repos.library_repository import LibraryRepository
from app.services.citation_validation_service import citation_validation_service


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


def _normalized_to_raw(source_type: SourceType, facts: dict[str, Any]) -> dict[str, Any]:
    """Build raw details payload from stored normalized facts.

    This is used during PATCH to:
        1) Convert the current (normalized) facts to a "raw" shape expected by
           the validators.
        2) Merge the user's patch into that raw shape.
        3) Re-validate and normalize again before persisting.

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
        return {
            "authors": _authors_norm_to_raw(facts.get("authors")),
            "title": facts.get("title") or "",
            "journal": facts.get("journal") or "",
            "year": facts.get("year") or "",
            "volume": facts.get("volume"),
            "issue": facts.get("issue"),
            "pages": facts.get("pages"),
            "doi": facts.get("doi"),
            "url": facts.get("url"),
        }

    if source_type == SourceType.magazine_newspaper:
        return {
            "authors": _authors_norm_to_raw(facts.get("authors")),
            "title": facts.get("title") or "",
            "publication": facts.get("publication") or "",
            "year": facts.get("year"),
            "date": facts.get("date"),
            "pages": facts.get("pages"),
            "url": facts.get("url"),
        }

    # NOTE: If your enum is named `encyclopedia_dictionary`, adjust this case accordingly.
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

    # NOTE: If your enum is named `website_webpage`, adjust this case accordingly.
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


def _deep_merge(base: MutableMapping[str, Any], patch: dict[str, Any] | None) -> dict[str, Any]:
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
    out: dict[str, Any] = deepcopy(base)
    for key, value in (patch or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)  # type: ignore[arg-type]
        else:
            out[key] = value
    return out


class CitationService:
    """Coordinates validation and persistence for citations."""

    # ----------------------------
    # Create
    # ----------------------------
    def create(
        self,
        db: Session,
        *,
        user_id: int,
        source_type: SourceType,
        details: dict[str, Any],
        style: str | None,
        library_id: int | None,
    ) -> Any:
        """Validate details, then persist normalized facts.

        Steps:
            - If `library_id` is provided, ensure the library is owned by the user.
            - Validate raw `details` for the `source_type`.
            - On success, persist normalized facts to the repository.

        Raises:
            LookupError: If the referenced library does not exist or is not owned by the user.
            ValueError: If validation fails.

        Returns:
            The persisted citation entity.
        """
        if library_id is not None:
            lib_repo = LibraryRepository(db)
            if lib_repo.get_owned(user_id, library_id) is None:
                msg = "Library not found"
                raise LookupError(msg)

        validation = citation_validation_service.validate(source_type, details)
        if not validation.is_valid:
            msg = "Validation failed"
            raise ValueError(msg)

        repo = CitationRepository(db)
        entity = repo.create(
            user_id=user_id,
            library_id=library_id,
            source_type=source_type,
            facts=validation.normalized_facts or {},
            style=(style.strip() if style else None),
        )
        return entity

    # ----------------------------
    # Read/List
    # ----------------------------
    def list_for_user(
        self,
        db: Session,
        *,
        user_id: int,
        library_id: int | None = None,
        source_type: str | None = None,
        page: int | None = None,
        size: int | None = None,
    ) -> list[Any]:
        """List citations for a user (optional filters and pagination).

        Args:
            db: DB session.
            user_id: Owner user ID.
            library_id: Optional library filter.
            source_type: Optional source-type filter (string/enum value).
            page: Optional page number (1-based).
            size: Optional page size.

        Returns:
            A list of citation entities (repository handles ordering/paging).
        """
        # M3 note: The repository doesn't yet implement filtering/pagination.
        # Touch the args to avoid pylint W0613 (unused-argument) until M8 adds support.
        _ = (source_type, page, size)

        repo = CitationRepository(db)
        return repo.list_for_user(user_id, library_id)

    def get_owned(self, db: Session, *, user_id: int, citation_id: int) -> Any:
        """Get a citation if owned by the user; else raise 404.

        Raises:
            LookupError: If the citation is not found or not owned by the user.
        """
        repo = CitationRepository(db)
        entity = repo.get_owned(user_id, citation_id)
        if not entity:
            msg = "Citation not found"
            raise LookupError(msg)
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
        details: dict[str, Any] | None = None,
        style: str | None = None,
        library_id: int | None = None,
    ) -> Any:
        """Partially update a citation (details/style/library).

        Behavior:
            - Library move: if `library_id` is provided, ensure target library is owned.
            - Details patch: denormalize current facts to a raw shape, deep-merge the patch,
              validate, then normalize and persist.
            - Style update: trimmed style string; empty -> None.

        Raises:
            LookupError: If the citation or target library is not found or not owned by user.
            ValueError: If validation of merged details fails.

        Returns:
            The updated citation entity.
        """
        uid = user_id
        # Defensive: tolerate callers passing User instead of user_id.
        if hasattr(user_id, "id"):  # pragma: no cover - defensive
            uid = int(getattr(user_id, "id"))

        entity = self.get_owned(db, user_id=uid, citation_id=citation_id)

        # Library move (owner check only when provided)
        if library_id is not None:
            lib_repo = LibraryRepository(db)
            if lib_repo.get_owned(uid, library_id) is None:
                msg = "Library not found"
                raise LookupError(msg)
            entity.library_id = library_id

        # Details patch -> denormalize to raw -> merge -> validate -> normalize
        if details is not None:
            current_raw = _normalized_to_raw(entity.source_type, entity.facts or {})
            merged_raw = _deep_merge(current_raw, details)

            validation = citation_validation_service.validate(entity.source_type, merged_raw)
            if not validation.is_valid:
                msg = "Validation failed"
                raise ValueError(msg)

            entity.facts = validation.normalized_facts or {}

        # Style update (only if provided)
        if style is not None:
            entity.style = style.strip() or None

        # Persist changes; flush for in-transaction read-your-writes semantics.
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
            msg = "Citation not found"
            raise LookupError(msg)
        repo.delete(entity)


citation_service = CitationService()

__all__ = ["citation_service", "CitationService"]
