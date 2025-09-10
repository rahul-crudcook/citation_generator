"""
Utilities for merging and reconciling citation fact dictionaries.

Primary policy:
- "User wins": only fill missing fields from fetched data unless
  `allow_overwrite=True`.
- Author arrays are merged with de-duplication by (last, first) case-insensitive.

This module is intentionally framework-agnostic and pure-Python for easy testing.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple


def _norm_author_key(author: Dict[str, Any]) -> Tuple[str, str]:
    """Create a case-insensitive identity key for an author."""
    last = str(author.get("last", "") or "").strip().lower()
    first = str(author.get("first", "") or "").strip().lower()
    return last, first


def _merge_authors(
    user_list: Optional[Iterable[Dict[str, Any]]],
    fetched_list: Optional[Iterable[Dict[str, Any]]],
    allow_overwrite: bool,
) -> List[Dict[str, Any]]:
    """Merge two author lists with de-duplication.

    Args:
        user_list: Authors already present (user-provided or existing).
        fetched_list: Authors coming from a fetcher.
        allow_overwrite: If True, fetched authors can replace user authors
            when user authors are missing or blank.

    Returns:
        A list of authors, preserving user order first, then fetched uniques.
    """
    user_list = list(user_list or [])
    fetched_list = list(fetched_list or [])

    # Build a set of existing identities to avoid duplicates.
    seen = {_norm_author_key(a) for a in user_list}

    merged: List[Dict[str, Any]] = list(user_list)

    for f in fetched_list:
        key = _norm_author_key(f)
        if key in seen:
            # Optional: enrich blanks if overwrite is allowed.
            if allow_overwrite:
                # Find and update the first matching author if user fields blank.
                for idx, existing in enumerate(merged):
                    if _norm_author_key(existing) == key:
                        last = existing.get("last") or f.get("last")
                        first = existing.get("first") or f.get("first")
                        merged[idx] = {"last": last or "", "first": first or ""}
                        break
            continue
        seen.add(key)
        merged.append({"last": f.get("last", "") or "", "first": f.get("first", "") or ""})

    return merged


def merge_facts(
    user_facts: Optional[Dict[str, Any]],
    fetched_facts: Dict[str, Any],
    *,
    allow_overwrite: bool = False,
) -> Dict[str, Any]:
    """Merge fact dictionaries according to the "user wins" policy.

    For scalar keys:
        - If user value is present and non-empty → keep it.
        - Else use fetched value.

    For list keys:
        - Authors: special merge with de-duplication.
        - Other lists: keep user list if present; otherwise fetched list.

    Args:
        user_facts: The baseline facts (often user-provided), or None.
        fetched_facts: New facts fetched from an external provider.
        allow_overwrite: If True, fetched values may overwrite non-informative
            user values in certain cases (e.g., enriching blanks).

    Returns:
        A merged dictionary of facts.
    """
    user_facts = dict(user_facts or {})
    out: Dict[str, Any] = dict(user_facts)

    for key, fetched_val in fetched_facts.items():
        user_val = user_facts.get(key)

        # Authors get special handling.
        if key == "authors":
            out[key] = _merge_authors(
                user_val if isinstance(user_val, list) else [],
                fetched_val if isinstance(fetched_val, list) else [],
                allow_overwrite,
            )
            continue

        # For lists that are not authors: user list wins if present.
        if isinstance(fetched_val, list):
            if allow_overwrite:
                # Overwrite only if user list is empty or None.
                if not user_val:
                    out[key] = list(fetched_val)
            else:
                if key not in out or out[key] in (None, [], ""):
                    out[key] = list(fetched_val)
            continue

        # Scalars and everything else.
        if allow_overwrite:
            # Overwrite only if user value is empty/None.
            if user_val in (None, "", [], {}):
                out[key] = fetched_val
        else:
            if key not in out or out[key] in (None, "", [], {}):
                out[key] = fetched_val

    return out
