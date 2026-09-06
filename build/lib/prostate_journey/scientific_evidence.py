"""Orchestrate an aggregate, provenance-locked synthetic scientific evidence package."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from . import DISCLAIMER, __version__
from .missingness_sensitivity import build_complete_truth_frame, write_missingness_outputs
from .pipeline import generate_tables
from .scientific_methods import load_event_hierarchy, write_survival_outputs
from .synthetic_utility import load_real_data_hook_spec, write_utility_outputs

REGISTRY_REQUIRED_FIELDS = {
    "analysis_id",
    "research_question",
    "analysis_type",
    "target_population",
    "study_population",
    "numerator",
    "denominator",
    "eligibility",
    "time_zero",
    "outcome_event",
    "observation_window",
    "competing_events",
    "censoring_events",
    "estimator",
    "assumptions",
    "sensitivity_analyses",
    "required_source_variables",
    "synthetic_interpretation_boundary",
    "reviewer_status",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _configuration_hash(config: Mapping[str, Any]) -> str:
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    """Replace non-finite scalars so frontend JSON remains standards-compliant."""
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _git_value(project_root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=project_root, text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def load_analysis_registry(path: str | Path) -> dict[str, Any]:
    """Validate registry completeness and prohibit unsupported review claims."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("analyses"), list):
        raise ValueError("Analysis registry must contain an analyses list")
    statuses = set(map(str, payload.get("status_vocabulary", [])))
    required_statuses = {
        "ENGINEERING DEFINITION",
        "PROPOSED CLINICAL DEFINITION",
        "SME REVIEWED",
        "SOURCE VALIDATED",
        "NOT YET VALIDATED",
    }
    if statuses != required_statuses:
        raise ValueError("Analysis registry status vocabulary is incomplete")
    identifiers: list[str] = []
    for analysis in payload["analyses"]:
        missing = sorted(REGISTRY_REQUIRED_FIELDS - analysis.keys())
        if missing:
            raise ValueError(f"Analysis {analysis.get('analysis_id')} is missing {missing}")
        status = str(analysis["reviewer_status"])
        if status not in statuses:
            raise ValueError(f"Unsupported reviewer status: {status}")
        if status in {"SME REVIEWED", "SOURCE VALIDATED"} and not analysis.get("review_evidence"):
            raise ValueError(f"Status {status} requires actual review evidence")
        identifiers.append(str(analysis["analysis_id"]))
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Analysis IDs must be unique")
    return payload


def verify_scientific_evidence_manifest(output_dir: str | Path) -> None:
    """Verify a sealed scientific package and every declared artifact."""
    root = Path(output_dir)
    manifest_path = root / "scientific_evidence_manifest.json"
    marker_path = root / "IMMUTABLE_SCIENTIFIC_EVIDENCE"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if _sha256(manifest_path) != marker_path.read_text(encoding="utf-8").strip():
        raise ValueError(f"Scientific evidence manifest changed after sealing: {root}")
    for filename, item in manifest["artifacts"].items():
        path = root / filename
        if _sha256(path) != item["sha256"] or path.stat().st_size != int(item["bytes"]):
            raise ValueError(f"Scientific evidence artifact changed after sealing: {path}")


def _wilson_interval(numerator: int, denominator: int) -> tuple[float, float, float]:
    if denominator <= 0:
        return math.nan, math.nan, math.nan
    z = 1.959963984540054
    proportion = numerator / denominator
    scale = 1 + z**2 / denominator
    centre = (proportion + z**2 / (2 * denominator)) / scale
    half_width = (
        z
        * math.sqrt(proportion * (1 - proportion) / denominator + z**2 / (4 * denominator**2))
        / scale
    )
    return proportion, max(0.0, centre - half_width), min(1.0, centre + half_width)


