"""Generate coherent organizations, stable-specialty providers and care teams."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .market import market_profiles

SETTING_SPECIALTIES = {
    "community_urology": ["urology", "primary_care"],
    "community_oncology": ["medical_oncology", "urology"],
    "academic_oncology": ["medical_oncology", "urology", "radiation_oncology"],
    "mixed_pathway": ["urology", "medical_oncology", "radiation_oncology"],
}


def generate_provider_network(
    patient: pd.DataFrame, config: dict, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create market/region organizations and providers with stable master specialties."""
    organizations: list[dict] = []
    providers: list[dict] = []
    profiles = market_profiles(config)

    specialty_choices = ["urology", "medical_oncology", "radiation_oncology", "primary_care"]
    specialty_probabilities = [0.45, 0.34, 0.16, 0.05]
    for market_code, profile in profiles.items():
        market_patients = int(patient.market_code.eq(market_code).sum())
        target = max(
            4,
            int(np.ceil(market_patients / 1000 * profile["providers_per_1000"])),
        )
        required_specialties = ["urology", "medical_oncology", "radiation_oncology"]
        sampled_specialties = required_specialties + list(
            rng.choice(
                specialty_choices,
                size=target - len(required_specialties),
                p=specialty_probabilities,
            )
        )
        organization_ids: dict[tuple[str, str], str] = {}
        for provider_counter, specialty in enumerate(sampled_specialties):
            allowed_settings = [
                setting
                for setting, specialties in SETTING_SPECIALTIES.items()
                if specialty in specialties
            ]
            setting_weights = np.array(
                [profile["care_setting_distribution"][setting] for setting in allowed_settings],
                dtype=float,
            )
            setting_weights /= setting_weights.sum()
            setting = str(rng.choice(allowed_settings, p=setting_weights))
            region = str(rng.choice(profile["regions"]))
            organization_key = (region, setting)
            if organization_key not in organization_ids:
                organization_id = f"ORG-{market_code}-{len(organization_ids):03d}"
                organization_ids[organization_key] = organization_id
                academic = setting == "academic_oncology"
                organizations.append(
                    {
                        "organization_id": organization_id,
                        "market_code": market_code,
                        "region": region,
                        "organization_type": setting,
                        "care_setting": setting,
                        "academic_flag": academic,
                        "multidisciplinary_team_flag": bool(academic or setting == "mixed_pathway"),
                        "synthetic_organization_flag": True,
                    }
                )
            organization_id = organization_ids[organization_key]
            academic = setting == "academic_oncology"
            providers.append(
                {
                    "provider_id": f"PR-{market_code}-{provider_counter:05d}",
                    "organization_id": organization_id,
                    "market_code": market_code,
                    "region": region,
                    "provider_specialty": specialty,
                    "care_setting": setting,
                    "academic_flag": academic,
                    "annual_prostate_volume": int(
                        rng.integers(45, 360) * (1.45 if academic else 1.0)
                    ),
                    "multidisciplinary_team_flag": bool(academic or setting == "mixed_pathway"),
                    "synthetic_provider_flag": True,
                }
            )
    return pd.DataFrame(organizations), pd.DataFrame(providers)


def generate_providers(
    patient: pd.DataFrame, config: dict, rng: np.random.Generator
) -> pd.DataFrame:
    """Backward-compatible provider-only wrapper."""
    return generate_provider_network(patient, config, rng)[1]


def assign_care_teams(
    patient: pd.DataFrame,
    providers: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Assign distinct urology, oncology and radiation providers per patient."""
    profiles = market_profiles(config)
    rows: list[dict] = []

    def choose(
        local_providers: pd.DataFrame,
        market_providers: pd.DataFrame,
        specialty: str,
        setting: str | None = None,
    ) -> pd.Series:
        candidates = local_providers[local_providers.provider_specialty.eq(specialty)]
        if candidates.empty:
            candidates = market_providers[market_providers.provider_specialty.eq(specialty)]
        if setting:
            preferred = candidates[candidates.care_setting.eq(setting)]
            if not preferred.empty:
                candidates = preferred
        return candidates.iloc[int(rng.integers(0, len(candidates)))]

    for _, person in patient.iterrows():
        profile = profiles[person.market_code]
        setting_distribution = profile["care_setting_distribution"]
        preferred_setting = str(
            rng.choice(list(setting_distribution), p=list(setting_distribution.values()))
        )
        local = providers[
            providers.market_code.eq(person.market_code) & providers.region.eq(person.region)
        ]
        market = providers[providers.market_code.eq(person.market_code)]

        urologist = choose(local, market, "urology", preferred_setting)
        oncologist = choose(local, market, "medical_oncology", preferred_setting)
        radiation = choose(local, market, "radiation_oncology", preferred_setting)
        rows.append(
            {
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "initial_urology_provider_id": urologist.provider_id,
                "initial_urology_organization_id": urologist.organization_id,
                "oncology_provider_id": oncologist.provider_id,
                "oncology_organization_id": oncologist.organization_id,
                "radiation_provider_id": radiation.provider_id,
                "radiation_organization_id": radiation.organization_id,
                "initial_care_setting": urologist.care_setting,
                "oncology_care_setting": oncologist.care_setting,
                "multidisciplinary_team_flag": bool(
                    urologist.multidisciplinary_team_flag or oncologist.multidisciplinary_team_flag
                ),
            }
        )
    return pd.DataFrame(rows)


def assign_initial_providers(
    patient: pd.DataFrame,
    providers: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Backward-compatible alias returning patient care-team assignments."""
    return assign_care_teams(patient, providers, config, rng)
