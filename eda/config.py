"""Configuration and explicit data contracts for the healthcare EDA foundation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

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
    """Resolve an explicit override or the newest valid certified release."""
    override = os.environ.get("EDA_DATASET_DIR")
    if override:
        candidate = Path(override).expanduser().resolve()
        metadata: dict[str, object] = {"selection_method": "EDA_DATASET_DIR override"}
    else:
        releases = PROJECT_ROOT / "data" / "releases"
        candidates: list[tuple[str, Path, dict[str, object]]] = []
        if releases.is_dir():
            for manifest_path in releases.glob("*/release_manifest.json"):
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if payload.get("decision") != "CERTIFIED — READY FOR BAYER ANALYSIS":
                    continue
                analytical = manifest_path.parent / str(
                    payload.get("analytical_dataset_directory", "analytical_dataset")
                )
                candidates.append((str(payload.get("created_at", "")), analytical, payload))
        if candidates:
            _, candidate, metadata = max(candidates, key=lambda item: item[0])
            metadata = {**metadata, "selection_method": "newest certified release"}
        else:
            candidate = PROJECT_ROOT / "data" / "gold"
            metadata = {"selection_method": "complete data/gold fallback"}

    missing = [
        f"{table}.parquet"
        for table in TABLE_CONTRACTS
        if not (candidate / f"{table}.parquet").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "No usable complete analytical dataset was found. Missing files under "
            f"{candidate}: {', '.join(missing)}"
        )
    return candidate.resolve(), metadata


def ensure_output_directories() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
