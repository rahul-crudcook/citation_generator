"""
Ingest API routes.

This module exposes the `/ingest` HTTP endpoints that power **M4 — Auto-fetchers**.
It follows a light controller (OOP) pattern so the business dependency (the
`IngestService`) is injected and methods live on a controller class.

Responsibilities:
- Accept a link (DOI / ISBN / URL) and optional SourceType hint.
- Call the ingest service to fetch and normalize citation facts.
- Return `{facts, confidence, source}` without persisting to the database.

Notes:
- Validation and normalization are delegated to the service layer.
- This file intentionally contains no external IO logic (HTTP/Redis) and no
  database access; it only orchestrates request/response handling.

Lint/Style:
- Written to satisfy pylint and formatted with black (88-col line length).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_ingest_service
from app.schemas.ingest import IngestLinkRequest, IngestLinkResponse
from app.services.ingest_service import IngestService


router = APIRouter(
    prefix="/ingest",
    tags=["ingest"],
)


class IngestController:
    """HTTP controller for ingest endpoints.

    The controller groups route handlers as instance methods to keep a clear
    separation of concerns and enable easier testing/mocking.

    Attributes:
        ingest_service: The domain service responsible for link ingestion.
    """

    def __init__(self, ingest_service: IngestService) -> None:
        """Initialize the controller.

        Args:
            ingest_service: Service that implements the ingest orchestration
                (detection, fetch, cache, normalize, confidence).
        """
        self._ingest_service = ingest_service

    async def ingest_link(self, payload: IngestLinkRequest) -> IngestLinkResponse:
        """Fetch normalized citation facts from a DOI/ISBN/URL.

        This method calls the ingest service to:
        1) Detect the link type (DOI/ISBN/URL).
        2) Resolve against the configured fetcher(s).
        3) Normalize facts and compute a confidence score.
        4) Return a response payload without saving anything to the DB.

        Args:
            payload: The request body containing an optional `source_type`
                hint and the raw `link` string.

        Returns:
            A structured response with `facts`, `confidence`, and `source`.

        Raises:
            HTTPException: 400 when the link is malformed/unsupported or when
                validation fails at the service layer; 503 when an upstream
                dependency is temporarily unavailable.
        """
        try:
            result = await self._ingest_service.ingest_link(
                link=payload.link,
                source_type=payload.source_type,
            )
        except ValueError as exc:  # Invalid input / unsupported link, etc.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:  # Upstream issues / timeouts surfaced by service
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

        # The service returns a domain result. Adapt it to the API schema.
        return IngestLinkResponse(
            facts=result.facts,
            confidence=result.confidence,
            source=result.source,
        )


@router.post(
    "/link",
    response_model=IngestLinkResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest a DOI/ISBN/URL and return normalized citation facts.",
    response_description=(
        "Normalized facts with confidence and the fetch source; no DB writes."
    ),
)
async def post_ingest_link(
    payload: IngestLinkRequest,
    ingest_service: IngestService = Depends(get_ingest_service),
) -> Any:
    """POST /ingest/link — Paste-a-link endpoint.

    Dependency injection:
        - `ingest_service` is provided by `app.api.deps.get_ingest_service`.
          It encapsulates detection, fetchers, caching, and normalization.

    Args:
        payload: JSON body: `{ "source_type"?: SourceType, "link": str }`
        ingest_service: The ingest service resolved by FastAPI DI.

    Returns:
        IngestLinkResponse JSON.

    Example:
        ```http
        POST /ingest/link
        Content-Type: application/json

        {
          "source_type": "journal_article",
          "link": "https://doi.org/10.1038/s41586-020-2649-2"
        }
        ```
    """
    controller = IngestController(ingest_service=ingest_service)
    return await controller.ingest_link(payload)
