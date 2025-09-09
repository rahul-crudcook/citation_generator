"""Pydantic schemas for authentication and users."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class TokenPair(BaseModel):
    """Access and refresh tokens."""

    access_token: str = Field(...)
    refresh_token: str = Field(...)
    token_type: str = Field(default="bearer")


class RegisterIn(BaseModel):
    """Payload for local registration."""

    email: EmailStr
    password: str
    display_name: str | None = None


class LoginIn(BaseModel):
    """Payload for local login."""

    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    """Payload for refreshing a token."""

    refresh_token: str


class UserOut(BaseModel):
    """Public representation of the user."""

    id: int
    email: EmailStr
    display_name: str | None = None
