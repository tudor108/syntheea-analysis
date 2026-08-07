"""End-to-end orchestration for deterministic synthetic generation."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .cohort_builder import build_patient_table
from .dashboard import write_dashboard
from .data_quality import raise_on_critical, validate_tables, write_quality_report
from .diagnosis_generator import generate_diagnoses
from .duckdb_loader import load_duckdb
from .journey_builder import build_eligibility, build_patient_journey, generate_encounters
from .outcome_generator import generate_outcomes
from .provider_generator import assign_initial_providers, generate_providers
from .reporting import write_cohort_report, write_run_metadata
from .synthea_loader import load_synthea_csv, select_base_patients
from .treatment_generator import generate_treatments

LOGGER = logging.getLogger(__name__)
TABLES = ("patient", "diagnosis", "provider", "encounter", "treatment", "outcome", "patient_journey")


def generate_tables(config: dict[str, Any], input_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Generate every normalized and gold table with one RNG stream."""
    rng = np.random.default_rng(config["random_seed"])
    raw = load_synthea_csv(input_dir)
    base = select_base_patients(raw, config["target_cohort_size"], config["random_seed"], config["minimum_age"], config["maximum_age"])
    patient = build_patient_table(base, config, rng)
    provider = generate_providers(patient, config, rng)
    assigned = assign_initial_providers(patient, provider, config, rng)
    diagnosis = generate_diagnoses(patient, config, rng)
    eligibility = build_eligibility(patient, diagnosis, config, rng)
    encounter = generate_encounters(patient, diagnosis, eligibility, assigned, config, rng)
    treatment = generate_treatments(patient, eligibility, encounter, assigned, config, rng)
    outcome = generate_outcomes(patient, eligibility, treatment, config, rng)
    patient["date_of_death"] = patient.patient_id.map(outcome.set_index("patient_id").death_date)
    journey = build_patient_journey(patient, diagnosis, assigned, eligibility, encounter, treatment, outcome, config)
    return {"patient": patient, "diagnosis": diagnosis.drop(columns="hormone_sensitive_confirmation_date"), "provider": provider, "encounter": encounter, "treatment": treatment, "outcome": outcome, "patient_journey": journey}


def export_tables(tables: dict[str, pd.DataFrame], gold_dir: str | Path) -> None:
    """Write all tables to CSV and Parquet."""
    root = Path(gold_dir); root.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_csv(root / f"{name}.csv", index=False, date_format="%Y-%m-%d")
        frame.to_parquet(root / f"{name}.parquet", index=False)
        LOGGER.info("Exported %-16s %d rows", name, len(frame))


def load_exported_tables(gold_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Reload Parquet outputs for independent CLI stages."""
    root = Path(gold_dir)
    return {name: pd.read_parquet(root / f"{name}.parquet") for name in TABLES}


def run_all(project_root: Path, config: dict, input_dir: Path, output_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    """Generate, export, validate, load DuckDB, report and record metadata."""
    gold = output_dir or project_root / "data" / "gold"
    reports = project_root / "data" / "reports"
    tables = generate_tables(config, input_dir)
    export_tables(tables, gold)
    results = validate_tables(tables); write_quality_report(results, reports); raise_on_critical(results)
    load_duckdb(gold); write_cohort_report(tables, reports); write_dashboard(tables["patient_journey"], reports)
    (reports / "config_snapshot.yaml").write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
    write_run_metadata(project_root, config, len(tables["patient"]), gold, reports)
    return tables
