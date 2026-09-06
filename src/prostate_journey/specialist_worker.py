"""Standalone declarative worker. It accepts no source code, SQL, or arbitrary operation."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any


def _deny_network() -> None:
    class DeniedSocket(socket.socket):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise PermissionError("network access is disabled in the analysis sandbox")

    socket.socket = DeniedSocket  # type: ignore[misc]
    socket.create_connection = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        PermissionError("network access is disabled in the analysis sandbox")
    )


def _apply_posix_limits(memory_mb: int, cpu_seconds: int) -> None:
    try:
        resource: Any = importlib.import_module("resource")
    except ImportError:
        return
    memory_bytes = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))


def _summarize(payload: dict[str, Any]) -> dict[str, Any]:
    requested_markets = payload["markets"]
    segments = payload["aggregate_snapshot"]["segments"]
    rows: list[dict[str, Any]] = []
    for market in requested_markets:
        segment = segments[market]
        denominator = int(segment["eligible"])
        numerator = int(segment["initiated90"])
        rows.append(
            {
                "market": market,
                "subgroup": "ALL",
                "metric_id": "proposed_eligible_to_initiation_90d",
                "label": "Proposed descriptive 90-day initiation summary",
                "numerator": numerator,
                "denominator": denominator,
                "rate": round(numerator / denominator, 8) if denominator else None,
                "unit": "proportion",
                "population": "Eligible generated synthetic records",
                "time_window": "90 days after eligibility",
                "method": "Declarative aggregate market summary",
                "parent_release_id": payload["parent_release_id"],
            }
        )
    return {"status": "ok", "rows": rows, "network": "denied", "code_generation": False}


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--action", choices=["summarize", "network-probe", "delay"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--memory-mb", type=int, required=True)
    parser.add_argument("--cpu-seconds", type=int, required=True)
    arguments = parser.parse_args()
    _apply_posix_limits(arguments.memory_mb, arguments.cpu_seconds)
    _deny_network()
    payload = json.loads(arguments.input.read_text(encoding="utf-8"))
    if arguments.action == "network-probe":
        try:
            socket.create_connection(("example.com", 443), timeout=0.1)
        except PermissionError:
            print(json.dumps({"status": "blocked", "network": "denied"}))
            return 0
        print(json.dumps({"status": "failed", "network": "available"}))
        return 3
    if arguments.action == "delay":
        time.sleep(float(payload.get("delay_seconds", 5)))
        print(json.dumps({"status": "unexpected_completion"}))
        return 0
    print(json.dumps(_summarize(payload), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    sys.exit(main())
