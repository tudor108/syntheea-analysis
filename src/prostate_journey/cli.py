"""Command-line interface for pipeline stages."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import typer
import yaml

from .app_config import assert_mutable_output_path, load_application_settings
from .application import serve_application
from .config import load_config
from .dashboard import write_dashboard
from .data_quality import raise_on_critical, validate_tables, write_quality_report
from .dataset_resolver import resolve_analytical_dataset
from .duckdb_loader import load_duckdb
from .healthcare_analysis import write_healthcare_analysis_report
from .industry_readiness import run_industry_checks
from .logging_config import configure_logging, logged_operation
from .pipeline import TABLES, export_tables, generate_tables, load_exported_tables
from .pipeline import run_all as execute_all
from .predictive_evidence import (
    build_predictive_evidence_package,
    verify_predictive_eda_inputs,
)
from .presentation import build_presentation_package
from .release_runner import create_fresh_certified_release
from .reporting import write_cohort_report
from .scientific_evidence import build_scientific_evidence_package
from .simulation import run_multi_seed_study

app = typer.Typer(no_args_is_help=True, help="Synthetic prostate journey demo pipeline")
ROOT = Path(__file__).resolve().parents[2]


def _mutable_output(path: Path, label: str) -> Path:
    settings = load_application_settings(ROOT)
    return assert_mutable_output_path(settings, path, label=label)


def _settings(
    config: Path,
    seed: int | None,
    cohort_size: int | None,
    scenario_version: str | None,
    log_level: str,
) -> dict[str, Any]:
    configure_logging(log_level)
    return load_config(
        config, random_seed=seed, target_cohort_size=cohort_size, scenario_version=scenario_version
    )


@app.command()
def generate(
    config: Path = typer.Option(ROOT / "configs/prostate_scenario.yaml"),
    seed: int | None = None,
    cohort_size: int | None = None,
    input_dir: Path = typer.Option(ROOT / "data/raw/synthea"),
    output_dir: Path = typer.Option(ROOT / "data/gold"),
    scenario_version: str | None = None,
    log_level: str = "INFO",
) -> None:
    """Generate and export normalized synthetic tables."""
    cfg = _settings(config, seed, cohort_size, scenario_version, log_level)
    export_tables(generate_tables(cfg, input_dir), _mutable_output(output_dir, "working dataset"))


@app.command("build-gold")
def build_gold(
    config: Path = typer.Option(ROOT / "configs/prostate_scenario.yaml"),
    seed: int | None = None,
    cohort_size: int | None = None,
    input_dir: Path = typer.Option(ROOT / "data/raw/synthea"),
    output_dir: Path = typer.Option(ROOT / "data/gold"),
    scenario_version: str | None = None,
    log_level: str = "INFO",
) -> None:
    """Rebuild analytical gold outputs deterministically."""
    generate(config, seed, cohort_size, input_dir, output_dir, scenario_version, log_level)


@app.command()
def validate(output_dir: Path = typer.Option(ROOT / "data/gold"), log_level: str = "INFO") -> None:
    """Validate existing outputs and fail on critical errors."""
    configure_logging(log_level)
    results = validate_tables(load_exported_tables(output_dir))
    write_quality_report(results, ROOT / "data/reports")
    raise_on_critical(results)


@app.command("load-duckdb")
def load_db(output_dir: Path = typer.Option(ROOT / "data/gold")) -> None:
    """Load Parquet exports into DuckDB."""
    load_duckdb(_mutable_output(output_dir, "DuckDB output"))


@app.command()
def report(
    dataset_dir: Path | None = typer.Option(
        None, help="Certified analytical dataset; defaults to the newest certified release."
    ),
    allow_working_gold: bool = typer.Option(
        False, help="Explicitly permit non-release data/gold for exploratory development."
    ),
) -> None:
    """Generate cohort reports from one resolved analytical source."""
    source = resolve_analytical_dataset(
        ROOT,
        TABLES,
        dataset_dir,
        allow_gold_fallback=allow_working_gold,
        require_certified=not allow_working_gold,
    )
    tables = load_exported_tables(source.analytical_dir)
    write_cohort_report(tables, ROOT / "data/reports")
    write_healthcare_analysis_report(tables, ROOT / "data/reports")


@app.command()
def dashboard(
    dataset_dir: Path | None = typer.Option(
        None, help="Certified analytical dataset; defaults to the newest certified release."
    ),
    report_dir: Path = typer.Option(ROOT / "data/reports"),
    allow_working_gold: bool = typer.Option(
        False, help="Explicitly permit non-release data/gold for exploratory development."
    ),
) -> None:
    """Create the visual cohort dashboard from one resolved source."""
    source = resolve_analytical_dataset(
        ROOT,
        TABLES,
        dataset_dir,
        allow_gold_fallback=allow_working_gold,
        require_certified=not allow_working_gold,
    )
    provenance = {
        "dataset_version": source.dataset_version,
        "selection_method": source.selection_method,
        "source_git_commit": source.release_manifest.get("git", {}).get("git_commit"),
        "analysis_git_commit": source.release_manifest.get("git", {}).get("git_commit"),
    }
    write_dashboard(
        load_exported_tables(source.analytical_dir)["patient_journey"],
        _mutable_output(report_dir, "dashboard output"),
        provenance,
    )


@app.command("presentation-package")
def presentation_package_command(
    dataset_dir: Path | None = typer.Option(
        None,
        help="Explicit analytical dataset; defaults to the newest complete certified release.",
    ),
    output_root: Path = typer.Option(ROOT / "outputs/presentation"),
    scientific_dir: Path | None = typer.Option(
        None, help="Optional sealed scientific evidence directory."
    ),
    simulation_dir: Path | None = typer.Option(
        None, help="Optional sealed multi-seed simulation directory."
    ),
    predictive_dir: Path | None = typer.Option(
        None, help="Optional sealed predictive research evidence directory."
    ),
) -> None:
    """Build a provenance-locked, aggregate-only stakeholder package."""
    configure_logging()
    safe_output_root = _mutable_output(output_root, "presentation output")
    with logged_operation("presentation_package"):
        output_dir = build_presentation_package(
            ROOT,
            dataset_dir,
            safe_output_root,
            scientific_dir,
            simulation_dir,
            predictive_dir,
        )
    typer.echo(f"Presentation package ready: {output_dir}")


@app.command("application-check")
def application_check_command(
    config: Path | None = typer.Option(None, help="Optional application configuration YAML."),
    presentation_dir: Path | None = typer.Option(
        None, help="Explicit package inside the governed presentation namespace."
    ),
) -> None:
    """Verify release and aggregate presentation readiness without starting a server."""
    settings = load_application_settings(
        ROOT,
        config_path=config,
        overrides={"presentation_dir": presentation_dir},
    )
    configure_logging(settings.log_level, settings.log_format)
    from .release_integrity import resolve_application_artifacts

    with logged_operation("application_check"):
        artifacts = resolve_application_artifacts(settings)
    typer.echo(
        json.dumps(
            {
                "status": "ready",
                "release_id": artifacts.release.dataset_version,
                "entrypoint": settings.presentation_entrypoint,
                "warnings": [*artifacts.release.warnings, *artifacts.presentation.warnings],
                "openai_required": False,
                "synthetic_data_only": True,
            },
            indent=2,
        )
    )


@app.command("serve")
def serve_command(
    config: Path | None = typer.Option(None, help="Optional application configuration YAML."),
    host: str | None = typer.Option(None, help="Bind host; environment default is recommended."),
    port: int | None = typer.Option(None, min=0, max=65535),
    presentation_dir: Path | None = typer.Option(
        None, help="Explicit package inside the governed presentation namespace."
    ),
) -> None:
    """Serve one verified aggregate presentation with health and readiness endpoints."""
    settings = load_application_settings(
        ROOT,
        config_path=config,
        overrides={"host": host, "port": port, "presentation_dir": presentation_dir},
    )
    configure_logging(settings.log_level, settings.log_format)
    serve_application(settings)


@app.command("ai-catalogue")
def ai_catalogue_command(
    config: Path | None = typer.Option(None, help="Optional AI Studio configuration YAML."),
) -> None:
    """Build the release-isolated, aggregate-only AI evidence catalogue."""
    from .ai_artifact_catalog import build_artifact_catalogue
    from .ai_studio_config import load_ai_studio_settings

    settings = load_ai_studio_settings(ROOT, config_path=config)
    catalogue = build_artifact_catalogue(ROOT, settings)
    typer.echo(
        json.dumps(
            {
                "status": "verified",
                "release_id": catalogue.release_id,
                "artifacts": len(catalogue.artifacts),
                "indexable_artifacts": sum(item.indexable for item in catalogue.artifacts),
                "patient_level_data_included": False,
                "catalogue_path": str(settings.catalogue_path),
            },
            indent=2,
        )
    )


@app.command("ai-sync-vector-store")
def ai_sync_vector_store_command(
    config: Path | None = typer.Option(None, help="Optional AI Studio configuration YAML."),
) -> None:
    """Upload only allow-listed release evidence to a short-lived File Search store."""
    from .ai_artifact_catalog import build_artifact_catalogue
    from .ai_openai import VectorStoreSynchronizer
    from .ai_studio_config import load_ai_studio_settings

    settings = load_ai_studio_settings(ROOT, config_path=config)
    catalogue = build_artifact_catalogue(ROOT, settings)
    state = VectorStoreSynchronizer(settings, catalogue).synchronize()
    typer.echo(
        json.dumps(
            {
                "status": "synchronized",
                "release_id": state["release_id"],
                "vector_store_id": state["vector_store_id"],
                "indexable_artifact_count": state["indexable_artifact_count"],
                "expires_after_days": state["expires_after_days"],
                "patient_level_data_included": False,
            },
            indent=2,
        )
    )


@app.command("ai-check")
def ai_check_command(
    config: Path | None = typer.Option(None, help="Optional AI Studio configuration YAML."),
) -> None:
    """Verify the local AI boundary without making an OpenAI request."""
    from .ai_artifact_catalog import build_artifact_catalogue, verify_artifact_catalogue
    from .ai_evidence_tools import EvidenceTools
    from .ai_openai import OpenAIEvidenceGateway
    from .ai_studio_config import load_ai_studio_settings

    settings = load_ai_studio_settings(ROOT, config_path=config)
    catalogue = build_artifact_catalogue(ROOT, settings)
    verify_artifact_catalogue(catalogue, ROOT, expected_release_id=catalogue.release_id)
    tools = EvidenceTools(ROOT, catalogue)
    metric = tools.get_certified_metric("initiated_90d")
    gateway = OpenAIEvidenceGateway(settings, catalogue)
    typer.echo(
        json.dumps(
            {
                "status": "ready",
                "release_id": catalogue.release_id,
                "catalogued_artifacts": len(catalogue.artifacts),
                "tactics": len(tools.tactics),
                "deterministic_smoke_metric": {
                    "metric_id": metric.metric_id,
                    "numerator": metric.numerator,
                    "denominator": metric.denominator,
                },
                "openai_configured": gateway.configured,
                "vector_search_configured": bool(gateway._vector_store_id()),
                "analytics_dependency": False,
                "patient_level_data_included": False,
            },
            indent=2,
        )
    )


@app.command("ai-studio")
def ai_studio_command(
    config: Path | None = typer.Option(None, help="Optional AI Studio configuration YAML."),
    host: str | None = typer.Option(None, help="Bind host; local loopback is recommended."),
    port: int | None = typer.Option(None, min=0, max=65535),
) -> None:
    """Serve the optional release-grounded AI Analysis Studio on its own port."""
    from .ai_studio import serve_ai_studio
    from .ai_studio_config import load_ai_studio_settings

    settings = load_ai_studio_settings(
        ROOT,
        config_path=config,
        overrides={"host": host, "port": port},
    )
    configure_logging("INFO", "json")
    serve_ai_studio(settings)


@app.command("ai-demo-package")
def ai_demo_package_command(
    config: Path | None = typer.Option(None, help="Optional AI Studio configuration YAML."),
    output_dir: Path | None = typer.Option(
        None, help="Target inside outputs/experiments; defaults to a release-scoped directory."
    ),
    confirm_run: bool = typer.Option(
        False,
        "--confirm-run",
        help="Explicitly execute the validated deterministic re-run used in demo step 6.",
    ),
) -> None:
    """Build the ten-frame, zero-API-cost static AI Studio demo fallback."""
    from .ai_demo import build_ai_demo_package
    from .ai_studio_config import load_ai_studio_settings

    settings = load_ai_studio_settings(ROOT, config_path=config)
    result = build_ai_demo_package(
        ROOT,
        settings,
        output_dir=output_dir,
        confirm_run=confirm_run,
    )
    typer.echo(json.dumps(result, indent=2))


@app.command("ai-specialist-check")
def ai_specialist_check_command(
    config: Path | None = typer.Option(None, help="Optional AI Studio configuration YAML."),
) -> None:
    """Validate specialist contracts, tools, lenses, and one non-executing preview."""
    from .ai_artifact_catalog import build_artifact_catalogue
    from .ai_evidence_tools import EvidenceTools
    from .ai_finops import load_cost_controls
    from .ai_studio_config import load_ai_studio_settings
    from .specialist_contracts import ExpertLens
    from .specialist_orchestrator import SpecialistOrchestrator
    from .specialist_tools import SpecialistAnalysisTools

    settings = load_ai_studio_settings(ROOT, config_path=config)
    catalogue = build_artifact_catalogue(ROOT, settings)
    evidence = EvidenceTools(ROOT, catalogue)
    tools = SpecialistAnalysisTools(settings, evidence)
    orchestrator = SpecialistOrchestrator(settings, tools)
    controls = load_cost_controls(settings.cost_controls_path)
    preview = orchestrator.prepare_preview(
        "Re-run initiation at 60 days for US with an explicit denominator.",
        selected_lens=ExpertLens.RWE_EPIDEMIOLOGY,
        tactic_id="initiation_landmarks",
        parameters={},
        remaining_budget_usd=float(controls.budgets.interactive_session.hard_stop_usd),
        specialist_mode=True,
        use_model_router=False,
    )
    typer.echo(
        json.dumps(
            {
                "status": "ready" if preview.validation.valid else "invalid",
                "release_id": catalogue.release_id,
                "tactics": len(tools.list_tactics()),
                "expert_lenses": len(orchestrator.lenses),
                "server_tools": len(tools.tool_contracts()),
                "preview_denominator": preview.population_preview.current_denominator,
                "confirmation_required": bool(preview.confirmation_token),
                "run_created": False,
                "patient_level_data_included": False,
            },
            indent=2,
        )
    )


@app.command("ai-offline-eval")
def ai_offline_eval_command(
    config: Path | None = typer.Option(None, help="Optional AI Studio configuration YAML."),
) -> None:
    """Run the deterministic/mocked AI quality and injection suite with no API calls."""
    from .ai_evaluation import run_offline_evaluation
    from .ai_studio_config import load_ai_studio_settings

    settings = load_ai_studio_settings(ROOT, config_path=config)
    report = run_offline_evaluation(settings)
    typer.echo(
        json.dumps(
            {
                "status": report["status"],
                "run_id": report["run_id"],
                "cases": len(report["cases"]),
                "provider_requests": 0,
                "actual_metered_usd": 0.0,
                "report_paths": report["report_paths"],
            },
            indent=2,
        )
    )
    if report["status"] != "PASS":
        raise typer.Exit(1)


@app.command("ai-live-eval")
def ai_live_eval_command(
    config: Path | None = typer.Option(None, help="Optional AI Studio configuration YAML."),
) -> None:
    """Run the fixed live suite under the immutable application hard stop below $2."""
    from .ai_evaluation import run_live_evaluation
    from .ai_studio_config import load_ai_studio_settings

    settings = load_ai_studio_settings(ROOT, config_path=config)
    report = run_live_evaluation(settings)
    typer.echo(
        json.dumps(
            {
                "status": report["status"],
                "run_id": report["run_id"],
                "completed_counts": report["completed_counts"],
                "actual_metered_usd": report["cost"]["actual_metered_usd"],
                "ledger_charged_usd": report["cost"]["ledger_charged_usd"],
                "below_hard_stop": report["cost"]["below_hard_stop"],
                "abort_reason": report["abort_reason"],
                "report_paths": report["report_paths"],
            },
            indent=2,
        )
    )
    if report["status"] != "PASS":
        raise typer.Exit(1)


@app.command("scientific-evidence")
def scientific_evidence_command(
    dataset_dir: Path | None = typer.Option(
        None,
        help="Analytical dataset; defaults to the newest accepted candidate release.",
    ),
    config: Path | None = typer.Option(
        None,
        help="Scenario YAML. Accepted releases default to their locked config snapshot.",
    ),
    output_root: Path = typer.Option(ROOT / "outputs/scientific"),
    input_dir: Path = typer.Option(ROOT / "data/raw/synthea"),
    allow_working_dataset: bool = typer.Option(
        False,
        help="Explicitly allow non-release data/gold or another development dataset.",
    ),
) -> None:
    """Build sealed survival, missingness, uncertainty, and utility evidence."""
    source = resolve_analytical_dataset(
        ROOT,
        TABLES,
        dataset_dir,
        allow_gold_fallback=allow_working_dataset,
        require_certified=not allow_working_dataset,
    )
    release_snapshot = (
        source.release_dir / "qa_evidence/reports/config_snapshot.yaml"
        if source.release_dir
        else None
    )
    if config is not None:
        cfg = load_config(config)
    elif release_snapshot is not None and release_snapshot.is_file():
        cfg = yaml.safe_load(release_snapshot.read_text(encoding="utf-8"))
    else:
        cfg = load_config(ROOT / "configs/prostate_scenario.yaml")
    output = _mutable_output(output_root / source.dataset_version, "scientific evidence output")
    result = build_scientific_evidence_package(
        project_root=ROOT,
        tables=load_exported_tables(source.analytical_dir),
        config=cfg,
        output_dir=output,
        release=source.dataset_version,
        analysis_registry_path=ROOT / "contracts/analysis_registry.yaml",
        event_hierarchy_path=ROOT / "configs/event_hierarchy.yaml",
        simulation_spec_path=ROOT / "configs/simulation_scenarios.yaml",
        real_hook_spec_path=ROOT / "contracts/real_data_evaluation_hooks.yaml",
        input_dir=input_dir,
    )
    typer.echo(f"Scientific evidence ready: {result}")


@app.command("simulation-study")
def simulation_study_command(
    specification: Path = typer.Option(ROOT / "configs/simulation_scenarios.yaml"),
    output_dir: Path | None = typer.Option(
        None,
        help="Fresh immutable output directory; defaults to a timestamped study directory.",
    ),
    input_dir: Path = typer.Option(ROOT / "data/raw/synthea"),
    release: str | None = typer.Option(
        None,
        help="Accepted release ID represented by the study; omit for an unbound development run.",
    ),
) -> None:
    """Run the sealed low/base/high multi-seed synthetic simulation study."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = _mutable_output(
        output_dir or ROOT / "outputs/simulations" / f"study-{timestamp}",
        "simulation output",
    )
    result = run_multi_seed_study(
        ROOT,
        specification,
        destination,
        input_dir=input_dir,
        release=release,
    )
    typer.echo(f"Simulation study ready: {result}")


