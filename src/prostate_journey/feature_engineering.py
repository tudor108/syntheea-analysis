"""Leakage-safe feature timing metadata and entity-level data splitting."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

import pandas as pd

IDENTIFIERS = {"patient_id", "source_archetype_id"}
BASELINE_FEATURES = {
    "market_code",
    "country",
    "market_depth",
    "age_at_index",
    "comorbidity_score",
    "frailty_proxy",
    "complexity_segment",
    "region",
    "insurance_type",
    "access_index",
    "socioeconomic_proxy",
}
DIAGNOSIS_FEATURES = {
    "prostate_stage",
    "metastatic_flag",
    "hormone_sensitive_flag",
    "castration_resistant_flag",
    "risk_group",
    "psa_value",
    "gleason_score",
    "isup_grade_group",
}
ELIGIBILITY_FIELDS = {
    "mhspc_flag",
    "denominator_status",
    "eligibility_flag",
    "eligible_for_arpi",
    "eligibility_date",
    "eligibility_reason",
    "ineligibility_reason",
    "clinical_exclusion_reason",
    "contraindication_flag",
    "data_sufficiency_flag",
    "eligibility_rule_version",
}
INITIAL_PATHWAY_FEATURES = {"initial_care_setting", "initial_provider_specialty"}
POST_REFERRAL_FEATURES = {
    "referral_status",
    "referral_completed_flag",
    "referral_delay_days",
    "decision_owner_specialty",
}
ACTIVE_SURVEILLANCE_FIELDS = {
    "active_surveillance_eligible_flag",
    "active_surveillance_status",
    "active_surveillance_start_date",
    "active_surveillance_exit_date",
    "active_surveillance_exit_reason",
    "active_surveillance_reclassification_flag",
    "active_surveillance_reclassification_date",
}
TREATMENT_START_FEATURES = {
    "treatment_episode_id",
    "treatment_start_date",
    "days_to_initiation",
    "initial_regimen",
    "initial_regimen_type",
    "combination_strategy",
    "intensification_flag",
    "regimen_component_count",
}
TARGET_LABELS = {
    "treatment_initiated",
    "initiation_90d_status",
    "initiated_within_30d",
    "initiated_within_60d",
    "initiated_within_90d",
    "eligible_not_initiated_90d",
    "persistence_3m_status",
    "persistent_3m",
    "persistence_6m_status",
    "persistent_6m",
    "persistence_12m_status",
    "persistent_12m",
    "persistence_12m_status_gap_30d",
    "persistent_12m_gap_30d",
    "persistence_12m_status_gap_60d",
    "persistent_12m_gap_60d",
    "persistence_12m_status_gap_90d",
    "persistent_12m_gap_90d",
    "discontinuation_flag",
    "discontinuation_date",
    "switch_flag",
    "switch_date",
    "restart_flag",
    "progression_event",
    "progression_date",
    "hospitalisation_flag",
    "first_hospitalisation_date",
    "adverse_event_flag",
    "death_flag",
    "death_date",
    "lost_to_follow_up_flag",
    "loss_to_follow_up_date",
    "final_outcome_status",
}
FUTURE_DESCRIPTIVE_FIELDS = {
    "pathway_care_setting",
    "prescription_event_count",
    "max_refill_gap_days",
    "event_coverage_until_date",
    "follow_up_days",
    "treatment_follow_up_days",
    "last_observed_date",
    "censor_date",
    "censor_reason",
}
ADMINISTRATIVE_FIELDS = {
    "observation_start_date",
    "observation_end_date",
    "synthetic_data_flag",
    "synthetic_scenario_version",
    "persistence_rule_version",
}


def _timing_rule(feature: str) -> tuple[str, str, bool, bool, str]:
    """Return stage, uses, future flag, predictor flag and availability condition."""
    if feature in IDENTIFIERS:
        return "identifier", "grouping_only", False, False, "never_as_predictor"
    if feature in BASELINE_FEATURES:
        return "baseline", "all_prediction_tasks", False, True, "available_at_index"
    if feature in DIAGNOSIS_FEATURES:
        return "diagnosis", "all_prediction_tasks", False, True, "recorded_by_eligibility_date"
    if feature in ELIGIBILITY_FIELDS:
        return "eligibility", "cohort_definition", False, False, "available_at_eligibility"
    if feature in INITIAL_PATHWAY_FEATURES:
        return "diagnosis_pathway", "all_prediction_tasks", False, True, "first_encounter_only"
    if feature in POST_REFERRAL_FEATURES:
        return (
            "post_referral",
            "pathway_gap,discontinuation_12m_if_observed",
            False,
            True,
            "referral_or_completion_date_le_prediction_index",
        )
    if feature in ACTIVE_SURVEILLANCE_FIELDS:
        return (
            "active_surveillance",
            "as_pathway_target_or_description",
            True,
            False,
            "event_date_le_analysis_cutoff",
        )
    if feature in TREATMENT_START_FEATURES:
        return "treatment_start", "discontinuation_12m", False, True, "available_at_treatment_start"
    if feature in TARGET_LABELS:
        return "target_or_outcome", "target_only", True, False, "never_as_predictor"
    if feature in FUTURE_DESCRIPTIVE_FIELDS:
        return "future", "descriptive_only", True, False, "event_date_le_analysis_cutoff"
    if feature in ADMINISTRATIVE_FIELDS:
        return "administrative", "cohort_governance", False, False, "not_a_model_feature"
    raise ValueError(f"Feature timing is not explicitly classified: {feature}")


def build_feature_timing_metadata(
    journey_columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Document timing and predictor eligibility for every analytical mart field."""
    columns = list(
        journey_columns
        if journey_columns is not None
        else sorted(
            IDENTIFIERS
            | BASELINE_FEATURES
            | DIAGNOSIS_FEATURES
            | ELIGIBILITY_FIELDS
            | INITIAL_PATHWAY_FEATURES
            | POST_REFERRAL_FEATURES
            | ACTIVE_SURVEILLANCE_FIELDS
            | TREATMENT_START_FEATURES
            | TARGET_LABELS
            | FUTURE_DESCRIPTIVE_FIELDS
            | ADMINISTRATIVE_FIELDS
        )
    )
    rows = []
    for index, feature in enumerate(columns):
        stage, uses, future, predictor_allowed, condition = _timing_rule(feature)
        rows.append(
            {
                "feature_metadata_id": f"FTM-{index:04d}",
                "feature_name": feature,
                "availability_stage": stage,
                "allowed_use_cases": uses,
                "future_information_flag": future,
                "predictor_allowed_flag": predictor_allowed,
                "availability_condition": condition,
                "target_label_flag": feature in TARGET_LABELS,
                "timing_rule_version": "FEATURE-TIMING-v2.0",
            }
        )
    return pd.DataFrame(rows)


