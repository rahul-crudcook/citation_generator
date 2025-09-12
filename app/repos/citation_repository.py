# app/repos/citation_repository.py
"""Citation repository.

This module provides database access for `Citation` entities with strict
row-level ownership enforcement helpers. It includes convenience methods
used by M7 exports and M8 search/bulk operations.

Key capabilities
----------------
- Ownership-gated fetches (`get_owned`, `get_by_id_owned`).
- Listing with pagination, style filter, and free-text search over JSONB facts
  (`list_for_user`).
- Deterministic ordering (created_at DESC, then id DESC).
- Bulk operations for delete and move (M8): `bulk_delete_for_user`, `bulk_move_for_user`.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.enums import SourceType
from app.models.citation import Citation
from app.repos.base import BaseRepository


class CitationRepository(BaseRepository[Citation]):
    """DB access layer for :class:`Citation` objects."""

    def __init__(self, db: Session) -> None:
        """Initialize the repository with a SQLAlchemy session."""
        super().__init__(db, Citation)
        self.db = db

    # ---------------------------------------------------------------------
    # Write APIs
    # ---------------------------------------------------------------------
    def create(
        self,
        *,
        user_id: int,
        library_id: int | None,
        source_type: SourceType,
        facts: dict,
        style: str | None,
    ) -> Citation:
        """Create and persist a new citation entity.

        Args:
            user_id: Owner of the citation.
            library_id: Optional library id to associate the citation with.
            source_type: Source type enum (e.g., book, journal_article).
            facts: Normalized facts payload to persist (JSONB).
            style: Optional preferred style (e.g., "apa").

        Returns:
            The newly created :class:`Citation` entity (flush/commit by caller).
        """
        entity = Citation(
            user_id=user_id,
            library_id=library_id,
            source_type=source_type,
            facts=facts,
            style=style,
            formatted_text=None,
        )
        return self.add(entity)

    # ---------------------------------------------------------------------
    # Read APIs (ownership enforced)
    # ---------------------------------------------------------------------
    def get_owned(self, user_id: int, citation_id: int) -> Optional[Citation]:
        """Return a citation only if owned by the given user.

        Args:
            user_id: Owner id to enforce row-level permission.
            citation_id: Citation id to fetch.

        Returns:
            The :class:`Citation` if found and owned; otherwise ``None``.
        """
        stmt = select(Citation).where(
            and_(Citation.id == citation_id, Citation.user_id == user_id)
        )
        return self.db.scalars(stmt).first()

    # Alias explicitly named for export use sites (M7)
    def get_by_id_owned(self, user_id: int, citation_id: int) -> Optional[Citation]:
        """Alias of :meth:`get_owned` for clarity in export flows."""
        return self.get_owned(user_id=user_id, citation_id=citation_id)

    # ---------------------------------------------------------------------
    # Search filters (M8)
    # ---------------------------------------------------------------------
    @staticmethod
    def _search_filters(query: str) -> list:
        """Build SQLAlchemy OR-conditions for free-text search over common fields.

        The search spans typical citation text fields inside JSONB `facts` and
        the optional `formatted_text` column when present.

        Args:
            query: Raw query string; callers should pass user input (the method
                   applies the ILIKE pattern).

        Returns:
            A list of SQLAlchemy binary expressions to be OR'ed together.
        """
        q = f"%{(query or '').strip()}%"
        # facts->>'key' -> SQLAlchemy: Citation.facts["key"].astext
        fields = [
            Citation.facts["article_title"].astext,
            Citation.facts["journal_title"].astext,
            Citation.facts["title"].astext,
            Citation.facts["work_title"].astext,
            Citation.facts["site_title"].astext,
            Citation.facts["publisher"].astext,
        ]
        conditions = [col.ilike(q) for col in fields]  # type: ignore[attr-defined]
        # Include formatted_text if the model has it.
        if hasattr(Citation, "formatted_text"):
            conditions.append(Citation.formatted_text.ilike(q))  # type: ignore[attr-defined]
        return conditions

    # ---------------------------------------------------------------------
    # List with filters/pagination (M8)
    # ---------------------------------------------------------------------
    def list_for_user(
        self,
        user_id: int,
        library_id: int | None = None,
        source_type: str | None = None,
        style: str | None = None,
        query: str | None = None,
        page: int | None = None,
        size: int | None = None,
    ) -> List[Citation]:
        """List citations for a user, with filters, search, and pagination.

        Order:
            - ``created_at DESC``
            - ``id DESC`` as deterministic tie-breaker

        Args:
            user_id: Owner id to enforce row-level permission.
            library_id: Optional library id filter.
            source_type: Optional source-type filter (string/enum value).
            style: Optional case-insensitive style filter (e.g., "apa").
            query: Optional free-text search over common title/venue/publisher fields.
            page: Optional page number (1-based). If provided with ``size``, applies LIMIT/OFFSET.
            size: Optional page size. If provided with ``page``, applies LIMIT/OFFSET.

        Returns:
            List of :class:`Citation` entities.
        """
        stmt = select(Citation).where(Citation.user_id == user_id)

        if library_id is not None:
            stmt = stmt.where(Citation.library_id == library_id)

        if source_type:
            # Accept both enum name and DB value; assume DB stores enum's value.
            stmt = stmt.where(Citation.source_type == source_type)

        if style:
            # Case-insensitive equality on style.
            stmt = stmt.where(func.lower(Citation.style) == func.lower(style))

        if query and query.strip():
            stmt = stmt.where(or_(*self._search_filters(query)))

        # Deterministic ordering (descending by recency)
        order_cols = []
        if hasattr(Citation, "created_at"):
            order_cols.append(Citation.created_at.desc())  # type: ignore[attr-defined]
        order_cols.append(Citation.id.desc())
        stmt = stmt.order_by(*order_cols)

        # Pagination
        if page and size:
            # Convert 1-based page to zero-based offset.
            page = max(1, int(page))
            size = max(1, int(size))
            stmt = stmt.limit(size).offset((page - 1) * size)

        return list(self.db.scalars(stmt).all())

    # Explicit method name used by ExportService (M7 bulk)
    def list_by_library(self, user_id: int, library_id: int) -> List[Citation]:
        """List all citations in a specific library for a given user.

        Enforces row-level ownership (user_id must match) and returns a
        deterministically ordered list.

        Order:
            - ``created_at DESC``
            - ``id DESC`` as deterministic tie-breaker

        Args:
            user_id: Owner id to enforce row-level permission.
            library_id: Library id whose citations should be listed.

        Returns:
            List of :class:`Citation` entities belonging to the user in the library.
        """
        stmt = (
            select(Citation)
            .where(
                and_(
                    Citation.user_id == user_id,
                    Citation.library_id == library_id,
                )
            )
        )

        # Deterministic ordering (descending by recency)
        order_cols = []
        if hasattr(Citation, "created_at"):
            order_cols.append(Citation.created_at.desc())  # type: ignore[attr-defined]
        order_cols.append(Citation.id.desc())
        stmt = stmt.order_by(*order_cols)

        return list(self.db.scalars(stmt).all())

    # ---------------------------------------------------------------------
    # Bulk operations (M8)
    # ---------------------------------------------------------------------
    def bulk_delete_for_user(self, *, user_id: int, ids: Iterable[int]) -> int:
        """Delete multiple citations owned by a user.

        Args:
            user_id: Owner id to enforce row-level permission.
            ids: Iterable of citation IDs to delete.

        Returns:
            Number of rows deleted.
        """
        clean_ids = [int(x) for x in ids]
        if not clean_ids:
            return 0

        stmt = (
            delete(Citation)
            .where(Citation.user_id == user_id)
            .where(Citation.id.in_(clean_ids))
        )
        result = self.db.execute(stmt)
        # Caller is responsible for commit.
        return int(result.rowcount or 0)

    def bulk_move_for_user(self, *, user_id: int, ids: Iterable[int], library_id: int) -> int:
        """Move multiple citations to a new library (ownership enforced).

        Args:
            user_id: Owner id to enforce row-level permission.
            ids: Iterable of citation IDs to move.
            library_id: Destination library id.

        Returns:
            Number of rows updated.
        """
        clean_ids = [int(x) for x in ids]
        if not clean_ids:
            return 0

        stmt = (
            update(Citation)
            .where(Citation.user_id == user_id)
            .where(Citation.id.in_(clean_ids))
            .values(library_id=library_id)
        )
        result = self.db.execute(stmt)
        # Caller is responsible for commit.
        return int(result.rowcount or 0)
