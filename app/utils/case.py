"""Case and text utilities for deterministic formatting (M6).

This module centralizes simple, predictable casing helpers used by
style formatters. The goal is *determinism* over linguistic complexity.

Functions
---------
- normalize_whitespace(text): collapse repeated spaces and trim.
- to_sentence_case(text): lowercase then capitalize first character.
- to_title_case(text, stop_words=None): title case with stop-word handling.

Notes
-----
These helpers intentionally avoid locale-specific rules. If you need more
sophisticated behavior (e.g., preserving acronyms or proper nouns), add
opt-in parameters or extend these functions in a backward-compatible way.
"""

from __future__ import annotations

from typing import Iterable, Set

# Default English stop-words for title casing (minimal set).
_DEFAULT_STOP_WORDS: Set[str] = {
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


def normalize_whitespace(text: str) -> str:
    """Return `text` with repeated spaces collapsed and trimmed.

    Examples
    --------
    >>> normalize_whitespace("  Hello   world  ")
    'Hello world'
    """
    s = (text or "").strip()
    # Avoid importing regex to keep this module lightweight.
    parts = [p for p in s.split(" ") if p != ""]
    return " ".join(parts)


def to_sentence_case(text: str) -> str:
    """Return a deterministic sentence-cased variant of `text`.

    Behavior
    --------
    - Trims whitespace and collapses repeats.
    - Lowercases the whole string.
    - Capitalizes only the first character, if present.

    Examples
    --------
    >>> to_sentence_case("  THE QUICK Brown FOX ")
    'The quick brown fox'
    """
    s = normalize_whitespace(text)
    if not s:
        return ""
    s = s.lower()
    return s[0].upper() + s[1:]


def to_title_case(text: str, stop_words: Iterable[str] | None = None) -> str:
    """Return `text` in deterministic title case with stop-word handling.

    Rules (simple and predictable)
    ------------------------------
    - First and last words are *always* capitalized.
    - Middle words that are present in `stop_words` are lowercased.
    - All other words are capitalized (first letter uppercased, rest lowercased).

    Parameters
    ----------
    text:
        The input string to transform.
    stop_words:
        Optional custom stop-word set; if omitted, a minimal English set is used.

    Examples
    --------
    >>> to_title_case("the lord of the rings")
    'The Lord of the Rings'
    >>> to_title_case("AN INTRODUCTION TO data SCIENCE")
    'An Introduction to Data Science'
    """
    s = normalize_whitespace(text)
    if not s:
        return ""

    sw: Set[str] = set(stop_words) if stop_words is not None else _DEFAULT_STOP_WORDS
    parts = s.split(" ")
    out: list[str] = []

    for idx, word in enumerate(parts):
        lower = word.lower()
        is_edge = idx == 0 or idx == len(parts) - 1
        if not is_edge and lower in sw:
            out.append(lower)
        else:
            out.append(lower.capitalize())

    return " ".join(out)


__all__ = ["normalize_whitespace", "to_sentence_case", "to_title_case"]
