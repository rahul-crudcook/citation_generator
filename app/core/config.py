"""Application configuration using Pydantic Settings (v2 style).

This module exposes a single `settings` instance of `Settings`, which reads
configuration from environment variables (and optionally a `.env` file).

Key features:
- App/env flags and CORS origins parsing (CSV or JSON list).
- Database DSN.
- JWT configuration (algorithm, expiries).
- Cookie-based auth toggles (HttpOnly/Secure/SameSite, names, domain).
- Google OAuth client settings (Authlib will use these).
- M4 (Auto-fetchers) settings: provider toggles, base URLs, HTTP timeouts,
  default User-Agent, and optional Redis URL + cache TTL.

Notes:
- No tight coupling to any framework; these settings are consumed by services.
- JWT can be used via headers and/or cookies (when `use_cookie_auth` is True).
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from pydantic import AnyHttpUrl, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables.

    All fields are read from environment variables (case-insensitive) using
    their `alias` names. Unknown environment variables are ignored.
    """

    # ----------------------------
    # App / environment
    # ----------------------------
    app_name: str = Field(default="citation-generator", alias="APP_NAME")
    env: str = Field(default="dev", alias="ENV")  # dev | stage | prod

    # ----------------------------
    # Database
    # ----------------------------
    database_url: str = Field(alias="DATABASE_URL")

    # ----------------------------
    # Security / JWT
    # ----------------------------
    secret_key: str = Field(alias="SECRET_KEY")
    jwt_alg: str = Field(default="HS256", alias="JWT_ALG")
    access_token_expire_minutes: int = Field(
        default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    refresh_token_expire_minutes: int = Field(
        default=60 * 24 * 30, alias="REFRESH_TOKEN_EXPIRE_MINUTES"
    )

    # ----------------------------
    # Cookie-based auth (stateless JWT in cookies)
    # ----------------------------
    use_cookie_auth: bool = Field(default=True, alias="USE_COOKIE_AUTH")
    access_cookie_name: str = Field(default="cg_access", alias="ACCESS_COOKIE_NAME")
    refresh_cookie_name: str = Field(default="cg_refresh", alias="REFRESH_COOKIE_NAME")
    cookie_domain: Optional[str] = Field(default=None, alias="COOKIE_DOMAIN")
    cookie_secure: Optional[bool] = Field(default=None, alias="COOKIE_SECURE")
    cookie_httponly: bool = Field(default=True, alias="COOKIE_HTTPONLY")
    cookie_samesite: str = Field(default="lax", alias="COOKIE_SAMESITE")  # lax|strict|none
    cookie_path: str = Field(default="/", alias="COOKIE_PATH")

    # ----------------------------
    # OAuth (Google) – used by Authlib
    # ----------------------------
    google_client_id: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: Optional[str] = Field(
        default=None, alias="GOOGLE_CLIENT_SECRET"
    )
    # Public callback/redirect URI registered in Google Console
    google_redirect_uri: Optional[AnyHttpUrl] = Field(
        default=None, alias="GOOGLE_REDIRECT_URI"
    )
    # Optional: restrict allowed post-login redirect targets (CSRF/open redirect safety)
    oauth_allowed_redirect_hosts: Optional[str] = Field(
        default=None, alias="OAUTH_ALLOWED_REDIRECT_HOSTS"
    )

    # ----------------------------
    # CORS
    # ----------------------------
    # Raw env form; can be CSV or JSON list. Example:
    #   CORS_ORIGINS='http://localhost:5173,http://127.0.0.1:5173'
    #   CORS_ORIGINS='["https://app.example.com", "https://admin.example.com"]'
    cors_origins_env: Optional[str] = Field(default=None, alias="CORS_ORIGINS")

    # ----------------------------
    # M4 — Auto-fetchers (HTTP, providers, cache)
    # ----------------------------
    # Provider toggles
    ENABLE_CROSSREF: bool = Field(default=True, alias="ENABLE_CROSSREF")
    ENABLE_OPENLIBRARY: bool = Field(default=True, alias="ENABLE_OPENLIBRARY")
    ENABLE_URL_SCRAPE: bool = Field(default=True, alias="ENABLE_URL_SCRAPE")
    # Future optional providers (stubs)
    ENABLE_ARXIV: bool = Field(default=False, alias="ENABLE_ARXIV")
    ENABLE_PUBMED: bool = Field(default=False, alias="ENABLE_PUBMED")

    # Provider base URLs
    CROSSREF_BASE_URL: str = Field(
        default="https://api.crossref.org/works", alias="CROSSREF_BASE_URL"
    )
    OPENLIBRARY_BASE_URL: str = Field(
        default="https://openlibrary.org", alias="OPENLIBRARY_BASE_URL"
    )

    # HTTP settings for fetchers
    FETCH_TIMEOUT_SECONDS: float = Field(default=10.0, alias="FETCH_TIMEOUT_SECONDS")
    USER_AGENT: str = Field(
        default="citation-generator/1.0 (+https://example.com)",
        alias="USER_AGENT",
    )

    # Cache (Redis optional). If REDIS_URL is empty, fall back to in-memory.
    REDIS_URL: Optional[str] = Field(default=None, alias="REDIS_URL")
    INGEST_CACHE_TTL_SECONDS: int = Field(
        default=60 * 60 * 24, alias="INGEST_CACHE_TTL_SECONDS"
    )  # 24h

    # ----------------------------
    # Pydantic settings behavior
    # ----------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    # ----------------------------
    # Derived / helper properties
    # ----------------------------
    @property
    def is_prod(self) -> bool:
        """Return True if running in production environment.

        Pylint can see `env` as a Field descriptor statically. To avoid E1101,
        coerce to string safely before `.lower()`.
        """
        env_value: Any = getattr(self, "env", "dev")
        return str(env_value).lower() == "prod"

    @property
    def cors_origins(self) -> List[str]:
        """Return CORS origins as a list, accepting JSON or CSV env values.

        Returns:
            List[str]: A list of origins. Empty list means CORS disabled.
        """
        raw = (self.cors_origins_env or "").strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        # CSV fallback
        return [part.strip() for part in raw.split(",") if part.strip()]

    @property
    def effective_cookie_secure(self) -> bool:
        """Decide `Secure` flag for cookies.

        If COOKIE_SECURE is explicitly set, use it.
        Otherwise default to True in prod, False elsewhere (for local dev).
        """
        if self.cookie_secure is not None:
            return bool(self.cookie_secure)
        return self.is_prod

    # ----------------------------
    # Validators
    # ----------------------------
    @field_validator("cookie_samesite")
    @classmethod
    def _validate_samesite(cls, v: str) -> str:  # noqa: D401
        """Ensure SameSite is one of: lax, strict, none (case-insensitive)."""
        valid = {"lax", "strict", "none"}
        if v is None:
            return "lax"
        lowered = v.strip().lower()
        if lowered not in valid:
            raise ValueError("COOKIE_SAMESITE must be one of: lax, strict, none")
        return lowered

    @field_validator("oauth_allowed_redirect_hosts")
    @classmethod
    def _normalize_hosts(cls, v: Optional[str], _: ValidationInfo) -> Optional[str]:
        """Normalize host allowlist to a comma-separated, stripped string.

        Accepts CSV or JSON list in env; stores as CSV string (or None).
        """
        if not v:
            return None
        raw = v.strip()
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                joined = ",".join(str(x).strip() for x in parsed if str(x).strip())
                return joined or None
        # CSV fallback
        csv = ",".join(part.strip() for part in raw.split(",") if part.strip())
        return csv or None


# A single importable settings instance
settings = Settings()
