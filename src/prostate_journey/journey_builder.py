"""Eligibility, encounter generation and patient-level journey assembly."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .diagnosis_generator import derive_mhspc


def build_eligibility(patient: pd.DataFrame, diagnosis: pd.DataFrame, config: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Derive eligibility using the documented demo cohort assumption."""
    eligibility_date = pd.concat(
        [
            pd.to_datetime(diagnosis["diagnosis_date"]),
            pd.to_datetime(diagnosis["metastatic_date"]),
            pd.to_datetime(diagnosis["hormone_sensitive_confirmation_date"]),
        ],
        axis=1,
    ).max(axis=1)
    mhspc = derive_mhspc(diagnosis)
    contraindication = rng.random(len(patient)) < config["contraindication_probability"]
    possible_followup = (pd.Timestamp(config["observation_end_date"]) - eligibility_date).dt.days
    eligible = mhspc & (patient.age_at_index >= 18) & ~contraindication & (
        possible_followup >= config["minimum_follow_up_days"]
    )
    return pd.DataFrame(
        {
            "patient_id": patient.patient_id,
            "mhspc_flag": mhspc,
            "eligibility_date": eligibility_date,
            "synthetic_contraindication_flag": contraindication,
            "eligible_for_arpi": eligible,
            "eligibility_rule_version": config["eligibility_rule_version"],
        }
    )


