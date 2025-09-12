# app/api/routes/health.py
"""Health and readiness endpoints (no Redis).

Exposes:
- GET /health/live   : simple liveness check.
- GET /health/ready  : readiness probe that verifies DB connectivity.
- GET /health/deps   : quick dependency probe (DB + external HTTP services).

Note:
The router itself has **no prefix**. `main.py` includes this router with
`prefix="/health"`, so final paths are `/health/live`, `/health/ready`,
and `/health/deps`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_db

router = APIRouter(tags=["health"])


# -----------------------------------------------------------------------------
# Basic liveness
# -----------------------------------------------------------------------------
@router.get("/live", status_code=status.HTTP_200_OK)
def liveness() -> Dict[str, str]:
    """Simple liveness endpoint (does not touch external deps)."""
    return {"status": "alive"}


# -----------------------------------------------------------------------------
# DB readiness helpers
# -----------------------------------------------------------------------------
def _check_db(session: Session) -> bool:
    """Return True if the database connection is healthy.

    Executes a lightweight `SELECT 1` to ensure connectivity and a working session.
    """
    try:
        result = session.execute(text("SELECT 1")).scalar_one()
        return int(result) == 1
    except SQLAlchemyError:
        return False


@router.get("/ready")
def readiness(response: Response, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Readiness gate: verifies that required dependencies are available.

    Currently checks:
      - Database connectivity

    Returns:
        A JSON object with per-component status and an overall state.
    """
    db_ok = _check_db(db)

    overall = "ok" if db_ok else "degraded"
    http_status = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    response.status_code = http_status  # set dynamic status

    return {
        "status": overall,
        "components": {
            "database": "ok" if db_ok else "unavailable",
        },
    }


# -----------------------------------------------------------------------------
# Dependency probe (DB + externals)
# -----------------------------------------------------------------------------
async def _probe_external(
    *,
    head_url: str,
    get_url_fallback: Optional[str] = None,
    timeout_s: float = 2.0,
) -> str:
    """Probe an external HTTP dependency with HEAD then optional GET fallback.

    Args:
        head_url: URL to probe via HTTP HEAD.
        get_url_fallback: If HEAD is unsupported or fails, GET this URL instead.
        timeout_s: Total timeout for the request.

    Returns:
        "ok" if the service responds with a non-5xx status; otherwise a short
        error string (e.g., "down", "timeout", "status: 500").
    """
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s, follow_redirects=True
        ) as client:
            # First try HEAD (lightweight).
            try:
                resp = await client.head(head_url)
                if resp.status_code < 500:
                    return "ok"
                # Fall through to GET if server error.
            except httpx.HTTPError:
                # Fall back to GET below.
                pass

            # Fallback GET (some services disallow HEAD or require a path).
            fallback_url = get_url_fallback or head_url
            resp = await client.get(fallback_url)
            return "ok" if resp.status_code < 500 else f"status:{resp.status_code}"
    except httpx.TimeoutException:
        return "timeout"
    except httpx.HTTPError:
        return "down"
    except Exception:  # pylint: disable=broad-except
        return "down"


@router.get("/deps", status_code=status.HTTP_200_OK)
async def deps_check(db: Session = Depends(get_db)) -> Dict[str, str]:
    """Quick dependency probe for operational dashboards.

    Checks:
        - Database (SELECT 1)
        - Crossref
        - OpenLibrary

    Returns:
        A flat JSON object: {"db": "...", "crossref": "...", "openlibrary": "..."}
        Each value is one of: "ok", "down", "timeout", or "status:<code>".
    """
    # DB: keep it simple and synchronous.
    db_status = "ok" if _check_db(db) else "down"

    # Crossref tends to work with either HEAD to host or GET to a tiny endpoint.
    crossref_status = await _probe_external(
        head_url="https://api.crossref.org/",
        get_url_fallback="https://api.crossref.org/works?rows=0",
        timeout_s=2.0,
    )

    # OpenLibrary: root GET is lightweight.
    openlibrary_status = await _probe_external(
        head_url="https://openlibrary.org/",
        get_url_fallback="https://openlibrary.org/",
        timeout_s=2.0,
    )

    return {
        "db": db_status,
        "crossref": crossref_status,
        "openlibrary": openlibrary_status,
    }
