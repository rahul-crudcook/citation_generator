# app/models/export_job.py
"""Export Job model & enums (M8).

This SQLAlchemy model backs background/bulk export jobs that the FE can poll.
It is intentionally “boring” and portable: we store enums as lowercase strings
and keep a JSON column for arbitrary job parameters.

Key choices
----------
- ORM attribute `kind` is stored in DB column named **"type"** for backward
  compatibility with an existing table/queries that use "type".
- `params_json` holds the request payload used to generate the export
  (e.g., {"library_id": 3, "type": "txt", "style": "apa"}).
- Timestamps: `created_at`, `updated_at`, `started_at`, `finished_at`.
- `error` stores a short error string in case the job fails.

Columns expected in table `exports`
-----------------------------------
id (bigint, pk, autoincrement)
user_id (bigint, fk -> users.id, not null)
type (varchar(16), not null)              <-- mapped from ORM attr `kind`
status (varchar(16), not null, default 'pending')
params_json (json, nullable)
file_path (varchar(512), nullable)
error (varchar(512), nullable)
created_at (timestamptz, default now(), not null)
updated_at (timestamptz, default now(), on update now(), not null)
started_at (timestamptz, nullable)
finished_at (timestamptz, nullable)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ExportKind(str, Enum):
    """Kinds of bulk export jobs."""
    LIBRARY = "library"  # export by a library id
    IDS = "ids"          # export by an explicit list of citation ids


class ExportStatus(str, Enum):
    """Lifecycle states for an export job."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExportJob(Base):
    """ORM model for a background/bulk export job."""

    __tablename__ = "exports"

    # --- Identity / ownership -------------------------------------------------
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        doc="Owner of the job (who requested the export).",
    )

    # --- Core job fields ------------------------------------------------------
    # NOTE: ORM attribute `kind` is stored in DB column "type".
    kind: Mapped[str] = mapped_column(
        "type",
        sa.String(length=16),
        nullable=False,
        doc='Job kind; stored as string: "library" | "ids".',
    )

    status: Mapped[str] = mapped_column(
        sa.String(length=16),
        nullable=False,
        server_default=ExportStatus.PENDING.value,
        doc='Job status as string: "pending" | "running" | "succeeded" | "failed".',
    )

    # Arbitrary parameters for the job (e.g., {"library_id": 3, "type": "docx", "style": "apa"})
    params_json: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)

    # Path to the generated file (set when SUCCEEDED)
    file_path: Mapped[Optional[str]] = mapped_column(sa.String(length=512), nullable=True)

    # Short error string (set when FAILED)
    error: Mapped[Optional[str]] = mapped_column(sa.String(length=512), nullable=True)

    # --- Timestamps -----------------------------------------------------------
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )

    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        onupdate=sa.text("now()"),
        nullable=False,
    )

    started_at: Mapped[Optional[sa.DateTime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    finished_at: Mapped[Optional[sa.DateTime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # --- Relationships --------------------------------------------------------
    user = relationship("User")

    # --- Convenience enum accessors ------------------------------------------
    @property
    def kind_enum(self) -> ExportKind:
        """Return the job kind as :class:`ExportKind` (fallback to IDS if invalid)."""
        try:
            return ExportKind(self.kind)
        except ValueError:
            return ExportKind.IDS

    @kind_enum.setter
    def kind_enum(self, value: ExportKind) -> None:
        """Set job kind from :class:`ExportKind`."""
        self.kind = value.value

    @property
    def status_enum(self) -> ExportStatus:
        """Return the job status as :class:`ExportStatus` (fallback to PENDING if invalid)."""
        try:
            return ExportStatus(self.status)
        except ValueError:
            return ExportStatus.PENDING

    @status_enum.setter
    def status_enum(self, value: ExportStatus) -> None:
        """Set job status from :class:`ExportStatus`."""
        self.status = value.value

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ExportJob id={self.id} user_id={self.user_id} "
            f"kind={self.kind} status={self.status}>"
        )
