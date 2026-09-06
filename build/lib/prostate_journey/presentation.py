"""Build a provenance-locked, aggregate-only stakeholder presentation package."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import DISCLAIMER, __version__
from .dashboard import eligible_cohort_funnel_counts, write_dashboard
from .dataset_resolver import AnalyticalDataset, resolve_analytical_dataset
from .executive_dashboard import write_executive_dashboard
from .healthcare_analysis import write_healthcare_analysis_report
from .pipeline import TABLES, load_exported_tables
from .predictive_dashboard import write_predictive_dashboard
from .predictive_evidence import verify_predictive_evidence_manifest
from .reporting import kpis, sha256, write_cohort_report
from .scientific_dashboard import write_scientific_dashboard
from .scientific_evidence import verify_scientific_evidence_manifest
from .simulation import verify_simulation_manifest
from .tactic_registry import (
    DEFAULT_TACTIC_REGISTRY,
    load_tactic_registry,
    validate_tactic_source_paths,
)

SCIENTIFIC_PRESENTATION_FILES = (
    "analysis_registry_snapshot.yaml",
    "event_hierarchy_snapshot.yaml",
    "scientific_frontend_summary.json",
    "survival_curves.csv",
    "number_at_risk.csv",
    "cumulative_incidence.csv",
    "estimator_uncertainty.csv",
    "missingness_method_performance.csv",
    "missingness_tipping_point.csv",
    "synthetic_utility_dimensions.csv",
    "SCIENTIFIC_METHODS_REPORT.md",
)
SIMULATION_PRESENTATION_FILES = (
    "within_scenario_variability.csv",
    "monte_carlo_error.csv",
    "scenario_envelope.csv",
    "sensitivity_drivers.csv",
    "uncertainty_plain_language.json",
)
PREDICTIVE_PRESENTATION_FILES = (
    "model_target_contracts_snapshot.yaml",
    "model_evaluation_snapshot.yaml",
    "model_governance_snapshot.yaml",
    "model_aliases_snapshot.yaml",
    "predictive_frontend_summary.json",
    "model_population_derivation.csv",
    "validation_metrics.csv",
    "flexible_calibration_curves.csv",
    "leakage_audit.csv",
    "validation_fold_registry.csv",
    "subgroup_metrics.csv",
    "robustness_metrics.csv",
    "prior_claim_reproduction.csv",
    "model_disposition.csv",
    "decision_curve_status.json",
    "decision_curve_status.md",
    "PREDICTIVE_EVALUATION_REPORT.md",
)


def _release_inventory_count(source: AnalyticalDataset) -> int:
    if source.release_dir is None:
        return 0
    checksum_path = source.release_dir / "CHECKSUMS.sha256"
    if not checksum_path.is_file():
        return 0
    return sum(1 for line in checksum_path.read_text(encoding="utf-8").splitlines() if line.strip())


def _write_evidence_manifest(
    output_dir: Path,
    source: AnalyticalDataset,
    *,
    generated_at: str,
    analysis_commit: str | None,
    configuration_hash: str | None,
    active_definitions: dict[str, str | None],
) -> None:
    artifacts = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file()
        and path.name not in {"evidence_manifest.json", "presentation_manifest.json"}
    )
    payload = {
        "manifest_type": "aggregate evidence and provenance",
        "release_id": source.dataset_version,
        "input_release": source.dataset_version,
        "source_commit": source.release_manifest.get("git", {}).get("git_commit"),
        "analysis_commit": analysis_commit,
        "configuration_hash": configuration_hash,
        "generated_time": generated_at,
        "qa_status": "INTERNAL CONSISTENCY PASSED",
        "active_filters": {
            "market_scenario": "ALL CONFIGURED SYNTHETIC SCENARIOS",
            "initiation_window_days": 90,
            "persistence_gap_days": 60,
        },
        "active_analytical_definition": active_definitions,
        "tactic_registry": "tactic_registry.json",
        "synthetic_only": True,
        "patient_level_data_included": False,
        "prohibited_use": (
            "No clinical decisions, treatment recommendations, patient action, market ranking, "
            "causal claims, commercial conclusions, or production AI."
        ),
        "artifacts": {
            path.relative_to(output_dir).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in artifacts
        },
    }
    (output_dir / "evidence_manifest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _git_value(project_root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=project_root, text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _kpi_map(frame: pd.DataFrame) -> dict[str, int]:
    return {str(row.kpi): int(str(row.value)) for row in frame.itertuples()}


def _presentation_kpis(journey: pd.DataFrame) -> pd.DataFrame:
    funnel = eligible_cohort_funnel_counts(journey)
    rows = [
        ("total_patients", len(journey), "all synthetic patients"),
        ("markets", int(journey.market_code.nunique()), "distinct configured markets"),
        ("eligible", funnel["eligible"], "eligibility_flag = true"),
        (
            "initiated_90d_among_eligible",
            funnel["initiated_90d"],
            "eligible and initiated_within_90d = true",
        ),
        (
            "treatment_gap_90d_among_eligible",
            funnel["treatment_gap_90d"],
            "eligible and evaluable but not initiated within 90 days",
        ),
        (
            "initiation_censored_90d_among_eligible",
            funnel["initiation_censored_not_evaluable_90d"],
            "eligible but not evaluable through day 90",
        ),
        (
            "evaluable_12m_among_eligible_initiated_90d",
            funnel["evaluable_12m"],
            "eligible 90-day initiators evaluable at 12 months",
        ),
        (
            "persistent_12m_among_eligible_initiated_90d",
            funnel["persistent_12m"],
            "eligible 90-day initiators with PERSISTENT 12-month status",
        ),
        (
            "censored_12m_among_eligible_initiated_90d",
            funnel["censored_12m"],
            "eligible 90-day initiators censored before 12-month assessment",
        ),
    ]
    return pd.DataFrame(rows, columns=["kpi", "value", "definition"]).assign(data_label=DISCLAIMER)


def _assert_consistency(
    journey: pd.DataFrame, cohort_metrics: pd.DataFrame, presentation_metrics: pd.DataFrame
) -> None:
    metrics = _kpi_map(cohort_metrics)
    canonical = _kpi_map(presentation_metrics)
    expected = {
        "total_patients": canonical["total_patients"],
        "markets": canonical["markets"],
        "eligible": canonical["eligible"],
        "initiated_90d": canonical["initiated_90d_among_eligible"],
        "treatment_gap_90d": canonical["treatment_gap_90d_among_eligible"],
    }
    mismatches = {
        name: {"cohort_report": metrics.get(name), "presentation": value}
        for name, value in expected.items()
        if metrics.get(name) != value
    }
    if mismatches:
        raise ValueError(f"Presentation KPI consistency gate failed: {mismatches}")


def _single_definition(journey: pd.DataFrame, field: str) -> str:
    values = sorted(journey[field].dropna().astype(str).unique())
    if len(values) != 1:
        raise ValueError(f"Expected one active {field} definition, found {values}")
    return values[0]


def _active_definitions(journey: pd.DataFrame, source: AnalyticalDataset) -> dict[str, str | None]:
    run = source.release_manifest.get("run_metadata", {})
    return {
        "scenario": run.get("scenario_version"),
        "clinical_rules": run.get("clinical_rules_version"),
        "market_profile": run.get("market_configuration_version"),
        "eligibility": _single_definition(journey, "eligibility_rule_version"),
        "initiation": "INITIATION-WINDOW-SYN-v1.0; primary landmark 90 days",
        "persistence": _single_definition(journey, "persistence_rule_version"),
        "persistence_primary_gap": "60 days; sensitivities 30/60/90 days",
        "censoring": "right-censor before each landmark; never imputed as failure",
    }


def _write_readme(
    output_dir: Path,
    source: AnalyticalDataset,
    metrics: dict[str, int],
    configuration_hash: str | None,
    active_definitions: dict[str, str | None],
    scientific_evidence_available: bool,
    predictive_evidence_available: bool,
) -> None:
    source_commit = source.release_manifest.get("git", {}).get("git_commit", "not recorded")
    lines = [
        "# Stakeholder presentation package",
        "",
        f"> **{DISCLAIMER}**",
        "",
        "This package is generated from one immutable analytical source. It contains only "
        "aggregated reports and no patient-level exports.",
        "",
        "## Locked source",
        "",
        f"- Dataset version: `{source.dataset_version}`",
        f"- Selection: {source.selection_method}",
        f"- Source commit: `{source_commit}`",
        f"- Configuration SHA-256: `{configuration_hash or 'not recorded'}`",
        f"- Analysis code version: `{__version__}`",
        f"- Analytical directory: `{source.analytical_dir}`",
        f"- Active definitions: `{json.dumps(active_definitions, sort_keys=True)}`",
        "",
        "## Headline synthetic KPIs",
        "",
        f"- Total cohort: {metrics['total_patients']:,}",
        f"- Markets: {metrics['markets']:,}",
        f"- Eligible: {metrics['eligible']:,}",
        f"- Initiated within 90 days: {metrics['initiated_90d']:,}",
        f"- Treatment gap at 90 days: {metrics['treatment_gap_90d']:,}",
        "",
        "Open `executive_story.html` for the four-view certified Analytics product or "
        "`cohort_dashboard.html` for the compact historical analytical view.",
        "Use `tactic_registry.json` for canonical tactic metadata, `evidence_manifest.json` "
        "for stakeholder provenance, and `presentation_manifest.json` for package integrity.",
        "Use `accessible_report.html`, `aggregate_export.csv`, and `demo_fallback.html` "
        "when an accessible, exportable, or static fallback is required. No patient-level "
        "export exists.",
    ]
    if scientific_evidence_available:
        lines.extend(
            [
                "",
                "Open `scientific_story.html` for the interactive survival, competing-risk, "
                "multi-seed, missingness, and utility methods cockpit.",
            ]
        )
    if predictive_evidence_available:
        lines.extend(
            [
                "",
                "Open `model_story.html` for the interactive target-contract, temporal-validation, "
                "calibration, robustness, subgroup-support and model-disposition evidence lab.",
            ]
        )
    (output_dir / "PRESENTATION_README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _copy_scientific_aggregates(
    source: Path,
    output_dir: Path,
    filenames: tuple[str, ...],
) -> None:
    for filename in filenames:
        path = source / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required aggregate scientific artifact is missing: {path}")
        shutil.copy2(path, output_dir / filename)


def _copy_predictive_aggregates(source: Path, output_dir: Path) -> None:
    _copy_scientific_aggregates(source, output_dir, PREDICTIVE_PRESENTATION_FILES)
    card_source = source / "model_cards"
    card_index = json.loads((card_source / "index.json").read_text(encoding="utf-8"))
    destination = output_dir / "model_cards"
    destination.mkdir(exist_ok=True)
    allowed = {"index.json"}
    for card in card_index:
        allowed.update({str(card["markdown"]), str(card["json"])})
    for filename in sorted(allowed):
        path = card_source / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required aggregate model-card artifact is missing: {path}")
        shutil.copy2(path, destination / filename)


def _assert_evidence_source_alignment(
    evidence_name: str,
    evidence_manifest: dict[str, Any],
    source: AnalyticalDataset,
) -> None:
    """Require scientific evidence to originate from the presentation release commit."""
    release_commit = source.release_manifest.get("git", {}).get("git_commit")
    evidence_commit = evidence_manifest.get("source_commit")
    if not release_commit or not evidence_commit:
        raise ValueError(
            f"{evidence_name} and release must both record a source commit for alignment"
        )
    if evidence_commit != release_commit:
        raise ValueError(
            f"{evidence_name} source commit does not match presentation release source commit"
        )


def build_presentation_package(
    project_root: str | Path,
    dataset_dir: str | Path | None = None,
    output_root: str | Path | None = None,
    scientific_dir: str | Path | None = None,
    simulation_dir: str | Path | None = None,
    predictive_dir: str | Path | None = None,
) -> Path:
    """Generate an internally consistent package from one accepted candidate release."""
    root = Path(project_root).resolve()
    registry_path = root / "configs" / "tactic_registry.yaml"
    if not registry_path.is_file():
        registry_path = DEFAULT_TACTIC_REGISTRY
    tactic_registry = load_tactic_registry(registry_path)
    validate_tactic_source_paths(tactic_registry, registry_path.parent.parent)
    source = resolve_analytical_dataset(root, TABLES, dataset_dir, require_certified=True)
    destination_root = Path(output_root).resolve() if output_root else root / "outputs/presentation"
    output_dir = destination_root / source.dataset_version
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()

    scientific_root = (
        Path(scientific_dir).resolve()
        if scientific_dir is not None
        else root / "outputs/scientific" / source.dataset_version
    )
    simulation_root = (
        Path(simulation_dir).resolve()
        if simulation_dir is not None
        else root / "outputs/simulations" / source.dataset_version
    )
    predictive_root = (
        Path(predictive_dir).resolve()
        if predictive_dir is not None
        else root / "outputs/predictive" / source.dataset_version
    )
    scientific_available = (scientific_root / "scientific_evidence_manifest.json").is_file()
    simulation_available = (simulation_root / "simulation_manifest.json").is_file()
    predictive_available = (predictive_root / "predictive_evidence_manifest.json").is_file()
    predictive_manifest: dict[str, Any] = {}
    if scientific_available:
        verify_scientific_evidence_manifest(scientific_root)
        scientific_manifest = json.loads(
            (scientific_root / "scientific_evidence_manifest.json").read_text(encoding="utf-8")
        )
        if scientific_manifest.get("release") != source.dataset_version:
            raise ValueError("Scientific evidence release does not match presentation release")
        _assert_evidence_source_alignment("Scientific evidence", scientific_manifest, source)
        _copy_scientific_aggregates(
            scientific_root,
            output_dir,
            SCIENTIFIC_PRESENTATION_FILES,
        )
    if simulation_available:
        verify_simulation_manifest(simulation_root)
        simulation_manifest = json.loads(
            (simulation_root / "simulation_manifest.json").read_text(encoding="utf-8")
        )
        if simulation_manifest.get("release") != source.dataset_version:
            raise ValueError("Simulation release does not match presentation release")
        _assert_evidence_source_alignment("Simulation", simulation_manifest, source)
        _copy_scientific_aggregates(
            simulation_root,
            output_dir,
            SIMULATION_PRESENTATION_FILES,
        )
    if predictive_available:
        verify_predictive_evidence_manifest(predictive_root)
        predictive_manifest = json.loads(
            (predictive_root / "predictive_evidence_manifest.json").read_text(encoding="utf-8")
        )
        if predictive_manifest.get("release") != source.dataset_version:
            raise ValueError("Predictive evidence release does not match presentation release")
        _assert_evidence_source_alignment("Predictive evidence", predictive_manifest, source)
        release_commit = source.release_manifest.get("git", {}).get("git_commit")
        if predictive_manifest.get("analysis_commit") != release_commit:
            raise ValueError("Predictive analysis commit does not match presentation release")
        if predictive_manifest.get("analysis_worktree_clean") is not True:
            raise ValueError("Predictive evidence was not generated from a clean worktree")
        component_hashes = predictive_manifest.get("configuration_component_hashes")
        expected_configuration_components = {
            "model_target_contracts_snapshot.yaml",
            "model_evaluation_snapshot.yaml",
            "model_governance_snapshot.yaml",
            "model_aliases_snapshot.yaml",
        }
        if (
            not predictive_manifest.get("configuration_hash")
            or not isinstance(component_hashes, dict)
            or set(component_hashes) != expected_configuration_components
        ):
            raise ValueError("Predictive evidence configuration identity is incomplete")
        if predictive_manifest.get("patient_level_predictions_included") is not False:
            raise ValueError("Predictive evidence for presentation must be aggregate only")
        if predictive_manifest.get("deployable") is not False:
            raise ValueError("Deployable predictive evidence cannot enter this research package")
        _copy_predictive_aggregates(predictive_root, output_dir)

    tables = load_exported_tables(source.analytical_dir)
    journey = tables["patient_journey"]
    release_run = source.release_manifest.get("run_metadata", {})
    configuration_hash = release_run.get("config_snapshot_sha256")
    active_definitions = _active_definitions(journey, source)
    metric_frame = kpis(journey)
    presentation_metrics = _presentation_kpis(journey)
    _assert_consistency(journey, metric_frame, presentation_metrics)
    write_cohort_report(tables, output_dir)
    write_healthcare_analysis_report(tables, output_dir)
    presentation_metrics.to_csv(output_dir / "presentation_kpis.csv", index=False)

    analysis_commit = _git_value(root, "rev-parse", "HEAD")
    provenance = {
        "dataset_version": source.dataset_version,
        "selection_method": source.selection_method,
        "source_git_commit": source.release_manifest.get("git", {}).get("git_commit"),
        "analysis_git_commit": analysis_commit,
        "configuration_hash": configuration_hash,
        "code_version": __version__,
        "generated_at": generated_at,
        "qa_status": "INTERNAL CONSISTENCY PASSED",
        "analytical_status": "STAGE-4 CONDITIONAL — SYNTHETIC ONLY",
        "verified_artifacts": _release_inventory_count(source),
        "active_analytical_definition": active_definitions,
        "scientific_evidence_available": scientific_available,
        "multi_seed_simulation_available": simulation_available,
        "predictive_evidence_available": predictive_available,
    }
    dashboard_path = write_dashboard(journey, output_dir, provenance=provenance)
    executive_dashboard_path = write_executive_dashboard(
        tables,
        output_dir,
        provenance,
        registry=tactic_registry,
        predictive_summary_path=(
            output_dir / "predictive_frontend_summary.json" if predictive_available else None
        ),
    )
    scientific_dashboard_path: Path | None = None
    predictive_dashboard_path: Path | None = None
    if scientific_available:
        scientific_dashboard_path = write_scientific_dashboard(
            scientific_root,
            simulation_root if simulation_available else None,
            output_dir,
            provenance,
        )
    if predictive_available:
        predictive_dashboard_path = write_predictive_dashboard(
            predictive_root,
            output_dir,
            provenance,
        )
    dashboard_text = dashboard_path.read_text(encoding="utf-8")
    presentation_metric_map = _kpi_map(presentation_metrics)
    required_dashboard_values = [
        source.dataset_version,
        f"{presentation_metric_map['eligible']:,}",
        f"{presentation_metric_map['initiated_90d_among_eligible']:,}",
        f"{presentation_metric_map['treatment_gap_90d_among_eligible']:,}",
    ]
    if any(value not in dashboard_text for value in required_dashboard_values):
        raise ValueError("Dashboard provenance or headline KPI consistency gate failed")
    executive_text = executive_dashboard_path.read_text(encoding="utf-8")
    executive_required_values = [
        source.dataset_version,
        f'"total":{presentation_metric_map["total_patients"]}',
        f'"eligible":{presentation_metric_map["eligible"]}',
        f'"initiated90":{presentation_metric_map["initiated_90d_among_eligible"]}',
        f'"gap90":{presentation_metric_map["treatment_gap_90d_among_eligible"]}',
    ]
    if any(value not in executive_text for value in executive_required_values):
        raise ValueError("Executive frontend provenance or headline KPI consistency gate failed")

    readme_metrics = {
        "total_patients": presentation_metric_map["total_patients"],
        "markets": presentation_metric_map["markets"],
        "eligible": presentation_metric_map["eligible"],
        "initiated_90d": presentation_metric_map["initiated_90d_among_eligible"],
        "treatment_gap_90d": presentation_metric_map["treatment_gap_90d_among_eligible"],
    }
    _write_readme(
        output_dir,
        source,
        readme_metrics,
        configuration_hash,
        active_definitions,
        scientific_available,
        predictive_available,
    )
    _write_evidence_manifest(
        output_dir,
        source,
        generated_at=generated_at,
        analysis_commit=analysis_commit,
        configuration_hash=configuration_hash,
        active_definitions=active_definitions,
    )
    generated_files = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "presentation_manifest.json"
    )
    manifest: dict[str, Any] = {
        "package_type": "aggregate stakeholder presentation",
        "generated_at": generated_at,
        "disclaimer": DISCLAIMER,
        "dataset_version": source.dataset_version,
        "selection_method": source.selection_method,
        "analytical_dataset_directory": str(source.analytical_dir),
        "release_directory": str(source.release_dir) if source.release_dir else None,
        "portable_release_locator": {
            "dataset_version": source.dataset_version,
            "analytical_directory_name": source.analytical_dir.name,
        },
        "source_release_created_at": source.release_manifest.get("created_at"),
        "source_release_decision": source.release_manifest.get("decision"),
        "configuration_hash": configuration_hash,
        "code_version": __version__,
        "active_analytical_definition": active_definitions,
        "source_git": source.release_manifest.get("git", {}),
        "analysis_git": {
            "commit": analysis_commit,
            "branch": _git_value(root, "branch", "--show-current"),
            "tracked_source_clean": (
                _git_value(root, "status", "--porcelain", "--untracked-files=no") == ""
            ),
        },
        "headline_kpis": presentation_metric_map,
        "consistency_gate": "PASSED",
        "patient_level_data_included": False,
        "tactic_registry": {
            "path": "tactic_registry.json",
            "schema_version": tactic_registry.schema_version,
            "tactic_count": len(tactic_registry.tactics),
            "synthetic_only": tactic_registry.synthetic_only,
        },
        "product_views": ["Executive", "Analyst", "Methodology", "Governance"],
        "exports": {
            "presentation_png": "browser-generated from certified aggregate state",
            "accessible_report": "accessible_report.html",
            "aggregate_csv": "aggregate_export.csv",
            "evidence_manifest": "evidence_manifest.json",
            "shareable_filter_state": "URL query parameters; aggregate context only",
            "patient_level_export": False,
        },
        "scientific_evidence": {
            "available": scientific_available,
            "source_directory": str(scientific_root) if scientific_available else None,
            "dashboard": scientific_dashboard_path.name if scientific_dashboard_path else None,
        },
        "multi_seed_simulation": {
            "available": simulation_available,
            "source_directory": str(simulation_root) if simulation_available else None,
        },
        "predictive_evidence": {
            "available": predictive_available,
            "source_directory": str(predictive_root) if predictive_available else None,
            "dashboard": predictive_dashboard_path.name if predictive_dashboard_path else None,
            "configuration_hash": predictive_manifest.get("configuration_hash"),
            "analysis_worktree_clean": predictive_manifest.get("analysis_worktree_clean"),
            "patient_level_predictions_included": False,
            "deployable_models": 0,
        },
        "output_files": {
            path.relative_to(output_dir).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in generated_files
        },
    }
    common_provenance = {
        "dataset_release": source.dataset_version,
        "source_commit": source.release_manifest.get("git", {}).get("git_commit"),
        "configuration_hash": configuration_hash,
        "code_version": __version__,
        "generation_timestamp": manifest["generated_at"],
        "active_analytical_definition": active_definitions,
        "synthetic_data_only": True,
    }
    manifest["artifact_provenance"] = {
        path.relative_to(output_dir).as_posix(): {
            **common_provenance,
            **manifest["output_files"][path.relative_to(output_dir).as_posix()],
        }
        for path in generated_files
    }
    (output_dir / "presentation_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return output_dir
