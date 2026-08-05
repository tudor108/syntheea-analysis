"""Leakage-safe analytical features."""
from __future__ import annotations

import pandas as pd


def model_ready_features(journey: pd.DataFrame) -> pd.DataFrame:
    """Return baseline-only features suitable for a non-initiation model demo."""
    columns = [
        "patient_id", "age_at_index", "comorbidity_score", "frailty_proxy", "region",
        "insurance_type", "prostate_stage", "metastatic_flag", "initial_care_setting",
        "initial_provider_specialty", "referral_delay_days", "eligible_not_initiated_90d",
    ]
    return journey[columns].copy()

