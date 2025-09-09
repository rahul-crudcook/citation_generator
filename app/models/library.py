"""Library model: per-user grouping of citations."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Library(Base):
    """A user-owned collection of citations."""

    __tablename__ = "libraries"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(length=120), nullable=False)

    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    user = relationship("User", back_populates="libraries")
    citations = relationship(
        "Citation",
        back_populates="library",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
