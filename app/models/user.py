"""User model."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    """Application user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        sa.String(length=320), nullable=False, unique=True, index=True
    )
    display_name: Mapped[str | None] = mapped_column(sa.String(length=160), nullable=True)
    provider: Mapped[str] = mapped_column(
        sa.String(length=32), nullable=False, server_default="local"
    )
    password_hash: Mapped[str | None] = mapped_column(sa.String(length=255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("true")
    )
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    libraries = relationship(
        "Library",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    citations = relationship(
        "Citation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"User(id={self.id!r}, email={self.email!r})"
