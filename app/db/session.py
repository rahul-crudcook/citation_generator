"""Database engine, session factory, and declarative Base.

This module centralizes database connectivity and ORM base setup.

Components:
    - Base: Declarative base class for all ORM models.
    - engine: Shared SQLAlchemy engine instance, created from DATABASE_URL.
    - SessionLocal: Session factory bound to the engine.

Design:
    - `pool_pre_ping=True` ensures stale connections are recycled.
    - `expire_on_commit=False` keeps objects usable after commit
      (handy in APIs where we return ORM data).
    - No autocommit: transactions are explicit.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""


# Shared engine instance (created once per process).
# In tests you can override DATABASE_URL to use SQLite in-memory.
engine = sa.create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,  # enable 2.0-style behavior consistently
)

# Session factory: short-lived sessions per request (see app/api/deps.py).
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)

__all__ = ["Base", "engine", "SessionLocal"]
