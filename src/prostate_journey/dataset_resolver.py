"""Resolve complete analytical datasets with explicit release provenance."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CERTIFIED_DECISION = "CANDIDATE — INTERNAL SYNTHETIC CONTRACT PASSED"
LEGACY_CERTIFIED_DECISION = "CERTIFIED — READY FOR BAYER ANALYSIS"
DEV_DEMO_DECISION = "DEV DEMO — RELEASE TEST FAILURES ALLOWED"
ACCEPTED_RELEASE_DECISIONS = {
    CERTIFIED_DECISION,
    LEGACY_CERTIFIED_DECISION,
    DEV_DEMO_DECISION,
}


@dataclass(frozen=True)
class AnalyticalDataset:
    """A validated analytical directory and the metadata used to select it."""

    analytical_dir: Path
    dataset_version: str
    selection_method: str
    release_dir: Path | None
    release_manifest: dict[str, Any]


def _validate_complete(candidate: Path, required_tables: Iterable[str]) -> Path:
    resolved = candidate.expanduser().resolve()
    missing = [
        f"{table}.parquet"
        for table in required_tables
        if not (resolved / f"{table}.parquet").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"Incomplete analytical dataset at {resolved}. Missing: {', '.join(missing)}"
        )
    return resolved


def resolve_analytical_dataset(
    project_root: str | Path,
    required_tables: Iterable[str],
    dataset_dir: str | Path | None = None,
    *,
    allow_gold_fallback: bool = False,
    require_certified: bool = False,
    release_root: str | Path | None = None,
) -> AnalyticalDataset:
    """Resolve an explicit dataset or the newest complete certified release.

    Stakeholder workflows set ``require_certified`` so an explicit path cannot
    bypass release certification. Exploratory workflows may opt into ``data/gold``
    fallback explicitly and must label that choice downstream.
    """
    root = Path(project_root).resolve()
    required = tuple(required_tables)
    if dataset_dir is not None:
        analytical = _validate_complete(Path(dataset_dir), required)
        manifest_path = analytical.parent / "release_manifest.json"
        manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid release manifest: {manifest_path}") from error
        if require_certified:
            if not manifest:
                raise ValueError(
                    f"A certified release manifest is required for this workflow: {manifest_path}"
                )
            if manifest.get("decision") not in ACCEPTED_RELEASE_DECISIONS:
                raise ValueError(
                    f"Dataset is not a certified release: {manifest.get('decision')!r}"
                )
            declared = manifest_path.parent / str(
                manifest.get("analytical_dataset_directory", "analytical_dataset")
            )
            if declared.resolve() != analytical:
                raise ValueError(
                    "Explicit analytical directory does not match its release manifest: "
                    f"{analytical} != {declared.resolve()}"
                )
        return AnalyticalDataset(
            analytical_dir=analytical,
            dataset_version=str(manifest.get("dataset_version", analytical.name)),
            selection_method="explicit dataset directory",
            release_dir=manifest_path.parent.resolve() if manifest else None,
            release_manifest=manifest,
        )

    releases_root = (
        Path(release_root).expanduser().resolve()
        if release_root is not None
        else root / "data" / "releases"
    )
    candidates: list[tuple[str, Path, Path, dict[str, Any]]] = []
    for manifest_path in releases_root.glob("*/release_manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("decision") not in ACCEPTED_RELEASE_DECISIONS:
            continue
        analytical = manifest_path.parent / str(
            manifest.get("analytical_dataset_directory", "analytical_dataset")
        )
        try:
            complete = _validate_complete(analytical, required)
        except FileNotFoundError:
            continue
        candidates.append((str(manifest.get("created_at", "")), complete, manifest_path, manifest))

    if candidates:
        _, analytical, manifest_path, manifest = max(candidates, key=lambda item: item[0])
        return AnalyticalDataset(
            analytical_dir=analytical,
            dataset_version=str(manifest.get("dataset_version", manifest_path.parent.name)),
            selection_method="newest complete certified release",
            release_dir=manifest_path.parent.resolve(),
            release_manifest=manifest,
        )

    if allow_gold_fallback:
        analytical = _validate_complete(root / "data" / "gold", required)
        return AnalyticalDataset(
            analytical_dir=analytical,
            dataset_version="working-gold",
            selection_method="explicitly allowed data/gold fallback",
            release_dir=None,
            release_manifest={},
        )

    raise FileNotFoundError(
        f"No complete certified analytical release found under {releases_root}. "
        "Create a certified release or pass an explicit dataset directory."
    )
