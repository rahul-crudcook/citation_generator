"""Pydantic schemas for Library resources.

These schemas define the input/output contracts for the Library endpoints:
- POST /libraries         -> LibraryCreate
- GET  /libraries         -> list[LibraryOut]
- PATCH /libraries/{id}   -> LibraryUpdate
- DELETE /libraries/{id}  -> (no body)
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["LibraryCreate", "LibraryUpdate", "LibraryOut"]

# NOTE:
# We keep schemas explicit (no shared base class) for clarity and stability.
# If you later add more fields (e.g., description), extend these models accordingly.


class LibraryCreate(BaseModel):
    """Input payload for creating a library/folder."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Human-friendly name for the library/folder.",
        examples=["My Research 2025", "Thesis Sources"],
    )


class LibraryUpdate(BaseModel):
    """Input payload for updating a library/folder (PATCH)."""

    # Minimal constraints per your request (no description/examples).
    name: str = Field(min_length=1, max_length=120)


class LibraryOut(BaseModel):
    """Response payload representing a library/folder."""

    id: int
    name: str
    created_at: datetime

    # Allow construction from ORM objects (SQLModel/SQLAlchemy rows).
    model_config = ConfigDict(from_attributes=True)
