"""Library service layer.

Encapsulates business rules for libraries:
- Validates and trims names.
- Enforces ownership checks before update/delete.
- Delegates DB operations to the repository layer.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.library import Library
from app.repos.library_repository import LibraryRepository

__all__ = ["library_service", "LibraryService"]


class LibraryService:
    """Operations around user libraries."""

    def __init__(self) -> None:
        # Maximum allowed length for library names.
        self._name_max: int = 120

    # ----------------------------
    # Create
    # ----------------------------
    def create(self, db: Session, *, user_id: int, name: str) -> Library:
        """Create a library for the user after basic validation.

        Args:
            db: Database session.
            user_id: ID of the user creating the library.
            name: Requested library name.

        Raises:
            ValueError: If the name is empty or exceeds maximum length.

        Returns:
            The newly created `Library` entity.
        """
        clean = name.strip()
        if not clean:
            msg = "Name cannot be empty"
            raise ValueError(msg)
        if len(clean) > self._name_max:
            msg = f"Name is too long (>{self._name_max} characters)"
            raise ValueError(msg)

        repo = LibraryRepository(db)
        return repo.create(user_id=user_id, name=clean)

    # ----------------------------
    # Read
    # ----------------------------
    def list_for_user(self, db: Session, *, user_id: int) -> list[Library]:
        """List all libraries for a given user.

        Args:
            db: Database session.
            user_id: Owner user ID.

        Returns:
            List of `Library` entities (newest first).
        """
        repo = LibraryRepository(db)
        return repo.list_for_user(user_id)

    def get_owned(self, db: Session, *, user_id: int, library_id: int) -> Library:
        """Fetch a library if owned by the user, else raise.

        Args:
            db: Database session.
            user_id: Owner user ID.
            library_id: Target library ID.

        Raises:
            LookupError: If the library does not exist or is not owned.

        Returns:
            The `Library` entity.
        """
        repo = LibraryRepository(db)
        entity = repo.get_owned(user_id, library_id)
        if not entity:
            msg = "Library not found"
            raise LookupError(msg)
        return entity

    # ----------------------------
    # Update
    # ----------------------------
    def rename(
        self, db: Session, *, user_id: int, library_id: int, new_name: str
    ) -> Library:
        """Rename an existing library, enforcing ownership and validation.

        Args:
            db: Database session.
            user_id: Owner user ID.
            library_id: Target library ID.
            new_name: New library name.

        Raises:
            LookupError: If the library is not found or not owned.
            ValueError: If the new name is invalid.

        Returns:
            The updated `Library` entity.
        """
        clean = new_name.strip()
        if not clean:
            msg = "Name cannot be empty"
            raise ValueError(msg)
        if len(clean) > self._name_max:
            msg = f"Name is too long (>{self._name_max} characters)"
            raise ValueError(msg)

        repo = LibraryRepository(db)
        entity = repo.get_owned(user_id, library_id)
        if not entity:
            msg = "Library not found"
            raise LookupError(msg)

        return repo.rename(entity, clean)

    # ----------------------------
    # Delete
    # ----------------------------
    def delete(self, db: Session, *, user_id: int, library_id: int) -> None:
        """Delete a library owned by the user.

        Args:
            db: Database session.
            user_id: Owner user ID.
            library_id: Target library ID.

        Raises:
            LookupError: If the library does not exist or is not owned.
        """
        repo = LibraryRepository(db)
        entity = repo.get_owned(user_id, library_id)
        if not entity:
            msg = "Library not found"
            raise LookupError(msg)
        repo.delete(entity)


library_service = LibraryService()
