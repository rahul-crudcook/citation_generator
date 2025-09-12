# app/main.py
"""FastAPI application entrypoint with CORS, routers, and minimal hardening.

This module exposes both:
- `create_app()` — application factory used by tests and scripts.
- `app` — a module-level instance used by ASGI servers (e.g., Uvicorn).

Key behaviors
-------------
- CORS derived from settings (CSV/JSON list support expected in
  `settings.cors_origins`).
- Credentials enabled to allow cookie-based JWT (HttpOnly cookies).
- Routers: health (incl. /health/deps), auth, citations (+/meta alias),
  libraries, ingest (M4), format (M6), and exports (M7 + M8 bulk jobs).
- Minimal security headers and JSON error handlers.

Notes
-----
- For M4, we wire the `/ingest` router. Infra objects (HTTP client / cache)
  are provided via dependency modules, not from this file.
- For M6, we wire the `/format` router for previewing citation strings.
- For M7/M8, we add the `exports` router (single + bulk export endpoints).
- No Redis wiring is done here; JWT remains stateless (header and/or cookie).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings

__all__ = ["create_app", "app"]

LOGGER = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Guarded router imports (avoid hard failures in early milestones)
# -----------------------------------------------------------------------------
def _safe_import(module_path: str, attr: str) -> Optional[object]:
    """Import `attr` from `module_path` safely, logging any exception."""
    try:
        module = __import__(module_path, fromlist=[attr])
        return getattr(module, attr)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.info("Optional router import failed for %s.%s: %s", module_path, attr, exc)
        return None


# Health routes (mounted under /health here)
HEALTH_ROUTES = _safe_import("app.api.routes.health", "router")

# Auth routes (declare their own prefix="/auth")
AUTH_ROUTES = _safe_import("app.api.routes.auth", "router")

# Citations routes (declare their own prefix="/citations") + META alias
CITATION_ROUTES = _safe_import("app.api.routes.citations", "router")
CITATION_META = _safe_import("app.api.routes.citations", "META_ROUTER")

# Libraries routes (optional)
LIBRARY_ROUTES = _safe_import("app.api.routes.libraries", "router")

# Ingest routes (optional; M4)
INGEST_ROUTES = _safe_import("app.api.routes.ingest", "router")

# Formatting routes (optional; M6, prefix="/format")
FORMAT_ROUTES = _safe_import("app.api.routes.format", "router")

# Exports routes (M7 + M8 bulk job endpoints live here)
EXPORTS_ROUTES = _safe_import("app.api.routes.exports", "router")


# -----------------------------------------------------------------------------
# Middleware and helpers
# -----------------------------------------------------------------------------
def _add_cors(application: FastAPI) -> None:
    """Attach CORS middleware based on settings.

    We support two patterns:
    - `["*"]` (or a single "*" string) to allow all origins (useful for local dev).
    - A concrete list of origins.
    """
    origins_list = list(settings.cors_origins or [])
    allow_all = len(origins_list) == 1 and origins_list[0] == "*"

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins_list,
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
    """Include available route modules in the application."""
    # health: router has no prefix; add it here (includes /health/live, /ready, /deps)
    if HEALTH_ROUTES is not None:
        application.include_router(HEALTH_ROUTES, prefix="/health", tags=["health"])
    else:
        LOGGER.warning("Health routes not found or failed to import.")

    # auth: router already declares prefix="/auth" → don't add another prefix here
    if AUTH_ROUTES is not None:
        application.include_router(AUTH_ROUTES, tags=["auth"])
    else:
        LOGGER.warning("Auth routes not found or failed to import.")

    # citations: include main router; also expose the META alias if present
    if CITATION_ROUTES is not None:
        application.include_router(CITATION_ROUTES, tags=["citations"])
        if CITATION_META is not None:
            application.include_router(CITATION_META, tags=["meta"])
    else:
        LOGGER.warning("Citation routes not found or failed to import.")

    # libraries: optional; safe if missing during early milestones
    if LIBRARY_ROUTES is not None:
        application.include_router(LIBRARY_ROUTES, tags=["libraries"])
    else:
        LOGGER.info("Library routes not found (optional).")

    # ingest: optional; safe if missing until M4 is merged
    if INGEST_ROUTES is not None:
        # The ingest router defines prefix="/ingest" internally.
        application.include_router(INGEST_ROUTES, tags=["ingest"])
    else:
        LOGGER.info("Ingest routes not found (optional for M4).")

    # format: optional; M6 router (prefix="/format" declared in the module)
    if FORMAT_ROUTES is not None:
        application.include_router(FORMAT_ROUTES, tags=["format"])
    else:
        LOGGER.info("Format routes not found (optional for M6).")

    # exports: M7 router (declares its own paths, including M8 bulk endpoints)
    if EXPORTS_ROUTES is not None:
        application.include_router(EXPORTS_ROUTES, tags=["exports"])
    else:
        LOGGER.info("Exports routes not found (optional for M7/M8).")


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


# -----------------------------------------------------------------------------
# App factory
# -----------------------------------------------------------------------------
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


# Module-level app instance for `uvicorn app.main:app --reload`
app: FastAPI = create_app()
