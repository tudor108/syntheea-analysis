"""Strict, fail-closed packaging for an immutable diagnostic release.

The generation pipeline deliberately remains separate from this module.  A release
is packaged only from a fresh staging run after its exported files have been
reloaded, reconciled, tested, hashed, and approved by every release gate.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import duckdb
import pandas as pd
from pandas.api import types as ptypes


class ReleasePackagingError(RuntimeError):
    """Raised whenever an immutable release cannot be certified safely."""


SOURCE_MEMBERS = (
    "src",
    "tests",
    "scripts",
    "pyproject.toml",
    "requirements.txt",
    "README.md",
    "Makefile",
)
SOURCE_CLEAN_PATHS = (*SOURCE_MEMBERS, "configs", "docs")
CONTEXT_FILES = ("pyproject.toml", "requirements.txt", "README.md", "Makefile")
IGNORED_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: str | Path) -> str:
    """Return the streaming SHA-256 digest of one file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ensure_unused_path(path: Path) -> None:
    if path.exists():
        raise ReleasePackagingError(
            f"Release directory already exists and cannot be reused: {path}"
        )


def assert_new_empty_release_dir(path: str | Path) -> Path:
    """Create a never-before-used release directory and an in-progress marker.

    Existing paths are rejected even when empty.  This prevents an old release from
    silently contributing stale files to a new baseline.
    """
    release_root = Path(path).resolve()
    _ensure_unused_path(release_root)
    release_root.parent.mkdir(parents=True, exist_ok=True)
    release_root.mkdir()
    if any(release_root.iterdir()):  # defensive against unusual concurrent creation
        raise ReleasePackagingError(
            f"New release directory is unexpectedly non-empty: {release_root}"
        )
    (release_root / ".release-in-progress").write_text(
        f"created_at={_utc_now()}\n", encoding="utf-8"
    )
    return release_root


