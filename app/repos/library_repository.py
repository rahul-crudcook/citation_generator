"""Repository layer for `Library` entities.

This module provides a thin data-access layer around SQLAlchemy for the
`Library` model. Keep business logic in services; repositories should
only perform DB reads/writes.
"""
from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.library import Library
from app.repos.base import BaseRepository

__all__ = ["LibraryRepository"]


class LibraryRepository(BaseRepository[Library]):
    """DB access methods for `Library` objects."""

    def __init__(self, db: Session) -> None:
        """Initialize the repository with a DB session."""
        super().__init__(db, Library)

    # ----------------------------
    # Create
    # ----------------------------
    def create(self, user_id: int, name: str) -> Library:
        """Create and persist a new library.

        Args:
            user_id: Owner user ID.
            name: Human-friendly library name.

        Returns:
            The newly created `Library` entity (flushed).
        """
        entity = Library(user_id=user_id, name=name)
        return self.add(entity)

    # ----------------------------
    # Read
    # ----------------------------
    def get_owned(self, user_id: int, library_id: int) -> Library | None:
        """Return a library only if it is owned by the given user.

        Args:
            user_id: Owner user ID.
            library_id: Target library ID.

        Returns:
            The `Library` entity if owned, otherwise `None`.
        """
        stmt = select(Library).where(
            and_(Library.id == library_id, Library.user_id == user_id)
        )
        return self.db.scalars(stmt).first()

    def list_for_user(self, user_id: int) -> list[Library]:
        """List all libraries for a user, newest first.

        Args:
            user_id: Owner user ID.

        Returns:
            A list of `Library` entities ordered by `created_at` desc.
        """
        stmt = (
            select(Library)
            .where(Library.user_id == user_id)
            .order_by(Library.created_at.desc())
        )
        return list(self.db.scalars(stmt).all())

    # ----------------------------
    # Update
    # ----------------------------
    def update(self, entity: Library) -> Library:
        """Persist changes to an existing library.

        This method is a convenience wrapper; callers typically mutate fields
        on the ORM instance and then call `update` to flush.

        Args:
            entity: The `Library` ORM instance to flush.

        Returns:
            The same `Library` instance after flush.
        """
        self.db.add(entity)
        self.db.flush()
        return entity

    def rename(self, entity: Library, new_name: str) -> Library:
        """Rename an existing library and persist the change.

        Args:
            entity: The `Library` to rename (already loaded/owned).
            new_name: The new library name (validated upstream).

        Returns:
            The updated `Library` entity after flush.
        """
        entity.name = new_name
        self.db.flush()
        return entity

    # ----------------------------
    # Delete
    # ----------------------------
    def delete(self, entity: Library) -> None:
        """Delete a library.

        Cascade behavior for related citations should be configured
        on the relationship/model level.

        Args:
            entity: The `Library` to delete.
        """
        super().delete(entity)
