# pylint: disable=W0718
# app/repos/export_job_repository.py
"""Repository for :class:`ExportJob` persistence (M8).

This module encapsulates CRUD operations for the ExportJob model and keeps
SQL/ORM concerns out of services and routes.

Design principles
-----------------
* **No commits here** — the caller (service/route) owns the transaction.
* **Small surface area** — create, get, get_owned, and set_status cover the needs.
* **Input normalization** — `params_json` may arrive as dict or JSON string; we
  normalize to a dict before persisting to the JSON column.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, Union, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.export_job import ExportJob, ExportKind, ExportStatus


class ExportJobRepository:
    """Data access layer for :class:`ExportJob`.

    Notes
    -----
    - This repository never commits; the service layer should call `session.commit()`.
    - Methods return ORM instances tracked by the provided session.
    """

    def __init__(self, db: Session) -> None:
        """Initialize the repository with a live SQLAlchemy session.

        Parameters
        ----------
        db:
            An active SQLAlchemy ORM session.
        """
        self._db = db

    # --------------------------------------------------------------------- #
    # Create / Read
    # --------------------------------------------------------------------- #

    def create(
        self,
        user_id: int,
        kind: Union[ExportKind, str],
        params_json: Union[dict, str, None],
        status: Union[ExportStatus, str],
    ) -> ExportJob:
        """Create and add (but do not commit) a new export job row.

        Parameters
        ----------
        user_id:
            Owner of the job.
        kind:
            Job kind, e.g. :class:`ExportKind.LIBRARY` or the string "library".
        params_json:
            Parameter bag for the job. Accepts a dict or a JSON-encoded string.
        status:
            Initial status (usually :class:`ExportStatus.PENDING`).

        Returns
        -------
        ExportJob
            The newly added (but not yet committed) ORM instance.
        """
        # Normalize kind/status to strings
        kind_value = kind.value if isinstance(kind, ExportKind) else str(kind)
        status_value = status.value if isinstance(status, ExportStatus) else str(status)

        # Normalize params_json to a dict for JSON column
        params_dict: Optional[dict[str, Any]]
        if params_json is None:
            params_dict = None
        elif isinstance(params_json, dict):
            params_dict = params_json
        else:
            # String input — attempt to parse JSON
            try:
                params_dict = json.loads(params_json)
            except Exception:
                # As a last resort, store as {"raw": "<string>"} so nothing is lost
                params_dict = {"raw": str(params_json)}

        now = datetime.utcnow()
        job = ExportJob(
            user_id=user_id,
            kind=kind_value,
            params_json=params_dict,
            status=status_value,
            created_at=now,
            updated_at=now,
        )
        self._db.add(job)
        # No commit here; caller manages transaction.
        return job

    def get(self, job_id: int) -> Optional[ExportJob]:
        """Retrieve a job by id (no ownership check).

        Returns
        -------
        Optional[ExportJob]
            The job instance if found, otherwise None.
        """
        stmt = select(ExportJob).where(ExportJob.id == job_id)
        return self._db.execute(stmt).scalar_one_or_none()

    def get_owned(self, user_id: int, job_id: int) -> Optional[ExportJob]:
        """Retrieve a job by id that is owned by the given user.

        Returns
        -------
        Optional[ExportJob]
            The job instance if found and owned by user, otherwise None.
        """
        stmt = select(ExportJob).where(
            ExportJob.id == job_id,
            ExportJob.user_id == user_id,
        )
        return self._db.execute(stmt).scalar_one_or_none()

    # --------------------------------------------------------------------- #
    # Update
    # --------------------------------------------------------------------- #

    def set_status(
        self,
        job_id: int,
        status: Union[ExportStatus, str],
        *,
        file_path: Optional[str] = None,
        error: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> None:
        """Update status and optional fields for a job (not committed).

        Parameters
        ----------
        job_id:
            Primary key of the job to update.
        status:
            New status ("pending" | "running" | "succeeded" | "failed").
        file_path:
            Optional absolute path to the exported file (on success).
        error:
            Optional error message (on failure).
        started_at:
            Optional timestamp when processing started.
        finished_at:
            Optional timestamp when processing finished.

        Raises
        ------
        ValueError
            If the job does not exist.
        """
        job = self.get(job_id)
        if job is None:
            raise ValueError(f"ExportJob {job_id} not found")

        # Normalize status to string
        job.status = status.value if isinstance(status, ExportStatus) else str(status)

        # Optional timestamps / outputs
        if started_at is not None:
            job.started_at = started_at
        if finished_at is not None:
            job.finished_at = finished_at
        if file_path is not None:
            job.file_path = file_path
        if error is not None:
            job.error = error

        job.updated_at = datetime.utcnow()
        # No commit here; caller manages transaction.
