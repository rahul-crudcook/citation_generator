# app/services/exporters/json_export.py
"""JSON exporter for citations.

Provides:
- write_single(citation) -> bytes
- write_bulk(citations) -> bytes

Shape:
- Single: {"id", "type", "facts", "style", "formatted_text"}
- Bulk:   [ { ... }, { ... }, ... ]
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from app.services.exporters.common import coerce_citation_dict


def write_single(citation: Any) -> bytes:
    """Return JSON bytes for a single citation.

    Args:
        citation: ORM/dict-like citation.

    Returns:
        UTF-8 encoded JSON representation of one citation object.
    """
    c = coerce_citation_dict(citation)
    obj = {
        "id": c.get("id"),
        "type": c.get("type"),
        "facts": c.get("facts") or {},
        "style": c.get("style"),
        "formatted_text": c.get("formatted_text"),
    }
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def write_bulk(citations: Iterable[Any]) -> bytes:
    """Return JSON bytes for multiple citations.

    Args:
        citations: Iterable of ORM/dict-like citations.

    Returns:
        UTF-8 encoded JSON array containing multiple citation objects.
    """
    arr = []
    for obj in citations:
        c = coerce_citation_dict(obj)
        arr.append(
            {
                "id": c.get("id"),
                "type": c.get("type"),
                "facts": c.get("facts") or {},
                "style": c.get("style"),
                "formatted_text": c.get("formatted_text"),
            }
        )
    return json.dumps(arr, ensure_ascii=False, indent=2).encode("utf-8")
