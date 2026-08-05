"""Build the normalized patient cohort."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_patient_table(base: pd.DataFrame, config: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Normalize source demographics and add explicit sampling metadata."""
    size = len(base)
    birth_col = "BIRTHDATE" if "BIRTHDATE" in base else "birthdate"
    id_col = "Id" if "Id" in base else "id"
    birth = pd.to_datetime(base[birth_col], errors="coerce")
    index = pd.to_datetime(base.get("synthetic_index_date", pd.Timestamp("2022-01-01")))
    age = ((index - birth).dt.days / 365.25).round().astype(int)
    state = base.get("STATE", pd.Series(rng.choice(["MA", "NY", "CA", "TX"], size)))
    race = base.get("RACE", pd.Series(rng.choice(["white", "black", "asian", "other"], size)))
    ethnicity = base.get("ETHNICITY", pd.Series("nonhispanic", index=base.index))
    zipcode = base.get("ZIP", pd.Series(rng.integers(10000, 99999, size).astype(str)))
    patient = pd.DataFrame(
        {
            "patient_id": [f"PJ-{i:08d}" for i in range(size)],
            "synthea_patient_id": base[id_col].astype(str).to_numpy(),
            "birth_date": birth.dt.normalize(),
            "birth_year": birth.dt.year,
            "age_at_index": age,
            "sex": "male",
            "country": "US",
            "region": pd.Series(state).astype(str).to_numpy(),
            "postal_code_prefix": pd.Series(zipcode).astype(str).str[:3].to_numpy(),
            "race": pd.Series(race).astype(str).str.lower().to_numpy(),
            "ethnicity": pd.Series(ethnicity).astype(str).str.lower().to_numpy(),
            "insurance_type": rng.choice(["commercial", "medicare", "medicaid", "other"], size, p=[.24, .61, .10, .05]),
            "comorbidity_score": np.clip(rng.poisson(1.8, size), 0, 8),
            "frailty_proxy": np.clip(rng.beta(2, 5, size), 0, 1).round(3),
            "socioeconomic_proxy": rng.choice(["low", "medium", "high"], size, p=[.28, .51, .21]),
            "date_of_death": pd.NaT,
            "synthetic_oversampling_flag": True,
            "population_representative_flag": False,
            "sampling_weight": 1.0,
            "synthetic_scenario_version": config["scenario_version"],
        }
    )
    missing = config["missing_data_probabilities"]
    for col in ("race", "ethnicity", "insurance_type"):
        mask = rng.random(size) < float(missing.get(col, 0))
        patient.loc[mask, col] = pd.NA
    return patient

