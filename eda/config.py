"""Configuration and explicit data contracts for the healthcare EDA foundation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from prostate_journey import __version__
from prostate_journey.dataset_resolver import resolve_analytical_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "eda"
FIGURES_DIR = OUTPUT_DIR / "figures"
RAW_SYNTHEA_DIR = PROJECT_ROOT / "data" / "raw" / "synthea"

DEEP_MARKETS = ("US", "DE", "JP")
SCAN_MARKETS = ("FR", "CN", "AU", "CA")
REQUIRED_MARKETS = DEEP_MARKETS + SCAN_MARKETS
ANALYSIS_DISCLAIMER = (
    "Synthetic demonstrational data only; not clinical guidance, diagnosis, causal evidence, "
    "real Bayer data, or a real-world market-size estimate."
)

DATA_EXTENSIONS = {
    ".csv",
    ".parquet",
    ".xlsx",
    ".xls",
    ".json",
    ".duckdb",
    ".db",
    ".sqlite",
    ".sqlite3",
}
EXCLUDED_SCAN_PARTS = {
    ".git",
    ".venv",
    ".release-venv",
    ".uv-cache",
    ".test-work",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "outputs",
}


@dataclass(frozen=True)
class TableContract:
    grain: str
    primary_key: str
    foreign_keys: tuple[tuple[str, str, str], ...] = ()
    patient_id: str | None = "patient_id"
    event_date: str | None = None


TABLE_CONTRACTS: dict[str, TableContract] = {
    "patient": TableContract(
        "one row per synthetic patient/archetype",
        "patient_id",
        patient_id="patient_id",
        event_date="index_date",
    ),
    "diagnosis": TableContract(
        "one index prostate diagnosis per patient",
        "diagnosis_id",
        (("patient_id", "patient", "patient_id"),),
        event_date="diagnosis_date",
    ),
    "disease_state_event": TableContract(
        "one dated disease-state event",
        "disease_state_event_id",
        (("patient_id", "patient", "patient_id"),),
        event_date="state_date",
    ),
    "eligibility": TableContract(
        "one versioned eligibility assessment per patient",
        "eligibility_id",
        (("patient_id", "patient", "patient_id"),),
        event_date="eligibility_date",
    ),
    "organization": TableContract("one synthetic organization", "organization_id", patient_id=None),
    "provider": TableContract(
        "one stable provider-master row",
        "provider_id",
        (("organization_id", "organization", "organization_id"),),
        patient_id=None,
    ),
    "encounter": TableContract(
        "one dated patient-provider encounter",
        "encounter_id",
        (
            ("patient_id", "patient", "patient_id"),
            ("provider_id", "provider", "provider_id"),
            ("organization_id", "organization", "organization_id"),
        ),
        event_date="encounter_date",
    ),
    "referral": TableContract(
        "one provider-to-provider referral",
        "referral_id",
        (
            ("patient_id", "patient", "patient_id"),
            ("source_provider_id", "provider", "provider_id"),
            ("destination_provider_id", "provider", "provider_id"),
            ("source_organization_id", "organization", "organization_id"),
            ("destination_organization_id", "organization", "organization_id"),
        ),
        event_date="referral_date",
    ),
    "active_surveillance": TableContract(
        "one active-surveillance assessment/pathway record",
        "active_surveillance_id",
        (("patient_id", "patient", "patient_id"),),
        event_date="as_start_date",
    ),
    "observation": TableContract(
        "one observation/censoring record per patient",
        "observation_id",
        (("patient_id", "patient", "patient_id"),),
        event_date="observation_start_date",
    ),
    "treatment_episode": TableContract(
        "one longitudinal treatment line/episode",
        "treatment_episode_id",
        (
            ("patient_id", "patient", "patient_id"),
            ("prescribing_provider_id", "provider", "provider_id"),
            ("previous_episode_id", "treatment_episode", "treatment_episode_id"),
        ),
        event_date="treatment_start_date",
    ),
    "treatment_regimen": TableContract(
        "one regimen attached to a treatment episode",
        "regimen_id",
        (
            ("patient_id", "patient", "patient_id"),
            ("treatment_episode_id", "treatment_episode", "treatment_episode_id"),
        ),
        event_date="regimen_start_date",
    ),
    "treatment_regimen_component": TableContract(
        "one drug/procedure component within a regimen",
        "component_id",
        (
            ("patient_id", "patient", "patient_id"),
            ("treatment_episode_id", "treatment_episode", "treatment_episode_id"),
            ("regimen_id", "treatment_regimen", "regimen_id"),
        ),
        event_date="component_start_date",
    ),
    "prescription_event": TableContract(
        "one dispensing/refill event",
        "prescription_event_id",
        (
            ("patient_id", "patient", "patient_id"),
            ("treatment_episode_id", "treatment_episode", "treatment_episode_id"),
            ("regimen_id", "treatment_regimen", "regimen_id"),
            ("component_id", "treatment_regimen_component", "component_id"),
        ),
        event_date="service_date",
    ),
    "adverse_event": TableContract(
        "one dated adverse event",
        "adverse_event_id",
        (
            ("patient_id", "patient", "patient_id"),
            ("treatment_episode_id", "treatment_episode", "treatment_episode_id"),
        ),
        event_date="adverse_event_date",
    ),
    "outcome": TableContract(
        "one derived outcome/censoring record per patient",
        "outcome_id",
        (("patient_id", "patient", "patient_id"),),
        event_date="last_observed_date",
    ),
    "patient_split": TableContract(
        "one reproducible analytical split per patient",
        "patient_split_id",
        (("patient_id", "patient", "patient_id"),),
        event_date=None,
    ),
    "feature_timing": TableContract(
        "one timing/governance record per mart field", "feature_metadata_id", patient_id=None
    ),
    "patient_journey": TableContract(
        "one analysis-ready row per patient",
        "patient_id",
        (("patient_id", "patient", "patient_id"),),
        event_date="eligibility_date",
    ),
}

RAW_GRAINS = {
    "patients": ("one raw Synthea patient", "Id"),
    "encounters": ("one raw Synthea encounter", "Id"),
    "conditions": ("one raw condition occurrence", None),
    "medications": ("one raw medication order/dispensing span", None),
    "observations": ("one raw clinical observation", None),
    "procedures": ("one raw procedure occurrence", None),
    "careplans": ("one raw care plan", "Id"),
    "claims": ("one raw claim", "Id"),
    "claims_transactions": ("one raw claim transaction", None),
    "devices": ("one raw device occurrence", None),
    "imaging_studies": ("one raw imaging study", "Id"),
    "immunizations": ("one raw immunization occurrence", None),
    "payer_transitions": ("one raw payer-enrollment span", None),
    "providers": ("one raw provider", "Id"),
    "organizations": ("one raw organization", "Id"),
    "payers": ("one raw payer", "Id"),
    "supplies": ("one raw supply occurrence", None),
    "allergies": ("one raw allergy occurrence", None),
}

DATE_ORDER_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "patient": (("birth_date", "index_date"),),
    "referral": (("referral_date", "completion_date"),),
    "active_surveillance": (
        ("as_start_date", "as_exit_date"),
        ("as_exit_date", "planned_treatment_start_date"),
    ),
    "observation": (
        ("observation_start_date", "last_observed_date"),
        ("last_observed_date", "observation_end_date"),
    ),
    "treatment_episode": (
        ("treatment_start_date", "treatment_end_date"),
        ("treatment_start_date", "discontinuation_date"),
        ("treatment_start_date", "switch_date"),
        ("treatment_start_date", "restart_date"),
    ),
    "treatment_regimen": (("regimen_start_date", "regimen_end_date"),),
    "treatment_regimen_component": (("component_start_date", "component_end_date"),),
    "prescription_event": (
        ("service_date", "covered_until_date"),
        ("service_date", "nominal_covered_until_date"),
    ),
}

EXPECTED_CATEGORIES: dict[tuple[str, str], set[str]] = {
    ("patient", "market_code"): set(REQUIRED_MARKETS),
    ("patient", "market_depth"): {"deep", "scan"},
    ("patient", "sex"): {"male"},
    ("diagnosis", "prostate_stage"): {"localized", "locally_advanced", "metastatic", "unknown"},
    ("disease_state_event", "state"): {
        "localized",
        "locally_advanced",
        "mHSPC",
        "mCRPC",
        "metastatic_other",
        "unknown",
    },
    ("provider", "provider_specialty"): {
        "urology",
        "medical_oncology",
        "radiation_oncology",
        "primary_care",
    },
    ("provider", "care_setting"): {
        "academic_oncology",
        "community_oncology",
        "community_urology",
        "mixed_pathway",
    },
    ("encounter", "provider_specialty"): {
        "urology",
        "medical_oncology",
        "radiation_oncology",
        "primary_care",
    },
    ("encounter", "care_setting"): {
        "academic_oncology",
        "community_oncology",
        "community_urology",
        "mixed_pathway",
    },
    ("referral", "referral_status"): {
        "completed",
        "pending",
        "rejected",
        "cancelled",
        "not_completed",
    },
    ("treatment_episode", "transition_type"): {"initial", "switch", "restart"},
    ("patient_journey", "persistence_12m_status"): {
        "PERSISTENT",
        "DISCONTINUED",
        "SWITCHED",
        "CENSORED_NOT_EVALUABLE",
        "NOT_APPLICABLE",
    },
    ("patient_journey", "initiation_90d_status"): {
        "INITIATED_WITHIN_90D",
        "NOT_INITIATED_WITHIN_90D",
        "CENSORED_NOT_EVALUABLE",
        "NOT_ELIGIBLE",
    },
}

IMPORTANT_MISSINGNESS_FIELDS = (
    "race",
    "ethnicity",
    "insurance_type",
    "psa_value",
    "gleason_score",
    "isup_grade_group",
    "referral_delay_days",
    "decision_owner_specialty",
    "initial_regimen",
    "event_coverage_until_date",
    "progression_date",
)

OUTCOME_OR_FUTURE_TOKENS = {
    "outcome",
    "progression",
    "death",
    "hospitalisation",
    "persistence",
    "persistent",
    "discontinuation",
    "switch",
    "restart",
    "censor",
    "follow_up",
    "last_observed",
}


def resolve_analytical_data_dir() -> tuple[Path, dict[str, object]]:
    """Resolve only a certified release unless working gold is explicitly allowed."""
    override = os.environ.get("EDA_DATASET_DIR")
    allow_working_gold = os.environ.get("EDA_ALLOW_WORKING_GOLD") == "1"
    selected = resolve_analytical_dataset(
        PROJECT_ROOT,
        TABLE_CONTRACTS,
        override,
        allow_gold_fallback=allow_working_gold,
        require_certified=not allow_working_gold,
    )
    manifest = selected.release_manifest
    run = manifest.get("run_metadata", {})
    metadata: dict[str, object] = {
        "dataset_version": selected.dataset_version,
        "selection_method": selected.selection_method,
        "created_at": manifest.get("created_at"),
        "decision": manifest.get("decision"),
        "overall_readiness": manifest.get("overall_readiness"),
        "source_commit": manifest.get("git", {}).get("git_commit"),
        "configuration_hash": run.get("config_snapshot_sha256"),
        "generator_version": run.get("generator_version"),
        "scenario_version": run.get("scenario_version"),
        "clinical_rules_version": run.get("clinical_rules_version"),
        "market_configuration_version": run.get("market_configuration_version"),
        "active_analytical_definition": {
            "eligibility": "eligibility_rule_version",
            "initiation": "INITIATION-WINDOW-SYN-v1.0 (primary 90 days)",
            "persistence": "persistence_rule_version (primary 60-day permissible gap)",
            "censoring": "explicit right-censoring at each landmark",
        },
        "working_gold_non_release": selected.release_dir is None,
    }
    return selected.analytical_dir, metadata


def write_eda_artifact_manifest(
    analytical_dir: Path, selection_metadata: dict[str, object]
) -> Path:
    """Map every current EDA output to one source release and definition set."""
    manifest_path = OUTPUT_DIR / "eda_artifact_manifest.json"
    artifacts: dict[str, dict[str, object]] = {}
    for path in sorted(OUTPUT_DIR.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        artifacts[path.relative_to(OUTPUT_DIR).as_posix()] = {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    payload = {
        "manifest_version": "2.2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "synthetic_data_only": True,
        "analytical_data_dir": str(analytical_dir),
        "provenance": selection_metadata,
        "code_version": __version__,
        "artifacts": artifacts,
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def ensure_output_directories() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