def build_estimator_uncertainty(
    journey: pd.DataFrame,
    *,
    release: str,
    scenario: str,
    seed_summary: str,
) -> pd.DataFrame:
    """Build within-dataset Wilson intervals, separate from simulation uncertainty."""
    eligible = journey.eligibility_flag.fillna(False).astype(bool)
    initiation_status = journey.initiation_90d_status.astype("string")
    initiation_evaluable = eligible & initiation_status.isin(
        ["INITIATED_WITHIN_90D", "NOT_INITIATED_WITHIN_90D"]
    )
    initiated = eligible & initiation_status.eq("INITIATED_WITHIN_90D")
    gap = eligible & initiation_status.eq("NOT_INITIATED_WITHIN_90D")
    persistence_status = journey.persistence_12m_status.astype("string")
    persistence_evaluable = initiated & persistence_status.isin(
        ["PERSISTENT", "DISCONTINUED", "SWITCHED"]
    )
    persistent = initiated & persistence_status.eq("PERSISTENT")
    definitions = [
        (
            "eligibility_rate",
            int(eligible.sum()),
            len(journey),
            "eligibility_flag = true",
            "all generated records",
            "all generated prostate-cancer archetypes",
            "index_date",
            0,
        ),
        (
            "initiation_90d_rate",
            int(initiated.sum()),
            int(initiation_evaluable.sum()),
            "eligible records initiated within 90 days",
            "eligible records evaluable through day 90",
            "eligible and 90-day-evaluable generated records",
            "eligibility_date",
            90,
        ),
        (
            "treatment_gap_90d_rate",
            int(gap.sum()),
            int(initiation_evaluable.sum()),
            "eligible evaluable records not initiated by day 90",
            "eligible records evaluable through day 90",
            "eligible and 90-day-evaluable generated records",
            "eligibility_date",
            90,
        ),
        (
            "persistence_12m_rate",
            int(persistent.sum()),
            int(persistence_evaluable.sum()),
            "eligible 90-day initiators classified PERSISTENT",
            "evaluable eligible 90-day initiators",
            "applicable generated initiators with resolved 12-month status",
            "treatment_start_date",
            365,
        ),
    ]
    rows: list[dict[str, Any]] = []
    for (
        metric,
        numerator,
        denominator,
        numerator_text,
        denominator_text,
        population,
        time_zero,
        horizon,
    ) in definitions:
        estimate, lower, upper = _wilson_interval(numerator, denominator)
        rows.append(
            {
                "metric_id": metric,
                "estimate": estimate,
                "estimator_confidence_lower": lower,
                "estimator_confidence_upper": upper,
                "uncertainty_type": "WILSON_SCORE_ESTIMATOR_CONFIDENCE_INTERVAL_95",
                "numerator": numerator_text,
                "numerator_count": numerator,
                "denominator": denominator_text,
                "denominator_count": denominator,
                "population_definition": population,
                "time_zero": time_zero,
                "horizon_days": horizon,
                "scenario": scenario,
                "seed_summary": seed_summary,
                "release": release,
                "assumptions": "binomial descriptive estimator within this generated dataset",
                "limitation": (
                    "Estimator uncertainty within one synthetic dataset; excludes scenario and "
                    "seed-regeneration uncertainty and has no real-world interpretation."
                ),
                "synthetic_data_only": True,
            }
        )
    return pd.DataFrame(rows)


def _complete_truth_config(config: Mapping[str, Any], cohort_size: int) -> dict[str, Any]:
    complete = deepcopy(dict(config))
    complete["target_cohort_size"] = cohort_size
    complete["profile"] = "scientific_truth_recovery"
    complete["scenario_version"] = f"{config['scenario_version']}-complete-pre-missingness"
    complete["missingness"] = {key: 0.0 for key in config["missingness"]}
    complete["readiness"] = {
        **dict(config.get("readiness", {})),
        "verify_reproducibility_full": False,
        "fail_on_p0_p1": False,
    }
    return complete


