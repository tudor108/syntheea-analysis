"""Generate specialty-consistent encounters and real source/destination referrals."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .market import market_profiles


def generate_pathway(
    patient: pd.DataFrame,
    diagnosis: pd.DataFrame,
    eligibility: pd.DataFrame,
    care_team: pd.DataFrame,
    providers: pd.DataFrame,
    observation: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create longitudinal encounters and referral records capped at censoring."""
    diagnosis_index = diagnosis.set_index("patient_id")
    eligibility_index = eligibility.set_index("patient_id")
    team_index = care_team.set_index("patient_id")
    provider_index = providers.set_index("provider_id")
    observation_index = observation.set_index("patient_id")
    profiles = market_profiles(config)
    encounters: list[dict] = []
    referrals: list[dict] = []

    def add_encounter(
        person: pd.Series,
        provider_id: str,
        encounter_date: pd.Timestamp,
        encounter_type: str,
        sequence: int,
        detail_level: str,
    ) -> None:
        provider = provider_index.loc[provider_id]
        encounters.append(
            {
                "encounter_id": f"ENC-{person.market_code}-{len(encounters):09d}",
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "provider_id": provider_id,
                "organization_id": provider.organization_id,
                "encounter_date": encounter_date,
                "encounter_type": encounter_type,
                "provider_specialty": provider.provider_specialty,
                "care_setting": provider.care_setting,
                "sequence_number": sequence,
                "detail_level": detail_level,
                "synthetic_event_flag": True,
            }
        )

    for _, person in patient.iterrows():
        dx = diagnosis_index.loc[person.patient_id]
        eligible = eligibility_index.loc[person.patient_id]
        team = team_index.loc[person.patient_id]
        censor = pd.Timestamp(observation_index.loc[person.patient_id].censor_date)
        profile = profiles[person.market_code]
        detail = profile["depth"]
        diagnosis_date = pd.Timestamp(dx.diagnosis_date)
        urology_date = min(diagnosis_date + pd.Timedelta(days=int(rng.integers(3, 25))), censor)
        add_encounter(
            person,
            team.initial_urology_provider_id,
            diagnosis_date,
            "diagnosis",
            0,
            detail,
        )
        add_encounter(
            person,
            team.initial_urology_provider_id,
            urology_date,
            "urology_decision",
            1,
            detail,
        )

        referral_candidate = bool(
            eligible.mhspc_flag
            or dx.locally_advanced_flag
            or (dx.localized_flag and dx.risk_group == "high")
        )
        completed = False
        if referral_candidate:
            referral_probability = profile["referral_probability"] + (
                config["referral"]["eligible_probability_increment"]
                if eligible.eligibility_flag
                else 0.0
            )
            if person.complexity_segment == "high":
                referral_probability -= config["referral"]["high_complexity_completion_penalty"]
            referred = rng.random() < np.clip(referral_probability, 0.20, 0.98)
            status_distribution = profile["referral_status_distribution"]
            status = (
                str(rng.choice(list(status_distribution), p=list(status_distribution.values())))
                if referred
                else "not_completed"
            )
            referral_date = urology_date
            delay = max(
                1,
                int(
                    rng.normal(
                        profile["referral_delay_mean_days"],
                        profile["referral_delay_sd_days"],
                    )
                ),
            )
            completion_date = (
                referral_date + pd.Timedelta(days=delay) if status == "completed" else pd.NaT
            )
            if pd.notna(completion_date) and completion_date > censor:
                status = "pending"
                completion_date = pd.NaT
            completed = status == "completed"
            referrals.append(
                {
                    "referral_id": f"REF-{person.market_code}-{len(referrals):08d}",
                    "patient_id": person.patient_id,
                    "market_code": person.market_code,
                    "source_provider_id": team.initial_urology_provider_id,
                    "source_organization_id": team.initial_urology_organization_id,
                    "source_specialty": "urology",
                    "destination_provider_id": team.oncology_provider_id,
                    "destination_organization_id": team.oncology_organization_id,
                    "destination_specialty": "medical_oncology",
                    "referral_date": referral_date,
                    "completion_date": completion_date,
                    "referral_status": status,
                    "referral_reason": "advanced_prostate_pathway_review",
                    "decision_owner_specialty": ("medical_oncology" if completed else "urology"),
                    "detail_level": detail,
                    "synthetic_event_flag": True,
                }
            )
            if completed:
                add_encounter(
                    person,
                    team.oncology_provider_id,
                    completion_date,
                    "oncology_consultation",
                    2,
                    detail,
                )

        followup_mean = float(profile["followup_visit_mean"])
        followup_count = int(rng.poisson(followup_mean))
        followup_provider = (
            team.oncology_provider_id if completed else team.initial_urology_provider_id
        )
        start_date = urology_date + pd.Timedelta(days=60)
        available = max(0, (censor - start_date).days)
        if available > 0:
            for followup_index in range(followup_count):
                event_date = start_date + pd.Timedelta(
                    days=int((followup_index + 1) * available / (followup_count + 1))
                )
                add_encounter(
                    person,
                    followup_provider,
                    event_date,
                    "oncology_follow_up" if completed else "urology_follow_up",
                    3 + followup_index,
                    detail,
                )
    encounter_columns = [
        "encounter_id",
        "patient_id",
        "market_code",
        "provider_id",
        "organization_id",
        "encounter_date",
        "encounter_type",
        "provider_specialty",
        "care_setting",
        "sequence_number",
        "detail_level",
        "synthetic_event_flag",
    ]
    referral_columns = [
        "referral_id",
        "patient_id",
        "market_code",
        "source_provider_id",
        "source_organization_id",
        "source_specialty",
        "destination_provider_id",
        "destination_organization_id",
        "destination_specialty",
        "referral_date",
        "completion_date",
        "referral_status",
        "referral_reason",
        "decision_owner_specialty",
        "detail_level",
        "synthetic_event_flag",
    ]
    return (
        pd.DataFrame(encounters, columns=encounter_columns),
        pd.DataFrame(referrals, columns=referral_columns),
    )
