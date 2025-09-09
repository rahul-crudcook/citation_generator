"""Citation model: normalized facts + style and formatted text."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SourceType
from app.db.session import Base


class Citation(Base):
    """A single citation owned by a user, optionally in a library."""

    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    library_id: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("libraries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    source_type: Mapped[SourceType] = mapped_column(
        sa.Enum(SourceType, name="source_type"), nullable=False
    )
    facts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    style: Mapped[str | None] = mapped_column(sa.String(length=32), nullable=True)
    formatted_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    user = relationship("User", back_populates="citations")
    library = relationship("Library", back_populates="citations")
