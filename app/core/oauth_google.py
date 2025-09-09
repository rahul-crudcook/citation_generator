"""Google OAuth helper (no server-side sessions, no Redis).

This module provides a small OOP wrapper to:
- Build an authorization URL for Google OAuth (with signed state & nonce).
- Exchange the authorization code for tokens.
- Fetch and normalize the user's profile from Google's OpenID UserInfo endpoint.
- Validate post-login redirects against an allowlist.

Key design points:
- Stateless: `state` and `nonce` are short-lived JWTs signed with our SECRET_KEY.
- No Starlette session middleware needed; works with FastAPI directly.
- Uses Authlib's HTTPX-based OAuth2Client (no global registry objects).

Env from `settings`:
- GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
- OAUTH_ALLOWED_REDIRECT_HOSTS (CSV/JSON host allowlist)

Scopes: openid email profile
"""

from __future__ import annotations

import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from authlib.integrations.httpx_client import OAuth2Client
from jose import JWTError, jwt
from pydantic import HttpUrl

from app.core.config import settings

# --- Google endpoints (OIDC) ---
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass(frozen=True)
class GoogleProfile:
    """Normalized subset of Google OIDC userinfo."""

    sub: str
    email: Optional[str]
    email_verified: Optional[bool]
    name: Optional[str]
    given_name: Optional[str]
    family_name: Optional[str]
    picture: Optional[str]


class OAuthStateError(ValueError):
    """Raised when the OAuth state/nonce is invalid or expired."""


class OAuthRedirectError(ValueError):
    """Raised when a requested redirect target host is not allowed."""


def _generate_nonce(length_bytes: int = 16) -> str:
    """Generate a URL-safe random nonce."""
    return secrets.token_urlsafe(length_bytes)


class GoogleOAuth:
    """Stateless Google OAuth helper.

    This class does not manage server-side sessions. It issues short-lived,
    signed JWT `state` and `nonce` values and verifies them upon callback.

    Args:
        client_id: Google OAuth client id.
        client_secret: Google OAuth client secret.
        redirect_uri: Registered redirect URI (must match Google's console).
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str | HttpUrl] = None,
        timeout_seconds: int = 10,
    ) -> None:
        self._client_id = client_id or settings.google_client_id or ""
        self._client_secret = client_secret or settings.google_client_secret or ""
        self._redirect_uri = str(redirect_uri or settings.google_redirect_uri or "")
        self._timeout = timeout_seconds

        if not self._client_id or not self._client_secret or not self._redirect_uri:
            raise ValueError(
                "GoogleOAuth misconfigured: set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                "and GOOGLE_REDIRECT_URI."
            )

        # A fresh client per helper instance (safe in FastAPI dependency scope).
        self._client = OAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            timeout=self._timeout,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_authorize_redirect(
        self,
        redirect_to: Optional[str],
        scope: Optional[List[str]] = None,
        prompt: Optional[str] = None,
        hd: Optional[str] = None,
        extras: Optional[Dict[str, Any]] = None,
        state_ttl_seconds: int = 600,
    ) -> str:
        """Construct Google's authorization URL with signed state & nonce.

        Args:
            redirect_to: Post-login redirect URL (must be on an allowed host, or None).
            scope: Scopes (defaults to ['openid', 'email', 'profile']).
            prompt: Google prompt (e.g., 'consent', 'select_account').
            hd: Hosted domain hint (e.g., 'example.com').
            extras: Extra query params.
            state_ttl_seconds: JWT TTL for state/nonce.

        Raises:
            OAuthRedirectError: if redirect_to host is not allowed.
        """
        self._validate_redirect_host(redirect_to)

        scopes = scope or ["openid", "email", "profile"]
        nonce = _generate_nonce()
        state = self._sign_state(redirect_to=redirect_to, nonce=nonce, ttl=state_ttl_seconds)

        params: Dict[str, Any] = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "nonce": nonce,
            "access_type": "offline",
            "include_granted_scopes": "true",
        }
        if prompt:
            params["prompt"] = prompt
        if hd:
            params["hd"] = hd
        if extras:
            params.update(extras)

        return f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for tokens (access/refresh/id_token)."""
        token = self._client.fetch_token(
            url=_GOOGLE_TOKEN_URL,
            code=code,
            grant_type="authorization_code",
            redirect_uri=self._redirect_uri,
        )
        return token

    def fetch_userinfo(self, access_token: str) -> GoogleProfile:
        """Fetch normalized OpenID userinfo with the given access token."""
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(_GOOGLE_USERINFO_URL, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return GoogleProfile(
            sub=str(data.get("sub", "")),
            email=data.get("email"),
            email_verified=data.get("email_verified"),
            name=data.get("name"),
            given_name=data.get("given_name"),
            family_name=data.get("family_name"),
            picture=data.get("picture"),
        )

    def verify_callback_state(
            self, state_jwt: str, received_nonce: Optional[str]) -> Dict[str, Any]:
        """Verify the signed state and (optional) nonce on callback.

        Returns:
            Decoded state payload (contains 'rt' redirect_to and 'nonce').

        Raises:
            OAuthStateError: invalid signature, expiration, or nonce mismatch.
        """
        try:
            payload = jwt.decode(
                token=state_jwt,
                key=settings.secret_key,
                algorithms=[settings.jwt_alg],
                options={"require_exp": True, "require_iat": True},
            )
        except JWTError as exc:
            raise OAuthStateError("Invalid or expired OAuth state") from exc

        expected_nonce = payload.get("nonce")
        if expected_nonce and received_nonce and expected_nonce != received_nonce:
            raise OAuthStateError("Nonce mismatch")

        redirect_to = payload.get("rt")
        self._validate_redirect_host(redirect_to)

        return payload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _sign_state(self, redirect_to: Optional[str], nonce: str, ttl: int) -> str:
        """Sign a compact state payload with a short expiration."""
        now = int(time.time())
        exp = now + int(ttl)
        claims: Dict[str, Any] = {
            "rt": redirect_to,
            "nonce": nonce,
            "iat": now,
            "exp": exp,
            "typ": "oauth_state",
        }
        return jwt.encode(claims, key=settings.secret_key, algorithm=settings.jwt_alg)

    @staticmethod
    def _validate_redirect_host(redirect_to: Optional[str]) -> None:
        """Allow redirects only to hosts on the configured allowlist.

        If `OAUTH_ALLOWED_REDIRECT_HOSTS` is unset, allow any host (dev).
        In prod, set it (CSV or JSON) to your app domains.
        """
        if not redirect_to:
            return
        parsed = urllib.parse.urlparse(redirect_to)
        if not parsed.scheme or not parsed.netloc:
            raise OAuthRedirectError("redirect_to must be an absolute URL")

        allowlist_csv = settings.oauth_allowed_redirect_hosts or ""
        if not allowlist_csv:
            return  # dev mode: permissive

        allowed = {h.strip().lower() for h in allowlist_csv.split(",") if h.strip()}
        host = parsed.netloc.lower()
        if host not in allowed:
            raise OAuthRedirectError(f"Redirect host not allowed: {host}")


# Factory function for DI convenience
def get_google_oauth() -> GoogleOAuth:
    """Create a configured GoogleOAuth helper from environment settings."""
    return GoogleOAuth(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
    )