def _frontend_payload(
    output: Path,
    release: str,
    estimator: pd.DataFrame,
) -> dict[str, Any]:
    survival = pd.read_csv(output / "survival_curves.csv")
    cif = pd.read_csv(output / "cumulative_incidence.csv")
    missingness = pd.read_csv(output / "missingness_method_performance.csv")
    utility = pd.read_csv(output / "synthetic_utility_dimensions.csv")
    survival_headlines: list[dict[str, Any]] = []
    for endpoint, endpoint_curve in survival.groupby("endpoint", sort=True):
        final = endpoint_curve.sort_values("time_days").iloc[-1]
        target_cif = cif.loc[(cif.endpoint.eq(endpoint))]
        target_cause = {
            "initiation": "initiation",
            "discontinuation": "discontinuation",
            "progression": "progression",
            "hospitalization": "hospitalization",
        }[str(endpoint)]
        target_rows = target_cif.loc[target_cif.cause.eq(target_cause)].sort_values("time_days")
        absolute_probability = float(target_rows.iloc[-1].cumulative_incidence)
        survival_headlines.append(
            {
                "endpoint": endpoint,
                "horizon_days": int(final.horizon_days),
                "study_population_n": int(final.denominator),
                "kaplan_meier_net_event_probability": float(final.net_event_probability),
                "aalen_johansen_cumulative_incidence": absolute_probability,
                "estimator_band_lower": float(final.confidence_lower),
                "estimator_band_upper": float(final.confidence_upper),
                "target_event_count": int(endpoint_curve.target_events.sum()),
                "competing_event_count": int(endpoint_curve.competing_events.sum()),
                "censoring_mark_count": int(endpoint_curve.censoring_mark_count.sum()),
                "limitation": str(final.limitation),
            }
        )
    return {
        "synthetic_data_only": True,
        "disclaimer": DISCLAIMER,
        "release": release,
        "uncertainty_types": {
            "estimator": "within one generated dataset; Wilson or Greenwood as labelled",
            "simulation": (
                "regenerating patients under unchanged assumptions; separate study output"
            ),
            "scenario": "changing coherent assumption bundles; separate study output",
        },
        "estimator_metrics": estimator.to_dict(orient="records"),
        "survival": survival_headlines,
        "missingness": missingness.to_dict(orient="records"),
        "utility_dimensions": utility.to_dict(orient="records"),
        "causal_interpretation_allowed": False,
        "clinical_validation_status": "NOT YET VALIDATED",
    }


