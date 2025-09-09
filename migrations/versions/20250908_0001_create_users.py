"""create users table

Revision ID: 20250908_0001
Revises:
Create Date: 2025-09-08
"""

# pylint: skip-file
from __future__ import annotations

from alembic import op  # type: ignore
import sqlalchemy as sa

# Alembic requires these exact variable names.
# pylint: disable=invalid-name

revision = "20250908_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create users table."""
    op.create_table(  # pylint: disable=no-member
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True, index=True),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default="local",
        ),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Drop users table."""
    op.drop_table("users")  # pylint: disable=no-member
