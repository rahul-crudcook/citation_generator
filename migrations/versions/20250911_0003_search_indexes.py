# pylint: disable=invalid-name,no-member
# pylint: disable=W0718
"""Alembic migration: add search-related indexes for citations.

This migration:
1) Attempts to enable the `pg_trgm` extension (if available), guarding against
   environments where the extension is not present or not permitted.
2) Adds a functional index on `lower(style)` to accelerate style filtering.
3) Adds a trigram GIN index (if `pg_trgm` is installed) over a concatenation of
   common text fields inside `facts` to speed up free-text search.

Notes
-----
- The trigram index creation is wrapped in a DO block that checks whether
  `pg_trgm` is installed (`pg_extension`), avoiding errors on platforms where
  the extension is unavailable.
- Downgrade drops only the created indexes; it does not drop the extension.
"""

from __future__ import annotations

from typing import Any, Callable

from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers (adjust `down_revision` to your actual previous rev)
# ---------------------------------------------------------------------------
revision = "20250911_0003"
down_revision = "20250908_0002"   # was '0002_previous_migration' — fix this
branch_labels = None
depends_on = None

# Provide a concrete callable reference for Pylint and type checkers.
# In normal Alembic runs, `op.execute` exists; the fallback is only for
# static analysis environments that may not load Alembic's context.
try:
    EXECUTE: Callable[[str], Any] = op.execute  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    def EXECUTE(_: str) -> None:  # noqa: D401 - trivial fallback
        """No-op fallback for static analysis environments."""
        return


def upgrade() -> None:
    """Apply the migration: enable pg_trgm (best-effort) and create indexes."""
    # 1) Best-effort enable pg_trgm; ignore if not available or not permitted.
    EXECUTE(
        """
        DO $$
        BEGIN
            BEGIN
                CREATE EXTENSION IF NOT EXISTS pg_trgm;
            EXCEPTION
                WHEN undefined_file THEN
                    -- pg_trgm not available on this server; skip.
                    NULL;
                WHEN insufficient_privilege THEN
                    -- Extension creation not permitted; skip.
                    NULL;
            END;
        END
        $$;
        """
    )

    # 2) Index for style equality/ILIKE filters.
    EXECUTE(
        """
        CREATE INDEX IF NOT EXISTS ix_citations_style_lower
        ON citations (lower(style));
        """
    )

    # 3) Trigram GIN index for free-text search across common fields in `facts`.
    #    Only create if pg_trgm is installed (present in pg_extension).
    EXECUTE(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
                CREATE INDEX IF NOT EXISTS ix_citations_search_trgm
                ON citations
                USING gin (
                    (
                        lower(
                            coalesce(facts->>'article_title','') || ' ' ||
                            coalesce(facts->>'journal_title','') || ' ' ||
                            coalesce(facts->>'title','') || ' ' ||
                            coalesce(facts->>'work_title','') || ' ' ||
                            coalesce(facts->>'site_title','') || ' ' ||
                            coalesce(facts->>'publisher','')
                        )
                    ) gin_trgm_ops
                );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Revert the migration: drop created indexes (keep extension intact)."""
    EXECUTE(
        """
        DROP INDEX IF EXISTS ix_citations_style_lower;
        """
    )
    EXECUTE(
        """
        DROP INDEX IF EXISTS ix_citations_search_trgm;
        """
    )
