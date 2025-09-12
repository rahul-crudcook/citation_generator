# pylint: disable=invalid-name,no-member
"""create libraries, citations, exports

Revision ID: 20250908_0002
Revises: 20250908_0001
Create Date: 2025-09-08
"""
from __future__ import annotations

# pylint: disable=no-member,invalid-name

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

revision = "20250908_0002"
down_revision = "20250908_0001"
branch_labels = None
depends_on = None

# Reference to an already-created enum type; DO NOT auto-create during table DDL.
source_type_enum = PGEnum(
    name="source_type",
    create_type=False,  # prevents auto CREATE TYPE during table creation
)


def upgrade() -> None:
    """Apply this revision: ensure enum exists, then create tables & indexes."""
    # 1) Create the enum only if it doesn't exist already (idempotent)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'source_type') THEN
                CREATE TYPE source_type AS ENUM (
                    'book',
                    'journal_article',
                    'magazine_newspaper',
                    'encyclopedia',
                    'website'
                );
            END IF;
        END$$;
        """
    )

    # 2) Create tables
    op.create_table(
        "libraries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_libraries_user_id", "libraries", ["user_id"])

    op.create_table(
        "citations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("library_id", sa.BigInteger, nullable=True),
        # IMPORTANT: use the existing enum type reference
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("facts", sa.JSON, nullable=False),
        sa.Column("style", sa.String(length=32), nullable=True),
        sa.Column("formatted_text", sa.Text, nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_citations_user_id", "citations", ["user_id"])
    op.create_index("ix_citations_library_id", "citations", ["library_id"])
    op.create_index("ix_citations_source_type", "citations", ["source_type"])

    op.create_table(
        "exports",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_exports_user_id", "exports", ["user_id"])


def downgrade() -> None:
    """Revert this revision: drop tables & indexes; then drop enum if unused."""
    op.drop_index("ix_exports_user_id", table_name="exports")
    op.drop_table("exports")

    op.drop_index("ix_citations_source_type", table_name="citations")
    op.drop_index("ix_citations_library_id", table_name="citations")
    op.drop_index("ix_citations_user_id", table_name="citations")
    op.drop_table("citations")

    op.drop_index("ix_libraries_user_id", table_name="libraries")
    op.drop_table("libraries")

    # Drop enum only if no longer used
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_depend d ON d.refobjid = t.oid
                WHERE t.typname = 'source_type'
                  AND d.deptype = 'a'  -- auto dependency (in use)
            ) THEN
                DROP TYPE IF EXISTS public.source_type;
            END IF;
        END$$;
        """
    )
