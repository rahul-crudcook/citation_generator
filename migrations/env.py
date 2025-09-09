"""Alembic environment wired to our SQLAlchemy Base & runtime settings.

Notes for linters:
- Alembic exposes attributes on `context` dynamically; Pylint can't infer them.
- We explicitly disable a few messages only for this file.
"""
from __future__ import annotations

# pylint: disable=wrong-import-position, no-member

from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- Ensure project importable when running `alembic` from repo root ---
ROOT = Path(__file__).resolve().parents[1]  # .../citation_generator
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import app settings & Base AFTER sys.path fix
from app.core.config import settings  # noqa: E402
from app.db.session import Base  # noqa: E402

# Alembic Config object (reads alembic.ini; merges TOML if present)
config = context.config  # type: ignore[attr-defined]

# Configure Python logging via alembic.ini if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject our runtime database URL (overrides sqlalchemy.url in .ini)
config.set_main_option("sqlalchemy.url", settings.database_url)

# Tell Alembic which metadata to compare/migrate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(  # type: ignore[attr-defined]
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():  # type: ignore[attr-defined]
        context.run_migrations()  # type: ignore[attr-defined]


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),  # type: ignore[attr-defined]
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(  # type: ignore[attr-defined]
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=False,
        )
        with context.begin_transaction():  # type: ignore[attr-defined]
            context.run_migrations()  # type: ignore[attr-defined]


if context.is_offline_mode():  # type: ignore[attr-defined]
    run_migrations_offline()
else:
    run_migrations_online()
