"""Batched multi-seed synthetic simulation with separated uncertainty outputs."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import yaml

from . import DISCLAIMER, __version__
from .config import load_config
from .pipeline import generate_tables

METRIC_DEFINITIONS: dict[str, dict[str, Any]] = {
    "eligibility_rate": {
        "numerator": "eligibility_flag = true",
        "denominator": "all generated patient records",
        "population_definition": "all generated prostate-cancer archetypes",
        "time_zero": "index_date",
        "horizon_days": 0,
    },
    "initiation_90d_rate": {
        "numerator": "eligible records initiated within 90 days",
        "denominator": "eligible records evaluable at 90 days",
        "population_definition": "eligibility_flag = true; early censoring excluded and reported",
        "time_zero": "eligibility_date",
        "horizon_days": 90,
    },
    "treatment_gap_90d_rate": {
        "numerator": "eligible evaluable records not initiated within 90 days",
        "denominator": "eligible records evaluable at 90 days",
        "population_definition": "eligibility_flag = true; early censoring excluded and reported",
        "time_zero": "eligibility_date",
        "horizon_days": 90,
    },
    "persistence_12m_rate": {
        "numerator": "eligible 90-day initiators classified PERSISTENT at 12 months",
        "denominator": "evaluable eligible 90-day initiators",
        "population_definition": "applicable eligible initiators with a resolved 12-month status",
        "time_zero": "treatment_start_date",
        "horizon_days": 365,
    },
    "progression_12m_rate": {
        "numerator": "records with generated progression by 365 days",
        "denominator": "all generated records",
        "population_definition": "all generated prostate-cancer archetypes",
        "time_zero": "observation_start_date",
        "horizon_days": 365,
    },
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _git_value(project_root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=project_root, text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def load_simulation_spec(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Simulation specification must be a mapping")
    required = {"version", "simulation", "scenarios", "scenario_axis", "synthetic_data_only"}
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"Simulation specification is missing: {missing}")
    if set(payload["scenarios"]) != {"low", "base", "high"}:
        raise ValueError("Simulation scenarios must be exactly low, base, and high")
    for name, scenario in payload["scenarios"].items():
        required_scenario = {
            "label",
            "reviewer_status",
            "assumption_status",
            "requires_sme_review",
            "overrides",
        }
        missing_scenario = sorted(required_scenario - set(scenario))
        if missing_scenario:
            raise ValueError(f"Scenario {name} is missing: {missing_scenario}")
        if scenario["assumption_status"] != "REQUIRES SME REVIEW":
            raise ValueError(f"Scenario {name} must remain marked REQUIRES SME REVIEW")
    settings = payload["simulation"]
    if int(settings["seeds_per_scenario"]) < 1:
        raise ValueError("seeds_per_scenario must be positive")
    configured_range = int(settings.get("seed_end_inclusive", settings["seed_start"]))
    configured_range -= int(settings["seed_start"])
    configured_range += 1
    if "seed_end_inclusive" in settings and configured_range != int(settings["seeds_per_scenario"]):
        raise ValueError("Configured inclusive seed range must match seeds_per_scenario")
    if int(settings["maximum_seeds_per_scenario"]) < int(settings["seeds_per_scenario"]):
        raise ValueError("maximum seeds cannot be lower than initial seeds")
    return payload


def extract_simulation_metrics(
    tables: Mapping[str, pd.DataFrame],
) -> dict[str, dict[str, float | int]]:
    """Extract denominator-reconciled scalar estimates from one generated cohort."""
    journey = tables["patient_journey"]
    eligible = journey.eligibility_flag.fillna(False).astype(bool)
    initiation_status = journey.initiation_90d_status.astype("string")
    initiation_evaluable = eligible & initiation_status.isin(
        ["INITIATED_WITHIN_90D", "NOT_INITIATED_WITHIN_90D"]
    )
    initiated = eligible & initiation_status.eq("INITIATED_WITHIN_90D")
    gap = eligible & initiation_status.eq("NOT_INITIATED_WITHIN_90D")
    initiation_censored = eligible & initiation_status.eq("CENSORED_NOT_EVALUABLE")
    if int(eligible.sum()) != int(initiated.sum() + gap.sum() + initiation_censored.sum()):
        raise AssertionError("Initiation denominator chain does not reconcile")

    persistence_status = journey.persistence_12m_status.astype("string")
    persistence_evaluable = initiated & persistence_status.isin(
        ["PERSISTENT", "DISCONTINUED", "SWITCHED"]
    )
    persistent = initiated & persistence_status.eq("PERSISTENT")
    persistence_censored = initiated & persistence_status.eq("CENSORED_NOT_EVALUABLE")
    persistence_not_applicable = initiated & persistence_status.eq("NOT_APPLICABLE")
    if int(initiated.sum()) != int(
        persistence_evaluable.sum() + persistence_censored.sum() + persistence_not_applicable.sum()
    ):
        raise AssertionError("Persistence denominator chain does not reconcile")

    total = int(len(journey))
    eligible_n = int(eligible.sum())
    initiation_denominator = int(initiation_evaluable.sum())
    persistence_denominator = int(persistence_evaluable.sum())
    progression_date = pd.to_datetime(journey.progression_date, errors="coerce")
    progression_origin = pd.to_datetime(journey.observation_start_date, errors="coerce")
    progression = (
        journey.progression_event.fillna(False).astype(bool)
        & progression_date.notna()
        & progression_date.le(progression_origin + pd.Timedelta(days=365))
    )
    metrics = {
        "eligibility_rate": (eligible_n, total),
        "initiation_90d_rate": (int(initiated.sum()), initiation_denominator),
        "treatment_gap_90d_rate": (int(gap.sum()), initiation_denominator),
        "persistence_12m_rate": (int(persistent.sum()), persistence_denominator),
        "progression_12m_rate": (int(progression.sum()), total),
    }
    return {
        metric: {
            "numerator_count": numerator,
            "denominator_count": denominator,
            "value": numerator / denominator if denominator else math.nan,
        }
        for metric, (numerator, denominator) in metrics.items()
    }


def _child_paths(output_root: Path, scenario: str, seed: int) -> dict[str, Path]:
    child = output_root / "children" / scenario / f"seed-{seed:06d}"
    return {
        "root": child,
        "config": child / "config_snapshot.yaml",
        "metrics": child / "metrics.json",
        "manifest": child / "child_manifest.json",
        "marker": child / "IMMUTABLE_CHILD_RUN",
    }


def verify_child_manifest(child_dir: str | Path) -> None:
    """Fail if a child manifest, configuration, or metric payload changed after sealing."""
    root = Path(child_dir)
    manifest_path = root / "child_manifest.json"
    marker_path = root / "IMMUTABLE_CHILD_RUN"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_manifest_hash = marker_path.read_text(encoding="utf-8").strip()
    if _sha256(manifest_path) != expected_manifest_hash:
        raise ValueError(f"Child manifest changed after sealing: {root}")
    for key in ("config_snapshot", "metrics"):
        item = manifest["artifacts"][key]
        path = root / item["path"]
        if _sha256(path) != item["sha256"] or path.stat().st_size != int(item["bytes"]):
            raise ValueError(f"Child artifact changed after sealing: {path}")


def verify_simulation_manifest(output_dir: str | Path) -> None:
    """Fail if a sealed parent manifest or declared aggregate artifact changed."""
    root = Path(output_dir).resolve()
    manifest_path = root / "simulation_manifest.json"
    marker_path = root / "IMMUTABLE_SIMULATION_STUDY"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if _sha256(manifest_path) != marker_path.read_text(encoding="utf-8").strip():
        raise ValueError(f"Simulation manifest changed after sealing: {root}")
    for item in manifest["artifacts"].values():
        path = root / str(item["path"])
        if _sha256(path) != item["sha256"] or path.stat().st_size != int(item["bytes"]):
            raise ValueError(f"Simulation artifact changed after sealing: {path}")
    declared_children = manifest.get("child_manifests")
    if not isinstance(declared_children, dict) or not declared_children:
        raise ValueError(f"Simulation manifest has no sealed child-run inventory: {root}")
    actual_children = {
        child.relative_to(root).as_posix()
        for child in root.glob("children/*/seed-*/child_manifest.json")
    }
    if actual_children != set(declared_children):
        raise ValueError(f"Simulation child-run inventory changed after sealing: {root}")
    for relative_path, item in declared_children.items():
        child_manifest = (root / str(relative_path)).resolve()
        try:
            child_manifest.relative_to(root)
        except ValueError as error:
            raise ValueError(f"Simulation child path escapes package: {relative_path}") from error
        if _sha256(child_manifest) != item["sha256"] or child_manifest.stat().st_size != int(
            item["bytes"]
        ):
            raise ValueError(f"Simulation child manifest changed after sealing: {child_manifest}")
        verify_child_manifest(child_manifest.parent)


def run_simulation_child(
    *,
    project_root: Path,
    output_root: Path,
    base_config: Mapping[str, Any],
    scenario_name: str,
    scenario_spec: Mapping[str, Any],
    seed: int,
    cohort_size: int,
    input_dir: Path,
    simulation_version: str,
    release: str | None = None,
) -> list[dict[str, Any]]:
    """Generate, summarize, and seal one seed/scenario child run."""
    paths = _child_paths(output_root, scenario_name, seed)
    paths["root"].parent.mkdir(parents=True, exist_ok=True)
    try:
        paths["root"].mkdir()
    except FileExistsError as error:
        raise FileExistsError(f"Immutable child run already exists: {paths['root']}") from error
    config = _deep_merge(base_config, scenario_spec.get("overrides", {}))
    config.update(
        {
            "random_seed": seed,
            "target_cohort_size": cohort_size,
            "profile": "simulation",
        }
    )
    config["readiness"] = {
        **dict(config.get("readiness", {})),
        "verify_reproducibility_full": False,
        "fail_on_p0_p1": False,
    }
    config_hash = _payload_hash(config)
    release_label = release or f"NOT_RELEASED_SIMULATION::{simulation_version}"
    tables = generate_tables(config, input_dir)
    metrics = extract_simulation_metrics(tables)
    paths["config"].write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
    paths["metrics"].write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    manifest = {
        "manifest_version": "1.0",
        "simulation_version": simulation_version,
        "release": release_label,
        "scenario": scenario_name,
        "scenario_label": str(scenario_spec["label"]),
        "reviewer_status": str(scenario_spec["reviewer_status"]),
        "assumption_status": str(scenario_spec["assumption_status"]),
        "seed": seed,
        "cohort_size": cohort_size,
        "configuration_sha256": config_hash,
        "generated_at": _utc_now(),
        "source_commit": _git_value(project_root, "rev-parse", "HEAD"),
        "code_version": __version__,
        "synthetic_data_only": True,
        "formal_clinical_or_market_claim": False,
        "artifacts": {
            "config_snapshot": {
                "path": paths["config"].name,
                "bytes": paths["config"].stat().st_size,
                "sha256": _sha256(paths["config"]),
            },
            "metrics": {
                "path": paths["metrics"].name,
                "bytes": paths["metrics"].stat().st_size,
                "sha256": _sha256(paths["metrics"]),
            },
        },
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    paths["marker"].write_text(_sha256(paths["manifest"]), encoding="utf-8")
    verify_child_manifest(paths["root"])

    rows: list[dict[str, Any]] = []
    for metric_id, values in metrics.items():
        definition = METRIC_DEFINITIONS[metric_id]
        rows.append(
            {
                "scenario": scenario_name,
                "scenario_label": str(scenario_spec["label"]),
                "seed": seed,
                "metric_id": metric_id,
                "value": values["value"],
                "numerator": definition["numerator"],
                "numerator_count": values["numerator_count"],
                "denominator": definition["denominator"],
                "denominator_count": values["denominator_count"],
                "population_definition": definition["population_definition"],
                "time_zero": definition["time_zero"],
                "horizon_days": definition["horizon_days"],
                "seed_summary": f"single seed {seed}",
                "release": release_label,
                "assumptions": (f"{scenario_spec['label']}; {scenario_spec['assumption_status']}"),
                "limitation": (
                    "Seed-level synthetic engineering result; not a patient outcome, clinical "
                    "finding, market estimate, or Bayer insight."
                ),
                "uncertainty_type": "SINGLE_SIMULATION_REPLICATE",
                "configuration_sha256": config_hash,
                "child_manifest": str(paths["manifest"].relative_to(output_root)),
                "synthetic_data_only": True,
            }
        )
    return rows


def summarize_simulation_replicates(
    replicates: pd.DataFrame,
    spec: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Separate within-scenario spread, Monte Carlo error, and scenario envelopes."""
    quantiles = list(map(float, spec["simulation"]["simulation_interval_quantiles"]))
    lower_q, upper_q = quantiles
    summary_rows: list[dict[str, Any]] = []
    for (scenario, metric_id), group in replicates.groupby(["scenario", "metric_id"], sort=True):
        finite = pd.to_numeric(group.value, errors="coerce").dropna()
        if finite.empty:
            mean = standard_deviation = mcse_value = lower = upper = math.nan
        else:
            mean = float(finite.mean())
            standard_deviation = float(finite.std(ddof=1)) if len(finite) > 1 else 0.0
            mcse_value = standard_deviation / math.sqrt(len(finite))
            lower = float(finite.quantile(lower_q))
            upper = float(finite.quantile(upper_q))
        first = group.iloc[0]
        summary_rows.append(
            {
                "scenario": scenario,
                "metric_id": metric_id,
                "mean_estimate": mean,
                "within_scenario_standard_deviation": standard_deviation,
                "simulation_interval_lower": lower,
                "simulation_interval_upper": upper,
                "monte_carlo_standard_error": mcse_value,
                "replications": int(group.seed.nunique()),
                "numerator": str(first.numerator),
                "mean_numerator_count": float(group.numerator_count.mean()),
                "denominator": str(first.denominator),
                "mean_denominator_count": float(group.denominator_count.mean()),
                "population_definition": str(first.population_definition),
                "time_zero": str(first.time_zero),
                "horizon_days": int(first.horizon_days),
                "seed_summary": (
                    f"{group.seed.nunique()} seeds: {group.seed.min()}-{group.seed.max()}"
                ),
                "release": str(first.release),
                "assumptions": str(first.assumptions),
                "limitation": str(first.limitation),
                "uncertainty_type": "WITHIN_SCENARIO_SIMULATION_INTERVAL_95",
                "synthetic_data_only": True,
            }
        )
    within = pd.DataFrame(summary_rows)
    mcse_frame = within[
        [
            "scenario",
            "metric_id",
            "monte_carlo_standard_error",
            "replications",
            "numerator",
            "denominator",
            "population_definition",
            "time_zero",
            "horizon_days",
            "seed_summary",
            "release",
            "assumptions",
            "limitation",
            "synthetic_data_only",
        ]
    ].copy()
    mcse_frame["uncertainty_type"] = "MONTE_CARLO_STANDARD_ERROR"

    envelope_rows: list[dict[str, Any]] = []
    driver_rows: list[dict[str, Any]] = []
    for metric_id, group in within.groupby("metric_id", sort=True):
        base_rows = group.loc[group.scenario.eq("base")]
        base_mean = float(base_rows.iloc[0].mean_estimate) if not base_rows.empty else math.nan
        first = group.iloc[0]
        means = pd.to_numeric(group.mean_estimate, errors="coerce")
        envelope_rows.append(
            {
                "metric_id": metric_id,
                "scenario": "low/base/high",
                "base_mean": base_mean,
                "scenario_envelope_lower": float(means.min()),
                "scenario_envelope_upper": float(means.max()),
                "numerator": str(first.numerator),
                "denominator": str(first.denominator),
                "population_definition": str(first.population_definition),
                "time_zero": str(first.time_zero),
                "horizon_days": int(first.horizon_days),
                "seed_summary": "; ".join(group.seed_summary.astype(str)),
                "release": str(first.release),
                "assumptions": "coherent low/base/high care-pathway-friction bundles",
                "limitation": (
                    "Envelope reflects changed unsupported assumptions, not estimator sampling "
                    "uncertainty or a real-world range."
                ),
                "uncertainty_type": "SCENARIO_ASSUMPTION_ENVELOPE_NOT_CONFIDENCE_INTERVAL",
                "synthetic_data_only": True,
            }
        )
        for row in group.itertuples(index=False):
            row_mean = float(cast(Any, row.mean_estimate))
            driver_rows.append(
                {
                    "metric_id": metric_id,
                    "scenario": row.scenario,
                    "scenario_mean": row_mean,
                    "base_mean": base_mean,
                    "difference_from_base": row_mean - base_mean,
                    "absolute_difference_from_base": abs(row_mean - base_mean),
                    "numerator": row.numerator,
                    "denominator": row.denominator,
                    "population_definition": row.population_definition,
                    "time_zero": row.time_zero,
                    "horizon_days": row.horizon_days,
                    "seed_summary": row.seed_summary,
                    "release": row.release,
                    "assumptions": row.assumptions,
                    "limitation": row.limitation,
                    "uncertainty_type": "SCENARIO_SENSITIVITY_DRIVER",
                    "synthetic_data_only": True,
                }
            )
    return within, mcse_frame, pd.DataFrame(envelope_rows), pd.DataFrame(driver_rows)