def generate_encounters(
    patient: pd.DataFrame,
    diagnosis: pd.DataFrame,
    eligibility: pd.DataFrame,
    assigned: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate diagnosis, urology decision, referral and oncology events."""
    rows: list[dict] = []
    for i in range(len(patient)):
        pid = patient.iloc[i].patient_id
        provider = assigned.iloc[i]
        dx_date = pd.Timestamp(diagnosis.iloc[i].diagnosis_date)
        eligibility_date = pd.Timestamp(eligibility.iloc[i].eligibility_date)
        urology_date = eligibility_date + pd.Timedelta(days=int(rng.integers(2, 22)))
        referral_cfg = config["referral"][provider.care_setting]
        referral = bool(eligibility.iloc[i].eligible_for_arpi and rng.random() < referral_cfg["probability"])
        delay = max(1, int(rng.normal(referral_cfg["delay_mean_days"], referral_cfg["delay_sd_days"])))
        oncology_date = urology_date + pd.Timedelta(days=delay) if referral else pd.NaT
        common = {
            "patient_id": pid,
            "provider_id": provider.provider_id,
            "organization_id": provider.organization_id,
            "care_setting": provider.care_setting,
            "synthetic_event_flag": True,
        }
        rows.append(
            {
                **common,
                "encounter_id": f"ENC-{i:08d}-0",
                "encounter_date": dx_date,
                "encounter_type": "diagnosis",
                "specialty": "urology",
                "referral_flag": False,
                "referral_source_specialty": pd.NA,
                "referral_target_specialty": pd.NA,
                "referral_date": pd.NaT,
                "referral_completed_flag": False,
                "referral_completion_date": pd.NaT,
            }
        )
        rows.append(
            {
                **common,
                "encounter_id": f"ENC-{i:08d}-1",
                "encounter_date": urology_date,
                "encounter_type": "urology_follow_up",
                "specialty": "urology",
                "referral_flag": referral,
                "referral_source_specialty": "urology" if referral else pd.NA,
                "referral_target_specialty": "medical_oncology" if referral else pd.NA,
                "referral_date": urology_date if referral else pd.NaT,
                "referral_completed_flag": referral,
                "referral_completion_date": oncology_date,
            }
        )
        if referral:
            rows.append(
                {
                    **common,
                    "encounter_id": f"ENC-{i:08d}-2",
                    "encounter_date": oncology_date,
                    "encounter_type": "oncology_consultation",
                    "specialty": "medical_oncology",
                    "referral_flag": False,
                    "referral_source_specialty": "urology",
                    "referral_target_specialty": "medical_oncology",
                    "referral_date": urology_date,
                    "referral_completed_flag": True,
                    "referral_completion_date": oncology_date,
                }
            )
    return pd.DataFrame(rows)


def build_patient_journey(
    patient: pd.DataFrame,
    diagnosis: pd.DataFrame,
    providers_assigned: pd.DataFrame,
    eligibility: pd.DataFrame,
    encounter: pd.DataFrame,
    treatment: pd.DataFrame,
    prescription_event: pd.DataFrame,
    outcome: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """Build the one-row-per-patient gold analytical table."""
    base = patient[["patient_id", "age_at_index", "comorbidity_score", "frailty_proxy", "region", "insurance_type", "synthetic_scenario_version"]].copy()
    base = base.merge(
        diagnosis[["patient_id", "prostate_stage", "metastatic_flag", "hormone_sensitive_flag", "castration_resistant_flag"]],
        on="patient_id",
    ).merge(eligibility.drop(columns="synthetic_contraindication_flag"), on="patient_id")
    provider_cols = providers_assigned[["care_setting", "provider_specialty", "multidisciplinary_team_flag"]].rename(
        columns={"care_setting": "initial_care_setting", "provider_specialty": "initial_provider_specialty"}
    ).reset_index(drop=True)
    base = pd.concat([base.reset_index(drop=True), provider_cols], axis=1)
    urology = encounter[encounter.encounter_type == "urology_follow_up"].groupby("patient_id").encounter_date.min()
    oncology = encounter[encounter.encounter_type == "oncology_consultation"].groupby("patient_id").encounter_date.min()
    base["first_urology_date"] = base.patient_id.map(urology)
    base["first_oncology_date"] = base.patient_id.map(oncology)
    base["referral_completed_flag"] = base.first_oncology_date.notna()
    base["referral_delay_days"] = (base.first_oncology_date - base.first_urology_date).dt.days.astype("Int64")
    starts = treatment.sort_values("treatment_start_date").groupby("patient_id").first() if not treatment.empty else pd.DataFrame()
    if not starts.empty and not prescription_event.empty:
        initial_treatment_ids = starts["treatment_id"]
        initial_events = prescription_event[prescription_event.treatment_id.isin(initial_treatment_ids)].sort_values("service_date")
        event_summary = initial_events.groupby("treatment_id").agg(
            prescription_event_count=("prescription_event_id", "size"),
            event_coverage_until_date=("covered_until_date", "max"),
            event_max_refill_gap_days=("refill_gap_days", "max"),
        )
    else:
        event_summary = pd.DataFrame(columns=[
            "prescription_event_count", "event_coverage_until_date", "event_max_refill_gap_days",
        ])
    base["prescription_event_count"] = base.patient_id.map(starts["treatment_id"].map(event_summary["prescription_event_count"]) if not starts.empty else pd.Series(dtype="float64")).fillna(0).astype("int64")
    base["max_refill_gap_days"] = base.patient_id.map(starts["treatment_id"].map(event_summary["event_max_refill_gap_days"]) if not starts.empty else pd.Series(dtype="float64")).fillna(0).astype("int64")
    event_coverage_until = base.patient_id.map(starts["treatment_id"].map(event_summary["event_coverage_until_date"]) if not starts.empty else pd.Series(dtype="datetime64[ns]"))
    for target, source in {
        "initial_treatment": "drug_name",
        "initial_treatment_class": "drug_class",
        "treatment_start_date": "treatment_start_date",
        "discontinuation_flag": "discontinuation_flag",
        "discontinuation_date": "discontinuation_date",
        "discontinuation_reason": "discontinuation_reason",
        "switch_flag": "switch_flag",
        "switch_date": "switch_date",
        "switched_to_drug": "switched_to_drug",
        "restart_flag": "restart_flag",
        "restart_date": "restart_date",
    }.items():
        base[target] = base.patient_id.map(starts[source]) if not starts.empty else pd.NA
    for flag in ("discontinuation_flag", "switch_flag", "restart_flag"):
        base[flag] = base[flag].astype("boolean")
    base["treatment_initiated"] = base.treatment_start_date.notna()
    base["days_to_initiation"] = (base.treatment_start_date - base.eligibility_date).dt.days.astype("Int64")
    for day in (30, 60, 90):
        base[f"initiated_within_{day}d"] = base.eligible_for_arpi & base.days_to_initiation.between(0, day).fillna(False)
    base["eligible_not_initiated_90d"] = base.eligible_for_arpi & ~base.initiated_within_90d
    for months, day in ((3, 90), (6, 180), (12, 365)):
        base[f"persistent_{months}m"] = (
            base.treatment_initiated
            & ((base.treatment_start_date + pd.to_timedelta(day, unit="D")) <= event_coverage_until)
            & (base.max_refill_gap_days <= config["allowable_gap_days"])
            & ~(base.discontinuation_flag.fillna(False) & (base.discontinuation_date <= base.treatment_start_date + pd.to_timedelta(day, unit="D")))
        )
    for gap in config["persistence_sensitivity_gaps"]:
        base[f"persistent_12m_gap_{gap}d"] = base["persistent_12m"] & (
            base.max_refill_gap_days <= gap
        )
    base["discontinued_within_12m"] = base.discontinuation_flag.fillna(False) & (
        (base.discontinuation_date - base.treatment_start_date).dt.days <= 365
    )
    base["days_to_discontinuation"] = (base.discontinuation_date - base.treatment_start_date).dt.days.astype("Int64")
    base["days_to_switch"] = (base.switch_date - base.treatment_start_date).dt.days.astype("Int64")
    base = base.merge(outcome, on="patient_id", how="left")
    base["days_to_progression"] = (base.progression_date - base.eligibility_date).dt.days.astype("Int64")
    base["follow_up_days"] = (base.censor_date - base.eligibility_date).dt.days.clip(lower=0).astype("Int64")
    for months, required_days in ((3, 90), (6, 180), (12, 365)):
        base[f"persistent_{months}m"] &= base.follow_up_days >= required_days
    for gap in config["persistence_sensitivity_gaps"]:
        base[f"persistent_12m_gap_{gap}d"] &= base.follow_up_days >= 365
    base = base.rename(columns={"outcome_status": "final_outcome_status"})
    base["synthetic_data_flag"] = True
    return base
