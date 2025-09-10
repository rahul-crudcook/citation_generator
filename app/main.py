"""FastAPI application entrypoint with CORS, routers, and minimal hardening.

This module exposes both:
- `create_app()` — application factory used by tests and scripts.
- `app` — a module-level instance used by ASGI servers (e.g., Uvicorn).

Key behaviors:
- CORS derived from settings (CSV/JSON list support expected in
  `settings.cors_origins`).
- Credentials enabled to allow cookie-based JWT (HttpOnly cookies).
- Routers: health, auth, citations, libraries, ingest (import-guarded).
- Minimal security headers and JSON error handlers.

Notes:
- For M4, we wire the `/ingest` router. Infra objects (HTTP client / cache)
  are provided via dependency modules, not from this file.
- No Redis is enforced here; JWT remains stateless (header and/or cookie).
"""

from __future__ import annotations

import logging
from typing import Iterable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings

__all__ = ["create_app", "app"]

LOGGER = logging.getLogger(__name__)

# ----------------------------
# Guarded router imports (avoid hard failures in early milestones)
# ----------------------------
try:
    from app.api.routes import health as health_routes  # type: ignore
except Exception as exc:  # pylint: disable=broad-except
    LOGGER.exception("Failed to import health routes: %s", exc)
    HEALTH_ROUTES = None  # type: ignore[assignment]
else:
    HEALTH_ROUTES = health_routes  # type: ignore[assignment]

try:
    from app.api.routes import auth as auth_routes  # type: ignore
except Exception as exc:  # pylint: disable=broad-except
    LOGGER.exception("Failed to import auth routes: %s", exc)
    AUTH_ROUTES = None  # type: ignore[assignment]
else:
    AUTH_ROUTES = auth_routes  # type: ignore[assignment]

try:
    from app.api.routes import citations as citation_routes  # type: ignore
except Exception as exc:  # pylint: disable=broad-except
    LOGGER.exception("Failed to import citation routes: %s", exc)
    CITATION_ROUTES = None  # type: ignore[assignment]
else:
    CITATION_ROUTES = citation_routes  # type: ignore[assignment]

try:
    from app.api.routes import libraries as library_routes  # type: ignore
except Exception as exc:  # pylint: disable=broad-except
    LOGGER.info("Library routes not found (optional): %s", exc)
    LIBRARY_ROUTES = None  # type: ignore[assignment]
else:
    LIBRARY_ROUTES = library_routes  # type: ignore[assignment]

# NEW: M4 ingest routes (optional — guarded import)
try:
    from app.api.routes import ingest as ingest_routes  # type: ignore
except Exception as exc:  # pylint: disable=broad-except
    LOGGER.info("Ingest routes not found (optional for M4): %s", exc)
    INGEST_ROUTES = None  # type: ignore[assignment]
else:
    INGEST_ROUTES = ingest_routes  # type: ignore[assignment]


# ----------------------------
# Middleware and helpers
# ----------------------------
def _add_cors(application: FastAPI) -> None:
    """Attach CORS middleware based on settings."""
    origins: Iterable[str] = settings.cors_origins or []
    allow_all = len(origins) == 1 and next(iter(origins), "") == "*"

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else list(origins),
        allow_credentials=True,  # enable cookie-based auth
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=600,
    )


def _add_security_headers(response: Response) -> None:
    """Set a minimal set of security headers on each response."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")


def _include_routers(application: FastAPI) -> None:
    """Include available route modules."""
    # health: router has no prefix; add it here
    if HEALTH_ROUTES is not None:
        application.include_router(
            HEALTH_ROUTES.router, prefix="/health", tags=["health"]
        )
    else:
        LOGGER.warning("Health routes not found or failed to import.")

    # auth: router already declares prefix="/auth" → don't add another prefix here
    if AUTH_ROUTES is not None:
        application.include_router(AUTH_ROUTES.router, tags=["auth"])
    else:
        LOGGER.warning("Auth routes not found or failed to import.")

    # citations: include main router; also expose the META alias if present
    if CITATION_ROUTES is not None:
        application.include_router(CITATION_ROUTES.router, tags=["citations"])
        if hasattr(CITATION_ROUTES, "META_ROUTER"):
            application.include_router(CITATION_ROUTES.META_ROUTER, tags=["meta"])
    else:
        LOGGER.warning("Citation routes not found or failed to import.")

    # libraries: optional; safe if missing during early milestones
    if LIBRARY_ROUTES is not None:
        application.include_router(LIBRARY_ROUTES.router, tags=["libraries"])
    else:
        LOGGER.info("Library routes not found (optional).")

    # ingest: optional; safe if missing until M4 is merged
    if INGEST_ROUTES is not None:
        # The ingest router defines prefix="/ingest" internally.
        application.include_router(INGEST_ROUTES.router, tags=["ingest"])
    else:
        LOGGER.info("Ingest routes not found (optional for M4).")


def _install_exception_handlers(application: FastAPI) -> None:
    """Register JSON error handlers for common exceptions."""

    @application.exception_handler(HTTPException)
    async def _http_exception_handler(  # type: ignore[override]
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        logging.getLogger(__name__).info(
            "HTTPException: path=%s status=%s detail=%s",
            request.url.path,
            exc.status_code,
            exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": True, "message": exc.detail},
        )

    @application.exception_handler(RequestValidationError)
    async def _validation_exception_handler(  # type: ignore[override]
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logging.getLogger(__name__).debug(
            "Validation error at %s: %s", request.url.path, exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": True,
                "message": "Validation error",
                "details": exc.errors(),
            },
        )


# ----------------------------
# App factory
# ----------------------------
def create_app() -> FastAPI:
    """Application factory used for tests and ASGI servers."""
    application = FastAPI(title=settings.app_name)

    _add_cors(application)
    _install_exception_handlers(application)
    _include_routers(application)

    @application.middleware("http")
    async def _security_headers_mw(  # type: ignore[override]
        request: Request, call_next
    ):
        """Attach minimal security headers to every response."""
        response = await call_next(request)
        _add_security_headers(response)
        return response

    @application.get("/", tags=["meta"])
    async def _root() -> dict[str, str]:
        """Basic root endpoint to verify service is alive."""
        return {"app": settings.app_name, "status": "ok"}

    return application


# Module-level app instance for `uvicorn main:app --reload`
app: FastAPI = create_app()
