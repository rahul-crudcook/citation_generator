"""Pydantic schemas for Library CRUD (M3)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LibraryCreate(BaseModel):
    """Payload to create a library."""
    name: str = Field(min_length=1, max_length=200)


class LibraryUpdate(BaseModel):
    """Payload to update a library (partial)."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)


class LibraryOut(BaseModel):
    """Library resource returned to clients."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