def _iter_files(members: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for member in members:
        if not member.exists():
            continue
        if member.is_file():
            files.append(member)
            continue
        for candidate in member.rglob("*"):
            if any(part in IGNORED_DIRECTORY_NAMES for part in candidate.parts):
                continue
            if candidate.is_file() and candidate.suffix not in {".pyc", ".pyo"}:
                files.append(candidate)
    return sorted(set(files), key=lambda value: value.as_posix())


def file_inventory(
    base_dir: str | Path,
    members: Iterable[str | Path] | None = None,
    *,
    exclude: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Hash a deterministic set of files relative to ``base_dir``."""
    base = Path(base_dir).resolve()
    selected = [base] if members is None else [base / Path(member) for member in members]
    excluded = {Path(value).as_posix() for value in exclude}
    inventory: list[dict[str, Any]] = []
    for path in _iter_files(selected):
        try:
            relative = path.resolve().relative_to(base).as_posix()
        except ValueError as error:
            raise ReleasePackagingError(
                f"Manifest member escapes base directory: {path}"
            ) from error
        if relative in excluded:
            continue
        inventory.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return inventory


def write_hash_manifest(
    output_path: str | Path,
    *,
    component: str,
    base_dir: str | Path,
    members: Iterable[str | Path] | None = None,
    exclude: Iterable[str] = (),
) -> dict[str, Any]:
    """Write one component SHA-256 manifest and return its payload."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    inventory = file_inventory(base_dir, members, exclude=exclude)
    payload = {
        "component": component,
        "generated_at": _utc_now(),
        "base_directory": str(Path(base_dir).resolve()),
        "file_count": len(inventory),
        "total_bytes": sum(item["bytes"] for item in inventory),
        "files": inventory,
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _coerce_csv_column(values: pd.Series, reference: pd.Series, table: str) -> pd.Series:
    dtype = reference.dtype
    try:
        if ptypes.is_datetime64_any_dtype(dtype):
            return pd.to_datetime(values, errors="raise")
        if ptypes.is_bool_dtype(dtype):
            normalized = values.astype("string").str.lower()
            invalid = normalized.dropna()[~normalized.dropna().isin(["true", "false", "1", "0"])]
            if not invalid.empty:
                raise ValueError(f"invalid boolean values {sorted(invalid.unique())}")
            mapped = normalized.map({"true": True, "false": False, "1": True, "0": False})
            return pd.Series(pd.array(mapped, dtype="boolean"), index=values.index)
        if ptypes.is_integer_dtype(dtype):
            return pd.to_numeric(values, errors="raise").astype(dtype)
        if ptypes.is_float_dtype(dtype):
            return pd.to_numeric(values, errors="raise").astype(dtype)
        return values.astype("string")
    except (TypeError, ValueError) as error:
        raise ReleasePackagingError(
            f"CSV value cannot be coerced to the Parquet contract: {table}.{reference.name}"
        ) from error


def _assert_csv_parquet_equal(table: str, csv_path: Path, parquet_path: Path) -> pd.DataFrame:
    parquet = pd.read_parquet(parquet_path)
    csv = pd.read_csv(csv_path, dtype="string", keep_default_na=True)
    if list(csv.columns) != list(parquet.columns):
        raise ReleasePackagingError(
            f"CSV/Parquet column mismatch for {table}: "
            f"csv={list(csv.columns)}, parquet={list(parquet.columns)}"
        )
    normalized_csv = pd.DataFrame(index=csv.index)
    normalized_parquet = pd.DataFrame(index=parquet.index)
    for column in parquet.columns:
        normalized_csv[column] = _coerce_csv_column(csv[column], parquet[column], table)
        if ptypes.is_bool_dtype(parquet[column].dtype):
            normalized_parquet[column] = pd.array(parquet[column], dtype="boolean")
        elif not (
            ptypes.is_datetime64_any_dtype(parquet[column].dtype)
            or ptypes.is_numeric_dtype(parquet[column].dtype)
        ):
            normalized_parquet[column] = parquet[column].astype("string")
        else:
            normalized_parquet[column] = parquet[column]
    try:
        pd.testing.assert_frame_equal(
            normalized_csv,
            normalized_parquet,
            check_dtype=False,
            check_exact=True,
            check_like=False,
        )
    except AssertionError as error:
        raise ReleasePackagingError(f"CSV/Parquet content mismatch for table {table}") from error
    return parquet


def reload_and_verify_exported_artifacts(
    gold_dir: str | Path,
    table_names: Sequence[str] | None = None,
    *,
    duckdb_path: str | Path | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Reload all exports and require exact CSV/Parquet and DuckDB row-count parity."""
    root = Path(gold_dir).resolve()
    if table_names is None:
        from .pipeline import TABLES  # lazy import keeps the packager independently usable

        table_names = TABLES
    if not table_names:
        raise ReleasePackagingError("No exported tables were supplied for release verification")

    frames: dict[str, pd.DataFrame] = {}
    evidence: dict[str, Any] = {"tables": {}, "verified_at": _utc_now()}
    for table in table_names:
        csv_path = root / f"{table}.csv"
        parquet_path = root / f"{table}.parquet"
        if not csv_path.is_file() or not parquet_path.is_file():
            raise ReleasePackagingError(f"Missing CSV or Parquet export for table {table}")
        frame = _assert_csv_parquet_equal(table, csv_path, parquet_path)
        frames[table] = frame
        evidence["tables"][table] = {
            "rows": len(frame),
            "columns": len(frame.columns),
            "csv_sha256": sha256_file(csv_path),
            "parquet_sha256": sha256_file(parquet_path),
        }

    database = Path(duckdb_path) if duckdb_path is not None else root / "prostate_journey.duckdb"
    if not database.is_file():
        raise ReleasePackagingError(f"DuckDB artifact is missing: {database}")
    connection = duckdb.connect(str(database), read_only=True)
    try:
        available = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            ).fetchall()
        }
        for table, frame in frames.items():
            if table not in available:
                raise ReleasePackagingError(f"DuckDB table is missing: {table}")
            quoted = table.replace('"', '""')
            row_count = int(connection.execute(f'SELECT count(*) FROM "{quoted}"').fetchone()[0])
            if row_count != len(frame):
                raise ReleasePackagingError(
                    f"DuckDB row-count mismatch for {table}: {row_count} != {len(frame)}"
                )
            evidence["tables"][table]["duckdb_rows"] = row_count
    finally:
        connection.close()
    evidence["duckdb_sha256"] = sha256_file(database)
    evidence["verified_table_count"] = len(frames)
    return frames, evidence


def _run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    started = _utc_now()
    start_clock = time.perf_counter()
    try:
        completed = runner(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        exit_code = int(completed.returncode)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except (OSError, subprocess.SubprocessError) as error:
        exit_code = 127
        stdout = ""
        stderr = f"{type(error).__name__}: {error}"
    return {
        "command": list(command),
        "command_display": subprocess.list2cmdline(list(command)),
        "started_at": started,
        "completed_at": _utc_now(),
        "duration_seconds": round(time.perf_counter() - start_clock, 6),
        "exit_code": exit_code,
        "passed": exit_code == 0,
        "stdout": stdout,
        "stderr": stderr,
    }


def _write_fallback_junit(path: Path, message: str) -> None:
    suite = ElementTree.Element(
        "testsuite",
        {"name": "release-test-execution", "tests": "1", "failures": "0", "errors": "1"},
    )
    case = ElementTree.SubElement(suite, "testcase", {"name": "pytest_execution"})
    error = ElementTree.SubElement(case, "error", {"message": message})
    error.text = message
    ElementTree.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _junit_summary(path: Path) -> dict[str, int | float]:
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall(".//testsuite"))
    return {
        "tests": sum(int(suite.attrib.get("tests", 0)) for suite in suites),
        "failures": sum(int(suite.attrib.get("failures", 0)) for suite in suites),
        "errors": sum(int(suite.attrib.get("errors", 0)) for suite in suites),
        "skipped": sum(int(suite.attrib.get("skipped", 0)) for suite in suites),
        "time_seconds": round(sum(float(suite.attrib.get("time", 0)) for suite in suites), 6),
    }


def run_release_tests(
    project_root: str | Path,
    qa_evidence_dir: str | Path,
    *,
    python_executable: str | Path | None = None,
    timeout: int = 3600,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Run Ruff and pytest, persist complete evidence, and fail on either error."""
    project = Path(project_root).resolve()
    qa = Path(qa_evidence_dir).resolve()
    qa.mkdir(parents=True, exist_ok=True)
    python = str(python_executable or sys.executable)
    junit_path = qa / "test_report.xml"
    commands = [
        ("ruff", [python, "-m", "ruff", "check", "src", "tests"]),
        ("pytest", [python, "-m", "pytest", "-q", f"--junitxml={junit_path}"]),
    ]
    results = {
        name: _run_process(command, cwd=project, timeout=timeout, runner=runner)
        for name, command in commands
    }
    if not junit_path.exists():
        _write_fallback_junit(junit_path, results["pytest"]["stderr"] or "pytest produced no JUnit")
    try:
        junit = _junit_summary(junit_path)
    except (ElementTree.ParseError, OSError, ValueError) as error:
        _write_fallback_junit(junit_path, f"invalid pytest JUnit: {error}")
        junit = _junit_summary(junit_path)

    passed = bool(
        all(result["passed"] for result in results.values())
        and junit["failures"] == 0
        and junit["errors"] == 0
    )
    payload = {
        "generated_at": _utc_now(),
        "project_root": str(project),
        "python_executable": python,
        "passed": passed,
        "commands": results,
        "junit": junit,
        "junit_sha256": sha256_file(junit_path),
    }
    (qa / "test_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown = [
        "# Release Test Report",
        "",
        f"Overall status: **{'PASS' if passed else 'FAIL'}**",
        "",
        f"Tests: {junit['tests']}; failures: {junit['failures']}; "
        f"errors: {junit['errors']}; skipped: {junit['skipped']}",
        "",
        "| Check | Exit | Duration (s) | Command |",
        "|---|---:|---:|---|",
    ]
    for name, result in results.items():
        markdown.append(
            f"| {name} | {result['exit_code']} | {result['duration_seconds']} | "
            f"`{result['command_display']}` |"
        )
        markdown.extend(
            [
                "",
                f"## {name} stdout",
                "",
                "```text",
                str(result["stdout"]),
                "```",
                "",
                f"## {name} stderr",
                "",
                "```text",
                str(result["stderr"]),
                "```",
            ]
        )
    (qa / "test_report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    if not passed:
        raise ReleasePackagingError("Ruff or pytest failed; release packaging is blocked")
    return payload


def _git_command(
    project_root: Path,
    git_executable: str | Path,
    arguments: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    try:
        completed = runner(
            [str(git_executable), *arguments],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ReleasePackagingError(f"Unable to execute Git: {error}") from error
    if completed.returncode != 0:
        raise ReleasePackagingError(
            f"Git command failed ({subprocess.list2cmdline([str(git_executable), *arguments])}): "
            f"{completed.stderr.strip()}"
        )
    return (completed.stdout or "").strip()


def assert_clean_source(
    project_root: str | Path,
    *,
    expected_commit: str | None = None,
    git_executable: str | Path = "git",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Require committed, non-stale source/config/test/documentation inputs."""
    project = Path(project_root).resolve()
    commit = _git_command(project, git_executable, ["rev-parse", "HEAD"], runner)
    branch = _git_command(project, git_executable, ["branch", "--show-current"], runner)
    status = _git_command(
        project,
        git_executable,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", *SOURCE_CLEAN_PATHS],
        runner,
    )
    if status:
        raise ReleasePackagingError(f"Tracked release source is dirty or untracked:\n{status}")
    if expected_commit is not None and commit != expected_commit:
        raise ReleasePackagingError(
            f"Stale source commit: current {commit}, expected generation commit {expected_commit}"
        )
    return {"git_commit": commit, "git_branch": branch, "source_clean": True}


def verify_run_provenance(
    report_dir: str | Path,
    gold_dir: str | Path,
    git_info: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Require run metadata to describe the exact current source and artifacts."""
    metadata_path = Path(report_dir) / "run_metadata.json"
    if not metadata_path.is_file():
        raise ReleasePackagingError(f"Run metadata is missing: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {
        "git_commit": git_info["git_commit"],
        "git_branch": git_info.get("git_branch"),
        "generator_version": config.get("generator_version"),
        "scenario_version": config.get("scenario_version"),
        "market_configuration_version": config.get("market_configuration", {}).get("version"),
        "clinical_rules_version": config.get("clinical_rule_configuration", {}).get("version"),
        "random_seed": config.get("random_seed"),
    }
    mismatches = {
        key: {"expected": value, "observed": metadata.get(key)}
        for key, value in expected.items()
        if value is not None and metadata.get(key) != value
    }
    if mismatches:
        raise ReleasePackagingError(f"Stale or inconsistent run provenance: {mismatches}")
    if metadata.get("git_tracked_source_clean") is not True:
        raise ReleasePackagingError("Run metadata does not attest a clean tracked source")
    if not metadata.get("generation_started_at") or not metadata.get("generation_completed_at"):
        raise ReleasePackagingError("Run metadata lacks execution start/completion timestamps")

    recorded = metadata.get("output_file_hashes", {})
    actual_files = sorted(path for path in Path(gold_dir).iterdir() if path.is_file())
    if set(recorded) != {path.name for path in actual_files}:
        raise ReleasePackagingError("Run metadata file inventory does not match the gold directory")
    for path in actual_files:
        entry = recorded[path.name]
        recorded_hash = entry.get("sha256") if isinstance(entry, Mapping) else entry
        recorded_bytes = entry.get("bytes") if isinstance(entry, Mapping) else None
        if recorded_hash != sha256_file(path) or (
            recorded_bytes is not None and int(recorded_bytes) != path.stat().st_size
        ):
            raise ReleasePackagingError(f"Run metadata hash/size mismatch: {path.name}")
    return metadata


def _assert_gate_mapping(payload: Mapping[str, Any], label: str) -> None:
    for key in (
        "overall_readiness_score",
        "independent_audit_score",
        "overall_score",
        "overall_readiness",
    ):
        if key in payload and float(payload[key]) != 100.0:
            raise ReleasePackagingError(f"{label} is below 100: {key}={payload[key]}")
    for key in (
        "critical_failures",
        "p0_blockers_remaining",
        "p1_issues_remaining",
        "p0_blockers",
        "p1_issues",
        "hard_failures",
        "hard_failure_count",
        "unresolved_hard_failures",
        "external_definition_blockers",
        "data_engineering_blockers",
        "reconciliation_mismatches",
        "total_mismatches",
        "mismatch_count",
    ):
        if key not in payload:
            continue
        value = payload[key]
        retains_blocker = (
            bool(value) if isinstance(value, (list, tuple, set, dict)) else int(value) != 0
        )
        if retains_blocker:
            raise ReleasePackagingError(f"{label} retains blockers: {key}={value}")
    for key in ("failed_requirements", "partial_requirements", "p0_p1_failures"):
        if payload.get(key):
            raise ReleasePackagingError(f"{label} retains non-passing requirements: {key}")
    for key in ("ready_for_bayer_diagnostic", "certified", "passed"):
        if key in payload and payload[key] is not True:
            raise ReleasePackagingError(f"{label} is not certified: {key}={payload[key]}")
    if "status" in payload and str(payload["status"]).strip().upper() != "PASS":
        raise ReleasePackagingError(f"{label} status is not PASS: {payload['status']}")


def assert_release_scores(
    report_dir: str | Path,
    *,
    additional_payloads: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Require 100/100 readiness, no hard fails, and no partial requirements."""
    root = Path(report_dir)
    report_files = {
        "data_quality": "data_quality_summary.json",
        "readiness": "readiness_audit.json",
        "adversarial": "adversarial_audit.json",
    }
    required_keys = {
        "data_quality": {"critical_failures", "rules"},
        "readiness": {
            "overall_readiness_score",
            "maximum_score",
            "failed_requirements",
            "partial_requirements",
            "p0_p1_failures",
        },
        "adversarial": {
            "independent_audit_score",
            "maximum_score",
            "p0_blockers_remaining",
            "p1_issues_remaining",
            "ready_for_bayer_diagnostic",
        },
    }
    payloads: dict[str, Any] = {}
    for label, filename in report_files.items():
        path = root / filename
        if not path.is_file():
            raise ReleasePackagingError(f"Required release-gate report is missing: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ReleasePackagingError(f"{label} release-gate report is not a JSON object")
        missing = sorted(required_keys[label] - payload.keys())
        if missing:
            raise ReleasePackagingError(
                f"{label} release-gate report lacks required fields: {missing}"
            )
        if "maximum_score" in payload and float(payload["maximum_score"]) != 100.0:
            raise ReleasePackagingError(
                f"{label} maximum score is not 100: {payload['maximum_score']}"
            )
        if label == "data_quality" and not isinstance(payload["rules"], list):
            raise ReleasePackagingError("data_quality rules must be a JSON list")
        _assert_gate_mapping(payload, label)
        payloads[label] = payload
    for index, payload in enumerate(additional_payloads, start=1):
        _assert_gate_mapping(payload, f"additional gate {index}")
    return {
        "overall_readiness_score": 100,
        "independent_audit_score": 100,
        "p0_blockers": 0,
        "p1_issues": 0,
        "hard_failures": 0,
        "reports": {label: filename for label, filename in report_files.items()},
    }


def assert_final_scorecard(
    scorecard_path: str | Path, *, expected_dimensions: int = 11
) -> dict[str, Any]:
    """Require the Prompt-3 final scorecard to be complete and uniformly perfect."""
    path = Path(scorecard_path).resolve()
    if not path.is_file():
        raise ReleasePackagingError(f"Final scorecard is missing: {path}")
    try:
        scorecard = pd.read_csv(path, dtype="string", keep_default_na=False)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        raise ReleasePackagingError(f"Final scorecard cannot be parsed: {path}") from error
    required_columns = {"dimension", "score_0_100", "status", "remaining_deficiency"}
    missing_columns = sorted(required_columns - set(scorecard.columns))
    if missing_columns:
        raise ReleasePackagingError(f"Final scorecard lacks required columns: {missing_columns}")
    if len(scorecard) != expected_dimensions:
        raise ReleasePackagingError(
            f"Final scorecard must contain exactly {expected_dimensions} dimensions, "
            f"found {len(scorecard)}"
        )
    if scorecard["dimension"].str.strip().eq("").any() or scorecard["dimension"].duplicated().any():
        raise ReleasePackagingError("Final scorecard dimensions must be populated and unique")
    scores = pd.to_numeric(scorecard["score_0_100"], errors="coerce")
    failing = scorecard.loc[
        scores.ne(100)
        | scorecard["status"].str.strip().str.upper().ne("PASS")
        | scorecard["remaining_deficiency"].str.strip().str.upper().ne("NONE"),
        ["dimension", "score_0_100", "status", "remaining_deficiency"],
    ]
    if scores.isna().any() or not failing.empty:
        raise ReleasePackagingError(
            f"Final scorecard is not uniformly 100/PASS/NONE: {failing.to_dict(orient='records')}"
        )
    return {
        "overall_score": 100,
        "passed": True,
        "dimensions": expected_dimensions,
        "scorecard_path": str(path),
        "scorecard_sha256": sha256_file(path),
    }


def _assert_callback_success(result: Any, label: str) -> None:
    if result is None:
        return
    if isinstance(result, bool):
        if not result:
            raise ReleasePackagingError(f"{label} returned failure")
        return
    if isinstance(result, pd.DataFrame):
        if "status" in result and not result.status.astype("string").str.upper().eq("PASS").all():
            raise ReleasePackagingError(f"{label} contains non-PASS rows")
        for column in ("mismatch_count", "failure_count", "hard_failures"):
            if column in result and pd.to_numeric(result[column]).fillna(0).sum() != 0:
                raise ReleasePackagingError(f"{label} contains {column} failures")
        return
    if isinstance(result, Mapping):
        _assert_gate_mapping(result, label)
        return
    if isinstance(result, (tuple, list)):
        for index, value in enumerate(result):
            _assert_callback_success(value, f"{label}[{index}]")


def _invoke_callback(callback: Callable[..., Any], **available: Any) -> Any:
    signature = inspect.signature(callback)
    if any(parameter.kind == parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return callback(**available)
    accepted = {name: value for name, value in available.items() if name in signature.parameters}
    return callback(**accepted)


def _lazy_release_callbacks() -> tuple[Callable[..., Any], Callable[..., Any]]:
    try:
        from .release_evidence import write_release_evidence
        from .release_reconciliation import write_release_reconciliation
    except ImportError as error:
        raise ReleasePackagingError(
            "Release reconciliation/evidence modules are required but unavailable"
        ) from error
    return write_release_reconciliation, write_release_evidence


def copy_versioned_context(
    project_root: str | Path,
    qa_evidence_dir: str | Path,
    *,
    analytical_dir: str | Path | None = None,
) -> dict[str, str]:
    """Copy versioned context into QA and a self-describing analytical package."""
    project = Path(project_root).resolve()
    qa = Path(qa_evidence_dir).resolve()
    copied: dict[str, str] = {}
    for directory in ("configs", "docs"):
        source = project / directory
        destination = qa / directory
        if not source.is_dir():
            raise ReleasePackagingError(f"Required release context directory is missing: {source}")
        if destination.exists():
            raise ReleasePackagingError(
                f"Release context destination already exists: {destination}"
            )
        shutil.copytree(source, destination, copy_function=shutil.copy2)
        copied[directory] = str(destination)
    contract = qa / "project_contract"
    contract.mkdir()
    for filename in CONTEXT_FILES:
        source = project / filename
        if source.is_file():
            shutil.copy2(source, contract / filename)
    copied["project_contract"] = str(contract)
    if analytical_dir is not None:
        analytical = Path(analytical_dir).resolve()
        analytical_docs = analytical / "docs"
        analytical_docs.mkdir()
        analytical_context = {
            analytical / "README.md": project / "README.md",
            analytical_docs / "ER_SCHEMA.md": project / "docs" / "ER_SCHEMA.md",
            analytical_docs / "DATA_DICTIONARY.md": project / "docs" / "DATA_DICTIONARY.md",
            analytical_docs / "COHORT_ANALYSIS.md": project / "docs" / "COHORT_ANALYSIS.md",
            analytical_docs / "SYNTHETIC_ASSUMPTIONS.md": (
                project / "docs" / "SYNTHETIC_ASSUMPTIONS.md"
            ),
        }
        for destination, source in analytical_context.items():
            if not source.is_file():
                raise ReleasePackagingError(
                    f"Required analytical context document is missing: {source}"
                )
            if destination.exists():
                raise ReleasePackagingError(
                    f"Analytical context destination already exists: {destination}"
                )
            shutil.copy2(source, destination)
        copied["analytical_context"] = str(analytical_docs)
    return copied


def write_component_hash_manifests(
    project_root: str | Path,
    input_dir: str | Path,
    release_root: str | Path,
    qa_evidence_dir: str | Path,
) -> dict[str, dict[str, Any]]:
    """Write source, configuration, documentation, input, and artifact inventories."""
    project = Path(project_root).resolve()
    inputs = Path(input_dir).resolve()
    release = Path(release_root).resolve()
    qa = Path(qa_evidence_dir).resolve()
    if not inputs.is_dir():
        raise ReleasePackagingError(f"Required input directory is missing: {inputs}")
    manifests = qa / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    payloads = {
        "source": write_hash_manifest(
            manifests / "source_manifest.json",
            component="source",
            base_dir=project,
            members=SOURCE_MEMBERS,
        ),
        "configs": write_hash_manifest(
            manifests / "config_manifest.json",
            component="configs",
            base_dir=project,
            members=("configs",),
        ),
        "docs": write_hash_manifest(
            manifests / "docs_manifest.json",
            component="docs",
            base_dir=project,
            members=("docs",),
        ),
        "input": write_hash_manifest(
            manifests / "input_manifest.json",
            component="input",
            base_dir=inputs,
        ),
    }
    artifact_relative = (manifests / "artifact_manifest.json").relative_to(release).as_posix()
    payloads["artifacts"] = write_hash_manifest(
        manifests / "artifact_manifest.json",
        component="release-artifacts-before-archives",
        base_dir=release,
        members=("analytical_dataset", "qa_evidence"),
        exclude=(artifact_relative,),
    )
    empty_components = [name for name, payload in payloads.items() if payload["file_count"] == 0]
    if empty_components:
        raise ReleasePackagingError(f"Empty SHA-256 component manifests: {empty_components}")
    return payloads


def _zip_directory(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(
        temporary, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True
    ) as archive:
        for path in _iter_files([source]):
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(f"{source.name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            with path.open("rb") as source_handle, archive.open(info, "w") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
    temporary.replace(destination)


def create_separate_release_archives(
    release_root: str | Path, dataset_version: str
) -> dict[str, dict[str, Any]]:
    """Create deterministic analytical-data and QA-evidence ZIP archives."""
    release = Path(release_root).resolve()
    analytical = release / "analytical_dataset"
    qa = release / "qa_evidence"
    if not analytical.is_dir() or not qa.is_dir():
        raise ReleasePackagingError("Both analytical_dataset and qa_evidence must exist")
    archives_dir = release / "archives"
    archives_dir.mkdir()
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "-", dataset_version).strip("-")
    if not safe_version:
        raise ReleasePackagingError("Dataset version cannot produce an archive name")
    archive_paths = {
        "analytical": archives_dir / f"{safe_version}-analytical.zip",
        "qa_evidence": archives_dir / f"{safe_version}-qa-evidence.zip",
    }
    _zip_directory(analytical, archive_paths["analytical"])
    _zip_directory(qa, archive_paths["qa_evidence"])
    return {
        name: {
            "path": path.relative_to(release).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for name, path in archive_paths.items()
    }


def _write_checksums(release: Path, output: Path) -> int:
    lines = []
    for item in file_inventory(release, exclude=(output.relative_to(release).as_posix(),)):
        lines.append(f"{item['sha256']}  {item['path']}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def write_final_release_files(
    release_root: str | Path,
    *,
    dataset_version: str,
    git_info: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    gate_summary: Mapping[str, Any],
    parity_evidence: Mapping[str, Any],
    test_report: Mapping[str, Any],
    archive_hashes: Mapping[str, Any],
    external_definition_blockers: int = 0,
    apply_filesystem_readonly: bool = False,
) -> dict[str, Any]:
    """Write the certified decision, final manifest, checksums, and immutable marker."""
    _assert_gate_mapping(gate_summary, "final gate")
    if external_definition_blockers:
        raise ReleasePackagingError(
            f"External definition blockers remain: {external_definition_blockers}"
        )
    if test_report.get("passed") is not True:
        raise ReleasePackagingError("Test report is not passing")

    release = Path(release_root).resolve()
    required_archives = {"analytical", "qa_evidence"}
    missing_archives = sorted(required_archives - archive_hashes.keys())
    if missing_archives:
        raise ReleasePackagingError(f"Required release archives are missing: {missing_archives}")
    resolved_archives: set[Path] = set()
    for label in sorted(required_archives):
        archive_entry = archive_hashes[label]
        if not isinstance(archive_entry, Mapping):
            raise ReleasePackagingError(f"Invalid {label} archive manifest entry")
        archive_path = (release / str(archive_entry.get("path", ""))).resolve()
        try:
            archive_path.relative_to(release)
        except ValueError as error:
            raise ReleasePackagingError(f"{label} archive escapes the release directory") from error
        if archive_path in resolved_archives:
            raise ReleasePackagingError(
                "Analytical and QA evidence archives must be separate files"
            )
        resolved_archives.add(archive_path)
        if not archive_path.is_file():
            raise ReleasePackagingError(f"{label} archive is missing: {archive_path}")
        if archive_entry.get("sha256") != sha256_file(archive_path):
            raise ReleasePackagingError(f"{label} archive SHA-256 mismatch")
        if int(archive_entry.get("bytes", -1)) != archive_path.stat().st_size:
            raise ReleasePackagingError(f"{label} archive size mismatch")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                corrupt_member = archive.testzip()
        except (OSError, zipfile.BadZipFile) as error:
            raise ReleasePackagingError(f"{label} archive is not a valid ZIP") from error
        if corrupt_member is not None:
            raise ReleasePackagingError(
                f"{label} archive contains a corrupt member: {corrupt_member}"
            )
    decision_path = release / "RELEASE_DECISION.md"
    analytical_archive = archive_hashes["analytical"]["path"]
    decision_path.write_text(
        "\n".join(
            [
                "# Final Release Decision",
                "",
                f"Dataset version: {dataset_version}",
                "",
                "Overall readiness: 100/100",
                "",
                "P0 blockers: 0",
                "",
                "P1 issues: 0",
                "",
                "External definition blockers: 0",
                "",
                "CERTIFIED — READY FOR BAYER ANALYSIS",
                "",
                "Senior Data Scientist accountability answer: **YES**.",
                "",
                "The full artifact reconciliation, release gates, Ruff, pytest, provenance, "
                "and checksums pass. Preserve the complete release directory and the "
                f"immutable analytical baseline archive `{analytical_archive}`.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "dataset_version": dataset_version,
        "created_at": _utc_now(),
        "decision": "CERTIFIED — READY FOR BAYER ANALYSIS",
        "overall_readiness": 100,
        "p0_blockers": 0,
        "p1_issues": 0,
        "external_definition_blockers": 0,
        "git": dict(git_info),
        "run_metadata": dict(run_metadata),
        "gate_summary": dict(gate_summary),
        "artifact_parity": dict(parity_evidence),
        "test_summary": {
            "passed": test_report["passed"],
            "junit": test_report.get("junit", {}),
            "commands": {
                name: {
                    "exit_code": result["exit_code"],
                    "duration_seconds": result["duration_seconds"],
                }
                for name, result in test_report.get("commands", {}).items()
            },
        },
        "archives": dict(archive_hashes),
        "analytical_dataset_directory": "analytical_dataset",
        "qa_evidence_directory": "qa_evidence",
        "immutable": True,
    }
    manifest_path = release / "release_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    in_progress = release / ".release-in-progress"
    in_progress.unlink(missing_ok=True)
    immutable_marker = release / "IMMUTABLE_RELEASE"
    immutable_marker.write_text(
        f"dataset_version={dataset_version}\n"
        f"release_manifest_sha256={sha256_file(manifest_path)}\n"
        f"sealed_at={_utc_now()}\n",
        encoding="utf-8",
    )
    _write_checksums(release, release / "CHECKSUMS.sha256")

    if apply_filesystem_readonly:
        for path in reversed(sorted(release.rglob("*"), key=lambda value: len(value.parts))):
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
            elif path.is_dir():
                os.chmod(path, stat.S_IREAD | stat.S_IEXEC)
        os.chmod(release, stat.S_IREAD | stat.S_IEXEC)
    return manifest


def package_certified_release(
    *,
    project_root: str | Path,
    staging_gold_dir: str | Path,
    staging_report_dir: str | Path,
    input_dir: str | Path,
    release_dir: str | Path,
    dataset_version: str,
    config: Mapping[str, Any],
    expected_git_commit: str | None = None,
    git_executable: str | Path = "git",
    python_executable: str | Path | None = None,
    reconcile_callback: Callable[..., Any] | None = None,
    evidence_callback: Callable[..., Any] | None = None,
    test_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    git_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    apply_filesystem_readonly: bool = False,
) -> dict[str, Any]:
    """Build a strict two-archive release from a fresh, already-generated staging run."""
    release_path = Path(release_dir).resolve()
    _ensure_unused_path(release_path)
    git_info = assert_clean_source(
        project_root,
        expected_commit=expected_git_commit,
        git_executable=git_executable,
        runner=git_runner,
    )
    run_metadata = verify_run_provenance(staging_report_dir, staging_gold_dir, git_info, config)
    # Reject bad staging evidence before creating an immutable release directory.
    assert_release_scores(staging_report_dir)

    release = assert_new_empty_release_dir(release_path)
    analytical = release / "analytical_dataset"
    qa = release / "qa_evidence"
    shutil.copytree(Path(staging_gold_dir), analytical, copy_function=shutil.copy2)
    reports = qa / "reports"
    shutil.copytree(Path(staging_report_dir), reports, copy_function=shutil.copy2)
    copy_versioned_context(project_root, qa, analytical_dir=analytical)

    tables, parity = reload_and_verify_exported_artifacts(analytical)
    if reconcile_callback is None or evidence_callback is None:
        lazy_reconcile, lazy_evidence = _lazy_release_callbacks()
        reconcile_callback = reconcile_callback or lazy_reconcile
        evidence_callback = evidence_callback or lazy_evidence
    reconciliation_arguments = {
        "tables": tables,
        "config": config,
        "report_dir": reports,
        "output_dir": reports,
        "qa_evidence_dir": qa,
        "qa_dir": qa,
        "gold_dir": analytical,
        "analytical_dir": analytical,
    }
    reconciliation = _invoke_callback(reconcile_callback, **reconciliation_arguments)
    _assert_callback_success(reconciliation, "release reconciliation")
    evidence_arguments = {
        **reconciliation_arguments,
        "reconciliation_summary": reconciliation,
    }
    release_evidence = _invoke_callback(evidence_callback, **evidence_arguments)
    _assert_callback_success(release_evidence, "release evidence")
    scorecard_value = (
        release_evidence.get("final_scorecard_csv", qa / "final_scorecard.csv")
        if isinstance(release_evidence, Mapping)
        else qa / "final_scorecard.csv"
    )
    scorecard_path = Path(scorecard_value)
    if not scorecard_path.is_absolute():
        scorecard_path = qa / scorecard_path
    try:
        scorecard_path.resolve().relative_to(qa.resolve())
    except ValueError as error:
        raise ReleasePackagingError("Final scorecard must be written inside qa_evidence") from error
    scorecard_gate = assert_final_scorecard(scorecard_path)
    extra_payloads = [
        value for value in (reconciliation, scorecard_gate) if isinstance(value, Mapping)
    ]
    gates = assert_release_scores(reports, additional_payloads=extra_payloads)
    gates["final_scorecard"] = scorecard_gate
    test_report = run_release_tests(
        project_root,
        qa,
        python_executable=python_executable,
        runner=test_runner,
    )
    write_component_hash_manifests(project_root, input_dir, release, qa)
    archives = create_separate_release_archives(release, dataset_version)
    return write_final_release_files(
        release,
        dataset_version=dataset_version,
        git_info=git_info,
        run_metadata=run_metadata,
        gate_summary=gates,
        parity_evidence=parity,
        test_report=test_report,
        archive_hashes=archives,
        apply_filesystem_readonly=apply_filesystem_readonly,
    )
