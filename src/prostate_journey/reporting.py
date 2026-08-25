"""Cohort reports, KPI extracts and reproducibility metadata."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from . import DISCLAIMER


def kpis(journey: pd.DataFrame) -> pd.DataFrame:
    """Calculate headline counts without implying real-world estimates."""
    metrics = {
        "total_patients": len(journey),
        "prostate_cancer": len(journey),
        "markets": int(journey.market_code.nunique()),
        "mhspc": int(journey.mhspc_flag.sum()),
        "eligible": int(journey.eligibility_flag.sum()),
        "initiated": int(journey.treatment_initiated.sum()),
        "initiated_30d": int(journey.initiated_within_30d.sum()),
        "initiated_60d": int(journey.initiated_within_60d.sum()),
        "initiated_90d": int(journey.initiated_within_90d.sum()),
        "treatment_gap_90d": int(journey.eligible_not_initiated_90d.sum()),
        "persistent_3m": int(journey.persistent_3m.fillna(False).sum()),
        "persistent_6m": int(journey.persistent_6m.fillna(False).sum()),
        "persistent_12m": int(journey.persistent_12m.fillna(False).sum()),
        "persistence_12m_censored": int(
            journey.persistence_12m_status.eq("CENSORED_NOT_EVALUABLE").sum()
        ),
        "active_surveillance_started": int(journey.active_surveillance_start_date.notna().sum()),
        "intensified": int(journey.intensification_flag.sum()),
        "discontinuations": int(journey.discontinuation_flag.fillna(False).sum()),
        "switches": int(journey.switch_flag.fillna(False).sum()),
        "restarts": int(journey.restart_flag.fillna(False).sum()),
        "progressions": int(journey.progression_event.sum()),
        "deaths": int(journey.death_flag.sum()),
        "lost_to_follow_up": int(journey.lost_to_follow_up_flag.sum()),
    }
    return pd.DataFrame(
        {"kpi": metrics.keys(), "value": metrics.values(), "data_label": DISCLAIMER}
    )


def write_cohort_report(tables: dict[str, pd.DataFrame], report_dir: str | Path) -> pd.DataFrame:
    """Write the markdown cohort summary and machine-readable KPI file."""
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    journey = tables["patient_journey"]
    metric_frame = kpis(journey)
    metric_frame.to_csv(root / "cohort_kpis.csv", index=False)
    lines = [
        f"# Cohort Summary\n\n> # {DISCLAIMER}\n"
        "> Configured distributions are demo assumptions, "
        "not clinical or commercial evidence.\n",
        "## Headline KPIs\n",
        "| KPI | Synthetic count |",
        "|---|---:|",
    ]
    lines.extend(f"| {row.kpi} | {row.value} |" for row in metric_frame.itertuples())
    for title, col in (
        ("Market", "market_code"),
        ("Care setting", "initial_care_setting"),
        ("Provider specialty", "initial_provider_specialty"),
        ("Initial regimen", "initial_regimen"),
        ("12-month persistence status", "persistence_12m_status"),
    ):
        lines += [f"\n## {title}\n", "| Value | Count |", "|---|---:|"]
        lines.extend(
            f"| {key} | {value} |"
            for key, value in journey[col].fillna("not_initiated").value_counts().items()
        )
    lines += ["\n## Missingness per patient-journey column\n", "| Column | Missing |", "|---|---:|"]
    lines.extend(f"| {col} | {int(value)} |" for col, value in journey.isna().sum().items())
    (root / "cohort_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return metric_frame


def sha256(path: Path) -> str:
    """Calculate a streaming SHA-256 checksum."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_run_metadata(
    project_root: Path,
    config: dict,
    cohort_size: int,
    gold_dir: Path,
    report_dir: Path,
    generation_started_at: str | None = None,
) -> None:
    """Record environment, source version, scenario and gold checksums."""

    def git_value(args: list[str], cwd: Path) -> str | None:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL, timeout=5
            ).strip()
        except (subprocess.SubprocessError, OSError):
            return None

    synthea_root = project_root / "external" / "synthea"
    outputs = {
        p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)}
        for p in sorted(gold_dir.iterdir())
        if p.is_file()
    }
    dependency_names = ["pandas", "numpy", "pyarrow", "duckdb", "PyYAML", "pydantic", "typer"]
    dependencies: dict[str, str | None] = {}
    for dependency in dependency_names:
        try:
            dependencies[dependency] = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError:
            dependencies[dependency] = None
    tracked_diff = git_value(["status", "--porcelain", "--untracked-files=no"], project_root)
    config_snapshot = report_dir / "config_snapshot.yaml"
    metadata = {
        "disclaimer": DISCLAIMER,
        "generation_started_at": generation_started_at,
        "generation_completed_at": datetime.now(UTC).isoformat(),
        "git_commit": git_value(["rev-parse", "HEAD"], project_root),
        "git_branch": git_value(["branch", "--show-current"], project_root),
        "git_tracked_source_clean": tracked_diff == "",
        "generator_version": config.get("generator_version", "unknown"),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "dependencies": dependencies,
        "synthea_commit": git_value(["rev-parse", "HEAD"], synthea_root)
        if synthea_root.exists()
        else None,
        "random_seed": config["random_seed"],
        "cohort_size": cohort_size,
        "scenario_version": config["scenario_version"],
        "market_configuration_version": config["market_configuration"]["version"],
        "clinical_rules_version": config["clinical_rule_configuration"]["version"],
        "config_snapshot_sha256": sha256(config_snapshot) if config_snapshot.exists() else None,
        "output_file_hashes": outputs,
    }
    (report_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
