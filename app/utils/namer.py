# citation_generator/app/utils/namer.py
"""Author name rendering utilities for citation formatting (M6).

This module provides deterministic helpers to:
- Normalize flexible author inputs (dict or string) into a {first,last} shape.
- Render a single author in short ('Last, F. M.') or long ('Last, First Middle') form.
- Render lists of authors with style-appropriate connectors and *et al.* rules.

The functions here are intentionally small and pure to make testing easy.

Input Flexibility
-----------------
- Dict form: {"first": "Jane Ann", "last": "Doe"}
- String (last-first): "Doe, Jane Ann"
- String (first-last): "Jane Ann Doe"
- String (single name): "Plato"  -> {"first":"", "last":"Plato"}

Style Defaults
--------------
If not provided explicitly, *et al.* thresholds and connectors fall back to
sane defaults per style (APA/MLA/Chicago/Turabian/Harvard).

Public API
----------
- normalize_person(person) -> dict[first,last]
- render_author_short(person) -> 'Last, F. M.'
- render_author_long(person)  -> 'Last, First Middle'
- render_authors_list(persons, *, style, et_al_threshold=None, max_authors=None) -> str
"""

from __future__ import annotations

from typing import Iterable, Mapping, Tuple

from app.core.enums import Style
from app.utils.case import normalize_whitespace

# -------------------------
# Style-specific defaults
# -------------------------

# Minimal, pragmatic thresholds (docs or configuration can tune these later):
DEFAULT_ET_AL: dict[Style, int] = {
    Style.apa: 3,
    Style.mla: 3,
    Style.chicago: 4,
    Style.turabian: 4,
    Style.harvard: 3,
}

# Connector words/symbols between the penultimate and final authors.
# APA uses an ampersand; others typically use 'and'.
FINAL_CONNECTOR: dict[Style, str] = {
    Style.apa: " & ",
    Style.mla: " and ",
    Style.chicago: " and ",
    Style.turabian: " and ",
    Style.harvard: " and ",
}

# Whether to include a serial comma before the final connector.
SERIAL_COMMA: dict[Style, bool] = {
    Style.apa: True,
    Style.mla: False,
    Style.chicago: True,  # Chicago typically prefers the serial comma
    Style.turabian: True,
    Style.harvard: False,
}


# -------------------------
# Normalization helpers
# -------------------------
def _split_author_string(s: str) -> Tuple[str, str]:
    """Split an author string into (first, last) using simple heuristics.

    Rules
    -----
    - 'Last, First Middle'  -> ('First Middle', 'Last')
    - 'First Middle Last'   -> ('First Middle', 'Last')
    - 'SingleName'          -> ('', 'SingleName')

    Returns
    -------
    (first, last)
    """
    text = normalize_whitespace(s)
    if not text:
        return "", ""
    if "," in text:
        last, first = [p.strip() for p in text.split(",", 1)]
        return normalize_whitespace(first), normalize_whitespace(last)
    parts = text.split(" ")
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def normalize_person(person: object) -> dict[str, str]:
    """Return a normalized person dict {'first','last'} from flexible input.

    Parameters
    ----------
    person:
        A dict with 'first'/'last' keys or a string (various shapes).

    Examples
    --------
    >>> normalize_person({"first":"Jane Ann","last":"Doe"})
    {'first': 'Jane Ann', 'last': 'Doe'}
    >>> normalize_person("Doe, Jane Ann")
    {'first': 'Jane Ann', 'last': 'Doe'}
    >>> normalize_person("Plato")
    {'first': '', 'last': 'Plato'}
    """
    if isinstance(person, Mapping):
        first = normalize_whitespace(str(person.get("first", "")))
        last = normalize_whitespace(str(person.get("last", "")))
        return {"first": first, "last": last}
    if isinstance(person, str):
        first, last = _split_author_string(person)
        return {"first": first, "last": last}
    # Unknown shape -> empty record (caller can filter out)
    return {"first": "", "last": ""}


