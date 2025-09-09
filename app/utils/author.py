"""Author parsing helpers (robust, stateless).

Goals (M2):
- Parse a variety of human name formats into a normalized dict:
  {first, middle, last, suffix}
- Handle:
    * "Last, First M. Jr." (comma style)
    * "First M. Last, Jr." (postfix suffix)
    * initials and multi-part middle names ("J. R. R.")
    * common suffixes (Jr., Sr., II, III, IV, Ph.D., MD, Esq.)
    * single-token names gracefully (put in `last`)
- Keep simple helpers for lists and display formatting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

# Common suffixes (case-insensitive, dots optional)
_SUFFIXES = {
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
    "phd",
    "ph.d",
    "md",
    "m.d",
    "dphil",
    "d.phil",
    "esq",
    "esq.",
}

# collapse multiple whitespace, keep hyphens/apostrophes (for O'Neil, Anne-Marie)
_WS_RE = re.compile(r"\s+")


def _norm_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _strip_trailing_comma(s: str) -> str:
    return s[:-1].strip() if s.endswith(",") else s


def _looks_like_suffix(token: str) -> bool:
    t = token.strip().lower().rstrip(".")
    return t in _SUFFIXES


def _split_by_commas(text: str) -> List[str]:
    # Split once or twice max; some formats have two commas:
    # "Last, First Middle, Jr."
    parts = [p.strip() for p in text.split(",")]
    return [p for p in parts if p]


def _extract_suffix_from_tail(tokens: List[str]) -> Tuple[List[str], str]:
    """If the last token looks like a suffix, peel it off."""
    if not tokens:
        return tokens, ""
    tail = tokens[-1]
    if _looks_like_suffix(tail):
        return tokens[:-1], tail.rstrip(".")
    return tokens, ""


def _split_first_middle_last(tokens: List[str]) -> Tuple[str, str, str]:
    """Given a sequence of name tokens (no commas, no suffix),
    return (first, middle, last). Handles 1..N tokens.
    """
    if not tokens:
        return "", "", ""
    if len(tokens) == 1:
        return "", "", tokens[0]
    if len(tokens) == 2:
        return tokens[0], "", tokens[1]
    # 3+ tokens → first token is first name, last token is last name,
    # everything in between is middle (allow initials like "J.", "R.")
    first = tokens[0]
    last = tokens[-1]
    middle = " ".join(tokens[1:-1])
    return first, middle, last


def parse_person_name(text: str) -> Dict[str, str]:
    """Parse a human name into {first, middle, last, suffix}.

    Accepts:
      - "Last, First M. Jr."
      - "First M. Last, Jr."
      - "First Last"
      - "Cher" (single token)
      - Leading/trailing/multiple spaces, dots in initials/suffixes.

    Returns:
      dict with keys: first, middle, last, suffix (always present, may be empty strings)
    """
    s = _norm_ws(text)
    if not s:
        return {"first": "", "middle": "", "last": "", "suffix": ""}

    # Case A: Comma-style variants
    if "," in s:
        parts = _split_by_commas(s)
        if len(parts) == 1:
            # Degenerate case: trailing comma or similar → treat as non-comma path
            s = _strip_trailing_comma(parts[0])
        elif len(parts) == 2:
            # "Last, First Middle"  OR  "First Middle Last, Jr"
            left, right = parts
            # Heuristic: if right side looks like a suffix ONLY, it's "First Last, Jr"
            if _looks_like_suffix(right) and " " in left:
                # Left contains first/middle/last; peel suffix
                tokens = left.split(" ")
                tokens, suffix = _extract_suffix_from_tail(tokens)
                first, middle, last = _split_first_middle_last(tokens)
                return {
                    "first": first,
                    "middle": middle,
                    "last": last,
                    "suffix": suffix,
                }
            # Otherwise assume "Last, First Middle"
            last = _strip_trailing_comma(left)
            right_tokens = right.split(" ")
            right_tokens, suffix = _extract_suffix_from_tail(right_tokens)
            first, middle, _ = _split_first_middle_last(right_tokens)
            return {
                "first": first,
                "middle": middle,
                "last": last,
                "suffix": suffix,
            }
        else:
            # Three-part comma split: "Last, First Middle, Jr."
            last = parts[0]
            right = " ".join(parts[1:-1])  # join middle chunk(s)
            suffix = parts[-1] if _looks_like_suffix(parts[-1]) else ""
            right_tokens = right.split(" ")
            first, middle, _ = _split_first_middle_last(right_tokens)
            return {
                "first": first,
                "middle": middle,
                "last": last,
                "suffix": suffix.rstrip("."),
            }

    # Case B: No comma → "First Middle Last [Suffix?]"
    tokens = s.split(" ")
    tokens, maybe_suffix = _extract_suffix_from_tail(tokens)
    first, middle, last = _split_first_middle_last(tokens)
    return {
        "first": first,
        "middle": middle,
        "last": last,
        "suffix": maybe_suffix,
    }


# ---------------------------------------------------------------------
# Friendly dataclass + list utilities (optional but handy)
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class Author:
    """Normalized author representation with display helper."""

    first: str = ""
    middle: str = ""
    last: str = ""
    suffix: str = ""

    def display(self) -> str:
        """Human-readable display (e.g., 'Last, First M., Jr.')."""
        parts: List[str] = []
        if self.first:
            parts.append(self.first)
        if self.middle:
            parts.append(self.middle)
        given = " ".join(parts).strip()
        core = f"{self.last}, {given}" if given else self.last
        return f"{core}, {self.suffix}" if self.suffix else core


def parse_author(text: str) -> Author:
    """Dataclass wrapper around `parse_person_name`."""
    data = parse_person_name(text)
    return Author(
        first=data.get("first", ""),
        middle=data.get("middle", ""),
        last=data.get("last", ""),
        suffix=data.get("suffix", ""),
    )


def parse_authors(authors: Optional[Iterable[str]]) -> List[Author]:
    """Parse an iterable of author strings into `Author` objects."""
    if not authors:
        return []
    return [parse_author(a) for a in authors if isinstance(a, str) and a.strip()]
