"""Export job model scaffold (for later bulk exports)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ExportJob(Base):
    """A background export job (placeholder for M3)."""

    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(sa.String(length=16), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(length=16), nullable=False, server_default="pending"
    )
    file_path: Mapped[str | None] = mapped_column(sa.String(length=512), nullable=True)

    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )

    user = relationship("User")
