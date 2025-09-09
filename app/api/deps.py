"""Common API dependencies for FastAPI routes.

This module exposes:
- `get_db`: Provide a per-request SQLAlchemy session with commit/rollback semantics.
- `get_current_user`: Strict dependency that returns the authenticated user or raises 401.
- `get_current_user_optional`: Lenient dependency that returns the user or `None`.
"""

from __future__ import annotations

from typing import Generator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.token_service import token_service

__all__ = [
    "get_db",
    "get_current_user",
    "get_current_user_optional",
]

# We allow missing Authorization headers so we can fall back to cookie tokens.
# `auto_error=False` prevents FastAPI from raising 401 before we can check cookies.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ----------------------------
# Database session per request
# ----------------------------
def get_db() -> Generator[Session, None, None]:
    """Yield a transactional SQLAlchemy session per request.

    Behavior:
        - Yields a session to the route handler.
        - Commits if the handler completes successfully.
        - Rolls back on exception and re-raises.
        - Closes the session in all cases.

    Yields:
        `Session`: The SQLAlchemy session bound to the current request.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:  # noqa: BLE001 - propagate after rollback
        db.rollback()
        raise
    finally:
        db.close()


# ----------------------------
# Token extraction helpers
# ----------------------------
def _get_bearer_from_authorization_header(raw_header: Optional[str]) -> Optional[str]:
    """Extract a Bearer token from an `Authorization` header value.

    Args:
        raw_header: The value of the Authorization header (e.g., "Bearer <token>").

    Returns:
        The token string if correctly prefixed with "Bearer ", otherwise `None`.
    """
    if not raw_header:
        return None

    parts = raw_header.split(" ", 1)
    if len(parts) != 2:
        return None

    scheme, token = parts[0].strip(), parts[1].strip()
    if scheme.lower() != "bearer" or not token:
        return None

    return token


def _get_token_from_request(request: Request, header_token: Optional[str]) -> Optional[str]:
    """Resolve the access token from Authorization header or cookies.

    Resolution order:
        1) Token parsed by `OAuth2PasswordBearer` (if present).
        2) Manual parse of the raw `Authorization` header.
        3) HttpOnly cookie (when cookie auth is enabled via settings).

    Args:
        request: The FastAPI `Request`.
        header_token: Token parsed by the OAuth2 dependency (may be `None`).

    Returns:
        The resolved JWT access token, or `None` if not found.
    """
    if header_token:
        return header_token

    # Manual parse as a fallback (covers proxy/header edge cases).
    raw_auth = request.headers.get("Authorization")
    token = _get_bearer_from_authorization_header(raw_auth)
    if token:
        return token

    # Optional cookie-based auth for browser clients.
    if settings.use_cookie_auth:
        token = request.cookies.get(settings.access_cookie_name)
        if token:
            return token

    return None


# ----------------------------
# Authenticated user helpers
# ----------------------------
def _resolve_user_from_token(token: str, db: Session) -> User:
    """Decode JWT, validate, and load the active user or raise 401.

    Args:
        token: Encoded JWT access token.
        db: SQLAlchemy session for DB lookups.

    Returns:
        The active `User` instance.

    Raises:
        HTTPException: 401 if the token is invalid/expired, or the user is missing/inactive.
    """
    try:
        payload = token_service.decode_access_token(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # We expect `sub` to be the user ID.
    user_id: Optional[int] = None
    sub = payload.get("sub")
    if sub is not None:
        try:
            user_id = int(sub)
        except (TypeError, ValueError):
            user_id = None

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    # If your User model uses a different active flag, adjust this attribute.
    if not user or not getattr(user, "is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User inactive or not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# ----------------------------
# Public dependencies
# ----------------------------
def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    header_token: Optional[str] = Depends(oauth2_scheme),
) -> User:
    """Return the current authenticated user, or raise 401.

    Use this dependency on protected endpoints.

    Args:
        request: The FastAPI request.
        db: SQLAlchemy session (injected).
        header_token: Token parsed via `OAuth2PasswordBearer` (may be `None`).

    Returns:
        The active `User`.

    Raises:
        HTTPException: 401 when no token is provided or when token/user is invalid.
    """
    token = _get_token_from_request(request, header_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _resolve_user_from_token(token, db)


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
    header_token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[User]:
    """Return the current user if authenticated; otherwise `None`.

    Useful for endpoints that can behave differently for authenticated users
    without failing when unauthenticated.

    Args:
        request: The FastAPI request.
        db: SQLAlchemy session (injected).
        header_token: Token parsed via `OAuth2PasswordBearer` (may be `None`).

    Returns:
        The active `User`, or `None` if not authenticated or if the token/user is invalid.
    """
    token = _get_token_from_request(request, header_token)
    if not token:
        return None

    try:
        return _resolve_user_from_token(token, db)
    except HTTPException:
        # Swallow auth errors for the optional variant.
        return None
