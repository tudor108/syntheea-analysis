"""Generate coherent observation windows and competing right-censoring events."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .market import market_profiles


def generate_observation(
    patient: pd.DataFrame,
    diagnosis: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Create one observation/censoring record per patient before clinical events."""
    diagnosis_by_patient = diagnosis.set_index("patient_id")
    profiles = market_profiles(config)
    administrative_end = pd.Timestamp(config["observation_end_date"])
    rows: list[dict] = []
    outcome_config = config["outcomes"]
    rule_version = config["clinical_rule_configuration"]["clinical_rules"]["observation_censoring"][
        "version"
    ]

    for _, person in patient.iterrows():
        dx = diagnosis_by_patient.loc[person.patient_id]
        diagnosis_date = pd.Timestamp(dx.diagnosis_date)
        available_days = max(1, (administrative_end - diagnosis_date).days)
        observation_start = diagnosis_date - pd.Timedelta(days=int(rng.integers(180, 731)))
        death_probability = (
            outcome_config["death_base_probability"]
            + outcome_config["metastatic_death_increment"] * bool(dx.metastatic_flag)
            + outcome_config["frailty_death_increment"] * float(person.frailty_proxy >= 0.55)
        )
        ltfu_probability = (
            outcome_config["ltfu_base_probability"]
            + max(0.0, 0.55 - float(person.access_index)) * 0.18
            + (0.025 if profiles[person.market_code]["depth"] == "scan" else 0.0)
        )
        death_date = pd.NaT
        ltfu_date = pd.NaT
        if available_days > 90 and rng.random() < np.clip(death_probability, 0.0, 0.55):
            death_date = diagnosis_date + pd.Timedelta(
                days=int(rng.integers(90, available_days + 1))
            )
        if available_days > 120 and rng.random() < np.clip(ltfu_probability, 0.0, 0.40):
            ltfu_date = diagnosis_date + pd.Timedelta(
                days=int(rng.integers(120, available_days + 1))
            )
        if pd.notna(death_date) and pd.notna(ltfu_date):
            if death_date <= ltfu_date:
                ltfu_date = pd.NaT
            else:
                death_date = pd.NaT
        terminal_dates = [administrative_end]
        if pd.notna(death_date):
            terminal_dates.append(death_date)
        if pd.notna(ltfu_date):
            terminal_dates.append(ltfu_date)
        censor_date = min(terminal_dates)
        censor_reason = (
            "death"
            if pd.notna(death_date)
            else "loss_to_follow_up"
            if pd.notna(ltfu_date)
            else "administrative_end"
        )
        rows.append(
            {
                "observation_id": f"OBS-{person.market_code}-{len(rows):07d}",
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "observation_start_date": observation_start,
                "observation_end_date": administrative_end,
                "last_observed_date": censor_date,
                "loss_to_follow_up_date": ltfu_date,
                "death_date": death_date,
                "censor_date": censor_date,
                "censor_reason": censor_reason,
                "follow_up_days_from_diagnosis": (censor_date - diagnosis_date).days,
                "observation_rule_version": rule_version,
                "synthetic_event_flag": True,
            }
        )
    return pd.DataFrame(rows)
