# app/core/logging_config.py
"""Structured logging setup for the application (JSON to stdout and optional file).

Features
--------
- JSON logs with a minimal, consistent schema.
- Stdout handler by default (12-factor friendly).
- Optional file sink when the `LOG_FILE` environment variable is set:
  the same JSON formatter is applied to a `FileHandler` alongside stdout.

Usage
-----
Call `configure_logging()` once during app startup (e.g., in `main.py`).
Optionally set `LOG_FILE=/var/log/app/app.log` to enable file logging.
"""

from __future__ import annotations

import json
import logging as py_logging
import os
import sys
from pathlib import Path
from typing import Any, Dict


class JsonFormatter(py_logging.Formatter):
    """Render log records as JSON lines with a minimal, consistent schema."""

    def format(self, record: py_logging.LogRecord) -> str:
        """Format a log record to a JSON string."""
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _build_stdout_handler() -> py_logging.Handler:
    """Create a stdout stream handler with JSON formatting."""
    handler = py_logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    return handler


def _maybe_build_file_handler() -> py_logging.Handler | None:
    """Create a file handler with JSON formatting if LOG_FILE is set.

    Returns:
        A configured `FileHandler` when `LOG_FILE` is provided; otherwise `None`.

    Notes:
        - Parent directories are created if they don't exist.
        - UTF-8 encoding is used to avoid locale-dependent issues.
    """
    log_file = os.getenv("LOG_FILE")
    if not log_file:
        return None

    path = Path(log_file).expanduser()
    try:
        # Ensure the directory exists (no-op if already present).
        if path.parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = py_logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        return file_handler
    except Exception:  # pylint: disable=broad-except
        # Fall back silently if file handler cannot be created; stdout still works.
        return None


def configure_logging(level: int = py_logging.INFO) -> None:
    """Configure global logging with JSON output to stdout and optional file.

    Args:
        level: Logging level for the root logger (default: INFO).
    """
    stdout_handler = _build_stdout_handler()
    file_handler = _maybe_build_file_handler()

    root = py_logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(stdout_handler)
    if file_handler is not None:
        root.addHandler(file_handler)
