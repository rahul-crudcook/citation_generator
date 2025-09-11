# app/api/routes/exports.py
"""Export endpoints (M7): single-citation and library-level exports.

Exposes:
- GET /citations/{citation_id}/export?type=docx|txt|bib|json
- GET /libraries/{library_id}/export?type=docx|txt|bib|json[&style=apa|mla|...]

These endpoints generate the export on the fly and stream it back to the client
with the appropriate content type and Content-Disposition filename.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

# Local deps/services
from app.api.deps import get_current_user, get_db  # type: ignore
from app.services.export_service import ExportService
from app.services.format_service import FormatService


router = APIRouter(tags=["exports"])


class ExportTypeEnum(str, Enum):
    """Supported export types for M7."""

    TXT = "txt"
    DOCX = "docx"
    BIB = "bib"
    JSON = "json"


def _build_export_service(db: Session) -> ExportService:
    """Factory to build an ExportService instance for this request.

    Args:
        db: SQLAlchemy session.

    Returns:
        A configured ExportService.
    """
    fmt = FormatService()
    return ExportService(db=db, format_service=fmt)


@router.get(
    "/citations/{citation_id}/export",
    summary="Export a single citation (TXT/DOCX/BibTeX/JSON)",
    response_class=StreamingResponse,
)
def export_citation(
    citation_id: int = Path(..., description="Citation ID to export"),
    export_type: ExportTypeEnum = Query(
        ...,
        alias="type",
        description="Export type: txt | docx | bib | json",
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),  # type: ignore
) -> StreamingResponse:
    """Stream a single citation export as an attachment.

    Ownership is enforced by the service/repository layer.

    Raises:
        HTTPException(404): If the citation does not exist or is not owned.
        HTTPException(400): If an unsupported export type is requested.
        HTTPException(500): For DOCX dependency errors or unexpected failures.
    """
    service = _build_export_service(db)

    try:
        artifact = service.export_single(
            user_id=int(current_user.id),  # type: ignore[attr-defined]
            citation_id=citation_id,
            export_type=export_type.value,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        # E.g., python-docx missing for DOCX exports
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    return StreamingResponse(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            # Optional: guard against MIME sniffing and framing
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get(
    "/libraries/{library_id}/export",
    summary="Export all citations in a library (TXT/DOCX/BibTeX/JSON) with heading",
    response_class=StreamingResponse,
)
def export_library(
    library_id: int = Path(..., description="Library (folder) ID to export"),
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
    current_user=Depends(get_current_user),  # type: ignore
) -> StreamingResponse:
    """Stream a bulk export for a library as an attachment.

    The service enforces ownership and applies heading rules:
      - APA/Chicago/Turabian/Harvard → 'References'
      - MLA → 'Works Cited'

    Raises:
        HTTPException(404): If the library does not exist or is not owned.
        HTTPException(400): If an unsupported export type is requested.
        HTTPException(500): For DOCX dependency errors or unexpected failures.
    """
    service = _build_export_service(db)

    try:
        artifact = service.export_library(
            user_id=int(current_user.id),  # type: ignore[attr-defined]
            library_id=library_id,
            export_type=export_type.value,
            style_for_heading=style_for_heading,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    return StreamingResponse(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
        },
    )
