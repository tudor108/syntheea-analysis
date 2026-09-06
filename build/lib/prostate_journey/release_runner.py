"""Fresh-run orchestration for the strict final release gate."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .pipeline import run_all
from .release_packager import (
    ReleasePackagingError,
    assert_clean_source,
    assert_new_empty_release_dir,
    package_certified_release,
)


def create_fresh_certified_release(
    *,
    project_root: str | Path,
    config: Mapping[str, Any],
    input_dir: str | Path,
    release_dir: str | Path,
    dataset_version: str,
    git_executable: str | Path = "git",
    python_executable: str | Path | None = None,
) -> dict[str, Any]:
    """Generate into a never-used stage, reload, certify, and package the exact run."""
    project = Path(project_root).resolve()
    release = Path(release_dir).resolve()
    source = assert_clean_source(project, git_executable=git_executable)
    if release.exists():
        raise ReleasePackagingError(f"Release path already exists and cannot be reused: {release}")

    staging = project / ".test-work" / "release-staging" / release.name
    assert_new_empty_release_dir(staging)
    gold = staging / "gold"
    reports = staging / "reports"
    run_all(project, dict(config), Path(input_dir), gold, reports)

    manifest = package_certified_release(
        project_root=project,
        staging_gold_dir=gold,
        staging_report_dir=reports,
        input_dir=input_dir,
        release_dir=release,
        dataset_version=dataset_version,
        config=config,
        expected_git_commit=source["git_commit"],
        git_executable=git_executable,
        python_executable=python_executable or sys.executable,
    )
    return {
        **manifest,
        "release_directory": str(release),
        "fresh_staging_directory": str(staging),
    }
