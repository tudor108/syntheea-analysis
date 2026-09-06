"""Generate coherent diagnosis and versioned disease-state records."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .market import market_profiles


def isup_from_patterns(primary: int, secondary: int) -> int:
    """Map explicit Gleason patterns to ISUP grade group."""
    score = primary + secondary
    if score <= 6:
        return 1
    if primary == 3 and secondary == 4:
        return 2
    if primary == 4 and secondary == 3:
        return 3
    if score == 8:
        return 4
    return 5


def _gleason_patterns(risk_group: str, rng: np.random.Generator) -> tuple[int, int]:
    if risk_group == "low":
        choices, probabilities = [(3, 3), (3, 4)], [0.90, 0.10]
    elif risk_group == "intermediate":
        choices, probabilities = [(3, 4), (4, 3), (4, 4)], [0.52, 0.38, 0.10]
    elif risk_group == "high":
        choices = [(4, 4), (4, 5), (5, 4), (5, 5)]
        probabilities = [0.38, 0.29, 0.23, 0.10]
    else:
        choices, probabilities = [(3, 4), (4, 3), (4, 4)], [0.30, 0.30, 0.40]
    return choices[int(rng.choice(len(choices), p=probabilities))]


def generate_diagnoses(
    patient: pd.DataFrame, config: dict, rng: np.random.Generator
) -> pd.DataFrame:
    """Generate one diagnosis per patient from explicit market and clinical assumptions."""
    profiles = market_profiles(config)
    state_model_version = config["clinical_rule_configuration"]["clinical_rules"][
        "clinical_state_model"
    ]["version"]
    rows: list[dict] = []
    for i, person in patient.iterrows():
        profile = profiles[person.market_code]
        stages = profile["stage_distribution"]
        stage = str(rng.choice(list(stages), p=list(stages.values())))
        risk_distribution = config["risk_distribution_by_stage"][stage]
        risk_group = str(rng.choice(list(risk_distribution), p=list(risk_distribution.values())))
        diagnosis_date = pd.Timestamp(person.index_date)
        metastatic = stage == "metastatic"
        metastatic_date = diagnosis_date if metastatic else pd.NaT
        cr_at_index = bool(
            metastatic and rng.random() < config["castration_resistant_at_index_probability"]
        )
        hormone_sensitive = bool(
            metastatic
            and not cr_at_index
            and rng.random() < config["hormone_sensitive_probability"]
        )
        primary, secondary = _gleason_patterns(risk_group, rng)
        score = primary + secondary
        isup = isup_from_patterns(primary, secondary)
        psa_multiplier = {
            "localized": 1.0,
            "locally_advanced": 1.5,
            "metastatic": 2.4,
            "unknown": 1.2,
        }[stage]
        psa = round(float(np.exp(rng.normal(2.45 + np.log(psa_multiplier), 0.72))), 1)
        sites = config["stage_metastatic_sites"]
        metastatic_site = (
            str(rng.choice(list(sites), p=list(sites.values()))) if metastatic else "not_applicable"
        )
        multiplier = float(profile["clinical_missingness_multiplier"])
        psa_missing = rng.random() < min(0.45, config["missingness"]["psa_base"] * multiplier)
        gleason_missing = rng.random() < min(
            0.45, config["missingness"]["gleason_base"] * multiplier
        )
        rows.append(
            {
                "diagnosis_id": f"DX-{person.market_code}-{i:07d}",
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "diagnosis_date": diagnosis_date,
                "prostate_cancer_flag": True,
                "prostate_stage": stage,
                "localized_flag": stage == "localized",
                "locally_advanced_flag": stage == "locally_advanced",
                "metastatic_flag": metastatic,
                "metastatic_date": metastatic_date,
                "metastatic_site": metastatic_site,
                "hormone_sensitive_flag": hormone_sensitive,
                "hormone_sensitive_confirmation_date": (
                    diagnosis_date if hormone_sensitive else pd.NaT
                ),
                "castration_resistant_flag": cr_at_index,
                "castration_resistant_date": diagnosis_date if cr_at_index else pd.NaT,
                "risk_group": risk_group,
                "psa_value": pd.NA if psa_missing else psa,
                "gleason_primary_pattern": pd.NA if gleason_missing else primary,
                "gleason_secondary_pattern": pd.NA if gleason_missing else secondary,
                "gleason_score": pd.NA if gleason_missing else score,
                "isup_grade_group": pd.NA if gleason_missing else isup,
                "diagnosis_source": "synthetic_market_enrichment",
                "clinical_state_model_version": state_model_version,
                "data_quality_flag": "pass",
            }
        )
    diagnosis = pd.DataFrame(rows)
    for column in (
        "gleason_primary_pattern",
        "gleason_secondary_pattern",
        "gleason_score",
        "isup_grade_group",
    ):
        diagnosis[column] = pd.array(diagnosis[column], dtype="Int64")
    return diagnosis


def derive_mhspc(diagnosis: pd.DataFrame) -> pd.Series:
    """Apply the configured synthetic mHSPC state derivation."""
    return (
        diagnosis.prostate_cancer_flag
        & diagnosis.metastatic_flag
        & diagnosis.hormone_sensitive_flag
        & ~diagnosis.castration_resistant_flag
    )


def generate_initial_disease_states(diagnosis: pd.DataFrame) -> pd.DataFrame:
    """Create one versioned initial disease-state event per diagnosis."""
    states = np.select(
        [
            diagnosis.castration_resistant_flag,
            derive_mhspc(diagnosis),
            diagnosis.metastatic_flag,
            diagnosis.locally_advanced_flag,
            diagnosis.localized_flag,
        ],
        ["mCRPC", "mHSPC", "metastatic_other", "locally_advanced", "localized"],
        default="unknown",
    )
    return pd.DataFrame(
        {
            "disease_state_event_id": [f"DSE-{i:08d}-0" for i in range(len(diagnosis))],
            "patient_id": diagnosis.patient_id,
            "market_code": diagnosis.market_code,
            "state_date": diagnosis.diagnosis_date,
            "state": states,
            "previous_state": pd.NA,
            "transition_reason": "index_diagnosis",
            "clinical_state_model_version": diagnosis.clinical_state_model_version,
            "synthetic_event_flag": True,
        }
    )
