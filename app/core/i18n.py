# pylint: disable=W0718

"""Lightweight internationalization (i18n) support.

This module provides a minimal, dependency-free i18n system suitable for
server-side validation messages and UX hints. It is intentionally small and
focused:

- A `MessageCatalog` encapsulates messages for a single locale.
- An `I18n` registry manages multiple catalogs and resolves lookups.
- A default English catalog is provided for common validation messages.

Usage
-----
from app.core.i18n import i18n, get_message

# Lookup with default locale ("en"):
msg = get_message("not_4_digits")  # "Year must be four digits (e.g., 2021)."

# Lookup with formatting:
msg = get_message("invalid_field", field="url")
# -> "Invalid value for 'url'."

# Add/override a locale at runtime:
i18n.add_catalog("hi", {"not_4_digits": "वर्ष चार अंकों का होना चाहिए (उदा., 2021)."})

Design Notes
------------
- No runtime dependencies (keeps startup fast and testing simple).
- Messages are format strings: `.format(**kwargs)` is applied on retrieval.
- Missing keys fall back to the message code itself (safe to display).
- Callers can provide fallback defaults per lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, MutableMapping, Optional


# ---------------------------------------------------------------------------
# Default English catalog (extend as needed)
# ---------------------------------------------------------------------------

DEFAULT_EN_MESSAGES: Mapping[str, str] = {
    # Core M5 validation codes used across services:
    "not_4_digits": "Year must be four digits (e.g., 2021).",
    "invalid_url": "URL must start with http:// or https://.",
    "bad_pages_range": "Use page ranges like 12–18 or lists like 12, 25–27.",
    "name_not_split": "Provide author names as separate first/last fields.",
    "empty_string": "This field cannot be empty.",

    # Generic/utility messages:
    "missing_required": "Missing required field: '{field}'.",
    "invalid_field": "Invalid value for '{field}'.",
    "unknown_error": "An unknown error occurred.",
}


# ---------------------------------------------------------------------------
# Catalog: messages for a single locale
# ---------------------------------------------------------------------------


@dataclass
class MessageCatalog:
    """A collection of localized messages for a single locale.

    Attributes:
        locale: BCP-47-ish language tag (e.g., "en", "en-US", "hi").
        messages: Mapping of message codes → format strings. Values can use
                  Python's `str.format(**kwargs)` placeholders.
    """

    locale: str
    messages: Dict[str, str] = field(default_factory=dict)

    def get(self, code: str, default: Optional[str] = None, **kwargs: Any) -> str:
        """Return the localized message for a given code.

        If the code does not exist in this catalog, falls back to `default` if
        provided, else the `code` itself (safe for developer eyes).

        Keyword arguments are passed to `str.format(**kwargs)`.

        Args:
            code: Message key.
            default: Optional fallback message if key is missing.
            **kwargs: Values for format placeholders.

        Returns:
            A formatted string.
        """
        template = self.messages.get(code, default if default is not None else code)
        try:
            return template.format(**kwargs)
        except Exception:
            # Return unformatted template on formatting errors to avoid masking issues.
            return template

    def merge(self, overrides: Mapping[str, str]) -> None:
        """Overlay/override messages in-place with the provided mapping.

        Args:
            overrides: A mapping of message codes → override strings.
        """
        self.messages.update(dict(overrides))


# ---------------------------------------------------------------------------
# I18n registry: manages catalogs and resolution
# ---------------------------------------------------------------------------


class I18n:
    """Registry and resolver for message catalogs across locales.

    Responsibilities:
    - Hold a mapping of `locale` → `MessageCatalog`.
    - Provide lookup with a default locale.
    - Allow runtime addition or override of catalogs.
    """

    def __init__(self, default_locale: str = "en") -> None:
        """Initialize the i18n registry.

        Args:
            default_locale: The locale used when none is explicitly provided.
        """
        self._catalogs: MutableMapping[str, MessageCatalog] = {}
        self._default_locale: str = default_locale

    # --- Catalog management -------------------------------------------------

    @property
    def default_locale(self) -> str:
        """Return the current default locale."""
        return self._default_locale

    def set_default_locale(self, locale: str) -> None:
        """Set the default locale used for lookups."""
        self._default_locale = locale

    def add_catalog(self, locale: str, messages: Mapping[str, str]) -> None:
        """Create or replace a catalog for a locale.

        Args:
            locale: Language tag (e.g., "en", "en-US", "hi").
            messages: Mapping of codes to message strings.
        """
        self._catalogs[locale] = MessageCatalog(locale=locale, messages=dict(messages))

    def get_catalog(self, locale: Optional[str] = None) -> MessageCatalog:
        """Return a catalog for the requested locale or the default one.

        If a catalog for the requested locale does not exist, an empty catalog
        is created on-the-fly (so callers can start populating it).
        """
        loc = locale or self._default_locale
        if loc not in self._catalogs:
            self._catalogs[loc] = MessageCatalog(locale=loc, messages={})
        return self._catalogs[loc]

    def merge_into(self, locale: str, overrides: Mapping[str, str]) -> None:
        """Overlay messages into an existing catalog (creates if missing)."""
        self.get_catalog(locale).merge(overrides)

    # --- Lookup -------------------------------------------------------------

    def get(
        self,
        code: str,
        *,
        locale: Optional[str] = None,
        default: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Resolve a message by code from the given or default locale.

        Args:
            code: Message key to resolve.
            locale: Preferred locale, falls back to default locale if None.
            default: Fallback message if not found in catalog.
            **kwargs: Format placeholders for the message.

        Returns:
            A formatted message string.
        """
        catalog = self.get_catalog(locale)
        return catalog.get(code, default=default, **kwargs)


# ---------------------------------------------------------------------------
# Module-level singleton and default wiring
# ---------------------------------------------------------------------------

i18n = I18n(default_locale="en")
# Preload English defaults
i18n.add_catalog("en", dict(DEFAULT_EN_MESSAGES))


def get_message(
    code: str,
    *,
    locale: Optional[str] = None,
    default: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Convenience function for callers that don't need the registry.

    Args:
        code: Message code to look up.
        locale: Optional locale (default registry locale if None).
        default: Optional fallback string if code is missing.
        **kwargs: Format placeholders.

    Returns:
        The formatted message string.
    """
    return i18n.get(code, locale=locale, default=default, **kwargs)
