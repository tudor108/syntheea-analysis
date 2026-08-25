"""Command-line interface for pipeline stages."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from .config import load_config
from .dashboard import write_dashboard
from .data_quality import raise_on_critical, validate_tables, write_quality_report
from .duckdb_loader import load_duckdb
from .logging_config import configure_logging
from .pipeline import export_tables, generate_tables, load_exported_tables
from .pipeline import run_all as execute_all
from .release_runner import create_fresh_certified_release
from .reporting import write_cohort_report

app = typer.Typer(no_args_is_help=True, help="Synthetic prostate journey demo pipeline")
ROOT = Path(__file__).resolve().parents[2]


def _settings(
    config: Path,
    seed: int | None,
    cohort_size: int | None,
    scenario_version: str | None,
    log_level: str,
):
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
    export_tables(generate_tables(cfg, input_dir), output_dir)


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
    load_duckdb(output_dir)


@app.command()
def report(output_dir: Path = typer.Option(ROOT / "data/gold")) -> None:
    """Generate cohort summary and KPI reports."""
    write_cohort_report(load_exported_tables(output_dir), ROOT / "data/reports")


@app.command()
def dashboard(
    output_dir: Path = typer.Option(ROOT / "data/gold"),
    report_dir: Path = typer.Option(ROOT / "data/reports"),
) -> None:
    """Create the visual cohort dashboard HTML."""
    write_dashboard(load_exported_tables(output_dir)["patient_journey"], report_dir)


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
    execute_all(ROOT, cfg, input_dir, output_dir, report_dir)


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
    """Create a fresh, strict 100/100 release with separate analytical and QA archives."""
    cfg = _settings(config, seed, cohort_size, scenario_version, log_level)
    if cfg.get("profile") != "full" or int(cfg["target_cohort_size"]) < 5000:
        raise typer.BadParameter(
            "Final certification requires the full profile with at least 5,000 patients."
        )
    if not cfg["readiness"].get("verify_reproducibility_full", False):
        raise typer.BadParameter("Final certification requires exact full-run reproducibility.")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dataset_version = release_name or (
        f"BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v{cfg['generator_version']}_{timestamp}"
    )
    release_dir = release_parent / dataset_version
    result = create_fresh_certified_release(
        project_root=ROOT,
        config=cfg,
        input_dir=input_dir,
        release_dir=release_dir,
        dataset_version=dataset_version,
        git_executable=git_executable,
    )
    typer.echo(f"CERTIFIED — READY FOR BAYER ANALYSIS: {result['release_directory']}")


if __name__ == "__main__":
    app()
