# app/api/routes/citations.py
"""Citation endpoints: discovery, validation (dry-run), CRUD, export, and bulk ops.

Scope
-----
M2:
    - Type discovery endpoints.
    - `/citations/validate` remains a *dry-run* (no DB writes), powered by
      ValidationService (M5 shape).

M3:
    - Create/Edit/Delete flows for citations.
    - Validate + normalize before persist.

M5:
    - `/citations/validate` returns structured helper output.

M6:
    - Create/Patch accept an optional *format-now* toggle (body extra or query
      `?format=true`) to compute and store `formatted_text` immediately.

M7:
    - `GET /citations/{citation_id}/export?type=docx|txt|bib|json`
      Streams a single citation export as an attachment. Ownership enforced.

M8:
    - Extend `GET /citations` with advanced filters: `query`, `style`,
      `source_type`, `library_id`, `page`, `size`.
    - Bulk actions:
        * `POST /citations/bulk/delete`  body: {"ids":[...]}
        * `POST /citations/bulk/move`    body: {"ids":[...], "library_id": ...}
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_validation_service  # type: ignore
from app.core.enums import SourceType
from app.models.user import User
from app.schemas.citation import (
    CitationCreateIn,
    CitationOut,
    CitationUpdateIn,
    CitationValidateIn,
    ValidationResponse,
)
from app.services.citation_service import citation_service
from app.services.export_service import ExportService
from app.services.format_service import FormatService
from app.services.validation_service import ValidationService

# Primary router for /citations endpoints
router = APIRouter(prefix="/citations", tags=["citations"])

# Separate router for global meta endpoints (alias for source-type discovery)
META_ROUTER = APIRouter(prefix="/meta", tags=["meta"])


class ExportTypeEnum(str, Enum):
    """Supported export types for single-citation export (M7)."""

    TXT = "txt"
    DOCX = "docx"
    BIB = "bib"
    JSON = "json"


# ----------------------------
# Bulk request models (M8)
# ----------------------------

class BulkDeleteIn(BaseModel):
    """Request payload for bulk deletion of citations."""

    ids: List[int] = Field(..., description="Non-empty list of citation IDs to delete.")

    @field_validator("ids")
    @classmethod
    def _validate_ids(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("`ids` must be a non-empty list.")
        if any((not isinstance(x, int)) or x <= 0 for x in value):
            raise ValueError("All `ids` must be positive integers.")
        return value


class BulkMoveIn(BaseModel):
    """Request payload for bulk move of citations into a library."""

    ids: List[int] = Field(..., description="Non-empty list of citation IDs to move.")
    library_id: int = Field(..., ge=1, description="Destination library ID (positive integer).")

    @field_validator("ids")
    @classmethod
    def _validate_ids(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("`ids` must be a non-empty list.")
        if any((not isinstance(x, int)) or x <= 0 for x in value):
            raise ValueError("All `ids` must be positive integers.")
        return value


def _build_export_service(db: Session) -> ExportService:
    """Create an ExportService instance with its FormatService dependency."""
    fmt = FormatService()
    return ExportService(db=db, format_service=fmt)


def _entity_to_out(entity: Any) -> Dict[str, Any]:
    """Map an ORM Citation entity to the `CitationOut` shape.

    Defensive against minor naming differences during refactors.
    """
    return {
        "id": getattr(entity, "id", None),
        "type": getattr(entity, "type", None) or getattr(entity, "source_type", None),
        "details": (
            getattr(entity, "details", None)
            or getattr(entity, "normalized_facts", None)
            or getattr(entity, "facts", None)
            or getattr(entity, "facts_json", None)
            or getattr(entity, "facts_jsonb", None)
            or {}
        ),
        "style": getattr(entity, "style", None),
        "formatted_text": getattr(entity, "formatted_text", None),
        "library_id": getattr(entity, "library_id", None),
        "created_at": getattr(entity, "created_at", None),
        "updated_at": getattr(entity, "updated_at", None),
    }


def _source_type_label(value: str) -> str:
    """Generate a human-friendly label for a source type value."""
    return value.replace("_", " ").title()


def _all_source_types() -> List[dict[str, str]]:
    """Return all supported source types as value/label pairs."""
    return [{"value": st.value, "label": _source_type_label(st.value)} for st in SourceType]


def _extract_format_now(
    payload: object,
    format_param: Optional[bool],
    format_now_param: Optional[bool],
) -> bool:
    """Determine whether caller requested immediate formatting (M6)."""
    # Query wins over body.
    if format_now_param is not None:
        return bool(format_now_param)
    if format_param is not None:
        return bool(format_param)

    # Try to read extra body fields (Pydantic v2 keeps them in `model_extra`).
    extra = getattr(payload, "model_extra", None)
    if isinstance(extra, dict):
        if "format_now" in extra:
            return bool(extra.get("format_now"))
        if "format" in extra:
            return bool(extra.get("format"))

    # Best-effort fallback where extras might be attached to __dict__.
    dunder = getattr(payload, "__dict__", None)
    if isinstance(dunder, dict):
        if "format_now" in dunder:
            return bool(dunder.get("format_now"))
        if "format" in dunder:
            return bool(dunder.get("format"))

    return False


# ----------------------------
# Discovery (types)
# ----------------------------
@router.get("/types", response_model=list[dict[str, str]])
def list_source_types() -> list[dict[str, str]]:
    """List supported source types (value + label) under the /citations namespace."""
    return _all_source_types()


@META_ROUTER.get("/source-types", response_model=list[dict[str, str]])
def list_source_types_alias() -> list[dict[str, str]]:
    """Alias: List supported source types at /meta/source-types for client bootstrapping."""
    return _all_source_types()


# ----------------------------
# Validation (dry-run, M5)
# ----------------------------
@router.post(
    "/validate",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
)
def validate_citation(
    payload: CitationValidateIn,
    _db: Session = Depends(get_db),  # kept for parity/metrics, unused (no writes)
    _user: User = Depends(get_current_user),  # require auth to scope to user space
    validation_service: ValidationService = Depends(get_validation_service),
) -> ValidationResponse:
    """Validate raw details against required & format rules for the given source type."""
    try:
        return validation_service.validate_with_helpers(payload.type, payload.details)
    except ValueError as exc:  # pragma: no cover - defensive path
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# ----------------------------
# CRUD (persist normalized facts)
# ----------------------------
@router.get("", response_model=list[CitationOut])
def list_citations(
    query: Optional[str] = Query(
        default=None,
        description="Free-text search across common fields (title/author/journal/publisher).",
    ),
    style: Optional[str] = Query(
        default=None, description="Filter by citation style key (e.g., 'apa')."),
    source_type: Optional[str] = Query(default=None,
                                    description="Filter by source type (e.g., 'journal_article')."),
    library_id: Optional[int] = Query(default=None, description="Filter by owning library id."),
    page: int = Query(1, ge=1, description="Page number (1-based)."),
    size: int = Query(50, ge=1, le=200, description="Page size."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CitationOut]:
    """List user's citations with filters & pagination (M8)."""
    try:
        entities = citation_service.list_for_user(
            db,
            user_id=user.id,
            library_id=library_id,
            source_type=source_type,
            style=style,
            query=query,
            page=page,
            size=size,
        )
    except ValueError as exc:  # pragma: no cover - defensive path
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return [_entity_to_out(c) for c in entities]


