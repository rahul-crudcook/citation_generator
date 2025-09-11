# app/repos/citation_repository.py
"""Citation repository.

This module provides database access for `Citation` entities with strict
row-level ownership enforcement helpers. It includes convenience methods
used by M7 exports:

- `get_by_id_owned(user_id, citation_id)`:
    Returns a citation if (and only if) it is owned by the given user.

- `list_by_library(user_id, library_id)`:
    Lists all citations in a library for a given user, ordered
    deterministically (by `created_at DESC`, then `id DESC` as a tie-breaker).

Existing read APIs are preserved (`get_owned`, `list_for_user`) for
backwards compatibility.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.enums import SourceType
from app.models.citation import Citation
from app.repos.base import BaseRepository


class CitationRepository(BaseRepository[Citation]):
    """DB access layer for `Citation` objects."""

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
            The newly created `Citation` entity (after flush/commit by caller).
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
            The `Citation` if found and owned; otherwise `None`.
        """
        stmt = select(Citation).where(
            and_(Citation.id == citation_id, Citation.user_id == user_id)
        )
        return self.db.scalars(stmt).first()

    # Alias explicitly named for export use sites (M7)
    def get_by_id_owned(self, user_id: int, citation_id: int) -> Optional[Citation]:
        """Alias of `get_owned` for clarity in export flows."""
        return self.get_owned(user_id=user_id, citation_id=citation_id)

    def list_for_user(
        self,
        user_id: int,
        library_id: int | None = None,
    ) -> List[Citation]:
        """List citations for a user, optionally filtered by library.

        Order:
            - `created_at DESC`
            - `id DESC` as deterministic tie-breaker

        Args:
            user_id: Owner id to enforce row-level permission.
            library_id: Optional library id filter.

        Returns:
            List of `Citation` entities.
        """
        stmt = select(Citation).where(Citation.user_id == user_id)
        if library_id is not None:
            stmt = stmt.where(Citation.library_id == library_id)

        # Deterministic ordering (descending by recency)
        order_cols = []
        if hasattr(Citation, "created_at"):
            order_cols.append(Citation.created_at.desc())  # type: ignore[attr-defined]
        order_cols.append(Citation.id.desc())
        stmt = stmt.order_by(*order_cols)

        return list(self.db.scalars(stmt).all())

    # Explicit method name used by ExportService (M7 bulk)
    def list_by_library(self, user_id: int, library_id: int) -> List[Citation]:
        """List all citations in a specific library for a given user.

        Enforces row-level ownership (user_id must match) and returns a
        deterministically ordered list.

        Order:
            - `created_at DESC`
            - `id DESC` as deterministic tie-breaker

        Args:
            user_id: Owner id to enforce row-level permission.
            library_id: Library id whose citations should be listed.

        Returns:
            List of `Citation` entities belonging to the user in the library.
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
