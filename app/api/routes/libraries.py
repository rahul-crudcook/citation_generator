"""Library CRUD routes (M3)."""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.library import LibraryCreate, LibraryOut, LibraryUpdate

router = APIRouter(prefix="/libraries", tags=["libraries"])


def _import_library_model() -> Any:
    """Import the Library ORM lazily so the router module always loads.

    We try `app.models.library.Library`. If not found, we raise a 500 at runtime
    (clear message) instead of failing module import and silently removing routes.
    """
    try:
        from app.models.library import Library  # type: ignore # pylint: disable=import-outside-toplevel
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Library model not found at app.models.library.Library. "
                "Create the model (id, user_id, name, timestamps) or adjust the import."
            ),
        ) from exc
    return Library


def _get_owned_library_or_404(db: Session, *, library_id: int, owner_id: int) -> Any:
    """Fetch a library by id, ensuring it belongs to the current user."""
    Library = _import_library_model()  # noqa: N806
    lib: Optional[Any] = (
        db.query(Library)
        .filter(Library.id == library_id, Library.user_id == owner_id)  # type: ignore[attr-defined]
        .first()
    )
    if lib is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library not found")
    return lib


@router.post("", response_model=LibraryOut, status_code=status.HTTP_201_CREATED)
def create_library(
    payload: LibraryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LibraryOut:
    """Create a new library for the current user."""
    Library = _import_library_model()  # noqa: N806
    lib = Library(user_id=user.id, name=payload.name)  # type: ignore[attr-defined]
    db.add(lib)
    db.flush()  # allocate id before commit for response shaping
    return LibraryOut.model_validate(lib)


@router.get("", response_model=List[LibraryOut])
def list_libraries(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[LibraryOut]:
    """List libraries owned by the current user."""
    Library = _import_library_model()  # noqa: N806
    order_col = getattr(Library, "created_at", Library.id)  # fallback to id
    libs = (
        db.query(Library)
        .filter(Library.user_id == user.id)  # type: ignore[attr-defined]
        .order_by(order_col.desc())
        .all()
    )
    return [LibraryOut.model_validate(l) for l in libs]


@router.patch("/{library_id}", response_model=LibraryOut)
def update_library(
    payload: LibraryUpdate,
    library_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LibraryOut:
    """Rename a library (owner-only)."""
    lib = _get_owned_library_or_404(db, library_id=library_id, owner_id=user.id)
    if payload.name is not None:
        lib.name = payload.name  # type: ignore[attr-defined]
    db.add(lib)
    return LibraryOut.model_validate(lib)


@router.delete(
    "/{library_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,  # <-- critical: no JSON body for 204
)
def delete_library(
    library_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a library (owner-only)."""
    lib = _get_owned_library_or_404(db, library_id=library_id, owner_id=user.id)
    db.delete(lib)
    # Explicitly return an empty 204 response
    return Response(status_code=status.HTTP_204_NO_CONTENT)
