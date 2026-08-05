"""Generate initiation, refills, discontinuation, switch and restart events."""
from __future__ import annotations

import numpy as np
import pandas as pd

DRUG_CLASS = {
    "ADT": "ADT", "darolutamide": "ARPI", "enzalutamide": "ARPI", "apalutamide": "ARPI",
    "abiraterone": "ARPI", "docetaxel": "chemotherapy", "other_systemic_therapy": "other",
}


def generate_treatments(
    patient: pd.DataFrame, eligibility: pd.DataFrame, encounter: pd.DataFrame,
    assigned: pd.DataFrame, config: dict, rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate longitudinal treatment episodes using only pre-outcome predictors."""
    rows: list[dict] = []
    selection = config["treatment_selection_probabilities"]
    observation_end = pd.Timestamp(config["observation_end_date"])
    oncology = encounter[encounter.encounter_type == "oncology_consultation"].groupby("patient_id").encounter_date.min()
    urology = encounter[encounter.encounter_type == "urology_follow_up"].groupby("patient_id").encounter_date.min()
    for i, person in patient.iterrows():
        if not bool(eligibility.iloc[i].eligible_for_arpi):
            continue
        setting = assigned.iloc[i].care_setting
        init_cfg = config["initiation"][setting]
        referral_delay = (oncology.get(person.patient_id, pd.NaT) - urology.get(person.patient_id, pd.NaT)).days if pd.notna(oncology.get(person.patient_id, pd.NaT)) else 90
        probability = init_cfg["probability_90d"] - (config["signals"]["high_comorbidity_initiation_penalty"] if person.comorbidity_score >= 4 else 0) - max(0, referral_delay - 30) / 500
        if rng.random() >= np.clip(probability, .05, .95):
            continue
        delay = max(1, int(rng.normal(init_cfg["days_mean"] + max(0, referral_delay - 30) * .25, init_cfg["days_sd"])))
        start = pd.Timestamp(eligibility.iloc[i].eligibility_date) + pd.Timedelta(days=delay)
        if start >= observation_end:
            continue
        drug = str(rng.choice(list(selection), p=list(selection.values())))
        duration_cfg = config["treatment_duration_days"]
        duration = int(np.clip(rng.normal(duration_cfg["mean"], duration_cfg["sd"]), duration_cfg["minimum"], duration_cfg["maximum"]))
        end = min(start + pd.Timedelta(days=duration), observation_end)
        refill_dates = list(pd.date_range(start, end, freq="30D"))
        gaps = np.clip(rng.normal(config["refill_gap_distribution"]["mean_days"], config["refill_gap_distribution"]["sd_days"], len(refill_dates)), 0, config["refill_gap_distribution"]["maximum_days"]).astype(int)
        max_gap = int(gaps.max(initial=0))
        covered_until = min(end, (refill_dates[-1] if refill_dates else start) + pd.Timedelta(days=30 + config["allowable_gap_days"]))
        disc_p = config["discontinuation_probability"] + (config["signals"]["high_comorbidity_discontinuation_increase"] if person.comorbidity_score >= 4 else 0)
        discontinuation = bool(rng.random() < np.clip(disc_p, 0, .8) and duration >= 60)
        disc_date = start + pd.Timedelta(days=int(rng.integers(45, max(46, min(duration, 500))))) if discontinuation else pd.NaT
        switch = bool(rng.random() < config["switch_probability"] and duration >= 90)
        switch_date = start + pd.Timedelta(days=int(rng.integers(60, max(61, min(duration, 450))))) if switch else pd.NaT
        alternatives = [d for d in selection if d != drug]
        switched_to = str(rng.choice(alternatives)) if switch else pd.NA
        restart = bool(discontinuation and not switch and rng.random() < config["restart_probability"])
        restart_date = disc_date + pd.Timedelta(days=config["allowable_gap_days"] + int(rng.integers(5, 80))) if restart else pd.NaT
        if pd.notna(restart_date) and restart_date > observation_end:
            restart, restart_date = False, pd.NaT
        reason = str(rng.choice(["adverse_event", "patient_choice", "clinical_change", "access", "other"])) if discontinuation else pd.NA
        rows.append({
            "treatment_id": f"TR-{i:08d}-0", "patient_id": person.patient_id, "drug_name": drug,
            "drug_class": DRUG_CLASS[drug], "regimen_name": f"synthetic_{drug}_regimen", "treatment_line": 1,
            "treatment_start_date": start, "treatment_end_date": disc_date if discontinuation and not restart else end,
            "days_supply": 30, "refill_date": start, "covered_until_date": covered_until,
            "treatment_setting": setting, "prescribing_specialty": assigned.iloc[i].provider_specialty,
            "prescribing_provider_id": assigned.iloc[i].provider_id, "discontinuation_flag": discontinuation,
            "discontinuation_date": disc_date, "discontinuation_reason": reason, "switch_flag": switch,
            "switch_date": switch_date, "previous_drug": drug if switch else pd.NA, "switched_to_drug": switched_to,
            "restart_flag": restart, "restart_date": restart_date, "temporary_gap_flag": restart,
            "max_refill_gap_days": max_gap, "synthetic_event_flag": True,
        })
        if switch:
            rows.append({
                **rows[-1], "treatment_id": f"TR-{i:08d}-1", "drug_name": switched_to,
                "drug_class": DRUG_CLASS[str(switched_to)], "regimen_name": f"synthetic_{switched_to}_regimen",
                "treatment_line": 2, "treatment_start_date": switch_date,
                "treatment_end_date": min(switch_date + pd.Timedelta(days=max(31, duration // 2)), observation_end),
                "refill_date": switch_date, "covered_until_date": min(switch_date + pd.Timedelta(days=max(31, duration // 2)), observation_end),
                "discontinuation_flag": False, "discontinuation_date": pd.NaT, "discontinuation_reason": pd.NA,
                "switch_flag": False, "switch_date": pd.NaT, "previous_drug": drug,
                "switched_to_drug": pd.NA, "restart_flag": False, "restart_date": pd.NaT, "temporary_gap_flag": False,
            })
    columns = [
        "treatment_id", "patient_id", "drug_name", "drug_class", "regimen_name", "treatment_line",
        "treatment_start_date", "treatment_end_date", "days_supply", "refill_date", "covered_until_date",
        "treatment_setting", "prescribing_specialty", "prescribing_provider_id", "discontinuation_flag",
        "discontinuation_date", "discontinuation_reason", "switch_flag", "switch_date", "previous_drug",
        "switched_to_drug", "restart_flag", "restart_date", "temporary_gap_flag", "max_refill_gap_days",
        "synthetic_event_flag",
    ]
    return pd.DataFrame(rows, columns=columns)
