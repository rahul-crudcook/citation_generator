"""
Add params_json column to the exports table.

This migration introduces a new JSON column named `params_json` on the
`exports` table. It allows flexible storage of export parameters as a JSON
object instead of adding multiple discrete columns.

Revision ID: 20250912_0004
Revises: 20250911_0003
Create Date: 2025-09-12 10:55:00
"""

# pylint: disable=invalid-name,no-member
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250912_0004"
down_revision = "20250911_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration: add params_json column to exports."""
    op.add_column("exports", sa.Column("params_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Rollback the migration: drop params_json column from exports."""
    op.drop_column("exports", "params_json")
