"""Generate active-surveillance episodes and monitoring events for localized disease."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .market import market_profiles


def generate_active_surveillance(
    patient: pd.DataFrame,
    diagnosis: pd.DataFrame,
    care_team: pd.DataFrame,
    providers: pd.DataFrame,
    observation: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create one AS assessment per localized patient plus dated monitoring encounters."""
    diagnosis_index = diagnosis.set_index("patient_id")
    team_index = care_team.set_index("patient_id")
    provider_index = providers.set_index("provider_id")
    observation_index = observation.set_index("patient_id")
    profiles = market_profiles(config)
    settings = config["active_surveillance"]
    rule = config["clinical_rule_configuration"]["clinical_rules"]["active_surveillance"]
    episodes: list[dict] = []
    encounters: list[dict] = []

    for _, person in patient.iterrows():
        dx = diagnosis_index.loc[person.patient_id]
        if not dx.localized_flag:
            continue
        team = team_index.loc[person.patient_id]
        provider = provider_index.loc[team.initial_urology_provider_id]
        censor = pd.Timestamp(observation_index.loc[person.patient_id].censor_date)
        eligible = bool(
            dx.risk_group in settings["eligibility_risk_groups"]
            and pd.notna(dx.isup_grade_group)
            and int(dx.isup_grade_group) <= 3
            and person.age_at_index <= 85
        )
        ineligibility_reason = pd.NA
        if not eligible:
            if pd.isna(dx.isup_grade_group):
                ineligibility_reason = "insufficient_grade_evidence"
            elif dx.risk_group not in settings["eligibility_risk_groups"]:
                ineligibility_reason = "risk_group_not_configured_for_as"
            else:
                ineligibility_reason = "age_or_complexity_review"
        profile = profiles[person.market_code]
        started = bool(eligible and rng.random() < profile["active_surveillance_uptake"])
        start_date = (
            pd.Timestamp(dx.diagnosis_date) + pd.Timedelta(days=int(rng.integers(14, 61)))
            if started
            else pd.NaT
        )
        if pd.notna(start_date) and start_date > censor:
            started = False
            start_date = pd.NaT
            ineligibility_reason = "censored_before_as_start"

        exit_date = pd.NaT
        exit_reason = pd.NA
        transition_to_treatment = False
        planned_treatment_start = pd.NaT
        as_status = "not_started"
        if started:
            as_status = "continued"
            available_days = (censor - start_date).days
            if (
                available_days >= settings["minimum_monitoring_days"]
                and rng.random() < settings["exit_probability"]
            ):
                exit_date = start_date + pd.Timedelta(
                    days=int(rng.integers(settings["minimum_monitoring_days"], available_days + 1))
                )
                reasons = settings["exit_reasons"]
                exit_reason = str(rng.choice(list(reasons), p=list(reasons.values())))
                transition_to_treatment = bool(
                    rng.random() < settings["transition_to_treatment_probability"]
                )
                if transition_to_treatment:
                    candidate_start = exit_date + pd.Timedelta(days=int(rng.integers(7, 91)))
                    if candidate_start < censor:
                        planned_treatment_start = candidate_start
                    else:
                        transition_to_treatment = False
                as_status = "exited"
            elif censor < pd.Timestamp(config["observation_end_date"]):
                as_status = "censored"

            monitoring_end = exit_date if pd.notna(exit_date) else censor
            interval = 120 if profile["depth"] == "deep" else 240
            monitoring_dates = pd.date_range(
                start_date + pd.Timedelta(days=interval), monitoring_end, freq=f"{interval}D"
            )
            for monitor_index, monitor_date in enumerate(monitoring_dates):
                encounter_type = "as_psa_monitoring"
                if profile["depth"] == "deep" and monitor_index % 3 == 2:
                    encounter_type = str(
                        rng.choice(["as_imaging_monitoring", "as_biopsy_monitoring"])
                    )
                encounters.append(
                    {
                        "encounter_id": f"ASENC-{person.market_code}-{len(encounters):08d}",
                        "patient_id": person.patient_id,
                        "market_code": person.market_code,
                        "provider_id": provider.name,
                        "organization_id": provider.organization_id,
                        "encounter_date": monitor_date,
                        "encounter_type": encounter_type,
                        "provider_specialty": provider.provider_specialty,
                        "care_setting": provider.care_setting,
                        "sequence_number": monitor_index,
                        "detail_level": profile["depth"],
                        "synthetic_event_flag": True,
                    }
                )

        episodes.append(
            {
                "active_surveillance_id": f"AS-{person.market_code}-{len(episodes):07d}",
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "as_eligibility_flag": eligible,
                "as_eligibility_reason": (
                    "localized_low_or_intermediate_risk" if eligible else pd.NA
                ),
                "as_ineligibility_reason": ineligibility_reason,
                "as_start_date": start_date,
                "as_status": as_status,
                "as_exit_date": exit_date,
                "as_exit_reason": exit_reason,
                "as_reclassification_event_flag": bool(
                    pd.notna(exit_reason)
                    and exit_reason in {"progression", "grade_reclassification", "psa_rise"}
                ),
                "as_reclassification_date": (
                    exit_date
                    if pd.notna(exit_reason)
                    and exit_reason in {"progression", "grade_reclassification", "psa_rise"}
                    else pd.NaT
                ),
                "transition_to_treatment_flag": transition_to_treatment,
                "planned_treatment_start_date": planned_treatment_start,
                "time_from_as_exit_to_treatment_days": (
                    (planned_treatment_start - exit_date).days if transition_to_treatment else pd.NA
                ),
                "monitoring_event_count": len(monitoring_dates) if started else 0,
                "active_surveillance_rule_version": rule["version"],
                "synthetic_event_flag": True,
            }
        )
    episode_columns = [
        "active_surveillance_id",
        "patient_id",
        "market_code",
        "as_eligibility_flag",
        "as_eligibility_reason",
        "as_ineligibility_reason",
        "as_start_date",
        "as_status",
        "as_exit_date",
        "as_exit_reason",
        "as_reclassification_event_flag",
        "as_reclassification_date",
        "transition_to_treatment_flag",
        "planned_treatment_start_date",
        "time_from_as_exit_to_treatment_days",
        "monitoring_event_count",
        "active_surveillance_rule_version",
        "synthetic_event_flag",
    ]
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
    return (
        pd.DataFrame(episodes, columns=episode_columns),
        pd.DataFrame(encounters, columns=encounter_columns),
    )