def _run_batch(
    seeds: list[int],
    *,
    workers: int,
    child_arguments: dict[str, Any],
) -> list[dict[str, Any]]:
    def run(seed: int) -> list[dict[str, Any]]:
        return run_simulation_child(seed=seed, **child_arguments)

    if workers <= 1:
        nested = [run(seed) for seed in seeds]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            nested = list(executor.map(run, seeds))
    return [row for rows in nested for row in rows]


def run_multi_seed_study(
    project_root: str | Path,
    specification_path: str | Path,
    output_dir: str | Path,
    *,
    input_dir: str | Path | None = None,
    release: str | None = None,
) -> Path:
    """Run a fresh low/base/high simulation with adaptive Monte Carlo precision."""
    project = Path(project_root).resolve()
    spec_path = Path(specification_path).resolve()
    spec = load_simulation_spec(spec_path)
    output = Path(output_dir).resolve()
    try:
        output.mkdir(parents=True)
    except FileExistsError as error:
        raise FileExistsError(
            f"Simulation output is immutable and already exists: {output}"
        ) from error
    in_progress = output / ".simulation-in-progress"
    in_progress.write_text(_utc_now(), encoding="utf-8")

    base_config_path = spec_path.parent / str(
        spec.get("base_config_file", "prostate_scenario.yaml")
    )
    base_config = load_config(base_config_path)
    settings = spec["simulation"]
    seed_start = int(settings["seed_start"])
    initial = int(settings["seeds_per_scenario"])
    maximum = int(settings["maximum_seeds_per_scenario"])
    batch_size = int(settings["adaptive_batch_size"])
    workers = int(settings.get("workers", 1))
    cohort_size = int(settings["cohort_size_per_seed"])
    tolerance = float(settings["mcse_tolerance_rate"])
    adaptive_metrics = set(map(str, settings["adaptive_metrics"]))
    generated_input = Path(input_dir).resolve() if input_dir else output / "_generated_input"
    generated_input.mkdir(parents=True, exist_ok=True)
    simulation_version = str(spec["version"])
    release_label = release or f"NOT_RELEASED_SIMULATION::{simulation_version}"
    all_rows: list[dict[str, Any]] = []
    adaptive_log: list[dict[str, Any]] = []

    for scenario_name in ("low", "base", "high"):
        scenario_spec = spec["scenarios"][scenario_name]
        completed = 0
        requested = initial
        while completed < requested:
            end = min(requested, maximum)
            seeds = list(range(seed_start + completed, seed_start + end))
            child_arguments = {
                "project_root": project,
                "output_root": output,
                "base_config": base_config,
                "scenario_name": scenario_name,
                "scenario_spec": scenario_spec,
                "cohort_size": cohort_size,
                "input_dir": generated_input,
                "simulation_version": simulation_version,
                "release": release_label,
            }
            all_rows.extend(_run_batch(seeds, workers=workers, child_arguments=child_arguments))
            completed = end
            scenario_rows = pd.DataFrame(all_rows)
            scenario_rows = scenario_rows.loc[scenario_rows.scenario.eq(scenario_name)]
            current, _, _, _ = summarize_simulation_replicates(
                scenario_rows,
                {
                    **spec,
                    "simulation": {
                        **settings,
                        "simulation_interval_quantiles": settings["simulation_interval_quantiles"],
                    },
                },
            )
            evaluated = current.loc[current.metric_id.isin(adaptive_metrics)]
            max_mcse = float(evaluated.monte_carlo_standard_error.max())
            extend = math.isfinite(max_mcse) and max_mcse > tolerance and completed < maximum
            adaptive_log.append(
                {
                    "scenario": scenario_name,
                    "seeds_completed": completed,
                    "maximum_rate_mcse": max_mcse,
                    "tolerance": tolerance,
                    "extended": extend,
                }
            )
            if extend:
                requested = min(maximum, completed + batch_size)
            else:
                break
        if bool(settings.get("fail_if_minimum_not_reached", True)) and completed < initial:
            raise RuntimeError(
                f"Scenario {scenario_name} completed only {completed}/{initial} seeds"
            )

    replicates = pd.DataFrame(all_rows).sort_values(
        ["scenario", "seed", "metric_id"], kind="stable"
    )
    within, mcse, envelope, drivers = summarize_simulation_replicates(replicates, spec)
    files = {
        "replicates": output / "simulation_replicate_metrics.csv",
        "within": output / "within_scenario_variability.csv",
        "mcse": output / "monte_carlo_error.csv",
        "envelope": output / "scenario_envelope.csv",
        "drivers": output / "sensitivity_drivers.csv",
        "explanation": output / "uncertainty_plain_language.json",
        "spec": output / "simulation_spec_snapshot.yaml",
    }
    replicates.to_csv(files["replicates"], index=False)
    within.to_csv(files["within"], index=False)
    mcse.to_csv(files["mcse"], index=False)
    envelope.to_csv(files["envelope"], index=False)
    drivers.to_csv(files["drivers"], index=False)
    files["spec"].write_text(yaml.safe_dump(spec, sort_keys=True), encoding="utf-8")
    explanation = {
        "synthetic_data_only": True,
        "disclaimer": DISCLAIMER,
        "within_scenario_variation": (
            "How much a metric changes when new synthetic patients are regenerated under the "
            "same assumptions. The empirical 2.5th-97.5th percentile is a simulation interval."
        ),
        "scenario_assumption_variation": (
            "How low/base/high coherent assumption bundles move the average metric. The envelope "
            "is not a confidence interval and is not a real-world range."
        ),
        "monte_carlo_error": (
            "How precisely the finite set of seeds estimates its own scenario mean: replicate "
            "standard deviation divided by the square root of completed seeds."
        ),
        "estimator_uncertainty": (
            "Uncertainty attached to a statistical estimator within one dataset is reported "
            "separately in the scientific evidence package."
        ),
    }
    files["explanation"].write_text(json.dumps(explanation, indent=2), encoding="utf-8")

    artifact_manifest = {
        path.name: {"path": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in files.values()
    }
    child_manifest_index = {
        child.relative_to(output).as_posix(): {
            "bytes": child.stat().st_size,
            "sha256": _sha256(child),
        }
        for child in sorted(output.glob("children/*/seed-*/child_manifest.json"))
    }
    expected_children = sum(
        int(group.seed.nunique()) for _, group in replicates.groupby("scenario")
    )
    if len(child_manifest_index) != expected_children:
        raise AssertionError(
            f"Child-run manifest inventory has {len(child_manifest_index)}/{expected_children} rows"
        )
    parent_manifest = {
        "manifest_version": "1.0",
        "simulation_version": simulation_version,
        "release": release_label,
        "generated_at": _utc_now(),
        "source_commit": _git_value(project, "rev-parse", "HEAD"),
        "source_tracked_clean": _git_value(project, "status", "--porcelain", "--untracked-files=no")
        == "",
        "code_version": __version__,
        "configuration_hash": _payload_hash(spec),
        "scenario_axis": spec["scenario_axis"],
        "scenarios": ["low", "base", "high"],
        "completed_seeds": {
            scenario: int(group.seed.nunique())
            for scenario, group in replicates.groupby("scenario")
        },
        "adaptive_precision_log": adaptive_log,
        "child_manifests": child_manifest_index,
        "uncertainty_types_kept_separate": [
            "WITHIN_SCENARIO_SIMULATION_INTERVAL_95",
            "SCENARIO_ASSUMPTION_ENVELOPE_NOT_CONFIDENCE_INTERVAL",
            "MONTE_CARLO_STANDARD_ERROR",
        ],
        "synthetic_data_only": True,
        "formal_clinical_or_market_claim": False,
        "artifacts": artifact_manifest,
    }
    manifest_path = output / "simulation_manifest.json"
    manifest_path.write_text(json.dumps(parent_manifest, indent=2), encoding="utf-8")
    (output / "IMMUTABLE_SIMULATION_STUDY").write_text(_sha256(manifest_path), encoding="utf-8")
    in_progress.unlink()
    verify_simulation_manifest(output)
    return output
