"""Pydantic schemas for export-related requests and responses.

This module defines:
- ExportBulkRequestByLibrary: Start a bulk export for an entire library.
- ExportBulkRequestByIds:     Start a bulk export for a specific list of IDs.
- ExportJobOut:               Polling/response model for an export job.

Notes
-----
* Uses Pydantic v2 style with `ConfigDict` for configuration.
* Keeps `status` as a string in `ExportJobOut` to decouple API from internal
  enums. The service/route layer can map enum -> string.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator

# Public re-exports for convenience in imports from other modules.
__all__ = [
    "ExportType",
    "ExportBulkRequestByLibrary",
    "ExportBulkRequestByIds",
    "ExportJobOut",
]

# -----------------------------------------------------------------------------
# Shared types
# -----------------------------------------------------------------------------

ExportType = Literal["docx", "txt", "bib", "json"]


# -----------------------------------------------------------------------------
# Request models
# -----------------------------------------------------------------------------

class ExportBulkRequestByLibrary(BaseModel):
    """Request to start a bulk export for a single library.

    Attributes
    ----------
    library_id:
        Identifier of the library whose citations are to be exported.
    type:
        Output format of the export artifact.
    style:
        Optional citation style to apply when rendering formatted text
        (e.g., "apa", "mla"). If omitted, the exporter may use a default.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    library_id: int = Field(..., ge=1, description="Target library ID (positive integer).")
    type: ExportType = Field(..., description="Export file type: docx | txt | bib | json.")
    style: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=32,
        description="Optional citation style key (e.g., 'apa', 'mla').",
    )


class ExportBulkRequestByIds(BaseModel):
    """Request to start a bulk export for a specific set of citation IDs.

    Attributes
    ----------
    ids:
        List of citation IDs to export. Must be non-empty and positive ints.
    type:
        Output format of the export artifact.
    style:
        Optional citation style to apply when rendering formatted text.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    ids: List[int] = Field(..., description="Non-empty list of citation IDs.")
    type: ExportType = Field(..., description="Export file type: docx | txt | bib | json.")
    style: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=32,
        description="Optional citation style key (e.g., 'apa', 'mla').",
    )

    @field_validator("ids")
    @classmethod
    def _validate_ids(cls, value: List[int]) -> List[int]:
        """Ensure `ids` is a non-empty list of positive integers."""
        if not value:
            raise ValueError("`ids` must be a non-empty list.")
        if any((not isinstance(x, int)) or x <= 0 for x in value):
            raise ValueError("All `ids` must be positive integers.")
        return value


# -----------------------------------------------------------------------------
# Response models
# -----------------------------------------------------------------------------

class ExportJobOut(BaseModel):
    """Public view of an export job for polling and status checks.

    Attributes
    ----------
    id:
        Unique identifier of the export job.
    status:
        Current status of the job as a lowercase string
        (e.g., 'pending', 'running', 'succeeded', 'failed').
    file_path:
        Absolute file path to the finished export artifact, present only
        when status == 'succeeded'. May be `None` otherwise.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    id: int = Field(..., ge=1, description="Export job ID (positive integer).")
    status: str = Field(..., min_length=3, max_length=16, description="Job status string.")
    file_path: Optional[str] = Field(
        default=None,
        description="Absolute file path for completed exports (succeeded only).",
    )
