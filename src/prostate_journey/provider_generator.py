"""Generate synthetic provider and organization attributes."""
from __future__ import annotations

import numpy as np
import pandas as pd


def generate_providers(patient: pd.DataFrame, config: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Create a reusable provider network spanning each region and setting."""
    rows: list[dict] = []
    specialties = config["provider_specialty_distribution"]
    settings = config["care_setting_distribution"]
    for region in sorted(patient["region"].dropna().unique()):
        for index in range(12):
            setting = rng.choice(list(settings), p=list(settings.values()))
            specialty = rng.choice(list(specialties), p=list(specialties.values()))
            academic = setting == "academic_oncology"
            rows.append(
                {
                    "provider_id": f"PR-{region}-{index:03d}",
                    "organization_id": f"ORG-{region}-{index // 3:02d}",
                    "provider_specialty": specialty,
                    "care_setting": setting,
                    "academic_flag": academic,
                    "region": region,
                    "annual_prostate_volume": int(rng.integers(30, 450) * (1.4 if academic else 1)),
                    "multidisciplinary_team_flag": bool(rng.random() < (.85 if academic else .38)),
                    "synthetic_provider_flag": True,
                }
            )
    return pd.DataFrame(rows)


def assign_initial_providers(
    patient: pd.DataFrame, providers: pd.DataFrame, config: dict, rng: np.random.Generator
) -> pd.DataFrame:
    """Assign one initial provider while respecting region and scenario setting mix."""
    settings = config["care_setting_distribution"]
    assigned = []
    for _, row in patient.iterrows():
        setting = rng.choice(list(settings), p=list(settings.values()))
        candidates = providers[(providers.region == row.region) & (providers.care_setting == setting)]
        if candidates.empty:
            candidates = providers[providers.region == row.region]
        assigned.append(candidates.iloc[int(rng.integers(0, len(candidates)))])
    return pd.DataFrame(assigned).reset_index(drop=True)

