# citation_generator/app/models/citation.py
"""Citation model: normalized facts + style and optional formatted text.

This model stores the canonical, **normalized** citation facts (as JSON/JSONB),
the chosen style (e.g., APA/MLA), and the latest server-generated
``formatted_text`` preview (nullable). The raw client payloads are validated
and normalized in the service layer before persistence.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SourceType
from app.db.session import Base


class Citation(Base):
    """A single citation owned by a user, optionally grouped in a library.

    Fields:
        id: Primary key.
        user_id: Owner (FK → users.id).
        library_id: Optional folder/group (FK → libraries.id, SET NULL on delete).
        source_type: One of :class:`app.core.enums.SourceType`.
        facts: Normalized citation facts (dict-like JSON/JSONB).
        style: Optional style slug (e.g., "apa", "mla").
        formatted_text: Optional cached, server-generated formatted string.
        created_at / updated_at: Timestamps (UTC).

    Relationships:
        user: Back-ref from ``User.citations``.
        library: Back-ref from ``Library.citations``.
    """

    __tablename__ = "citations"

    # ----------------------------
    # Identifiers / ownership
    # ----------------------------
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    library_id: Mapped[Optional[int]] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("libraries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ----------------------------
    # Core data
    # ----------------------------
    source_type: Mapped[SourceType] = mapped_column(
        sa.Enum(SourceType, name="source_type"),
        nullable=False,
        index=True,
        doc="Canonical citation source type.",
    )
    facts: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, doc="Normalized citation facts (JSONB)."
    )
    style: Mapped[Optional[str]] = mapped_column(
        sa.String(length=32),
        nullable=True,
        doc="Optional style slug for formatting (e.g., 'apa', 'mla').",
    )
    formatted_text: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
        doc="Cached formatted string (updated by formatter on demand).",
    )

    # ----------------------------
    # Timestamps
    # ----------------------------
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        doc="Creation timestamp (UTC).",
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        onupdate=sa.text("now()"),
        nullable=False,
        doc="Last update timestamp (UTC).",
    )

    # ----------------------------
    # Relationships
    # ----------------------------
    user = relationship("User", back_populates="citations")
    library = relationship("Library", back_populates="citations")

    # ----------------------------
    # Helpers
    # ----------------------------
    def __repr__(self) -> str:  # pragma: no cover - debug helper
        """Return a concise debug representation."""
        return (
            f"Citation(id={self.id!r}, user_id={self.user_id!r}, "
            f"source_type={self.source_type!r}, style={self.style!r})"
        )
