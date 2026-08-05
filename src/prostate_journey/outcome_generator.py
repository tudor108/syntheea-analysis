"""Generate progression, hospitalization, death, LTFU and censoring."""
from __future__ import annotations

import numpy as np
import pandas as pd


def generate_outcomes(
    patient: pd.DataFrame, eligibility: pd.DataFrame, treatment: pd.DataFrame,
    config: dict, rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate mutually interpretable terminal and non-terminal outcomes."""
    rows = []
    observation_end = pd.Timestamp(config["observation_end_date"])
    for i, person in patient.iterrows():
        elig = pd.Timestamp(eligibility.iloc[i].eligibility_date)
        patient_tx = treatment[treatment.patient_id == person.patient_id] if not treatment.empty else treatment
        last_tx = patient_tx[["treatment_end_date", "restart_date", "switch_date"]].max().max() if not patient_tx.empty else pd.NaT
        progression = bool(rng.random() < config["progression_probability"])
        progression_date = min(elig + pd.Timedelta(days=int(rng.integers(120, 900))), observation_end) if progression else pd.NaT
        cr_transition = bool(progression and eligibility.iloc[i].mhspc_flag and rng.random() < config["castration_resistant_transition_probability"])
        cr_date = progression_date + pd.Timedelta(days=int(rng.integers(0, 91))) if cr_transition else pd.NaT
        if pd.notna(cr_date) and cr_date > observation_end: cr_transition, cr_date = False, pd.NaT
        hospital_p = config["hospitalisation_probability"] + (config["signals"]["high_comorbidity_hospitalisation_increase"] if person.comorbidity_score >= 4 else 0)
        hospital = bool(rng.random() < np.clip(hospital_p, 0, .8))
        hospital_date = min(elig + pd.Timedelta(days=int(rng.integers(30, 700))), observation_end) if hospital else pd.NaT
        adverse = bool(rng.random() < config["adverse_event_probability"])
        death = bool(rng.random() < config["death_probability"])
        earliest_death = max(elig + pd.Timedelta(days=120), pd.Timestamp(last_tx) + pd.Timedelta(days=1) if pd.notna(last_tx) else elig + pd.Timedelta(days=120))
        death_date = earliest_death + pd.Timedelta(days=int(rng.integers(1, 180))) if death else pd.NaT
        if pd.notna(death_date) and death_date > observation_end: death, death_date = False, pd.NaT
        ltfu = bool(not death and rng.random() < config["loss_to_follow_up_probability"])
        last_observed = elig + pd.Timedelta(days=int(rng.integers(150, 800))) if ltfu else observation_end
        last_observed = min(last_observed, observation_end)
        censor = min([d for d in (observation_end, death_date, last_observed) if pd.notna(d)])
        if death: status = "deceased"
        elif ltfu: status = "lost_to_follow_up"
        elif progression: status = "progressed"
        elif not patient_tx.empty and bool(patient_tx.iloc[0].restart_flag): status = "restarted"
        elif not patient_tx.empty and bool(patient_tx.iloc[0].switch_flag): status = "switched"
        elif not patient_tx.empty and bool(patient_tx.iloc[0].discontinuation_flag): status = "discontinued"
        elif not patient_tx.empty: status = "active_treatment"
        else: status = "censored"
        rows.append({
            "patient_id": person.patient_id, "progression_event": progression, "progression_date": progression_date,
            "castration_resistant_transition": cr_transition, "castration_resistant_date": cr_date,
            "hospitalisation_flag": hospital, "first_hospitalisation_date": hospital_date,
            "adverse_event_flag": adverse, "adverse_event_type": rng.choice(["fatigue", "hypertension", "laboratory_abnormality", "other"]) if adverse else pd.NA,
            "death_flag": death, "death_date": death_date, "lost_to_follow_up_flag": ltfu,
            "last_observed_date": last_observed, "censor_date": censor, "outcome_status": status,
        })
    return pd.DataFrame(rows)
