"""Authentication routes.

Supports:
- Local email/password register + login (M1).
- Stateless JWT access/refresh tokens.
- Optional HttpOnly cookie issuance/clearing (no Redis).
- A simple `/me` using the shared dependency.

Google OAuth can be added later without breaking these contracts.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.security import jwt_service
from app.models.user import User
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, TokenPair, UserOut
from app.services.auth_service import auth_service
from app.services.token_service import token_service

router = APIRouter(prefix="/auth", tags=["auth"])


# ----------------------------
# Cookie helpers (stateless JWT-in-cookies)
# ----------------------------
def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Attach access and refresh tokens as secure cookies, if cookie auth is enabled."""
    if not settings.use_cookie_auth:
        return

    response.set_cookie(
        key=settings.access_cookie_name,
        value=access_token,
        httponly=settings.cookie_httponly,
        secure=settings.effective_cookie_secure,
        samesite=settings.cookie_samesite,  # "lax" | "strict" | "none"
        domain=settings.cookie_domain,
        path=settings.cookie_path,
        max_age=settings.access_token_expire_minutes * 60,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=settings.cookie_httponly,
        secure=settings.effective_cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path=settings.cookie_path,
        max_age=settings.refresh_token_expire_minutes * 60,
    )


def _clear_auth_cookies(response: Response) -> None:
    """Clear auth cookies (logout), if cookie auth is enabled."""
    if not settings.use_cookie_auth:
        return

    response.delete_cookie(
        key=settings.access_cookie_name,
        domain=settings.cookie_domain,
        path=settings.cookie_path,
    )
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        domain=settings.cookie_domain,
        path=settings.cookie_path,
    )


# ----------------------------
# Routes
# ----------------------------
@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> UserOut:
    """Register a new local user."""
    try:
        user = auth_service.register_local(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    """Login with email/password and receive a token pair.

    Returns tokens in the JSON body. If cookie auth is enabled, also sets
    HttpOnly cookies for access and refresh tokens.
    """
    user = auth_service.verify_local_credentials(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access = token_service.issue_access(str(user.id))
    refresh = token_service.issue_refresh(str(user.id))
    _set_auth_cookies(response, access, refresh)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(payload: RefreshIn, response: Response) -> TokenPair:
    """Exchange a valid refresh token for a new token pair.

    Uses the provided refresh token in the JSON body. If cookie auth is enabled,
    sets fresh cookies as well.
    """
    try:
        claims = jwt_service.decode(payload.refresh_token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if claims.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    subject = str(claims["sub"])
    access = token_service.issue_access(subject)
    refresh = token_service.issue_refresh(subject)
    _set_auth_cookies(response, access, refresh)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(response: Response) -> Response:
    """Clear auth cookies (if enabled). Returns 204 No Content."""
    _clear_auth_cookies(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Return the current user's profile using JWT from header or cookies."""
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
    )
