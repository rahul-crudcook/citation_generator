"""Security helpers for issuing and verifying JWTs (access/refresh).

This module intentionally stays minimal because token construction/validation
logic lives primarily in `app.services.token_service`. We keep a small
`JWTService` here for places that need direct encode/decode access (e.g.,
refresh flow in early milestones), without coupling those call sites to the
full token service.

Design:
- Stateless JWTs (no DB/Redis lookups).
- Standard claims: sub, type, iat, exp.
- Caller maps decode errors to HTTP 401 (we surface python-jose exceptions).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Final

from jose import jwt

from app.core.config import settings


class JWTService:
    """Issue and verify signed JWTs for access/refresh tokens."""

    _CLAIM_SUB: Final[str] = "sub"
    _CLAIM_TYP: Final[str] = "type"
    _CLAIM_IAT: Final[str] = "iat"
    _CLAIM_EXP: Final[str] = "exp"

    def __init__(self, secret_key: str, algorithm: str) -> None:
        """Initialize with a shared secret and algorithm (e.g., HS256)."""
        self._secret_key = secret_key
        self._alg = algorithm

    def issue_token(self, subject: str, expires_in_minutes: int, token_type: str) -> str:
        """Create a signed JWT with standard claims.

        Args:
            subject: Subject identifier (usually the user id as a string).
            expires_in_minutes: TTL for the token.
            token_type: Semantic type ("access" or "refresh").

        Returns:
            Encoded JWT string.
        """
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=expires_in_minutes)
        payload: Dict[str, Any] = {
            self._CLAIM_SUB: subject,
            self._CLAIM_TYP: token_type,
            self._CLAIM_IAT: int(now.timestamp()),
            self._CLAIM_EXP: int(exp.timestamp()),
        }
        return jwt.encode(payload, self._secret_key, algorithm=self._alg)

    def decode(self, token: str) -> Dict[str, Any]:
        """Decode and verify a JWT, returning its claims.

        Notes:
            - Raises `jose.JWTError` (and subclasses) on failure.
            - Callers should map these to HTTP 401 as appropriate.

        Args:
            token: Encoded JWT string.

        Returns:
            Decoded claims as a dictionary.
        """
        return jwt.decode(token, self._secret_key, algorithms=[self._alg])


# Singleton used across the app (kept for backward compatibility).
jwt_service = JWTService(settings.secret_key, settings.jwt_alg)
