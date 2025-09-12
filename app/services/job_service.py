# app/services/job_service.py
# pylint: disable=W0718
"""Background export job orchestration service.

This service coordinates creation, scheduling, and execution of *bulk* export
jobs. It persists job state in the DB, runs the heavy work off the event loop,
and updates status to RUNNING/SUCCEEDED/FAILED.

Key points
----------
* Public surface is small and intention-revealing.
* DB access is delegated to the repository; export logic to ExportService.
* Scheduling uses `asyncio.create_task` from an **async** calling context
  (our POST /exports/bulk route is async), avoiding "no running event loop".
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.db.session import SessionLocal  # sessionmaker/scoped_session factory
from app.models.export_job import ExportJob, ExportKind, ExportStatus
from app.repos.export_job_repository import ExportJobRepository
from app.services.export_service import ExportService
from app.services.format_service import FormatService

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobScheduleResult:
    """Simple DTO describing a scheduled job."""

    job_id: int
    status: str


class JobService:
    """Coordinates background export jobs.

    Responsibilities:
    - Create a persisted job row (status=PENDING).
    - Schedule work asynchronously (returns immediately).
    - Transition job state through RUNNING -> SUCCEEDED/FAILED.
    - Expose job lookup for polling.

    Notes
    -----
    The heavy export runs in a worker thread via `asyncio.to_thread`
    to keep the event loop responsive and to isolate DB sessions.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            session_factory: Callable returning a new SQLAlchemy Session.
                             Defaults to :data:`app.db.session.SessionLocal`.
            logger: Logger instance to use (defaults to module logger).
        """
        self._session_factory: Callable[[], Session] = session_factory or SessionLocal
        self._log = logger or LOGGER

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def create_export_job(
        self,
        user_id: int,
        *,
        kind: ExportKind,
        params: Dict[str, Any],
    ) -> ExportJob:
        """Persist a new export job in PENDING state.

        Args:
            user_id: Owner of the job.
            kind: Export job kind (e.g. ExportKind.LIBRARY or ExportKind.IDS).
            params: Parameter bag to persist in `exports.params_json`.
                    Expected keys:
                      - library export: {"library_id": int, "type": "...", "style": "..."}
                      - ids export:     {"ids": [int, ...], "type": "...", "style": "..."}

        Returns:
            The newly created :class:`ExportJob` ORM object.
        """
        if not params.get("type"):
            raise ValueError("params['type'] is required (docx|txt|bib|json)")

        with self._session_scope() as db:
            repo = ExportJobRepository(db)
            # Repo accepts dict or JSON string and normalizes to a dict for JSON column.
            job = repo.create(
                user_id=user_id,
                kind=kind,
                params_json=params,  # pass dict; repo handles normalization
                status=ExportStatus.PENDING,
            )
            self._log.debug(
                "Created export job",
                extra={"job_id": job.id, "user_id": user_id, "kind": kind.value},
            )
            return job

    async def schedule_export_job(self, job_id: int) -> JobScheduleResult:
        """Schedule the job's worker on the current event loop.

        This method is `async` so callers in async routes can `await` it,
        ensuring a running loop context exists for `asyncio.create_task`.

        Args:
            job_id: The persisted job id.

        Returns:
            :class:`JobScheduleResult` reflecting the scheduled state.
        """
        # We are in an async context; it is safe to create a task.
        asyncio.create_task(self._run_job_worker(job_id))
        self._log.info("Scheduled export job", extra={"job_id": job_id})
        return JobScheduleResult(job_id=job_id, status=ExportStatus.PENDING.value)

    def get_job(self, user_id: int, job_id: int) -> Optional[ExportJob]:
        """Fetch a job if owned by the given user (for polling)."""
        with self._session_scope() as db:
            repo = ExportJobRepository(db)
            return repo.get_owned(user_id=user_id, job_id=job_id)

    # ------------------------------------------------------------------ #
    # Internal worker
    # ------------------------------------------------------------------ #

    async def _run_job_worker(self, job_id: int) -> None:
        """Async worker that executes an export job and updates its status.

        Steps
        -----
        1) Mark job RUNNING and read persisted params.
        2) Run heavy export on a worker thread (its own DB session).
        3) On success: mark SUCCEEDED and persist `file_path`.
        4) On failure: mark FAILED and persist error message.
        """
        self._log.debug("Worker starting", extra={"job_id": job_id})

        # ---- Step 1: transition to RUNNING and load params
        try:
            with self._session_scope() as db:
                repo = ExportJobRepository(db)

                job = db.get(ExportJob, job_id)
                if job is None:
                    self._log.error("Job not found; aborting", extra={"job_id": job_id})
                    return

                repo.set_status(
                    job_id=job.id,
                    status=ExportStatus.RUNNING,
                    started_at=datetime.utcnow(),
                )

                raw_params = getattr(job, "params_json", None)
                params = self._decode_params(raw_params)
                user_id = int(job.user_id)
                export_type = str(params.get("type") or "txt")
        except Exception as exc:  # pragma: no cover - defensive
            self._log.exception("Failed to initialize job worker", extra={"job_id": job_id})
            with self._session_scope() as db:
                ExportJobRepository(db).set_status(
                    job_id=job_id,
                    status=ExportStatus.FAILED,
                    error=str(exc),
                    finished_at=datetime.utcnow(),
                )
            return

        # ---- Step 2: run the heavy work in a thread
        try:
            file_path = await asyncio.to_thread(
                self._export_in_thread, user_id, export_type, params
            )
        except Exception as exc:  # pragma: no cover - defensive
            # ---- Step 4: FAILED
            self._log.exception("Export job failed", extra={"job_id": job_id})
            with self._session_scope() as db:
                ExportJobRepository(db).set_status(
                    job_id=job_id,
                    status=ExportStatus.FAILED,
                    error=str(exc),
                    finished_at=datetime.utcnow(),
                )
            return

        # ---- Step 3: SUCCEEDED
        with self._session_scope() as db:
            ExportJobRepository(db).set_status(
                job_id=job_id,
                status=ExportStatus.SUCCEEDED,
                file_path=file_path,
                finished_at=datetime.utcnow(),
            )
            self._log.info(
                "Export job succeeded", extra={"job_id": job_id, "file_path": file_path}
            )

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #

    def _session_scope(self) -> "_SessionContext":
        """Return a context manager that owns a short-lived DB session."""
        return _SessionContext(self._session_factory)

    @staticmethod
    def _decode_params(params_json: Any) -> Dict[str, Any]:
        """Deserialize persisted params to a dict (accept dict or JSON string)."""
        if params_json is None:
            return {}
        if isinstance(params_json, dict):
            return params_json
        try:
            return json.loads(str(params_json))
        except Exception:  # pragma: no cover - defensive
            return {}

    # ------------------------------------------------------------------ #
    # Export execution (runs inside a background thread)
    # ------------------------------------------------------------------ #

    def _export_in_thread(
        self, user_id: int, export_type: str, params: Dict[str, Any]
    ) -> str:
        """Perform the export in a dedicated thread with its own DB session.

        Decides which ExportService method to call based on params.

        Returns:
            Absolute file path to the generated export artifact.
        """
        db = self._session_factory()
        try:
            fmt = FormatService()
            service = ExportService(db=db, format_service=fmt)

            style = params.get("style")
            if "library_id" in params:
                library_id = int(params["library_id"])
                return service.export_library_to_file(
                    user_id=user_id,
                    library_id=library_id,
                    export_type=export_type,
                    style=style,
                )

            if "ids" in params:
                ids = params["ids"]
                if not isinstance(ids, list) or not ids:
                    raise ValueError("'ids' must be a non-empty list of integers")
                id_list = [int(x) for x in ids]
                return service.export_ids_to_file(
                    user_id=user_id,
                    ids=id_list,
                    export_type=export_type,
                    style=style,
                )

            raise ValueError("Missing export scope: provide 'library_id' or non-empty 'ids'.")
        finally:
            # Always close the worker session.
            try:
                db.close()
            except Exception:  # pragma: no cover - defensive
                pass


class _SessionContext:  # pylint: disable=too-few-public-methods
    """Small context manager to manage session lifecycle (commit/rollback)."""

    def __init__(self, factory: Callable[[], Session]) -> None:
        self._factory = factory
        self._session: Optional[Session] = None

    def __enter__(self) -> Session:
        self._session = self._factory()
        return self._session

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        assert self._session is not None
        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        finally:
            self._session.close()
