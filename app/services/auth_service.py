"""Authentication application service."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.auth import RegisterIn
from app.services.password_service import password_service


class AuthService:
    """Business logic for registering and logging in users."""

    def register_local(self, db: Session, payload: RegisterIn) -> User:
        """Register a local user (email/password). Commit & refresh so it's persisted."""
        existing = self.get_user_by_email(db, payload.email)
        if existing:
            msg = "User already exists."
            raise ValueError(msg)

        user = User(
            email=payload.email,
            display_name=payload.display_name,
            provider="local",
            password_hash=password_service.hash(payload.password),
        )
        db.add(user)
        db.commit()          # <-- persist
        db.refresh(user)     # <-- get id & defaults from DB
        return user

    def get_user_by_email(self, db: Session, email: str) -> Optional[User]:
        """Fetch a user by email address."""
        stmt = select(User).where(User.email == email)
        return db.scalars(stmt).first()

    def verify_local_credentials(self, db: Session, email: str, password: str) -> Optional[User]:
        """Validate login credentials and return the user if valid."""
        user = self.get_user_by_email(db, email)
        if not user or not user.password_hash:
            return None
        if not password:
            return None
        if not password_service.verify(password, user.password_hash):
            return None
        return user


auth_service = AuthService()