# -------------------------
# Rendering helpers
# -------------------------
def _initials(name: str) -> str:
    """Return initials for 'First Middle' -> 'F. M.' (no trailing space)."""
    parts = [p for p in normalize_whitespace(name).split(" ") if p]
    return " ".join(f"{p[0].upper()}." for p in parts)


def render_author_short(person: object) -> str:
    """Render a single author in short form: 'Last, F. M.'.

    Examples
    --------
    >>> render_author_short({"first":"Jane Ann","last":"Doe"})
    'Doe, J. A.'
    >>> render_author_short("Doe, Jane")
    'Doe, J.'
    >>> render_author_short("Plato")
    'Plato'
    """
    norm = normalize_person(person)
    first, last = norm["first"], norm["last"]
    if not first and not last:
        return ""
    if not last:
        return _initials(first)
    if not first:
        return last
    return f"{last}, {_initials(first)}"


def render_author_long(person: object) -> str:
    """Render a single author in long form: 'Last, First Middle'.

    Examples
    --------
    >>> render_author_long({"first":"Jane Ann","last":"Doe"})
    'Doe, Jane Ann'
    >>> render_author_long("Doe, Jane")
    'Doe, Jane'
    >>> render_author_long("Plato")
    'Plato'
    """
    norm = normalize_person(person)
    first, last = norm["first"], norm["last"]
    if not first and not last:
        return ""
    if not last:
        return first
    if not first:
        return last
    return f"{last}, {first}"


def _join_with_connector(parts: list[str], *, style: Style) -> str:
    """Join a list of author strings with style-specific punctuation."""
    n = len(parts)
    if n == 0:
        return ""
    if n == 1:
        return parts[0]
    connector = FINAL_CONNECTOR.get(style, " and ")
    use_serial = SERIAL_COMMA.get(style, False)
    if n == 2:
        return f"{parts[0]}{connector}{parts[1]}"
    # n >= 3
    head = ", ".join(parts[:-1])
    if use_serial:
        return f"{head},{connector}{parts[-1]}"
    return f"{head}{connector}{parts[-1]}"


def render_authors_list(
    persons: Iterable[object],
    *,
    style: Style,
    et_al_threshold: int | None = None,
    max_authors: int | None = None,
    short: bool = True,
) -> str:
    """Render an author list according to style conventions.

    Parameters
    ----------
    persons:
        Iterable of person dicts/strings to render.
    style:
        Citation style (affects connector and serial comma).
    et_al_threshold:
        If number of authors >= threshold, render as "First Author et al."
        instead of the full list. If None, a style default is used.
    max_authors:
        Optional cap for how many authors to include when not using *et al.*
        (e.g., limit to 20). None means unlimited.
    short:
        If True, use short form ('Last, F. M.'); if False, long form
        ('Last, First Middle').

    Returns
    -------
    str
        Rendered author list string.

    Examples
    --------
    >>> from app.core.enums import Style
    >>> render_authors_list(["Doe, Jane", "Smith, John"], style=Style.apa)
    'Doe, J., & Smith, J.'
    >>> render_authors_list(["Doe, Jane", "Smith, John", "Roe, Alex"], style=Style.mla)
    'Doe, Jane, et al.'
    """
    et_threshold = et_al_threshold or DEFAULT_ET_AL.get(style, 3)
    people = [normalize_person(p) for p in persons or []]
    people = [p for p in people if p["first"] or p["last"]]

    if not people:
        return ""

    if len(people) >= et_threshold:
        # "First Author et al."
        first = people[0]
        piece = render_author_long(first) if not short else render_author_short(first)
        return f"{piece} et al."

    # Otherwise, render all (with optional cap)
    if max_authors is not None:
        people = people[: max_authors or 0]

    rendered: list[str] = []
    for p in people:
        rendered.append(render_author_short(p) if short else render_author_long(p))

    return _join_with_connector(rendered, style=style)


__all__ = [
    "DEFAULT_ET_AL",
    "FINAL_CONNECTOR",
    "SERIAL_COMMA",
    "normalize_person",
    "render_author_short",
    "render_author_long",
    "render_authors_list",
]
