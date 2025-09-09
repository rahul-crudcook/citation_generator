"""Password hashing/verification service."""
from __future__ import annotations

from passlib.context import CryptContext


class PasswordService:
    """Wrap passlib so the rest of the app remains decoupled."""

    def __init__(self) -> None:
        self._ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash(self, plain: str) -> str:
        """Hash a plaintext password."""
        return self._ctx.hash(plain)

    def verify(self, plain: str, hashed: str) -> bool:
        """Check if plaintext matches the given hash."""
        return self._ctx.verify(plain, hashed)


password_service = PasswordService()