def build_scientific_evidence_package(
    *,
    project_root: str | Path,
    tables: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
    output_dir: str | Path,
    release: str,
    analysis_registry_path: str | Path,
    event_hierarchy_path: str | Path,
    simulation_spec_path: str | Path,
    real_hook_spec_path: str | Path,
    input_dir: str | Path,
) -> Path:
    """Build a fresh scientific package without claiming Stage-4 completion."""
    project = Path(project_root).resolve()
    output = Path(output_dir).resolve()
    try:
        output.mkdir(parents=True)
    except FileExistsError as error:
        raise FileExistsError(f"Scientific evidence output already exists: {output}") from error
    in_progress = output / ".scientific-in-progress"
    in_progress.write_text(_utc_now(), encoding="utf-8")
    registry = load_analysis_registry(analysis_registry_path)
    hierarchy = load_event_hierarchy(event_hierarchy_path)
    simulation_spec = yaml.safe_load(Path(simulation_spec_path).read_text(encoding="utf-8"))
    hook_spec = load_real_data_hook_spec(real_hook_spec_path)
    scenario = str(config["scenario_version"])
    seed_summary = f"single source seed {config['random_seed']}"
    configuration_hash = _configuration_hash(config)

    snapshots = {
        "analysis_registry_snapshot.yaml": Path(analysis_registry_path),
        "event_hierarchy_snapshot.yaml": Path(event_hierarchy_path),
        "simulation_spec_snapshot.yaml": Path(simulation_spec_path),
        "real_data_evaluation_hooks_snapshot.yaml": Path(real_hook_spec_path),
    }
    for destination, source in snapshots.items():
        shutil.copy2(source, output / destination)

    write_survival_outputs(
        tables["patient_journey"],
        hierarchy,
        output,
        scenario=scenario,
        seed_summary=seed_summary,
        release=release,
    )
    estimator = build_estimator_uncertainty(
        tables["patient_journey"],
        release=release,
        scenario=scenario,
        seed_summary=seed_summary,
    )
    estimator.to_csv(output / "estimator_uncertainty.csv", index=False)

    experiment = simulation_spec["missingness_truth_recovery"]
    complete_config = _complete_truth_config(config, int(experiment["truth_cohort_size"]))
    complete_tables = generate_tables(complete_config, input_dir)
    truth = build_complete_truth_frame(complete_tables)
    write_missingness_outputs(
        truth,
        config,
        experiment,
        output,
        release=release,
        scenario=scenario,
    )
    write_utility_outputs(
        tables,
        config,
        output,
        release=release,
        scenario=scenario,
        seed_summary=seed_summary,
        real_hook_spec=hook_spec,
    )
    frontend = _json_safe(_frontend_payload(output, release, estimator))
    (output / "scientific_frontend_summary.json").write_text(
        json.dumps(frontend, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )

    report = [
        "# Scientific-methods implementation report",
        "",
        f"> **{DISCLAIMER}**",
        "",
        f"- Release/source: `{release}`",
        f"- Configuration SHA-256: `{configuration_hash}`",
        f"- Analyses registered: {len(registry['analyses'])}",
        f"- Event hierarchy: `{hierarchy['version']}`",
        "- Causal interpretation: prohibited; no causal estimand or identification strategy "
        "approved.",
        "",
        "## Implemented methods",
        "",
        "- Explicit endpoint populations, time zero, horizon, event/competing/censor states.",
        "- Kaplan-Meier with Greenwood log-log estimator bands, censor counts, and exact risk "
        "tables.",
        "- Aalen-Johansen cumulative incidence for configured competing events.",
        "- Wilson estimator intervals kept separate from seed and scenario variation.",
        "- Complete pre-missingness truth retention plus MCAR/MAR/MNAR truth-recovery experiments.",
        "- Dimension-specific synthetic utility/realism checks without a universal score.",
        "",
        "## Approval boundary",
        "",
        "Event definitions, same-day priorities, populations, estimators, and missingness "
        "assumptions "
        "remain engineering proposals. Oncology, RWE, biostatistics, privacy/security, model-risk, "
        "and data-owner review are required before any governed real-data use.",
    ]
    (output / "SCIENTIFIC_METHODS_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    manifest_path = output / "scientific_evidence_manifest.json"
    artifacts = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in sorted(output.iterdir())
        if path.is_file() and path not in {manifest_path, in_progress}
    }
    manifest = {
        "manifest_version": "1.0",
        "package_type": "synthetic scientific methods evidence",
        "generated_at": _utc_now(),
        "release": release,
        "source_commit": _git_value(project, "rev-parse", "HEAD"),
        "analysis_commit": _git_value(project, "rev-parse", "HEAD"),
        "configuration_hash": configuration_hash,
        "code_version": __version__,
        "scenario": scenario,
        "seed_summary": seed_summary,
        "active_analytical_definition": {
            "registry_version": registry["registry_version"],
            "event_hierarchy_version": hierarchy["version"],
            "persistence": config["prescription"]["definition_version"],
            "missingness_experiment": simulation_spec["version"],
        },
        "synthetic_data_only": True,
        "formal_clinical_or_regulatory_claim": False,
        "causal_interpretation_allowed": False,
        "artifacts": artifacts,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "IMMUTABLE_SCIENTIFIC_EVIDENCE").write_text(_sha256(manifest_path), encoding="utf-8")
    in_progress.unlink()
    verify_scientific_evidence_manifest(output)
    return output
