"""JWT token creation and verification service.

This module provides a small, focused OOP wrapper over `python-jose` for
issuing and validating stateless JWT access/refresh tokens.

Design goals:
- Keep tokens *stateless* (no DB/Redis lookups).
- Separate public API from internals for easy future changes
  (e.g., switching to RS256, adding `iss`/`aud`, etc.).
- Clear exceptions: decoding returns `ValueError` on failure so callers
  can map to HTTP 401 consistently.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Final

from jose import JWTError, jwt

from app.core.config import settings


class TokenService:
    """Encapsulates JWT encode/decode for access & refresh tokens."""

    # Claim keys (kept as constants for maintainability)
    _CLAIM_SUB: Final[str] = "sub"
    _CLAIM_TYP: Final[str] = "type"
    _CLAIM_IAT: Final[str] = "iat"
    _CLAIM_EXP: Final[str] = "exp"

    def __init__(self, secret_key: str | None = None, algorithm: str | None = None) -> None:
        """Initialize the service.

        Args:
            secret_key: Optional override; defaults to settings.secret_key.
            algorithm: Optional override; defaults to settings.jwt_alg.
        """
        self._secret = secret_key or settings.secret_key
        self._alg = algorithm or settings.jwt_alg

    # ---------- Public API (preferred names) ----------

    def create_access_token(self, subject: str, expires_minutes: int | None = None) -> str:
        """Create a signed access token for a user id (subject)."""
        minutes = expires_minutes or settings.access_token_expire_minutes
        return self._create_token(subject=subject, token_type="access", minutes=minutes)

    def create_refresh_token(self, subject: str, expires_minutes: int | None = None) -> str:
        """Create a signed refresh token for a user id (subject)."""
        minutes = expires_minutes or settings.refresh_token_expire_minutes
        return self._create_token(subject=subject, token_type="refresh", minutes=minutes)

    def decode_access_token(self, token: str) -> Dict[str, Any]:
        """Decode and validate an access token, raising ValueError on error."""
        payload = self._decode(token)
        self._ensure_type(payload, expected="access")
        return payload

    def decode_refresh_token(self, token: str) -> Dict[str, Any]:
        """Decode and validate a refresh token, raising ValueError on error."""
        payload = self._decode(token)
        self._ensure_type(payload, expected="refresh")
        return payload

    # ---------- Backward-compatible aliases ----------
    # These match names already used by your routes.

    def issue_access(self, subject: str, expires_minutes: int | None = None) -> str:
        """Alias for create_access_token (kept for compatibility)."""
        return self.create_access_token(subject, expires_minutes)

    def issue_refresh(self, subject: str, expires_minutes: int | None = None) -> str:
        """Alias for create_refresh_token (kept for compatibility)."""
        return self.create_refresh_token(subject, expires_minutes)

    # ---------- Internals ----------

    def _create_token(self, subject: str, token_type: str, minutes: int) -> str:
        """Create a signed JWT with common claims."""
        now = datetime.now(tz=timezone.utc)
        exp = now + timedelta(minutes=minutes)

        payload: Dict[str, Any] = {
            self._CLAIM_SUB: subject,
            self._CLAIM_TYP: token_type,
            self._CLAIM_IAT: int(now.timestamp()),
            self._CLAIM_EXP: int(exp.timestamp()),
        }
        return jwt.encode(payload, self._secret, algorithm=self._alg)

    def _decode(self, token: str) -> Dict[str, Any]:
        """Decode a JWT and validate its signature/expiry.

        Returns:
            JWT payload as a dictionary.

        Raises:
            ValueError: If decoding fails for any reason.
        """
        try:
            # jose verifies "exp" automatically when present
            return jwt.decode(token, self._secret, algorithms=[self._alg])
        except JWTError as exc:  # include ExpiredSignatureError, JWTClaimsError, etc.
            raise ValueError("Invalid token") from exc

    @staticmethod
    def _ensure_type(payload: Dict[str, Any], expected: str) -> None:
        """Ensure token `type` claim matches the expected value.

        Args:
            payload: Decoded JWT payload.
            expected: Expected token type ("access" or "refresh").

        Raises:
            ValueError: If the type is missing or does not match.
        """
        actual = payload.get("type")
        if actual != expected:
            raise ValueError("Invalid token type")


# Provide a typed singleton so linters know its interface.
token_service: TokenService = TokenService()