@app.command("predictive-evidence")
def predictive_evidence_command(
    dataset_dir: Path | None = typer.Option(
        None,
        help="Certified analytical dataset; defaults to the newest accepted candidate release.",
    ),
    eda_dir: Path = typer.Option(
        ROOT / "outputs/eda",
        help="Release-matched cohort and longitudinal EDA artifacts.",
    ),
    output_root: Path = typer.Option(ROOT / "outputs/predictive"),
) -> None:
    """Build sealed temporal, market, calibration, subgroup, and disposition evidence."""
    source = resolve_analytical_dataset(ROOT, TABLES, dataset_dir, require_certified=True)
    input_hashes = verify_predictive_eda_inputs(eda_dir, source)
    release_commit = source.release_manifest.get("git", {}).get("git_commit")
    if not release_commit:
        raise ValueError("Selected release does not record a source commit")
    result = build_predictive_evidence_package(
        project_root=ROOT,
        tables=load_exported_tables(source.analytical_dir),
        flags=pd.read_parquet(eda_dir / "cohort_patient_flags.parquet"),
        persistence=pd.read_parquet(eda_dir / "persistence_event_data.parquet"),
        output_dir=_mutable_output(
            output_root / source.dataset_version, "predictive evidence output"
        ),
        release=source.dataset_version,
        release_source_commit=str(release_commit),
        model_contract_path=ROOT / "contracts/model_target_contracts.yaml",
        evaluation_config_path=ROOT / "configs/model_evaluation.yaml",
        governance_path=ROOT / "contracts/model_governance.yaml",
        alias_config_path=ROOT / "configs/model_aliases.yaml",
        input_hashes=input_hashes,
    )
    typer.echo(f"Predictive evidence ready: {result}")


