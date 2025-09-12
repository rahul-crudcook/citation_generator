# app/api/routes/exports.py
"""Export-related API endpoints.

This module exposes:
- M7 (streaming/inline exports)
  * GET /citations/{citation_id}/export?type=docx|txt|bib|json
  * GET /libraries/{library_id}/export?type=docx|txt|bib|json[&style=apa|mla|...]

- M8 (async bulk export jobs)
  * POST /exports/bulk
      Body:
        { "library_id": <int>, "type": "docx|txt|bib|json", "style": "apa|..." }
        OR
        { "ids": [<int>, ...], "type": "docx|txt|bib|json", "style": "apa|..." }
      Returns: { "id": <job_id>, "status": "pending" }

  * GET /exports/{id}
      Returns: { "id": <job_id>, "status": "pending|running|succeeded|failed",
                 "file_path": "<path>|null" }

Implementation notes
--------------------
* M7 endpoints remain synchronous streaming responses (no background work).
* M8 endpoint creates a DB job row and schedules an **async** worker, then
  returns 202 so clients can poll /exports/{id}.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

# Local deps/services
from app.api.deps import get_current_user, get_db  # type: ignore
from app.schemas.export import (
    ExportBulkRequestByIds,
    ExportBulkRequestByLibrary,
    ExportJobOut,
)
from app.services.export_service import ExportService
from app.services.format_service import FormatService
from app.services.job_service import JobService
from app.models.export_job import ExportKind, ExportStatus

router = APIRouter(tags=["exports"])


class ExportTypeEnum(str, Enum):
    """Supported export types for single-streaming endpoints (M7)."""

    TXT = "txt"
    DOCX = "docx"
    BIB = "bib"
    JSON = "json"


# ---------------------------------------------------------------------------
# Helpers / small factories (simple, testable construction points)
# ---------------------------------------------------------------------------


def _build_export_service(db: Session) -> ExportService:
    """Build an ExportService instance for the request."""
    fmt = FormatService()
    return ExportService(db=db, format_service=fmt)


def _build_job_service() -> JobService:
    """Build a JobService (uses default session factory for background work)."""
    return JobService()


# ---------------------------------------------------------------------------
# M7: Streaming exports (single citation / whole library)
# ---------------------------------------------------------------------------


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
    """Stream a single citation export as a file attachment.

    Ownership is enforced inside the service.
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
        # E.g., missing optional deps (like python-docx) for DOCX exports.
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
            "If omitted, the service may infer a dominant style or default to APA."
        ),
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),  # type: ignore
) -> StreamingResponse:
    """Stream a full-library export as a file attachment.

    Ownership is enforced inside the service.
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


# ---------------------------------------------------------------------------
# M8: Bulk export job endpoints (async scheduling)
# ---------------------------------------------------------------------------


@router.post(
    "/exports/bulk",
    response_model=ExportJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Schedule a bulk export (by library or list of citation IDs).",
)
async def schedule_bulk_export(
    payload: Union[ExportBulkRequestByLibrary, ExportBulkRequestByIds],
    current_user=Depends(get_current_user),  # type: ignore
) -> ExportJobOut:
    """Create a DB job row and schedule its background worker.

    The worker runs asynchronously and will update the job's status and file path.

    Returns:
        ExportJobOut with initial `status='pending'`.
    """
    job_service = _build_job_service()

    # Determine job kind and params persisted into `exports.params_json`
    if isinstance(payload, ExportBulkRequestByLibrary):
        params = {
            "library_id": int(payload.library_id),
            "type": str(payload.type),
            "style": payload.style,
        }
        kind = ExportKind.LIBRARY
    elif isinstance(payload, ExportBulkRequestByIds):
        params = {
            "ids": [int(x) for x in payload.ids],
            "type": str(payload.type),
            "style": payload.style,
        }
        kind = ExportKind.IDS
    else:  # defensive (should never happen due to Pydantic models)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    # Persist job (pending)
    job = job_service.create_export_job(
        user_id=int(current_user.id),  # type: ignore[attr-defined]
        kind=kind,
        params=params,
    )

    # Schedule the async worker on the current event loop.
    # This route is async, so `create_task` inside the service is safe.
    await job_service.schedule_export_job(job.id)

    return ExportJobOut(id=int(job.id), status=ExportStatus.PENDING.value, file_path=None)


@router.get(
    "/exports/{job_id}",
    response_model=ExportJobOut,
    status_code=status.HTTP_200_OK,
    summary="Get export job status.",
)
def get_export_job(
    job_id: int = Path(..., ge=1, description="Export job ID"),
    current_user=Depends(get_current_user),  # type: ignore
) -> ExportJobOut:
    """Return the current state of a bulk export job (for client polling)."""
    job_service = _build_job_service()
    job = job_service.get_job(
        user_id=int(current_user.id), job_id=job_id  # type: ignore[attr-defined]
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    file_path = getattr(job, "file_path", None)
    # If the model uses a plain string, leave it; if enum-like, take .value
    status_str = getattr(job.status, "value", str(job.status))
    return ExportJobOut(id=int(job.id), status=status_str, file_path=file_path)
