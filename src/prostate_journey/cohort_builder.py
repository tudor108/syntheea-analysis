"""Build the independent, normalized multi-market patient cohort."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .market import market_profiles


def build_patient_table(base: pd.DataFrame, config: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Derive patient attributes from unique archetypes and explicit market profiles."""
    size = len(base)
    birth_col = "BIRTHDATE" if "BIRTHDATE" in base else "birthdate"
    id_col = "Id" if "Id" in base else "id"
    birth = pd.to_datetime(base[birth_col], errors="coerce").dt.normalize()
    index_date = pd.to_datetime(
        base.get("synthetic_index_date", pd.Series(pd.Timestamp("2022-01-01"), index=base.index))
    ).dt.normalize()
    age = ((index_date - birth).dt.days // 365).astype("int64")
    market_code = base.get("market_code", pd.Series("US", index=base.index)).astype(str)
    profiles = market_profiles(config)

    comorbidity = np.clip(rng.poisson(1.3 + np.maximum(age - 60, 0) / 22, size), 0, 9).astype(int)
    frailty = np.clip(rng.beta(2.0 + np.maximum(age - 70, 0) / 12, 5.0, size), 0, 1).round(3)
    socioeconomic = np.where(
        base["access_index"].astype(float) < 0.42,
        "low",
        np.where(base["access_index"].astype(float) > 0.72, "high", "medium"),
    )

    patient = pd.DataFrame(
        {
            "patient_id": [f"PJ-{code}-{index:07d}" for index, code in enumerate(market_code)],
            "source_patient_id": base.get("source_patient_id", base[id_col].astype(str)).to_numpy(),
            "source_archetype_id": base.get(
                "source_archetype_id",
                pd.Series([f"ARCH-US-{i:08d}" for i in range(size)]),
            )
            .astype(str)
            .to_numpy(),
            "source_record_type": base.get(
                "source_record_type", pd.Series("generated_archetype", index=base.index)
            )
            .astype(str)
            .to_numpy(),
            "birth_date": birth,
            "index_date": index_date,
            "birth_year": birth.dt.year,
            "age_at_index": age,
            "sex": "male",
            "market_code": market_code.to_numpy(),
            "country": base.get("country", pd.Series("United States", index=base.index)).to_numpy(),
            "market_depth": base.get(
                "market_depth", pd.Series("deep", index=base.index)
            ).to_numpy(),
            "region": base.get("STATE", pd.Series("Unknown", index=base.index))
            .astype(str)
            .to_numpy(),
            "postal_code_prefix": base.get("ZIP", pd.Series("00000", index=base.index))
            .astype(str)
            .str[:3]
            .to_numpy(),
            "race": base.get("RACE", pd.Series("unknown", index=base.index))
            .astype(str)
            .str.lower()
            .to_numpy(),
            "ethnicity": base.get("ETHNICITY", pd.Series("unknown", index=base.index))
            .astype(str)
            .str.lower()
            .to_numpy(),
            "insurance_type": base.get(
                "insurance_type", pd.Series("other", index=base.index)
            ).to_numpy(),
            "access_index": base.get("access_index", pd.Series(0.5, index=base.index))
            .astype(float)
            .to_numpy(),
            "comorbidity_score": comorbidity,
            "frailty_proxy": frailty,
            "complexity_segment": np.where(
                (comorbidity >= 4) | (frailty >= 0.55),
                "high",
                np.where((comorbidity >= 2) | (frailty >= 0.30), "medium", "low"),
            ),
            "socioeconomic_proxy": socioeconomic,
            "date_of_death": pd.NaT,
            "synthetic_oversampling_flag": False,
            "population_representative_flag": False,
            "sampling_weight": 1.0,
            "synthetic_scenario_version": config["scenario_version"],
        }
    )

    for market, profile in profiles.items():
        mask = patient.market_code.eq(market)
        multiplier = float(profile["clinical_missingness_multiplier"])
        for column, base_probability in (
            ("race", config["missingness"]["race_base"]),
            ("ethnicity", config["missingness"]["ethnicity_base"]),
            ("insurance_type", config["missingness"]["insurance_base"]),
        ):
            missing = mask & (rng.random(size) < min(0.45, base_probability * multiplier))
            patient.loc[missing, column] = pd.NA
    return patient
