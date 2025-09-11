# citation_generator/app/services/formatters/base.py
"""Base classes and utilities for style-specific citation formatters (M6).

Each concrete formatter implements per-source-type methods that accept
**normalized facts** (from M5) and return a deterministic citation string.

Implementations should be pure (no I/O), easy to unit test, and avoid side
effects. Any style-specific punctuation, capitalization, and author rendering
rules live in the concrete subclasses.

Public interface (called by FormatService):
    - format_book(facts) -> str
    - format_journal_article(facts) -> str
    - format_magazine_newspaper(facts) -> str
    - format_encyclopedia(facts) -> str
    - format_website(facts) -> str
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Tuple


class BaseFormatter(ABC):
    """Abstract base for all style formatters."""

    # ---------- Minimal, deterministic helpers shared by subclasses ----------
    _STOP_WORDS: set[str] = {
        "a",
        "an",
        "the",
        "and",
        "but",
        "or",
        "nor",
        "for",
        "so",
        "yet",
        "as",
        "at",
        "by",
        "in",
        "of",
        "on",
        "per",
        "to",
        "via",
        "with",
        "from",
        "into",
        "over",
        "under",
        "off",
    }

    @staticmethod
    def _trim(value: Any) -> Any:
        """Trim strings; return other types unchanged."""
        if isinstance(value, str):
            return value.strip()
        return value

    @classmethod
    def _sentence_case(cls, text: str) -> str:
        """Very lightweight sentence case."""
        s = (text or "").strip()
        if not s:
            return ""
        s = s.lower()
        return s[0].upper() + s[1:]

    @classmethod
    def _title_case(cls, text: str) -> str:
        """Deterministic title case with a small stop-word list."""
        s = (text or "").strip()
        if not s:
            return ""
        words = s.split()
        out: list[str] = []
        for idx, w in enumerate(words):
            lower = w.lower()
            if idx not in (0, len(words) - 1) and lower in cls._STOP_WORDS:
                out.append(lower)
            else:
                out.append(lower.capitalize())
        return " ".join(out)

    @staticmethod
    def _split_author(author: str) -> Tuple[str, str]:
        """Split an author string into (first, last) using simple heuristics."""
        s = (author or "").strip()
        if not s:
            return "", ""
        if "," in s:
            last, first = [p.strip() for p in s.split(",", 1)]
            return first, last
        parts = s.split()
        if len(parts) == 1:
            return "", parts[0]
        return " ".join(parts[:-1]), parts[-1]

    @staticmethod
    def _initials(name: str) -> str:
        """Convert 'First Middle' -> 'F. M.'."""
        parts = [p for p in name.split() if p]
        return " ".join(f"{p[0].upper()}." for p in parts)

    # -------------------------- Abstract API surface -------------------------
    @abstractmethod
    def format_book(self, facts: Mapping[str, Any]) -> str:
        """Format a book citation."""

    @abstractmethod
    def format_journal_article(self, facts: Mapping[str, Any]) -> str:
        """Format a journal article citation."""

    @abstractmethod
    def format_magazine_newspaper(self, facts: Mapping[str, Any]) -> str:
        """Format a magazine/newspaper citation."""

    @abstractmethod
    def format_encyclopedia(self, facts: Mapping[str, Any]) -> str:
        """Format an encyclopedia/dictionary citation."""

    @abstractmethod
    def format_website(self, facts: Mapping[str, Any]) -> str:
        """Format a website/webpage citation."""
