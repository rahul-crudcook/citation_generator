"""Base repository with common helpers."""
from __future__ import annotations

from typing import Generic, Optional, Sequence, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository offering common CRUD-ish helpers."""

    def __init__(self, db: Session, model: Type[T]) -> None:
        self.db = db
        self.model = model

    def add(self, entity: T) -> T:
        """Add & return entity (flush but don't commit)."""
        self.db.add(entity)
        self.db.flush()
        return entity

    def get(self, entity_id: int) -> Optional[T]:
        """Get by PK or None."""
        return self.db.get(self.model, entity_id)

    def delete(self, entity: T) -> None:
        """Delete (flush but don't commit)."""
        self.db.delete(entity)
        self.db.flush()

    def list_by(self, *criteria) -> Sequence[T]:
        """List by SQLAlchemy boolean criteria."""
        stmt = select(self.model).where(*criteria)
        return list(self.db.scalars(stmt).all())