@router.post("", response_model=CitationOut, status_code=status.HTTP_201_CREATED)
def create_citation(
    payload: CitationCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    # M6: allow formatting via query flag as well
    format_q: Optional[bool] = Query(default=None, alias="format"),
    format_now_q: Optional[bool] = Query(default=None, alias="format_now"),
) -> CitationOut:
    """Validate and persist a citation; stores normalized facts."""
    try:
        format_now = _extract_format_now(payload, format_q, format_now_q)
        entity = citation_service.create(
            db,
            user_id=user.id,
            source_type=payload.type,
            details=payload.details,
            style=payload.style,
            library_id=payload.library_id,
            format_now=format_now,
        )
        return _entity_to_out(entity)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/{citation_id}", response_model=CitationOut)
def get_citation(
    citation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CitationOut:
    """Get a single citation owned by the current user."""
    try:
        entity = citation_service.get_owned(db, user_id=user.id, citation_id=citation_id)
        return _entity_to_out(entity)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch("/{citation_id}", response_model=CitationOut)
def update_citation(
    citation_id: int,
    payload: CitationUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    # M6: allow formatting via query flag as well
    format_q: Optional[bool] = Query(default=None, alias="format"),
    format_now_q: Optional[bool] = Query(default=None, alias="format_now"),
) -> CitationOut:
    """Update details/style/library for a citation (with optional format-now)."""
    try:
        format_now = _extract_format_now(payload, format_q, format_now_q)
        entity = citation_service.update(
            db,
            user_id=user.id,
            citation_id=citation_id,
            details=payload.details,
            style=payload.style,
            library_id=payload.library_id,
            format_now=format_now,
        )
        return _entity_to_out(entity)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete(
    "/{citation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,  # ensures no response body for 204
)
def delete_citation(
    citation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a citation owned by the current user (returns 204 No Content)."""
    try:
        citation_service.delete(db, user_id=user.id, citation_id=citation_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


# ----------------------------
# M8: Bulk operations
# ----------------------------

@router.post("/bulk/delete", summary="Bulk delete citations", status_code=status.HTTP_200_OK)
def bulk_delete_citations(
    payload: BulkDeleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, int]:
    """Delete multiple citations owned by the current user.

    Returns:
        {"deleted": <count>}
    """
    try:
        deleted = citation_service.bulk_delete(
            db,
            user_id=user.id,
            ids=payload.ids,
        )
        return {"deleted": int(deleted)}
    except ValueError as exc:
        # Bad IDs or validation issues
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/bulk/move", summary="Bulk move citations to a library",
             status_code=status.HTTP_200_OK)
def bulk_move_citations(
    payload: BulkMoveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, int]:
    """Move multiple citations to a target library (must be owned by user).

    Returns:
        {"moved": <count>}
    """
    try:
        moved = citation_service.bulk_move(
            db,
            user_id=user.id,
            ids=payload.ids,
            library_id=payload.library_id,
        )
        return {"moved": int(moved)}
    except LookupError as exc:
        # Library not found or not owned
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        # Bad IDs or validation issues
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# ----------------------------
# M7: Single-citation export
# ----------------------------
@router.get(
    "/{citation_id}/export",
    summary="Export a single citation (TXT/DOCX/BibTeX/JSON)",
)
def export_citation(
    citation_id: int,
    export_type: ExportTypeEnum = Query(
        ...,
        alias="type",
        description="Export type: txt | docx | bib | json",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Return a single citation export as an attachment (ownership enforced)."""
    service = _build_export_service(db)

    try:
        artifact = service.export_single(
            user_id=int(user.id),  # type: ignore[attr-defined]
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
