"""End-to-end deterministic multi-market synthetic generation."""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .active_surveillance_generator import generate_active_surveillance
from .adversarial_audit import raise_on_adversarial_failure, write_adversarial_audit
from .cohort_builder import build_patient_table
from .dashboard import write_dashboard
from .data_quality import raise_on_critical, validate_tables, write_quality_report
from .diagnosis_generator import generate_diagnoses, generate_initial_disease_states
from .duckdb_loader import load_duckdb
from .feature_engineering import build_feature_timing_metadata, build_patient_split
from .journey_builder import build_eligibility, build_patient_journey
from .observation_generator import generate_observation
from .outcome_generator import generate_outcome_model
from .pathway_generator import generate_pathway
from .provider_generator import assign_care_teams, generate_provider_network
from .readiness_audit import raise_on_readiness_failure, write_readiness_audit
from .reporting import write_cohort_report, write_run_metadata
from .synthea_loader import load_synthea_csv, make_multimarket_base
from .treatment_generator import generate_treatment_model

LOGGER = logging.getLogger(__name__)
TABLES = (
    "patient",
    "diagnosis",
    "disease_state_event",
    "eligibility",
    "organization",
    "provider",
    "encounter",
    "referral",
    "active_surveillance",
    "observation",
    "treatment_episode",
    "treatment_regimen",
    "treatment_regimen_component",
    "prescription_event",
    "adverse_event",
    "outcome",
    "patient_split",
    "feature_timing",
    "patient_journey",
)


def verify_exact_reproducibility(
    first: dict[str, pd.DataFrame], second: dict[str, pd.DataFrame]
) -> None:
    """Raise if two same-seed generations differ in any exported table."""
    if set(first) != set(second):
        raise ValueError("Reproducibility failure: table contracts differ")
    for table_name in TABLES:
        try:
            pd.testing.assert_frame_equal(
                first[table_name],
                second[table_name],
                check_dtype=True,
                check_exact=True,
                check_like=False,
            )
        except AssertionError as error:
            raise ValueError(f"Reproducibility failure in table {table_name}") from error


def generate_tables(config: dict[str, Any], input_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Generate every normalized domain and the derived mart with one RNG stream."""
    rng = np.random.default_rng(config["random_seed"])
    raw = load_synthea_csv(input_dir)
    base = make_multimarket_base(raw, config)
    patient = build_patient_table(base, config, rng)
    diagnosis = generate_diagnoses(patient, config, rng)
    disease_state = generate_initial_disease_states(diagnosis)
    observation = generate_observation(patient, diagnosis, config, rng)
    eligibility = build_eligibility(patient, diagnosis, observation, config, rng)
    organization, provider = generate_provider_network(patient, config, rng)
    care_team = assign_care_teams(patient, provider, config, rng)
    encounter, referral = generate_pathway(
        patient,
        diagnosis,
        eligibility,
        care_team,
        provider,
        observation,
        config,
        rng,
    )
    active_surveillance, surveillance_encounter = generate_active_surveillance(
        patient,
        diagnosis,
        care_team,
        provider,
        observation,
        config,
        rng,
    )
    encounter = pd.concat([encounter, surveillance_encounter], ignore_index=True)
    (
        treatment_episode,
        treatment_regimen,
        regimen_component,
        prescription_event,
        treatment_referral,
    ) = generate_treatment_model(
        patient,
        eligibility,
        referral,
        active_surveillance,
        care_team,
        observation,
        config,
        rng,
    )
    referral = pd.concat([referral, treatment_referral], ignore_index=True)
    outcome, adverse_event, followup_state = generate_outcome_model(
        patient,
        diagnosis,
        eligibility,
        observation,
        treatment_episode,
        regimen_component,
        config,
        rng,
    )
    disease_state = pd.concat([disease_state, followup_state], ignore_index=True)
    patient["date_of_death"] = patient.patient_id.map(
        observation.set_index("patient_id").death_date
    )
    patient_split = build_patient_split(patient, config)
    patient_journey = build_patient_journey(
        patient,
        diagnosis,
        eligibility,
        encounter,
        referral,
        active_surveillance,
        treatment_episode,
        treatment_regimen,
        regimen_component,
        prescription_event,
        observation,
        outcome,
        config,
    )
    feature_timing = build_feature_timing_metadata(patient_journey.columns)
    return {
        "patient": patient,
        "diagnosis": diagnosis,
        "disease_state_event": disease_state,
        "eligibility": eligibility,
        "organization": organization,
        "provider": provider,
        "encounter": encounter,
        "referral": referral,
        "active_surveillance": active_surveillance,
        "observation": observation,
        "treatment_episode": treatment_episode,
        "treatment_regimen": treatment_regimen,
        "treatment_regimen_component": regimen_component,
        "prescription_event": prescription_event,
        "adverse_event": adverse_event,
        "outcome": outcome,
        "patient_split": patient_split,
        "feature_timing": feature_timing,
        "patient_journey": patient_journey,
    }


def export_tables(tables: dict[str, pd.DataFrame], gold_dir: str | Path) -> None:
    """Write all normalized and analytical tables to CSV and Parquet."""
    root = Path(gold_dir)
    root.mkdir(parents=True, exist_ok=True)
    for legacy_name in ("treatment.csv", "treatment.parquet"):
        (root / legacy_name).unlink(missing_ok=True)
    for name, frame in tables.items():
        frame.to_csv(root / f"{name}.csv", index=False, date_format="%Y-%m-%d")
        frame.to_parquet(root / f"{name}.parquet", index=False)
        LOGGER.info("Exported %-28s %d rows", name, len(frame))


def load_exported_tables(gold_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Reload the complete Parquet contract for independent pipeline stages."""
    root = Path(gold_dir)
    return {name: pd.read_parquet(root / f"{name}.parquet") for name in TABLES}


def run_all(
    project_root: Path,
    config: dict,
    input_dir: Path,
    output_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Generate, audit, export, load DuckDB and report; fail on actual P0/P1 issues."""
    gold = output_dir or project_root / "data" / "gold"
    reports = project_root / "data" / "reports"
    runtime_config = deepcopy(config)
    tables = generate_tables(runtime_config, input_dir)
    verify_full = bool(
        runtime_config["readiness"].get("verify_reproducibility_full", False)
        and runtime_config["target_cohort_size"] >= 5000
    )
    if verify_full:
        LOGGER.info("Verifying exact same-seed reproducibility across all tables")
        repeated_tables = generate_tables(runtime_config, input_dir)
        verify_exact_reproducibility(tables, repeated_tables)
        runtime_config["readiness"]["runtime_reproducibility_verified"] = True
        del repeated_tables
    else:
        runtime_config["readiness"]["runtime_reproducibility_verified"] = None
    dq_results = validate_tables(tables)
    write_quality_report(dq_results, reports)
    raise_on_critical(dq_results)
    readiness = write_readiness_audit(tables, dq_results, runtime_config, reports)
    adversarial = write_adversarial_audit(tables, runtime_config, reports)
    if runtime_config["readiness"].get("fail_on_p0_p1", True):
        raise_on_readiness_failure(readiness)
        raise_on_adversarial_failure(adversarial)
    export_tables(tables, gold)
    load_duckdb(gold)
    write_cohort_report(tables, reports)
    write_dashboard(tables["patient_journey"], reports)
    (reports / "config_snapshot.yaml").write_text(
        yaml.safe_dump(runtime_config, sort_keys=True), encoding="utf-8"
    )
    write_run_metadata(project_root, runtime_config, len(tables["patient"]), gold, reports)
    return tables
