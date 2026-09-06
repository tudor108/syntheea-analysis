"""Minimal aggregate-only HTTP application with health and readiness contracts."""

from __future__ import annotations

import json
import logging
import os
import posixpath
import signal
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from types import FrameType
from typing import Any
from urllib.parse import unquote, urlsplit

from .app_config import ApplicationSettings
from .logging_config import logged_operation
from .release_integrity import ApplicationArtifacts, resolve_application_artifacts

LOGGER = logging.getLogger(__name__)


class RuntimeState:
    """Cache a verified release/presentation pair while keeping liveness independent."""

    def __init__(self, settings: ApplicationSettings, *, run_id: str | None = None) -> None:
        self.settings = settings
        self.run_id = run_id or str(uuid.uuid4())
        self.started = time.monotonic()
        self.artifacts: ApplicationArtifacts | None = None
        self.error_category: str | None = None
        self.error_message: str | None = None
        self.checked_at = 0.0
        self.lock = threading.Lock()
        self.refresh(force=True)

    def refresh(self, *, force: bool = False) -> bool:
        with self.lock:
            elapsed = time.monotonic() - self.checked_at
            if not force and elapsed < self.settings.readiness_cache_seconds:
                return self.artifacts is not None
            started = time.perf_counter()
            try:
                artifacts = resolve_application_artifacts(self.settings)
            except Exception as error:
                self.artifacts = None
                self.error_category = type(error).__name__
                self.error_message = str(error)
                status = "FAILED"
            else:
                self.artifacts = artifacts
                self.error_category = None
                self.error_message = None
                status = "SUCCEEDED"
            self.checked_at = time.monotonic()
            LOGGER.info(
                "readiness_probe",
                extra={
                    "run_id": self.run_id,
                    "release_id": (
                        self.artifacts.release.dataset_version if self.artifacts else None
                    ),
                    "operation": "readiness",
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error_category": self.error_category,
                },
            )
            return self.artifacts is not None

    def health_payload(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": self.settings.service_name,
            "environment": self.settings.environment,
            "run_id": self.run_id,
            "uptime_seconds": round(time.monotonic() - self.started, 3),
            "synthetic_data_only": True,
        }

    def readiness_payload(self) -> dict[str, Any]:
        if self.artifacts is None:
            return {
                "status": "not_ready",
                "service": self.settings.service_name,
                "run_id": self.run_id,
                "error_category": self.error_category,
                "message": self.error_message,
                "openai_required": False,
                "synthetic_data_only": True,
            }
        warnings = [
            *self.artifacts.release.warnings,
            *self.artifacts.presentation.warnings,
        ]
        return {
            "status": "ready",
            "service": self.settings.service_name,
            "run_id": self.run_id,
            "release_id": self.artifacts.release.dataset_version,
            "entrypoint": self.settings.presentation_entrypoint,
            "release_integrity": "passed",
            "presentation_integrity": "passed",
            "warnings": warnings,
            "openai_required": False,
            "synthetic_data_only": True,
        }


class AnalyticsRequestHandler(SimpleHTTPRequestHandler):
    """Serve only files recorded in the verified presentation manifest."""

    server_version = "ProstateJourneyAnalytics/2.2"
    sys_version = ""
    state: RuntimeState

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        directory = (
            self.state.artifacts.presentation.presentation_dir
            if self.state.artifacts is not None
            else self.state.settings.paths.presentations
        )
        super().__init__(*args, directory=str(directory), **kwargs)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _normalized_path(self) -> str | None:
        raw_path = unquote(urlsplit(self.path).path)
        normalized = posixpath.normpath(raw_path).lstrip("/")
        candidate = PurePosixPath(normalized)
        if normalized in {"", "."}:
            return ""
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        return candidate.as_posix()

    def do_GET(self) -> None:  # noqa: N802
        path = self._normalized_path()
        if path is None:
            self._write_json(HTTPStatus.BAD_REQUEST, {"status": "invalid_path"})
            return
        if path == "health":
            self._write_json(HTTPStatus.OK, self.state.health_payload())
            return
        if path == "ready":
            ready = self.state.refresh()
            self._write_json(
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                self.state.readiness_payload(),
            )
            return
        if path == "":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"/{self.state.settings.presentation_entrypoint}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.state.artifacts is None:
            self._write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"status": "not_ready", "message": "Certified presentation is unavailable"},
            )
            return
        if path not in self.state.artifacts.presentation.output_files:
            self._write_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def list_directory(self, path: str | os.PathLike[str]) -> None:
        self._write_json(HTTPStatus.FORBIDDEN, {"status": "directory_listing_disabled"})
        return None

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info(
            "http_request",
            extra={
                "run_id": self.state.run_id,
                "release_id": (
                    self.state.artifacts.release.dataset_version
                    if self.state.artifacts is not None
                    else None
                ),
                "operation": "http_request",
                "status": str(args[1]) if len(args) > 1 else "UNKNOWN",
                "duration_ms": None,
                "error_category": None,
            },
        )


def create_application_server(
    settings: ApplicationSettings,
    *,
    run_id: str | None = None,
) -> tuple[ThreadingHTTPServer, RuntimeState]:
    """Create a server without starting its request loop, enabling deterministic tests."""
    state = RuntimeState(settings, run_id=run_id)
    handler = type(
        "ConfiguredAnalyticsRequestHandler",
        (AnalyticsRequestHandler,),
        {"state": state},
    )
    server = ThreadingHTTPServer((settings.host, settings.port), handler)
    server.daemon_threads = True
    return server, state


def serve_application(settings: ApplicationSettings) -> None:
    """Run the application until SIGINT/SIGTERM and close its socket cleanly."""
    with logged_operation("application_serve") as run_id:
        server, state = create_application_server(settings, run_id=run_id)

        def request_shutdown(signum: int, _frame: FrameType | None) -> None:
            LOGGER.info(
                "shutdown_requested",
                extra={
                    "run_id": state.run_id,
                    "release_id": (
                        state.artifacts.release.dataset_version if state.artifacts else None
                    ),
                    "operation": "shutdown",
                    "status": "STARTED",
                    "duration_ms": 0,
                    "error_category": None,
                },
            )
            threading.Thread(target=server.shutdown, daemon=True).start()

        previous_handlers: dict[signal.Signals, Any] = {}
        if threading.current_thread() is threading.main_thread():
            for signal_number in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signal_number] = signal.getsignal(signal_number)
                signal.signal(signal_number, request_shutdown)
        try:
            server.serve_forever(poll_interval=0.25)
        finally:
            server.server_close()
            for signal_number, previous in previous_handlers.items():
                signal.signal(signal_number, previous)
