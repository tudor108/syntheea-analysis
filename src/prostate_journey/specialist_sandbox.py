"""Parent-side controls for the no-code declarative analysis worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal


class SandboxError(RuntimeError):
    """Fail-closed sandbox execution error."""


def run_isolated_worker(
    run_directory: Path,
    payload: dict[str, Any],
    *,
    action: Literal["summarize", "network-probe", "delay"] = "summarize",
    timeout_seconds: int = 20,
    max_output_bytes: int = 1_000_000,
    memory_mb: int = 256,
    cpu_seconds: int = 15,
) -> dict[str, Any]:
    """Run a fixed declarative operation with no network or generated-code interface."""
    run_root = run_directory.resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    input_path = (run_root / "sandbox_input.json").resolve()
    if not input_path.is_relative_to(run_root):
        raise SandboxError("sandbox input escaped its run directory")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > max_output_bytes:
        raise SandboxError("sandbox input exceeds configured byte limit")
    input_path.write_text(serialized, encoding="utf-8")
    input_path.chmod(0o444)
    worker = Path(__file__).with_name("specialist_worker.py").resolve()
    environment = {
        "NO_PROXY": "*",
        "no_proxy": "*",
        "PYTHONIOENCODING": "utf-8",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
    }
    command = [
        sys.executable,
        "-I",
        str(worker),
        "--action",
        action,
        "--input",
        str(input_path),
        "--memory-mb",
        str(memory_mb),
        "--cpu-seconds",
        str(cpu_seconds),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=run_root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise SandboxError("sandbox exceeded configured duration limit") from error
    if len(completed.stdout) + len(completed.stderr) > max_output_bytes:
        raise SandboxError("sandbox output exceeded configured byte limit")
    if completed.returncode != 0:
        raise SandboxError(f"sandbox failed with governed worker status {completed.returncode}")
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SandboxError("sandbox returned an invalid bounded result") from error
    if not isinstance(result, dict):
        raise SandboxError("sandbox result must be one JSON object")
    return result
