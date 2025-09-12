"""
Add audit/status columns to the `exports` table (idempotent).

This migration adds the following columns if they are missing:
- updated_at  (timezone-aware, server default NOW())
- started_at  (timezone-aware, nullable)
- finished_at (timezone-aware, nullable)
- error       (text, nullable)

It’s written defensively so it won’t fail if some columns already exist,
which can happen if a manual migration was applied or a previous run
partially succeeded.

Revision ID: 20250912_0005
Revises: 20250912_0004
Create Date: 2025-09-12 11:12:00
"""

# pylint: disable=invalid-name,no-member
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# Alembic identifiers
revision = "20250912_0005"
down_revision = "20250912_0004"
branch_labels = None
depends_on = None


def _has_column(conn, table_name: str, column_name: str) -> bool:
    """Return True if `column_name` exists on `table_name`."""
    inspector = sa.inspect(conn)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    """Apply the migration: add audit/status columns to `exports` if missing."""
    conn = op.get_bind()

    if not _has_column(conn, "exports", "updated_at"):
        op.add_column(
            "exports",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    if not _has_column(conn, "exports", "started_at"):
        op.add_column(
            "exports",
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_column(conn, "exports", "finished_at"):
        op.add_column(
            "exports",
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_column(conn, "exports", "error"):
        op.add_column("exports", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    """Rollback: remove audit/status columns from `exports` if present."""
    conn = op.get_bind()

    if _has_column(conn, "exports", "error"):
        op.drop_column("exports", "error")

    if _has_column(conn, "exports", "finished_at"):
        op.drop_column("exports", "finished_at")

    if _has_column(conn, "exports", "started_at"):
        op.drop_column("exports", "started_at")

    if _has_column(conn, "exports", "updated_at"):
        op.drop_column("exports", "updated_at")
