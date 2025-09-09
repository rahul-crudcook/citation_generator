"""Health and readiness endpoints (no Redis).

Exposes:
- GET /health/live  : simple liveness check.
- GET /health/ready : readiness probe that verifies DB connectivity.

Note:
The router itself has **no prefix**. `main.py` includes this router with
`prefix="/health"`, so final paths are `/health/live` and `/health/ready`.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_db

router = APIRouter(tags=["health"])


@router.get("/live", status_code=status.HTTP_200_OK)
def liveness() -> Dict[str, str]:
    """Simple liveness endpoint (does not touch external deps)."""
    return {"status": "alive"}


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
