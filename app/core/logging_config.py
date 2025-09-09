"""Structured logging setup for the application (JSON to stdout)."""
from __future__ import annotations

import json
import logging as py_logging
import sys
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


def configure_logging(level: int = py_logging.INFO) -> None:
    """Configure global logging with JSON output to stdout."""
    handler = py_logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = py_logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)
