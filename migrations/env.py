"""Alembic environment configuration.

This module wires Alembic to the project's SQLAlchemy metadata and runtime
settings, so `alembic upgrade head` uses the same DB URL the app uses.

Key behaviors
-------------
- Ensures the repository root is on sys.path so `from app...` imports work when
  Alembic is executed from the project root.
- Loads `settings.database_url` and injects it into Alembic's config.
  IMPORTANT: Alembic reads its INI via `configparser`, where `%` is an
  interpolation token. If your DATABASE_URL contains URL-encoded characters
  like `%40` (encoded '@'), we **escape percent signs** to `%%` before setting
  the option to avoid `ValueError: invalid interpolation syntax`.
- Exposes `target_metadata = Base.metadata` so autogenerate can diff models.
- Provides both offline and online migration flows with sensible options:
  compare types & server defaults for more accurate diffs.

Usage
-----
- CLI: `alembic upgrade head`, `alembic revision --autogenerate -m "..."`, etc.
"""

from __future__ import annotations

# Pylint can't infer Alembic's dynamic attributes on `context`.
# Also, we intentionally import after sys.path adjustments below.
# pylint: disable=wrong-import-position, no-member

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# -----------------------------------------------------------------------------
# Make the project importable when running Alembic from repo root
# -----------------------------------------------------------------------------
# Resolve: .../<repo>/migrations/env.py  -> repo root is parents[1]
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import app settings & SQLAlchemy Base AFTER fixing sys.path
from app.core.config import settings  # noqa: E402
from app.db.session import Base  # noqa: E402

# -----------------------------------------------------------------------------
# Alembic configuration / logging
# -----------------------------------------------------------------------------
# Alembic Config object, already loaded from alembic.ini
config = context.config  # type: ignore[attr-defined]

# Configure Python logging using alembic.ini if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# -----------------------------------------------------------------------------
# Inject runtime database URL (escape % for ConfigParser)
# -----------------------------------------------------------------------------
# Alembic's ConfigParser treats '%' as interpolation. Escape them defensively.
_db_url_for_ini = settings.database_url.replace("%", "%%")
config.set_main_option("sqlalchemy.url", _db_url_for_ini)

# Target metadata for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    In offline mode Alembic builds SQL strings without an actual DB connection.
    The URL is embedded in the context so statement output can be generated.

    This mode is useful for environments where direct DB connections are not
    allowed during build, or when you want raw SQL scripts.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(  # type: ignore[attr-defined]
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,            # render bind params as literals
        dialect_opts={"paramstyle": "named"},
        compare_type=True,             # detect type changes
        compare_server_default=True,   # detect server-default changes
    )

    with context.begin_transaction():  # type: ignore[attr-defined]
        context.run_migrations()       # type: ignore[attr-defined]


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In online mode we create an Engine and associate a live connection with the
    context so Alembic can run operations directly against the database.
    """
    # Pull the 'sqlalchemy.*' section as a dict for `engine_from_config`
    ini_section = config.get_section(config.config_ini_section, {})  # type: ignore[attr-defined]

    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # avoid connection pooling during migration
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(  # type: ignore[attr-defined]
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=False,  # set True only for legacy SQLite batch ops
        )

        with context.begin_transaction():  # type: ignore[attr-defined]
            context.run_migrations()       # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# Entrypoint: choose offline vs online
# -----------------------------------------------------------------------------
if context.is_offline_mode():  # type: ignore[attr-defined]
    run_migrations_offline()
else:
    run_migrations_online()