@app.command("industry-check")
def industry_check_command(
    dataset_dir: Path | None = typer.Option(None, help="Optional dataset to validate."),
    presentation_dir: Path | None = typer.Option(
        None, help="Optional stakeholder package to reconcile."
    ),
    eda_dir: Path | None = typer.Option(None, help="Optional EDA directory to reconcile."),
    scientific_dir: Path | None = typer.Option(
        None, help="Optional scientific evidence package to reconcile."
    ),
    simulation_dir: Path | None = typer.Option(
        None, help="Optional multi-seed simulation package to reconcile."
    ),
    predictive_dir: Path | None = typer.Option(
        None, help="Optional predictive research evidence package to reconcile."
    ),
    output: Path = typer.Option(ROOT / "outputs/industry_readiness/industry_check_report.json"),
    allow_missing_release: bool = typer.Option(
        False, help="Run source gates when release artifacts have not yet been built."
    ),
) -> None:
    """Run the executable synthetic Industry Readiness Baseline gates."""
    safe_output = _mutable_output(output, "industry check output")
    result = run_industry_checks(
        ROOT,
        dataset_dir=dataset_dir,
        presentation_dir=presentation_dir,
        eda_dir=eda_dir,
        scientific_dir=scientific_dir,
        simulation_dir=simulation_dir,
        predictive_dir=predictive_dir,
        output_path=safe_output,
        allow_missing_release=allow_missing_release,
    )
    typer.echo(
        f"Industry checks: {result['overall_status']} "
        f"({result['summary']['passed']} passed, {result['summary']['failed']} failed, "
        f"{result['summary']['skipped']} skipped) — {result['report_path']}"
    )
    if result["overall_status"] != "PASS":
        raise typer.Exit(code=1)


