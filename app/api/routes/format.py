# app/api/routes/format.py
# pylint: disable=W0718
"""Formatting preview endpoints (M6).

Exposes:
    POST /format/preview  → { style, source_type, facts } ⇒ { formatted }

Design
------
- Stateless preview that never writes to the DB.
- Style dispatching and rendering are delegated to `FormatService`.
- Requires authentication (same as other protected endpoints).
- Uses dedicated request/response models from `app.schemas.format`.
  If those models are not present yet, this module falls back to
  minimal inline Pydantic models to keep the app operational.

Usage
-----
Request:
    {
      "style": "apa",
      "source_type": "journal_article",
      "facts": {...}
    }

Response:
    { "formatted": "Author, A. A. (2021). Title..." }
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_user, get_format_service
from app.models.user import User
from app.services.format_service import FormatService

# ---------------------------------------------------------------------------
# Try to import the shared schemas; provide a fallback if not present yet.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - import-time wiring
    from app.schemas.format import (  # type: ignore
        FormatPreviewIn,
        FormatPreviewOut,
    )
except Exception:  # noqa: BLE001 - fallback for bootstrapping
    class FormatPreviewIn(BaseModel):  # type: ignore[no-redef]
        """Fallback request model for /format/preview.

        NOTE: Prefer using `app/schemas/format.py` in production.
        """

        style: str
        source_type: str
        facts: dict[str, Any]

    class FormatPreviewOut(BaseModel):  # type: ignore[no-redef]
        """Fallback response model for /format/preview."""

        formatted: str


# Primary router for /format endpoints
router = APIRouter(prefix="/format", tags=["format"])


@router.post(
    "/preview",
    response_model=FormatPreviewOut,
    status_code=status.HTTP_200_OK,
)
def format_preview(
    payload: FormatPreviewIn,
    _user: User = Depends(get_current_user),
    formatter: FormatService = Depends(get_format_service),
) -> FormatPreviewOut:
    """Return a formatted citation string for the given style and facts.

    This endpoint *does not* persist data. It is intended for client-side
    previews before saving a citation or when experimenting with styles.

    Args:
        payload: The preview request containing the style, source_type, and facts.
        _user:   Authenticated user (required; unused here but enforces access).
        formatter: The shared `FormatService` instance.

    Returns:
        A `FormatPreviewOut` object with the formatted string.

    Raises:
        HTTPException(400): When the style/source_type is unknown or facts are invalid.
    """
    try:
        formatted = formatter.preview(
            style=getattr(payload, "style"),
            source_type=getattr(payload, "source_type"),
            facts=getattr(payload, "facts"),
        )
    except ValueError as exc:
        # Input/selection errors: bad style, unsupported source_type, or
        # irrecoverable formatting issues should surface as 400.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # Defensive guardrail; avoid leaking internals.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Formatting failed unexpectedly.",
        ) from exc

    return FormatPreviewOut(formatted=formatted)


__all__ = ["router"]