def build_patient_split(patient: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Assign reproducible market-stratified splits at independent archetype level."""
    split_config = config["splitting"]
    train_cutoff = float(split_config["train"])
    validation_cutoff = train_cutoff + float(split_config["validation"])
    rows = []
    for _, person in patient.iterrows():
        key = f"{config['random_seed']}|{person.market_code}|{person.source_archetype_id}"
        bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16) / float(16**12)
        split = (
            "train"
            if bucket < train_cutoff
            else "validation"
            if bucket < validation_cutoff
            else "test"
        )
        rows.append(
            {
                "patient_split_id": f"SPLIT-{person.patient_id}",
                "patient_id": person.patient_id,
                "source_archetype_id": person.source_archetype_id,
                "market_code": person.market_code,
                "split": split,
                "split_rule_version": split_config["version"],
            }
        )
    return pd.DataFrame(rows)


def treatment_initiation_features(journey: pd.DataFrame) -> pd.DataFrame:
    """Return eligibility-time predictors plus the initiation target."""
    columns = [
        "patient_id",
        *sorted(BASELINE_FEATURES - {"country", "market_depth"}),
        *sorted(DIAGNOSIS_FEATURES),
        *sorted(INITIAL_PATHWAY_FEATURES),
        "eligible_not_initiated_90d",
    ]
    return journey.loc[journey.eligibility_flag, columns].copy()


def discontinuation_features(journey: pd.DataFrame) -> pd.DataFrame:
    """Return treatment-start predictors plus the 12-month persistence target."""
    columns = [
        "patient_id",
        *sorted(BASELINE_FEATURES - {"country", "market_depth"}),
        *sorted(DIAGNOSIS_FEATURES),
        *sorted(INITIAL_PATHWAY_FEATURES),
        *sorted(TREATMENT_START_FEATURES - {"treatment_episode_id"}),
        "persistence_12m_status",
    ]
    return journey.loc[journey.treatment_initiated, columns].copy()


def pathway_gap_features(journey: pd.DataFrame) -> pd.DataFrame:
    """Return diagnosis-time predictors plus the referral-completion target."""
    columns = [
        "patient_id",
        *sorted(BASELINE_FEATURES - {"country", "market_depth"}),
        *sorted(DIAGNOSIS_FEATURES),
        *sorted(INITIAL_PATHWAY_FEATURES),
        "referral_completed_flag",
    ]
    return journey[columns].copy()


def model_ready_features(journey: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible alias for treatment-initiation features."""
    return treatment_initiation_features(journey)
