# app/api/routes/citations.py
"""Citation endpoints: list source types, validate details (dry-run), and CRUD.

Scope
-----
M2:
    - Type discovery endpoints.
    - `/citations/validate` remains a *dry-run* (no DB writes), now powered by
      ValidationService (M5 shape).

M3:
    - Create/Edit/Delete flows for citations.
    - Validate + normalize before persist.

M5:
    - `/citations/validate` returns structured helper output.

M6:
    - Create/Patch accept an optional *format-now* toggle (body extra or query `?format=true`)
      to compute and store `formatted_text` immediately.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_validation_service
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
from app.services.validation_service import ValidationService

# Primary router for /citations endpoints
router = APIRouter(prefix="/citations", tags=["citations"])

# Separate router for global meta endpoints (alias for source-type discovery)
META_ROUTER = APIRouter(prefix="/meta", tags=["meta"])


def _entity_to_out(entity: Any) -> Dict[str, Any]:
    """Map an ORM Citation entity to the `CitationOut` shape.

    This function is defensive against minor naming differences that can occur
    during refactors (e.g., `type` vs `source_type`, `facts` vs `facts_jsonb`).

    Args:
        entity: ORM instance representing a citation.

    Returns:
        A dict that conforms to `CitationOut`.
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
    """Generate a human-friendly label for a source type value.

    Example:
        "journal_article" -> "Journal Article"
    """
    return value.replace("_", " ").title()


def _all_source_types() -> List[dict[str, str]]:
    """Return all supported source types as value/label pairs."""
    return [{"value": st.value, "label": _source_type_label(st.value)} for st in SourceType]


def _extract_format_now(
    payload: object,
    format_param: Optional[bool],
    format_now_param: Optional[bool],
) -> bool:
    """Determine whether caller requested immediate formatting (M6).

    Resolution priority:
        1) Explicit query flags: `?format=true|false` or `?format_now=true|false`
           (the latter wins if both are provided).
        2) Extra body field `format` or `format_now` (ignored by Pydantic model but
           available via `model_extra` in Pydantic v2). Either truthy enables formatting.

    Args:
        payload: The Pydantic model instance received in the body.
        format_param: Parsed query parameter `format`.
        format_now_param: Parsed query parameter `format_now`.

    Returns:
        True if formatting should run immediately.
    """
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

    # Best-effort fallback for environments where extras might be attached to __dict__
    # (defensive; harmless if absent).
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
    """Validate raw details against required & format rules for the given source type.

    This endpoint performs a *dry-run*:
        - It does not write to the database.
        - It returns a structured payload with helper fields for UX.

    Returns:
        ValidationResponse: M5-shaped payload with `missing_required`,
        `format_issues`, `suggestions`, and `normalized_facts`.
    """
    try:
        # payload.type is a SourceType (enum); the service accepts the enum.
        return validation_service.validate_with_helpers(payload.type, payload.details)
    except ValueError as exc:
        # Defensive: bad enum or schema-level error mapping to 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# ----------------------------
# CRUD (persists, uses normalized facts)
# ----------------------------
@router.get("", response_model=list[CitationOut])
def list_citations(
    library_id: Optional[int] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CitationOut]:
    """List user's citations, optionally filtered by library/source_type; supports pagination.

    Note:
        Response model is a flat list for now. If/when you switch to a paged contract,
        return a Page object (items, total, page, size).
    """
    try:
        entities = citation_service.list_for_user(
            db,
            user_id=user.id,
            library_id=library_id,
            source_type=source_type,
            page=page,
            size=size,
        )
    except ValueError as exc:
        # e.g., invalid enum for source_type propagated by service
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
    """Validate and persist a citation; stores normalized facts.

    If `format=true` (or `format_now=true`) is provided as a query parameter,
    or an extra body field `format` / `format_now` is present, the service will
    also compute and persist `formatted_text` immediately (M6).
    """
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
        # e.g., library not found or not owned by user
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        # e.g., validation errors bubbled up as 400 by service
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
    """Update details/style/library for a citation.

    The service:
        - merges partial details,
        - re-validates,
        - normalizes,
        - persists,
        - and (optionally) formats `formatted_text` when requested via the
          *format-now* toggle.
    """
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
        # Not found, not owned, or target library not owned by the user
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        # Validation failure or bad input
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