@app.command("run-all")
def run_all_command(
    config: Path = typer.Option(ROOT / "configs/prostate_scenario.yaml"),
    seed: int | None = None,
    cohort_size: int | None = None,
    input_dir: Path = typer.Option(ROOT / "data/raw/synthea"),
    output_dir: Path = typer.Option(ROOT / "data/gold"),
    report_dir: Path = typer.Option(ROOT / "data/reports"),
    scenario_version: str | None = None,
    log_level: str = "INFO",
) -> None:
    """Run all stages and enforce critical data-quality gates."""
    cfg = _settings(config, seed, cohort_size, scenario_version, log_level)
    safe_output = _mutable_output(output_dir, "working dataset")
    safe_reports = _mutable_output(report_dir, "working report")
    with logged_operation(
        "analytical_pipeline", release_id=str(cfg.get("scenario_version", "working"))
    ):
        execute_all(ROOT, cfg, input_dir, safe_output, safe_reports)


@app.command("final-release")
def final_release_command(
    config: Path = typer.Option(ROOT / "configs/prostate_scenario.yaml"),
    seed: int | None = None,
    cohort_size: int | None = None,
    input_dir: Path = typer.Option(ROOT / "data/raw/synthea"),
    release_parent: Path = typer.Option(ROOT / "data/releases"),
    release_name: str | None = None,
    scenario_version: str | None = None,
    git_executable: str = "git",
    log_level: str = "INFO",
) -> None:
    """Create a fresh candidate with separate analytical and QA evidence archives."""
    cfg = _settings(config, seed, cohort_size, scenario_version, log_level)
    if cfg.get("profile") != "full" or int(cfg["target_cohort_size"]) < 5000:
        raise typer.BadParameter(
            "The final candidate requires the full profile with at least 5,000 patients."
        )
    if not cfg["readiness"].get("verify_reproducibility_full", False):
        raise typer.BadParameter("The final candidate requires exact full-run reproducibility.")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dataset_version = release_name or (
        f"BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v{cfg['generator_version']}_{timestamp}"
    )
    release_dir = release_parent / dataset_version
    with logged_operation("release_certification", release_id=dataset_version):
        result = create_fresh_certified_release(
            project_root=ROOT,
            config=cfg,
            input_dir=input_dir,
            release_dir=release_dir,
            dataset_version=dataset_version,
            git_executable=git_executable,
        )
    typer.echo(f"CANDIDATE — INTERNAL SYNTHETIC CONTRACT PASSED: {result['release_directory']}")


if __name__ == "__main__":
    app()
