# app/api/routes/libraries.py
"""Library CRUD routes (M3) + Library export (M7).

Adds:
- GET /libraries/{library_id}/export?type=docx|txt|bib|json[&style=apa|mla|...]
  Authorizes ownership, generates a single file with proper heading rules
  (e.g., "References" for APA/Chicago/Turabian/Harvard, "Works Cited" for MLA).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db  # type: ignore
from app.models.user import User
from app.schemas.library import LibraryCreate, LibraryOut, LibraryUpdate
from app.services.export_service import ExportService
from app.services.format_service import FormatService

router = APIRouter(prefix="/libraries", tags=["libraries"])


class ExportTypeEnum(str, Enum):
    """Supported export types for library-level export (M7)."""

    TXT = "txt"
    DOCX = "docx"
    BIB = "bib"
    JSON = "json"


def _import_library_model() -> Any:
    """Import the Library ORM lazily so the router module always loads.

    We try `app.models.library.Library`. If not found, we raise a 500 at runtime
    (clear message) instead of failing module import and silently removing routes.
    """
    try:
        # pylint: disable=import-outside-toplevel
        from app.models.library import Library  # type: ignore
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


def _build_export_service(db: Session) -> ExportService:
    """Factory to construct an ExportService with its formatting dependency."""
    fmt = FormatService()
    return ExportService(db=db, format_service=fmt)


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
    db.flush()
    return LibraryOut.model_validate(lib)


@router.get("", response_model=List[LibraryOut])
def list_libraries(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[LibraryOut]:
    """List libraries owned by the current user."""
    Library = _import_library_model()  # noqa: N806
    order_col = getattr(Library, "created_at", Library.id)
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
    response_class=Response,
)
def delete_library(
    library_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a library (owner-only)."""
    lib = _get_owned_library_or_404(db, library_id=library_id, owner_id=user.id)
    db.delete(lib)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------
# M7: Bulk export endpoint (library → single artifact)
# --------------------------------------------------------------------
@router.get(
    "/{library_id}/export",
    summary="Export all citations in a library (TXT/DOCX/BibTeX/JSON) with heading",
    response_class=Response,  # IMPORTANT: return bytes directly (no StreamingResponse)
)
def export_library(
    library_id: int = Path(..., gt=0, description="Library (folder) ID to export"),
    export_type: ExportTypeEnum = Query(
        ...,
        alias="type",
        description="Export type: txt | docx | bib | json",
    ),
    style_for_heading: Optional[str] = Query(
        None,
        alias="style",
        description=(
            "Optional style for heading/format fallback (e.g., apa, mla). "
            "If omitted, the service will infer a dominant style or default to APA."
        ),
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Return a bulk export for a library as an attachment.

    We use a plain `Response` because we already have bytes; `StreamingResponse`
    would treat raw bytes as an iterable of ints and error on `.encode()`.
    """
    lib = _get_owned_library_or_404(db, library_id=library_id, owner_id=user.id)
    service = _build_export_service(db)

    try:
        artifact = service.export_library(
            user_id=int(user.id),  # type: ignore[attr-defined]
            library_id=lib.id,  # type: ignore[attr-defined]
            export_type=export_type.value,
            style_for_heading=style_for_heading,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
        },
    )
