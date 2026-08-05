"""Generate prostate diagnoses, stage and demo mHSPC state."""
from __future__ import annotations

import numpy as np
import pandas as pd


def generate_diagnoses(patient: pd.DataFrame, config: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Generate one diagnosis record per demo patient from configured assumptions."""
    n = len(patient)
    stages = config["stage_distribution"]
    stage = rng.choice(list(stages), n, p=list(stages.values()))
    diagnosis_date = pd.to_datetime("2021-01-01") + pd.to_timedelta(rng.integers(0, 730, n), unit="D")
    metastatic = stage == "metastatic"
    metastatic_date = pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns]")
    metastatic_date.loc[metastatic] = diagnosis_date[metastatic] + pd.to_timedelta(
        rng.integers(0, 61, metastatic.sum()), unit="D"
    )
    hormone_sensitive = metastatic & (rng.random(n) < config["hormone_sensitive_probability"])
    sites = config["stage_metastatic_sites"]
    metastatic_site = np.where(
        metastatic, rng.choice(list(sites), n, p=list(sites.values())), "unknown"
    )
    gleason = np.clip(np.rint(rng.normal(7.4 + metastatic * .6, 1.0, n)), 6, 10)
    diagnosis = pd.DataFrame(
        {
            "diagnosis_id": [f"DX-{i:08d}" for i in range(n)],
            "patient_id": patient.patient_id,
            "diagnosis_date": diagnosis_date,
            "prostate_cancer_flag": True,
            "prostate_stage": stage,
            "localized_flag": stage == "localized",
            "locally_advanced_flag": stage == "locally_advanced",
            "metastatic_flag": metastatic,
            "metastatic_date": metastatic_date,
            "metastatic_site": metastatic_site,
            "hormone_sensitive_flag": hormone_sensitive,
            "hormone_sensitive_confirmation_date": metastatic_date.where(metastatic, diagnosis_date),
            "castration_resistant_flag": False,
            "castration_resistant_date": pd.NaT,
            "risk_group": rng.choice(["low", "intermediate", "high", "unknown"], n, p=[.13, .31, .51, .05]),
            "psa_value": np.round(np.exp(rng.normal(3.0 + metastatic * .7, .8, n)), 1),
            "gleason_score": pd.array(gleason, dtype="Int64"),
            "isup_grade_group": pd.array(np.clip(gleason - 5, 1, 5), dtype="Int64"),
            "diagnosis_source": "synthetic_enrichment",
            "data_quality_flag": "pass",
        }
    )
    missing = config["missing_data_probabilities"]
    for col in ("psa_value", "gleason_score"):
        diagnosis.loc[rng.random(n) < missing.get(col, 0), col] = pd.NA
    return diagnosis


def derive_mhspc(diagnosis: pd.DataFrame) -> pd.Series:
    """Apply the explicit demo mHSPC rule at index date."""
    return (
        diagnosis["prostate_cancer_flag"]
        & diagnosis["metastatic_flag"]
        & diagnosis["hormone_sensitive_flag"]
        & ~diagnosis["castration_resistant_flag"]
    )
