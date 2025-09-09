"""Citation repository."""
from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.enums import SourceType
from app.models.citation import Citation
from app.repos.base import BaseRepository


class CitationRepository(BaseRepository[Citation]):
    """DB access for Citation objects."""

    def __init__(self, db: Session) -> None:
        super().__init__(db, Citation)

    def create(
        self,
        *,
        user_id: int,
        library_id: int | None,
        source_type: SourceType,
        facts: dict,
        style: str | None,
    ) -> Citation:
        """Create and persist a citation entity."""
        entity = Citation(
            user_id=user_id,
            library_id=library_id,
            source_type=source_type,
            facts=facts,
            style=style,
            formatted_text=None,
        )
        return self.add(entity)

    def get_owned(self, user_id: int, citation_id: int) -> Citation | None:
        """Return a citation only if owned by the user."""
        stmt = select(Citation).where(
            and_(Citation.id == citation_id, Citation.user_id == user_id)
        )
        return self.db.scalars(stmt).first()

    def list_for_user(self, user_id: int, library_id: int | None = None) -> list[Citation]:
        """List citations for a user, optional filter by library."""
        stmt = select(Citation).where(Citation.user_id == user_id)
        if library_id is not None:
            stmt = stmt.where(Citation.library_id == library_id)
        stmt = stmt.order_by(Citation.created_at.desc())
        return list(self.db.scalars(stmt).all())
