"""Library endpoints: create, list, update, and delete.

Routes:
- GET    /libraries              -> list libraries owned by the current user
- POST   /libraries              -> create a new library
- PATCH  /libraries/{library_id} -> rename an existing library (owner-only)
- DELETE /libraries/{library_id} -> delete a library (owner-only; cascades citations)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.library import LibraryCreate, LibraryOut, LibraryUpdate
from app.services.library_service import library_service

router = APIRouter(prefix="/libraries", tags=["libraries"])


@router.get("", response_model=list[LibraryOut])
def list_libraries(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LibraryOut]:
    """List all libraries owned by the current authenticated user."""
    return library_service.list_for_user(db, user_id=user.id)


@router.post("", response_model=LibraryOut, status_code=status.HTTP_201_CREATED)
def create_library(
    payload: LibraryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LibraryOut:
    """Create a new library for the current user."""
    try:
        entity = library_service.create(db, user_id=user.id, name=payload.name)
        return entity
    except ValueError as exc:
        # Bad input (e.g., empty/too-long name after trimming).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.patch("/{library_id}", response_model=LibraryOut)
def update_library(
    library_id: int,
    payload: LibraryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LibraryOut:
    """Rename an existing library owned by the current user."""
    try:
        entity = library_service.rename(
            db, user_id=user.id, library_id=library_id, new_name=payload.name
        )
        return entity
    except LookupError as exc:
        # Library not found or not owned by the user.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        # Invalid new name (validation failed).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete("/{library_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_library(
    library_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a library owned by the current user (citations cascade)."""
    try:
        library_service.delete(db, user_id=user.id, library_id=library_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
