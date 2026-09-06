"""Secret-conscious structured logging for analytical and application operations."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

OPERATION_FIELDS = ("run_id", "release_id", "operation", "status", "duration_ms", "error_category")


class OperationFieldFilter(logging.Filter):
    """Supply null operational fields for legacy log calls and text formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        for field in OPERATION_FIELDS:
            if not hasattr(record, field):
                setattr(record, field, None)
        return True


class JsonLogFormatter(logging.Formatter):
    """Emit one stable JSON object per log record without serializing arbitrary payloads."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **{field: getattr(record, field, None) for field in OPERATION_FIELDS},
        }
        if record.exc_info:
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    """Configure deterministic JSON logs or a concise local text fallback."""
    normalized = level.upper()
    if normalized not in logging.getLevelNamesMapping():
        raise ValueError(f"Unsupported log level: {level}")
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    elif log_format == "text":
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s | "
                "run_id=%(run_id)s release_id=%(release_id)s operation=%(operation)s "
                "status=%(status)s duration_ms=%(duration_ms)s error_category=%(error_category)s"
            )
        )
    else:
        raise ValueError(f"Unsupported log format: {log_format}")
    handler.addFilter(OperationFieldFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(normalized)


@contextmanager
def logged_operation(
    operation: str,
    *,
    release_id: str | None = None,
    run_id: str | None = None,
    logger: logging.Logger | None = None,
) -> Iterator[str]:
    """Log operation start/completion/failure with required operational fields."""
    active_logger = logger or logging.getLogger("prostate_journey.operation")
    active_run_id = run_id or str(uuid.uuid4())
    started = time.perf_counter()
    common = {
        "run_id": active_run_id,
        "release_id": release_id,
        "operation": operation,
        "duration_ms": 0,
        "error_category": None,
    }
    active_logger.info("operation_started", extra={**common, "status": "STARTED"})
    try:
        yield active_run_id
    except Exception as error:
        duration = round((time.perf_counter() - started) * 1000, 3)
        active_logger.exception(
            "operation_failed",
            extra={
                **common,
                "status": "FAILED",
                "duration_ms": duration,
                "error_category": type(error).__name__,
            },
        )
        raise
    else:
        duration = round((time.perf_counter() - started) * 1000, 3)
        active_logger.info(
            "operation_completed",
            extra={**common, "status": "SUCCEEDED", "duration_ms": duration},
        )
