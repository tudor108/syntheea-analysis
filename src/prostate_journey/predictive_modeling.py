"""Leakage-safe synthetic prediction data, validation, and calibration methods."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

PRIMARY_PATHWAY = "mhspc_mcspc"
MODEL_TARGETS = {
    "non_initiation_90d": "non_initiated_within_90_days",
    "discontinuation_12m": "discontinued_within_12_months",
    "treatment_switch_12m": "switched_treatment",
    "restart_after_gap": "restarted_after_gap",
}
Z_975 = 1.959963984540054


class LeakageViolation(ValueError):
    """Raised when a predictor, timestamp, split, or identity leaks prohibited information."""


def _as_datetime(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result:
            result[column] = pd.to_datetime(result[column], errors="coerce")
    return result


def _age_band(value: Any) -> str:
    if pd.isna(value):
        return "MISSING"
    age = float(value)
    if age < 65:
        return "LT_65"
    if age < 75:
        return "65_74"
    return "GE_75"


def _volume_band(value: Any) -> str:
    if pd.isna(value):
        return "MISSING"
    if float(value) < 150:
        return "LOW_LT_150"
    if float(value) < 300:
        return "MEDIUM_150_299"
    return "HIGH_GE_300"


def _calendar_period(value: Any) -> str:
    date = pd.Timestamp(value)
    if date.year <= 2020:
        return "2019_2020"
    if date.year <= 2022:
        return "2021_2022"
    return "2023_2024"


def _derivation_row(
    model_id: str,
    order: int,
    step: str,
    reason: str,
    entered_n: int,
    retained_n: int,
) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "step_order": order,
        "derivation_step": step,
        "reason": reason,
        "entered_n": entered_n,
        "excluded_n": entered_n - retained_n,
        "retained_n": retained_n,
        "reconciliation_difference": entered_n - (entered_n - retained_n) - retained_n,
    }


def _record_filter(
    rows: list[dict[str, Any]],
    model_id: str,
    order: int,
    step: str,
    reason: str,
    before: pd.DataFrame,
    mask: pd.Series,
) -> pd.DataFrame:
    retained = before.loc[mask.fillna(False)].copy()
    rows.append(_derivation_row(model_id, order, step, reason, len(before), len(retained)))
    return retained


def build_feature_frame(
    base: pd.DataFrame,
    tables: Mapping[str, pd.DataFrame],
    *,
    prediction_stage: str,
    numeric_features: Sequence[str],
    categorical_features: Sequence[str],
) -> pd.DataFrame:
    """Derive only information available by each row's explicit prediction time."""
    frame = _as_datetime(base, ["prediction_index_date", "outcome_date"])
    patient = tables["patient"][
        [
            "patient_id",
            "age_at_index",
            "comorbidity_score",
            "frailty_proxy",
            "access_index",
            "insurance_type",
            "market_code",
        ]
    ]
    diagnosis = _as_datetime(
        tables["diagnosis"][["patient_id", "diagnosis_date", "metastatic_date", "metastatic_site"]],
        ["diagnosis_date", "metastatic_date"],
    )
    frame = frame.merge(patient, on="patient_id", how="left", validate="one_to_one")
    frame = frame.merge(diagnosis, on="patient_id", how="left", validate="one_to_one")

    def map_patient_dates(values: pd.Series) -> pd.Series:
        if values.empty:
            return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        mapping = {str(key): value for key, value in values.items()}
        return pd.to_datetime(frame.patient_id.astype(str).map(mapping), errors="coerce")

    encounter = _as_datetime(tables["encounter"], ["encounter_date"])
    encounters = encounter.merge(
        frame[["patient_id", "prediction_index_date"]], on="patient_id", how="inner"
    )
    prior_encounters = encounters.loc[
        encounters.encounter_date.lt(encounters.prediction_index_date)
    ].copy()
    prior_180 = prior_encounters.loc[
        prior_encounters.encounter_date.ge(
            prior_encounters.prediction_index_date - pd.Timedelta(days=180)
        )
    ]
    utilization = prior_180.groupby("patient_id").size()
    prior_hospital = (
        prior_encounters.assign(
            _hospital=prior_encounters.encounter_type.astype(str)
            .str.lower()
            .str.contains(r"hospital|inpatient|emergency|\bed\b", regex=True)
        )
        .groupby("patient_id")
        ._hospital.max()
    )
    baseline_encounters = encounters.loc[
        encounters.encounter_date.le(encounters.prediction_index_date)
    ].sort_values(["patient_id", "encounter_date", "sequence_number", "encounter_id"])
    last_encounter = baseline_encounters.drop_duplicates("patient_id", keep="last").set_index(
        "patient_id"
    )
    max_encounter = baseline_encounters.groupby("patient_id").encounter_date.max()
    frame["prior_healthcare_utilization_180d"] = (
        frame.patient_id.map(utilization).fillna(0).astype(int)
    )
    frame["prior_hospitalization"] = (
        frame.patient_id.map(prior_hospital).fillna(False).map({True: "YES", False: "NO"})
    )
    frame["care_setting"] = frame.patient_id.map(last_encounter.care_setting)
    frame["provider_specialty"] = frame.patient_id.map(last_encounter.provider_specialty)
    frame["_max_encounter_feature_date"] = map_patient_dates(max_encounter)
    frame["_safe_provider_id"] = frame.patient_id.map(last_encounter.provider_id)

    treatment = _as_datetime(tables["treatment_episode"], ["treatment_start_date"])
    if prediction_stage == "treatment_start":
        episode_provider = treatment.set_index("treatment_episode_id").prescribing_provider_id
        supplied = frame.treatment_episode_id.map(episode_provider)
        frame["_safe_provider_id"] = supplied.fillna(frame._safe_provider_id)
    provider = tables["provider"].set_index("provider_id")
    frame["care_setting"] = frame._safe_provider_id.map(provider.care_setting).fillna(
        frame.care_setting
    )
    frame["provider_specialty"] = frame._safe_provider_id.map(provider.provider_specialty).fillna(
        frame.provider_specialty
    )
    frame["provider_volume_band"] = frame._safe_provider_id.map(
        provider.annual_prostate_volume
    ).map(_volume_band)

    referral = _as_datetime(tables["referral"], ["referral_date", "completion_date"])
    referrals = referral.merge(
        frame[["patient_id", "prediction_index_date"]], on="patient_id", how="inner"
    )
    baseline_referrals = referrals.loc[
        referrals.referral_date.le(referrals.prediction_index_date)
    ].copy()
    baseline_referrals["completed_by_index"] = baseline_referrals.referral_status.eq(
        "completed"
    ) & baseline_referrals.completion_date.le(baseline_referrals.prediction_index_date)
    referral_state = baseline_referrals.groupby("patient_id").completed_by_index.max()
    frame["referral_proxy"] = np.where(
        frame.patient_id.map(referral_state).fillna(False),
        "COMPLETED_BY_INDEX",
        np.where(
            frame.patient_id.isin(set(baseline_referrals.patient_id.astype(str))),
            "RECORDED_NOT_COMPLETED_BY_INDEX",
            "NO_PRE_INDEX_REFERRAL",
        ),
    )
    frame["_max_referral_feature_date"] = map_patient_dates(
        baseline_referrals.groupby("patient_id").referral_date.max()
    )
    completed_used = baseline_referrals.loc[baseline_referrals.completed_by_index]
    frame["_max_referral_completion_feature_date"] = map_patient_dates(
        completed_used.groupby("patient_id").completion_date.max()
    )

    episodes = treatment.merge(
        frame[["patient_id", "prediction_index_date"]], on="patient_id", how="inner"
    )
    prior_treatments = episodes.loc[
        episodes.treatment_start_date.lt(episodes.prediction_index_date)
    ]
    prior_treatment_count = prior_treatments.groupby("patient_id").size()
    frame["prior_treatment_count"] = (
        frame.patient_id.map(prior_treatment_count).fillna(0).astype(int)
    )
    frame["prior_treatment_status"] = np.where(
        frame.prior_treatment_count.gt(0), "PRIOR_TREATMENT", "NO_PRIOR_TREATMENT"
    )
    frame["_max_prior_treatment_feature_date"] = map_patient_dates(
        prior_treatments.groupby("patient_id").treatment_start_date.max()
    )

    diagnosis_available = frame.diagnosis_date.le(frame.prediction_index_date)
    metastasis_available = frame.metastatic_date.le(frame.prediction_index_date)
    frame["metastatic_site"] = frame.metastatic_site.where(metastasis_available)
    frame["disease_state"] = frame.get("pathway_disease_state", "mHSPC")
    frame["age_band"] = frame.age_at_index.map(_age_band)
    frame["time_since_diagnosis_days"] = (
        frame.prediction_index_date - frame.diagnosis_date.where(diagnosis_available)
    ).dt.days
    frame["time_since_metastasis_days"] = (
        frame.prediction_index_date - frame.metastatic_date.where(metastasis_available)
    ).dt.days
    frame["calendar_period"] = frame.prediction_index_date.map(_calendar_period)
    model_features = list(numeric_features) + list(categorical_features)
    frame["missingness_pattern"] = np.select(
        [
            frame[model_features].isna().sum(axis=1).eq(0),
            frame[model_features].isna().sum(axis=1).eq(1),
        ],
        ["NO_MISSING", "ONE_MISSING"],
        default="TWO_PLUS_MISSING",
    )
    return frame.drop(columns=["_safe_provider_id"])


def build_model_datasets(
    flags: pd.DataFrame,
    persistence: pd.DataFrame,
    tables: Mapping[str, pd.DataFrame],
    evaluation_config: Mapping[str, Any],
    *,
    initiation_window_days: int = 90,
    persistence_gap_days: int = 60,
    horizon_days: int = 365,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Derive four one-row-per-patient targets and a fully reconciled population chain."""
    numeric = list(map(str, evaluation_config["features"]["numeric"]))
    categorical = list(map(str, evaluation_config["features"]["categorical"]))
    flags = _as_datetime(
        flags,
        ["cohort_index_date", "censor_date", "initiation_date"],
    )
    persistence = _as_datetime(
        persistence,
        ["treatment_start_date", "persistence_endpoint_date", "restart_date", "censor_date"],
    )
    total_patients = int(tables["patient"].patient_id.nunique())
    derivation: list[dict[str, Any]] = []
    if "pathway_membership" not in flags:
        raise ValueError("Cohort flags must contain explicit pathway_membership")

    initiation_model_id = "non_initiation_90d"
    pathway = flags.loc[
        flags.pathway.eq(PRIMARY_PATHWAY) & flags.pathway_membership.fillna(False)
    ].copy()
    derivation.append(
        _derivation_row(
            initiation_model_id,
            1,
            "all_analytical_patients_to_primary_pathway",
            "Select the explicit recorded mHSPC pathway row (legacy key: mhspc_mcspc).",
            total_patients,
            len(pathway),
        )
    )
    primary = _record_filter(
        derivation,
        initiation_model_id,
        2,
        "proposed_eligibility",
        "eligible_candidate = true",
        pathway,
        pathway.eligible_candidate.fillna(False),
    )
    primary = _record_filter(
        derivation,
        initiation_model_id,
        3,
        "valid_prediction_time",
        "cohort_index_date is observed",
        primary,
        primary.cohort_index_date.notna(),
    )
    observable_column = f"observable_for_{initiation_window_days}d"
    outcome_column = f"initiated_within_{initiation_window_days}d"
    if observable_column not in primary or outcome_column not in primary:
        raise ValueError(f"Unsupported initiation window: {initiation_window_days}")
    primary = _record_filter(
        derivation,
        initiation_model_id,
        4,
        f"observable_through_day_{initiation_window_days}",
        f"{observable_column} = true; early censoring excluded",
        primary,
        primary[observable_column].fillna(False),
    )
    primary = _record_filter(
        derivation,
        initiation_model_id,
        5,
        "determinate_binary_outcome",
        f"{outcome_column} is observed",
        primary,
        primary[outcome_column].notna(),
    )
    if primary.patient_id.duplicated(keep=False).any():
        raise LeakageViolation("Duplicate patient rows in the initiation model source")
    before_dedup = len(primary)
    primary = primary.sort_values(["cohort_index_date", "patient_id"]).drop_duplicates(
        "patient_id", keep="first"
    )
    derivation.append(
        _derivation_row(
            initiation_model_id,
            6,
            "one_row_per_patient",
            "Deterministic patient deduplication; duplicates are a gate failure.",
            before_dedup,
            len(primary),
        )
    )
    initiation_base = primary[
        [
            "patient_id",
            "cohort_index_date",
            "pathway_disease_state",
            "initiation_date",
            outcome_column,
        ]
    ].rename(columns={"cohort_index_date": "prediction_index_date"})
    initiation_base["target"] = (~initiation_base[outcome_column].astype(bool)).astype(int)
    initiation_base["outcome_date"] = initiation_base.initiation_date.where(
        initiation_base[outcome_column].astype(bool),
        initiation_base.prediction_index_date + pd.Timedelta(days=initiation_window_days),
    )
    initiation_features = build_feature_frame(
        initiation_base,
        tables,
        prediction_stage="eligibility",
        numeric_features=numeric,
        categorical_features=categorical,
    )
    initiation_features["target_name"] = "non_initiated_within_90_days"
    initiation_features["target_horizon_days"] = initiation_window_days

    p_source = persistence.loc[
        persistence.pathway.eq(PRIMARY_PATHWAY)
        & persistence.gap_threshold_days.eq(persistence_gap_days)
    ].copy()
    treatment_base_count = len(p_source)
    common_treatment_steps = [
        _derivation_row(
            model_id,
            1,
            "all_analytical_patients_to_initiators",
            (
                "Select primary-pathway initiators under the "
                f"{persistence_gap_days}-day gap specification."
            ),
            total_patients,
            treatment_base_count,
        )
        for model_id in ("discontinuation_12m", "treatment_switch_12m", "restart_after_gap")
    ]
    derivation.extend(common_treatment_steps)
    valid_time = p_source.treatment_start_date.notna()
    for model_id in ("discontinuation_12m", "treatment_switch_12m", "restart_after_gap"):
        derivation.append(
            _derivation_row(
                model_id,
                2,
                "valid_prediction_time",
                "treatment_start_date is observed",
                len(p_source),
                int(valid_time.sum()),
            )
        )
    p_source = p_source.loc[valid_time].copy()
    if p_source.patient_id.duplicated(keep=False).any():
        raise LeakageViolation("Duplicate patient rows in the persistence model source")
    if p_source.treatment_episode_id.isna().any():
        raise LeakageViolation("Persistence model source contains a missing treatment episode ID")
    by_horizon = p_source.days_to_persistence_endpoint.le(horizon_days)
    event_free_beyond = p_source.days_to_persistence_endpoint.gt(horizon_days)
    horizon_date = p_source.treatment_start_date + pd.Timedelta(days=horizon_days)
    gap_failure_by_horizon = by_horizon & p_source.persistence_failure_flag.fillna(False)
    restart_class = p_source.event_classification.eq("TEMPORARY_GAP_RESTARTED")
    dated_restart = restart_class & p_source.restart_date.notna()
    invalid_restart_chronology = dated_restart & (
        p_source.restart_date.lt(p_source.persistence_endpoint_date)
        | p_source.restart_date.gt(p_source.censor_date)
    )
    if invalid_restart_chronology.any():
        raise LeakageViolation(
            "Restart target contains a restart date before its gap or after observation ended"
        )
    restart_by_horizon = (
        gap_failure_by_horizon & dated_restart & p_source.restart_date.le(horizon_date)
    )
    no_restart_through_horizon = (
        gap_failure_by_horizon
        & p_source.censor_date.ge(horizon_date)
        & (~restart_class | (dated_restart & p_source.restart_date.gt(horizon_date)))
    )

    definitions = {
        "discontinuation_12m": (
            (by_horizon & p_source.persistence_failure_flag.fillna(False)) | event_free_beyond,
            (by_horizon & p_source.persistence_failure_flag.fillna(False)).astype(int),
            (
                "persistence failure by horizon or event-free beyond horizon; earlier "
                "competing/censoring excluded"
            ),
        ),
        "treatment_switch_12m": (
            (by_horizon & p_source.event_classification.eq("SWITCHED")) | event_free_beyond,
            (by_horizon & p_source.event_classification.eq("SWITCHED")).astype(int),
            "switch by horizon or event-free beyond horizon; earlier other states excluded",
        ),
        "restart_after_gap": (
            restart_by_horizon | no_restart_through_horizon,
            restart_by_horizon.astype(int),
            (
                "qualifying persistence failure by horizon plus dated restart by horizon or "
                "observation through horizon without restart; undated/early-censored status "
                "excluded"
            ),
        ),
    }
    datasets: dict[str, pd.DataFrame] = {"non_initiated_within_90_days": initiation_features}
    for model_id, (known, label, reason) in definitions.items():
        selected = p_source.loc[known].copy()
        derivation.append(
            _derivation_row(
                model_id,
                3,
                "determinate_horizon_outcome",
                reason,
                len(p_source),
                len(selected),
            )
        )
        if selected.patient_id.duplicated(keep=False).any():
            raise LeakageViolation(f"Duplicate patient rows for model target: {model_id}")
        before_dedup = len(selected)
        selected = selected.sort_values(
            ["treatment_start_date", "patient_id", "treatment_episode_id"]
        ).drop_duplicates("patient_id", keep="first")
        derivation.append(
            _derivation_row(
                model_id,
                4,
                "one_row_per_patient",
                "Deterministic patient deduplication; duplicates are a gate failure.",
                before_dedup,
                len(selected),
            )
        )
        selected["target"] = label.loc[selected.index].astype(int)
        outcome_horizon = selected.treatment_start_date + pd.Timedelta(days=horizon_days)
        if model_id == "restart_after_gap":
            selected["_model_outcome_date"] = selected.restart_date.where(
                selected.target.eq(1), outcome_horizon
            )
        else:
            selected["_model_outcome_date"] = selected.persistence_endpoint_date.where(
                selected.target.eq(1), outcome_horizon
            )
        target_name = MODEL_TARGETS[model_id]
        base = selected[
            [
                "patient_id",
                "treatment_episode_id",
                "treatment_start_date",
                "disease_state",
                "_model_outcome_date",
                "target",
            ]
        ].rename(
            columns={
                "treatment_start_date": "prediction_index_date",
                "disease_state": "pathway_disease_state",
                "_model_outcome_date": "outcome_date",
            }
        )
        featured = build_feature_frame(
            base,
            tables,
            prediction_stage="treatment_start",
            numeric_features=numeric,
            categorical_features=categorical,
        )
        featured["target_name"] = target_name
        featured["target_horizon_days"] = horizon_days
        datasets[target_name] = featured

    derivation_frame = pd.DataFrame(derivation).sort_values(
        ["model_id", "step_order"], kind="stable", ignore_index=True
    )
    if not derivation_frame.reconciliation_difference.eq(0).all():
        raise AssertionError("Model population derivation does not reconcile")
    expected = {model_id: len(datasets[target]) for model_id, target in MODEL_TARGETS.items()}
    final_counts = derivation_frame.groupby("model_id").tail(1).set_index("model_id").retained_n
    if any(int(final_counts[model_id]) != count for model_id, count in expected.items()):
        raise AssertionError("Final model populations do not match derivation table")
    for target_name, frame in datasets.items():
        if frame.patient_id.duplicated().any():
            raise LeakageViolation(f"Duplicate patient in model population: {target_name}")
    return datasets, derivation_frame


def audit_feature_frame(
    frame: pd.DataFrame,
    selected_features: Sequence[str],
    prohibited_features: Sequence[str],
    *,
    target_name: str,
) -> pd.DataFrame:
    """Run aggregate sentinels for direct, temporal, outcome, identity, and market leakage."""
    selected = set(map(str, selected_features))
    prohibited = set(map(str, prohibited_features))
    rows: list[dict[str, Any]] = []

    def add(check: str, failures: int, detail: str) -> None:
        rows.append(
            {
                "target": target_name,
                "scope": "model_population",
                "check": check,
                "status": "PASS" if failures == 0 else "FAIL",
                "failure_count": int(failures),
                "detail": detail,
            }
        )

    missing_features = selected - set(frame.columns)
    add(
        "selected_features_present",
        len(missing_features),
        f"missing selected features={sorted(missing_features)}",
    )
    direct_leaks = selected & prohibited
    add(
        "prohibited_feature_sentinel",
        len(direct_leaks),
        f"prohibited selected features={sorted(direct_leaks)}",
    )
    add(
        "one_row_per_patient",
        int(frame.patient_id.duplicated().sum()),
        "patient and episode duplication is prohibited",
    )
    add(
        "prediction_time_complete",
        int(frame.prediction_index_date.isna().sum()),
        "every model row requires explicit time zero",
    )
    target_numeric = pd.to_numeric(frame.target, errors="coerce")
    add(
        "binary_target",
        int((target_numeric.isna() | ~target_numeric.isin([0, 1])).sum()),
        "target values must be complete and binary",
    )
    for column in (
        "_max_encounter_feature_date",
        "_max_referral_feature_date",
        "_max_referral_completion_feature_date",
        "_max_prior_treatment_feature_date",
    ):
        timestamp = pd.to_datetime(frame[column], errors="coerce")
        index = pd.to_datetime(frame.prediction_index_date, errors="coerce")
        failures = int((timestamp.notna() & timestamp.gt(index)).sum())
        add(
            f"{column.removeprefix('_max_')}_not_after_prediction_time",
            failures,
            "all contributing event timestamps must be on/before time zero",
        )
    outcome = pd.to_datetime(frame.outcome_date, errors="coerce")
    index = pd.to_datetime(frame.prediction_index_date, errors="coerce")
    add(
        "outcome_ascertainment_time_complete",
        int(outcome.isna().sum()),
        "every binary target requires an explicit ascertainment time",
    )
    horizon_days = pd.to_numeric(frame.target_horizon_days, errors="coerce")
    add(
        "positive_target_horizon_complete",
        int((horizon_days.isna() | horizon_days.le(0)).sum()),
        "every row requires a positive declared prediction horizon",
    )
    add(
        "outcome_not_before_prediction_time",
        int((outcome.notna() & outcome.lt(index)).sum()),
        "the outcome/ascertainment date cannot precede prediction",
    )
    horizon_end = index + pd.to_timedelta(horizon_days, unit="D")
    add(
        "outcome_not_after_declared_horizon",
        int((outcome.notna() & outcome.gt(horizon_end)).sum()),
        "the binary target must be fully ascertained within its declared horizon",
    )
    add(
        "market_complete_for_holdout",
        int(frame.market_code.isna().sum()),
        "market is required for leave-one-market-out evaluation",
    )
    return pd.DataFrame(rows)


def raise_on_leakage(audit: pd.DataFrame) -> None:
    """Block model evaluation when any leakage sentinel fails."""
    failures = audit.loc[audit.status.eq("FAIL")]
    if not failures.empty:
        detail = "; ".join(
            f"{row.target}/{row.check}={row.failure_count}"
            for row in failures.itertuples(index=False)
        )
        raise LeakageViolation(f"Predictive leakage gate failed: {detail}")


def audit_partition(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    target_name: str,
    fold_id: str,
    design: str,
    holdout_market: str | None = None,
) -> pd.DataFrame:
    """Prove patient, temporal, and market isolation for one outer validation fold."""
    overlap = set(train.patient_id.astype(str)) & set(test.patient_id.astype(str))
    rows = [
        {
            "target": target_name,
            "scope": fold_id,
            "check": "patient_isolation",
            "status": "PASS" if not overlap else "FAIL",
            "failure_count": len(overlap),
            "detail": "no patient may occur in both outer train and validation",
        }
    ]
    if design in {"ROLLING_TEMPORAL", "FINAL_TEMPORAL_HOLDOUT"}:
        train_max = pd.Timestamp(train.prediction_index_date.max())
        test_min = pd.Timestamp(test.prediction_index_date.min())
        failures = int(train_max >= test_min)
        rows.append(
            {
                "target": target_name,
                "scope": fold_id,
                "check": "strict_temporal_isolation",
                "status": "PASS" if failures == 0 else "FAIL",
                "failure_count": failures,
                "detail": f"train_max={train_max.date()}; validation_min={test_min.date()}",
            }
        )
    if design == "LEAVE_ONE_MARKET_OUT":
        if holdout_market is None:
            raise ValueError("Leave-one-market-out audit requires a holdout market")
        contamination = int(train.market_code.eq(holdout_market).sum())
        wrong_test = int(test.market_code.ne(holdout_market).sum())
        failures = contamination + wrong_test
        rows.append(
            {
                "target": target_name,
                "scope": fold_id,
                "check": "market_isolation",
                "status": "PASS" if failures == 0 else "FAIL",
                "failure_count": failures,
                "detail": f"holdout_market={holdout_market}; train and test markets are isolated",
            }
        )
    return pd.DataFrame(rows)


@dataclass
class FeatureEncoder:
    """Median/scale/reference encoder fitted on an explicitly supplied training subset."""

    numeric_features: list[str]
    categorical_features: list[str]
    medians: dict[str, float]
    means: dict[str, float]
    scales: dict[str, float]
    categories: dict[str, list[str]]
    encoded_names: list[str]
    source_features: list[str]

    @classmethod
    def fit(
        cls,
        frame: pd.DataFrame,
        numeric_features: Sequence[str],
        categorical_features: Sequence[str],
    ) -> FeatureEncoder:
        numeric: list[str] = []
        categorical: list[str] = []
        medians: dict[str, float] = {}
        means: dict[str, float] = {}
        scales: dict[str, float] = {}
        categories: dict[str, list[str]] = {}
        encoded_names: list[str] = []
        sources: list[str] = []
        for feature in numeric_features:
            values = pd.to_numeric(frame[feature], errors="coerce")
            if not values.notna().any():
                continue
            median = float(values.median())
            filled = values.fillna(median)
            scale = float(filled.std(ddof=0))
            if not math.isfinite(scale) or scale < 1e-10:
                continue
            numeric.append(str(feature))
            medians[str(feature)] = median
            means[str(feature)] = float(filled.mean())
            scales[str(feature)] = scale
            encoded_names.append(f"{feature} (per training SD)")
            sources.append(str(feature))
        for feature in categorical_features:
            values = frame[feature].astype("string").fillna("MISSING")
            levels = sorted(map(str, values.unique().tolist()))
            if len(levels) <= 1:
                continue
            categorical.append(str(feature))
            encoded_levels = [*levels, "__UNSEEN__"]
            categories[str(feature)] = encoded_levels
            for level in encoded_levels[1:]:
                encoded_names.append(f"{feature}={level} vs {levels[0]}")
                sources.append(str(feature))
        return cls(
            numeric,
            categorical,
            medians,
            means,
            scales,
            categories,
            encoded_names,
            sources,
        )

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        columns: list[np.ndarray] = []
        for feature in self.numeric_features:
            values = pd.to_numeric(frame[feature], errors="coerce").fillna(self.medians[feature])
            columns.append(
                ((values.to_numpy(dtype=float) - self.means[feature]) / self.scales[feature])[
                    :, None
                ]
            )
        for feature in self.categorical_features:
            values = frame[feature].astype("string").fillna("MISSING")
            known = self.categories[feature][:-1]
            values = values.where(values.isin(known), "__UNSEEN__")
            for level in self.categories[feature][1:]:
                columns.append(values.eq(level).to_numpy(dtype=float)[:, None])
        return np.hstack(columns) if columns else np.empty((len(frame), 0))


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -35, 35)))


def fit_logistic(
    matrix: np.ndarray,
    target: np.ndarray,
    *,
    l2_penalty: float = 1.0,
    max_iterations: int = 100,
) -> tuple[np.ndarray, int]:
    """Fit transparent L2 logistic regression with Newton/IRLS updates."""
    if len(target) == 0 or len(np.unique(target)) < 2:
        raise ValueError("Logistic fitting requires both outcome classes")
    design = np.column_stack([np.ones(len(matrix)), matrix])
    coefficients = np.zeros(design.shape[1], dtype=float)
    prevalence = float(np.clip(target.mean(), 1e-6, 1 - 1e-6))
    coefficients[0] = math.log(prevalence / (1 - prevalence))
    penalty = np.eye(design.shape[1]) * l2_penalty
    penalty[0, 0] = 0.0
    iterations = max_iterations
    for iteration in range(max_iterations):
        probability = _sigmoid(design @ coefficients)
        weights = np.clip(probability * (1 - probability), 1e-7, None)
        gradient = design.T @ (target - probability) - penalty @ coefficients
        information = (design.T * weights) @ design + penalty
        try:
            step = np.linalg.solve(information, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(information) @ gradient
        coefficients += step
        if float(np.max(np.abs(step))) < 1e-7:
            iterations = iteration + 1
            break
    return coefficients, iterations


def predict_logistic(matrix: np.ndarray, coefficients: np.ndarray) -> np.ndarray:
    return _sigmoid(np.column_stack([np.ones(len(matrix)), matrix]) @ coefficients)


def roc_auc(target: np.ndarray, probability: np.ndarray) -> float | None:
    positives = int(target.sum())
    negatives = len(target) - positives
    if positives == 0 or negatives == 0:
        return None
    ranks = pd.Series(probability).rank(method="average").to_numpy()
    rank_sum = float(ranks[target == 1].sum())
    return float((rank_sum - positives * (positives + 1) / 2) / (positives * negatives))


def pr_auc(target: np.ndarray, probability: np.ndarray) -> float | None:
    """Average precision, reported as the step-wise area under the precision-recall curve."""
    positives = int(target.sum())
    if positives == 0:
        return None
    order = np.argsort(-probability, kind="stable")
    ordered_target = target[order]
    ordered_probability = probability[order]
    threshold_ends = np.r_[
        np.flatnonzero(np.diff(ordered_probability) != 0), len(ordered_probability) - 1
    ]
    true_positive = np.cumsum(ordered_target)[threshold_ends]
    predicted_positive = threshold_ends + 1
    precision = true_positive / predicted_positive
    recall = true_positive / positives
    recall_increment = np.diff(np.r_[0.0, recall])
    return float(np.sum(recall_increment * precision))


def brier_score(target: np.ndarray, probability: np.ndarray) -> float:
    return float(np.mean((probability - target) ** 2))


def calibration_intercept_slope(
    target: np.ndarray, probability: np.ndarray
) -> tuple[float | None, float | None]:
    """Estimate calibration intercept and slope without modifying validation predictions."""
    if len(target) < 5 or len(np.unique(target)) < 2:
        return None, None
    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    logit = np.log(clipped / (1 - clipped))
    if float(np.std(logit)) < 1e-10:
        observed = float(np.clip(target.mean(), 1e-6, 1 - 1e-6))
        predicted = float(np.clip(clipped.mean(), 1e-6, 1 - 1e-6))
        intercept = math.log(observed / (1 - observed)) - math.log(predicted / (1 - predicted))
        return intercept, None
    coefficients, _ = fit_logistic(logit[:, None], target.astype(float), l2_penalty=1e-8)
    return float(coefficients[0]), float(coefficients[1])


def _metric_values(target: np.ndarray, probability: np.ndarray) -> dict[str, float | None]:
    intercept, slope = calibration_intercept_slope(target, probability)
    return {
        "roc_auc": roc_auc(target, probability),
        "pr_auc": pr_auc(target, probability),
        "brier_score": brier_score(target, probability),
        "calibration_intercept": intercept,
        "calibration_slope": slope,
    }


def bootstrap_metric_intervals(
    target: np.ndarray,
    probability: np.ndarray,
    *,
    repeats: int,
    seed: int,
) -> dict[str, float | None]:
    """Patient-level percentile bootstrap for threshold-free validation metrics."""
    rng = np.random.default_rng(seed)
    names: dict[str, Callable[[np.ndarray, np.ndarray], float | None]] = {
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "brier_score": lambda y, p: brier_score(y, p),
    }
    values: dict[str, list[float]] = {name: [] for name in names}
    for _ in range(repeats):
        sample = rng.integers(0, len(target), len(target))
        for name, metric in names.items():
            value = metric(target[sample], probability[sample])
            if value is not None and math.isfinite(value):
                values[name].append(float(value))
    intervals: dict[str, float | None] = {}
    for name, samples in values.items():
        if len(samples) < max(10, repeats // 2):
            intervals[f"{name}_ci_lower"] = None
            intervals[f"{name}_ci_upper"] = None
        else:
            intervals[f"{name}_ci_lower"] = float(np.quantile(samples, 0.025))
            intervals[f"{name}_ci_upper"] = float(np.quantile(samples, 0.975))
    return intervals


def flexible_calibration_curve(
    target: np.ndarray,
    probability: np.ndarray,
    *,
    points: int,
) -> pd.DataFrame:
    """Build a Gaussian-kernel calibration smoother with local effective support."""
    if len(target) == 0:
        return pd.DataFrame()
    clipped = np.clip(probability.astype(float), 1e-6, 1 - 1e-6)
    grid = np.unique(np.quantile(clipped, np.linspace(0.02, 0.98, max(3, points))))
    bandwidth = max(float(np.std(clipped)) * 0.35, 0.03)
    rows: list[dict[str, Any]] = []
    for predicted in grid:
        weights = np.exp(-0.5 * ((clipped - predicted) / bandwidth) ** 2)
        weight_sum = float(weights.sum())
        effective_n = float(weight_sum**2 / np.sum(weights**2))
        observed = float(np.sum(weights * target) / weight_sum)
        standard_error = math.sqrt(max(observed * (1 - observed), 0.0) / max(effective_n, 1.0))
        rows.append(
            {
                "mean_predicted_probability": float(predicted),
                "smoothed_observed_event_rate": observed,
                "confidence_lower": max(0.0, observed - Z_975 * standard_error),
                "confidence_upper": min(1.0, observed + Z_975 * standard_error),
                "local_effective_n": effective_n,
                "bandwidth": bandwidth,
                "curve_method": "GAUSSIAN_KERNEL_DESCRIPTIVE_CALIBRATION",
                "uncertainty_type": "LOCAL_NORMAL_APPROXIMATION_NOT_SIMULTANEOUS_BAND",
            }
        )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class ValidationPartition:
    fold_id: str
    design: str
    train_index: np.ndarray
    test_index: np.ndarray
    holdout_market: str | None = None


def make_validation_partitions(
    frame: pd.DataFrame, validation_config: Mapping[str, Any]
) -> tuple[list[ValidationPartition], pd.Timestamp]:
    """Create repeated rolling folds, one untouched holdout, and development-only LOMO folds."""
    ordered = frame.sort_values(["prediction_index_date", "patient_id"]).reset_index(drop=True)
    dates = np.sort(ordered.prediction_index_date.dropna().dt.normalize().unique())
    if len(dates) < 8:
        raise ValueError(
            "At least eight distinct prediction dates are required for temporal validation"
        )
    holdout_fraction = float(validation_config["final_temporal_holdout_fraction"])
    holdout_start_position = min(
        len(dates) - 1,
        max(1, int(math.floor((1 - holdout_fraction) * len(dates)))),
    )
    holdout_start = pd.Timestamp(dates[holdout_start_position])
    development_mask = ordered.prediction_index_date.dt.normalize().lt(holdout_start).to_numpy()
    final_mask = ~development_mask
    partitions: list[ValidationPartition] = []
    development_dates = dates[:holdout_start_position]
    repeats = int(validation_config["rolling_repeats"])
    origins = int(validation_config["rolling_origins_per_repeat"])
    initial_fraction = float(validation_config["rolling_initial_training_fraction"])
    validation_fraction = float(validation_config["rolling_validation_fraction"])
    minimum_train_n = int(validation_config["minimum_training_n"])
    minimum_test_n = int(validation_config["minimum_validation_n"])
    seen_boundaries: set[tuple[int, int]] = set()
    latest_train_fraction = max(initial_fraction, 1.0 - validation_fraction)
    base_fractions = np.linspace(initial_fraction, latest_train_fraction, origins)
    validation_dates_n = max(1, int(round(validation_fraction * len(development_dates))))
    repeat_step = max(1, validation_dates_n // max(4, 2 * repeats))
    for repeat in range(repeats):
        for origin, fraction in enumerate(base_fractions, 1):
            centred_repeat = 2 * repeat - (repeats - 1)
            train_end = int(round(fraction * len(development_dates))) + centred_repeat * repeat_step
            train_end = min(max(train_end, 1), len(development_dates) - 1)
            test_end = min(len(development_dates), train_end + validation_dates_n)
            boundary = (train_end, test_end)
            if boundary in seen_boundaries or test_end <= train_end:
                continue
            seen_boundaries.add(boundary)
            train_cutoff = pd.Timestamp(development_dates[train_end - 1])
            test_cutoff = pd.Timestamp(development_dates[test_end - 1])
            train_index = np.flatnonzero(
                ordered.prediction_index_date.dt.normalize().le(train_cutoff).to_numpy()
            )
            test_index = np.flatnonzero(
                ordered.prediction_index_date.dt.normalize().gt(train_cutoff).to_numpy()
                & ordered.prediction_index_date.dt.normalize().le(test_cutoff).to_numpy()
            )
            if len(train_index) < minimum_train_n or len(test_index) < minimum_test_n:
                continue
            partitions.append(
                ValidationPartition(
                    fold_id=f"rolling-r{repeat + 1}-o{origin}",
                    design="ROLLING_TEMPORAL",
                    train_index=train_index,
                    test_index=test_index,
                )
            )
    development_index = np.flatnonzero(development_mask)
    final_index = np.flatnonzero(final_mask)
    if len(development_index) < minimum_train_n or len(final_index) < minimum_test_n:
        raise ValueError("Final temporal holdout does not meet configured sample-size minima")
    partitions.append(
        ValidationPartition(
            fold_id="final-untouched-temporal-holdout",
            design="FINAL_TEMPORAL_HOLDOUT",
            train_index=development_index,
            test_index=final_index,
        )
    )
    development = ordered.iloc[development_index]
    for market in sorted(development.market_code.astype(str).unique()):
        market_test = development.market_code.astype(str).eq(market).to_numpy()
        train_index = development_index[~market_test]
        test_index = development_index[market_test]
        if len(train_index) < minimum_train_n or len(test_index) < minimum_test_n:
            continue
        partitions.append(
            ValidationPartition(
                fold_id=f"lomo-{market}",
                design="LEAVE_ONE_MARKET_OUT",
                train_index=train_index,
                test_index=test_index,
                holdout_market=market,
            )
        )
    return partitions, holdout_start


def _inner_temporal_split(
    train: pd.DataFrame,
    validation_config: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    dates = np.sort(train.prediction_index_date.dropna().dt.normalize().unique())
    fraction = float(validation_config["inner_calibration_fraction"])
    if len(dates) < 4:
        return train.copy(), train.iloc[0:0].copy(), "IDENTITY_INSUFFICIENT_INNER_DATES"
    position = min(len(dates) - 1, max(1, int(math.floor((1 - fraction) * len(dates)))))
    start = pd.Timestamp(dates[position])
    model_fit = train.loc[train.prediction_index_date.dt.normalize().lt(start)].copy()
    calibration = train.loc[train.prediction_index_date.dt.normalize().ge(start)].copy()
    minimum = int(validation_config["minimum_validation_n"])
    if (
        len(model_fit) < int(validation_config["minimum_training_n"])
        or len(calibration) < minimum
        or model_fit.target.nunique() < 2
        or calibration.target.nunique() < 2
    ):
        return train.copy(), train.iloc[0:0].copy(), "IDENTITY_INSUFFICIENT_INNER_SUPPORT"
    return model_fit, calibration, "NESTED_TEMPORAL_PLATT"


def _fit_platt(raw_probability: np.ndarray, target: np.ndarray) -> np.ndarray:
    clipped = np.clip(raw_probability, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped))[:, None]
    coefficients, _ = fit_logistic(logits, target.astype(float), l2_penalty=1e-6)
    return coefficients


def _apply_platt(raw_probability: np.ndarray, coefficients: np.ndarray | None) -> np.ndarray:
    if coefficients is None:
        return np.clip(raw_probability, 1e-6, 1 - 1e-6)
    clipped = np.clip(raw_probability, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped))[:, None]
    return predict_logistic(logits, coefficients)


def _evaluation_row(
    *,
    target_name: str,
    model_id: str,
    model: str,
    partition: ValidationPartition,
    train: pd.DataFrame,
    model_fit: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    probability: np.ndarray,
    bootstrap_repeats: int,
    bootstrap_seed: int,
    calibration_status: str,
    encoded_feature_count: int,
) -> dict[str, Any]:
    target = test.target.to_numpy(dtype=int)
    metrics = _metric_values(target, probability)
    intervals = bootstrap_metric_intervals(
        target,
        probability,
        repeats=bootstrap_repeats,
        seed=bootstrap_seed,
    )
    return {
        "model_id": model_id,
        "target": target_name,
        "model": model,
        "evaluation_design": partition.design,
        "fold_id": partition.fold_id,
        "holdout_market": partition.holdout_market,
        "status": "EVALUATED",
        "outer_train_n": len(train),
        "model_fit_n": len(model_fit),
        "calibration_n": len(calibration),
        "validation_n": len(test),
        "validation_event_n": int(target.sum()),
        "validation_non_event_n": int(len(target) - target.sum()),
        "event_prevalence": float(target.mean()),
        "train_period_start": pd.Timestamp(train.prediction_index_date.min()).date(),
        "train_period_end": pd.Timestamp(train.prediction_index_date.max()).date(),
        "validation_period_start": pd.Timestamp(test.prediction_index_date.min()).date(),
        "validation_period_end": pd.Timestamp(test.prediction_index_date.max()).date(),
        "preprocessing_fit_scope": "model_fit rows only",
        "imputation_fit_scope": "model_fit medians only",
        "category_fit_scope": "model_fit levels only",
        "feature_selection": "NONE",
        "calibration_method": calibration_status,
        "encoded_feature_count": encoded_feature_count,
        "bootstrap_repeats": bootstrap_repeats,
        "uncertainty_type": "PATIENT_LEVEL_PERCENTILE_BOOTSTRAP_95",
        "threshold_metrics_status": "NOT REPORTED — NO PRESPECIFIED OPERATIONAL THRESHOLD",
        **metrics,
        **intervals,
    }


def evaluate_partition(
    frame: pd.DataFrame,
    partition: ValidationPartition,
    *,
    model_id: str,
    target_name: str,
    numeric_features: Sequence[str],
    categorical_features: Sequence[str],
    validation_config: Mapping[str, Any],
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Fit nested preprocessing/calibration and evaluate two prespecified comparators."""
    train = frame.iloc[partition.train_index].copy()
    test = frame.iloc[partition.test_index].copy()
    split_audit = audit_partition(
        train,
        test,
        target_name=target_name,
        fold_id=partition.fold_id,
        design=partition.design,
        holdout_market=partition.holdout_market,
    )
    raise_on_leakage(split_audit)
    minimum_events = int(validation_config["minimum_events_per_validation"])
    if (
        train.target.nunique() < 2
        or test.target.nunique() < 2
        or int(test.target.sum()) < minimum_events
        or int((1 - test.target).sum()) < minimum_events
    ):
        row = {
            "model_id": model_id,
            "target": target_name,
            "model": "NOT_FITTED",
            "evaluation_design": partition.design,
            "fold_id": partition.fold_id,
            "holdout_market": partition.holdout_market,
            "status": "INSUFFICIENT_OUTCOME_SUPPORT",
            "outer_train_n": len(train),
            "validation_n": len(test),
            "validation_event_n": int(test.target.sum()),
            "validation_non_event_n": int((1 - test.target).sum()),
            "event_prevalence": float(test.target.mean()),
        }
        return pd.DataFrame([row]), pd.DataFrame(), split_audit, {}

    model_fit, calibration, calibration_status = _inner_temporal_split(train, validation_config)
    encoder = FeatureEncoder.fit(model_fit, numeric_features, categorical_features)
    coefficients, _ = fit_logistic(
        encoder.transform(model_fit),
        model_fit.target.to_numpy(dtype=float),
        l2_penalty=float(validation_config["l2_penalty"]),
    )
    platt_coefficients: np.ndarray | None = None
    if not calibration.empty:
        raw_calibration = predict_logistic(encoder.transform(calibration), coefficients)
        platt_coefficients = _fit_platt(raw_calibration, calibration.target.to_numpy(dtype=int))
    raw_test = predict_logistic(encoder.transform(test), coefficients)
    model_probability = _apply_platt(raw_test, platt_coefficients)
    prevalence_probability = np.repeat(float(model_fit.target.mean()), len(test))
    bootstrap_repeats = int(validation_config["bootstrap_repeats"])
    rows = [
        _evaluation_row(
            target_name=target_name,
            model_id=model_id,
            model="regularized_logistic_nested_calibration",
            partition=partition,
            train=train,
            model_fit=model_fit,
            calibration=calibration,
            test=test,
            probability=model_probability,
            bootstrap_repeats=bootstrap_repeats,
            bootstrap_seed=seed,
            calibration_status=calibration_status,
            encoded_feature_count=len(encoder.encoded_names),
        ),
        _evaluation_row(
            target_name=target_name,
            model_id=model_id,
            model="training_prevalence_comparator",
            partition=partition,
            train=train,
            model_fit=model_fit,
            calibration=calibration.iloc[0:0],
            test=test,
            probability=prevalence_probability,
            bootstrap_repeats=bootstrap_repeats,
            bootstrap_seed=seed + 100_000,
            calibration_status="NOT APPLICABLE — CONSTANT TRAINING PREVALENCE",
            encoded_feature_count=0,
        ),
    ]
    curves: list[pd.DataFrame] = []
    scored: dict[str, pd.DataFrame] = {}
    for offset, (model_name, probability) in enumerate(
        (
            ("regularized_logistic_nested_calibration", model_probability),
            ("training_prevalence_comparator", prevalence_probability),
        )
    ):
        curve = flexible_calibration_curve(
            test.target.to_numpy(dtype=int),
            probability,
            points=int(validation_config["calibration_curve_points"]),
        )
        curve.insert(0, "model_id", model_id)
        curve.insert(1, "target", target_name)
        curve.insert(2, "model", model_name)
        curve.insert(3, "evaluation_design", partition.design)
        curve.insert(4, "fold_id", partition.fold_id)
        curve.insert(5, "holdout_market", partition.holdout_market)
        curves.append(curve)
        scored[model_name] = test.assign(probability=probability, _model_offset=offset)

    fold_row = pd.DataFrame(
        [
            {
                "model_id": model_id,
                "target": target_name,
                "fold_id": partition.fold_id,
                "evaluation_design": partition.design,
                "holdout_market": partition.holdout_market,
                "outer_train_n": len(train),
                "model_fit_n": len(model_fit),
                "calibration_n": len(calibration),
                "validation_n": len(test),
                "outer_train_max_time": pd.Timestamp(train.prediction_index_date.max()).date(),
                "validation_min_time": pd.Timestamp(test.prediction_index_date.min()).date(),
                "preprocessor_fitted_on_validation": False,
                "imputer_fitted_on_validation": False,
                "feature_selection_inside_resampling": "NOT APPLICABLE — NO FEATURE SELECTION",
                "calibration_fit_scope": (
                    "inner temporal calibration subset"
                    if not calibration.empty
                    else "identity fallback; no validation fitting"
                ),
            }
        ]
    )
    return (
        pd.DataFrame(rows),
        pd.concat(curves, ignore_index=True),
        pd.concat([split_audit, fold_row], ignore_index=True, sort=False),
        scored,
    )


def run_validation_framework(
    datasets: Mapping[str, pd.DataFrame],
    contracts: Mapping[str, Any],
    evaluation_config: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, pd.DataFrame],
]:
    """Run all leakage gates, repeated temporal folds, final holdouts, and LOMO evaluations."""
    feature_config = evaluation_config["features"]
    numeric = list(map(str, feature_config["numeric"]))
    categorical = list(map(str, feature_config["categorical"]))
    selected = numeric + categorical
    prohibited = list(map(str, feature_config["prohibited"]))
    contract_by_target = {str(model["target_name"]): model for model in contracts["models"]}
    metric_frames: list[pd.DataFrame] = []
    curve_frames: list[pd.DataFrame] = []
    audit_frames: list[pd.DataFrame] = []
    fold_frames: list[pd.DataFrame] = []
    final_scores: dict[str, pd.DataFrame] = {}
    base_seed = int(evaluation_config["random_seed"])
    for target_index, (target_name, source_frame) in enumerate(datasets.items()):
        frame = source_frame.sort_values(
            ["prediction_index_date", "patient_id"], kind="stable", ignore_index=True
        )
        feature_audit = audit_feature_frame(
            frame,
            selected,
            prohibited,
            target_name=target_name,
        )
        raise_on_leakage(feature_audit)
        audit_frames.append(feature_audit)
        partitions, holdout_start = make_validation_partitions(
            frame, evaluation_config["validation"]
        )
        model_id = str(contract_by_target[target_name]["model_id"])
        for partition_index, partition in enumerate(partitions):
            metrics, curves, fold_audit, scores = evaluate_partition(
                frame,
                partition,
                model_id=model_id,
                target_name=target_name,
                numeric_features=numeric,
                categorical_features=categorical,
                validation_config=evaluation_config["validation"],
                seed=base_seed + 10_000 * target_index + 100 * partition_index,
            )
            metrics["final_holdout_start"] = holdout_start.date()
            metric_frames.append(metrics)
            if not curves.empty:
                curve_frames.append(curves)
            split_rows = fold_audit.loc[fold_audit.check.notna()].copy()
            if not split_rows.empty:
                audit_frames.append(split_rows)
            registry_rows = fold_audit.loc[fold_audit.check.isna()].copy()
            if not registry_rows.empty:
                fold_frames.append(registry_rows)
            if partition.design == "FINAL_TEMPORAL_HOLDOUT" and scores:
                final_scores[target_name] = scores["regularized_logistic_nested_calibration"].drop(
                    columns=["_model_offset"]
                )
    return (
        pd.concat(metric_frames, ignore_index=True, sort=False),
        pd.concat(curve_frames, ignore_index=True, sort=False) if curve_frames else pd.DataFrame(),
        pd.concat(audit_frames, ignore_index=True, sort=False),
        pd.concat(fold_frames, ignore_index=True, sort=False) if fold_frames else pd.DataFrame(),
        final_scores,
    )


def build_subgroup_metrics(
    final_scores: Mapping[str, pd.DataFrame],
    contracts: Mapping[str, Any],
    evaluation_config: Mapping[str, Any],
) -> pd.DataFrame:
    """Report support, discrimination, calibration, uncertainty, and missingness without ranking."""
    contract_by_target = {str(model["target_name"]): model for model in contracts["models"]}
    subgroup_config = evaluation_config["subgroups"]
    dimensions = list(map(str, subgroup_config["dimensions"]))
    selected_features = list(map(str, evaluation_config["features"]["numeric"])) + list(
        map(str, evaluation_config["features"]["categorical"])
    )
    bootstrap_repeats = min(100, int(evaluation_config["validation"]["bootstrap_repeats"]))
    base_seed = int(evaluation_config["random_seed"]) + 700_000
    rows: list[dict[str, Any]] = []
    group_counter = 0
    for target_name, scored in final_scores.items():
        model_id = str(contract_by_target[target_name]["model_id"])
        for dimension in dimensions:
            for value, group in scored.groupby(dimension, dropna=False, sort=True):
                target = group.target.to_numpy(dtype=int)
                probability = group.probability.to_numpy(dtype=float)
                event_n = int(target.sum())
                non_event_n = len(target) - event_n
                support = (
                    len(target) >= int(subgroup_config["minimum_n"])
                    and event_n >= int(subgroup_config["minimum_events"])
                    and non_event_n >= int(subgroup_config["minimum_non_events"])
                )
                metrics = _metric_values(target, probability)
                intervals = bootstrap_metric_intervals(
                    target,
                    probability,
                    repeats=bootstrap_repeats,
                    seed=base_seed + group_counter,
                )
                group_counter += 1
                rows.append(
                    {
                        "model_id": model_id,
                        "target": target_name,
                        "model": "regularized_logistic_nested_calibration",
                        "evaluation_design": "FINAL_TEMPORAL_HOLDOUT_SUBGROUP",
                        "subgroup_dimension": dimension,
                        "subgroup_value": str(value),
                        "n": len(target),
                        "event_n": event_n,
                        "non_event_n": non_event_n,
                        "event_prevalence": float(target.mean()) if len(target) else None,
                        "predictor_missingness_rate": float(
                            group[selected_features].isna().sum().sum()
                            / max(1, len(group) * len(selected_features))
                        ),
                        "support_status": (
                            "EVALUABLE WITH UNCERTAINTY — DO NOT RANK"
                            if support
                            else "INSUFFICIENT SUPPORT — DO NOT RANK"
                        ),
                        "ranking_allowed": False,
                        "bootstrap_repeats": bootstrap_repeats,
                        "uncertainty_type": "PATIENT_LEVEL_PERCENTILE_BOOTSTRAP_95",
                        **metrics,
                        **intervals,
                    }
                )
    return pd.DataFrame(rows)


def _final_partition(
    frame: pd.DataFrame, validation_config: Mapping[str, Any]
) -> ValidationPartition:
    partitions, _ = make_validation_partitions(frame, validation_config)
    return next(item for item in partitions if item.design == "FINAL_TEMPORAL_HOLDOUT")


def _evaluate_robustness_variant(
    frame: pd.DataFrame,
    *,
    model_id: str,
    target_name: str,
    numeric_features: Sequence[str],
    categorical_features: Sequence[str],
    evaluation_config: Mapping[str, Any],
    seed: int,
) -> dict[str, Any]:
    validation = dict(evaluation_config["validation"])
    validation["bootstrap_repeats"] = min(100, int(validation["bootstrap_repeats"]))
    partition = _final_partition(frame, validation)
    metrics, _, _, _ = evaluate_partition(
        frame.sort_values(["prediction_index_date", "patient_id"], ignore_index=True),
        partition,
        model_id=model_id,
        target_name=target_name,
        numeric_features=numeric_features,
        categorical_features=categorical_features,
        validation_config=validation,
        seed=seed,
    )
    primary = metrics.loc[metrics.model.eq("regularized_logistic_nested_calibration")]
    if primary.empty:
        return {str(key): value for key, value in metrics.iloc[0].to_dict().items()}
    return {str(key): value for key, value in primary.iloc[0].to_dict().items()}


def _robustness_row(
    result: Mapping[str, Any],
    *,
    robustness_type: str,
    scenario: str,
    interpretation: str,
) -> dict[str, Any]:
    fields = (
        "model_id",
        "target",
        "model",
        "status",
        "validation_n",
        "validation_event_n",
        "validation_non_event_n",
        "event_prevalence",
        "roc_auc",
        "roc_auc_ci_lower",
        "roc_auc_ci_upper",
        "pr_auc",
        "pr_auc_ci_lower",
        "pr_auc_ci_upper",
        "brier_score",
        "brier_score_ci_lower",
        "brier_score_ci_upper",
        "calibration_intercept",
        "calibration_slope",
        "requested_event_prevalence",
        "resampling_method",
    )
    return {
        "robustness_type": robustness_type,
        "scenario": scenario,
        **{field: result.get(field) for field in fields},
        "interpretation": interpretation,
        "synthetic_data_only": True,
    }


def _resample_prevalence_shift(
    target: np.ndarray,
    probability: np.ndarray,
    *,
    odds_multiplier: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Shift event prevalence by outcome-stratified resampling without refitting the model."""
    positive = np.flatnonzero(target == 1)
    negative = np.flatnonzero(target == 0)
    if not len(positive) or not len(negative):
        raise ValueError("Prevalence-shift resampling requires both outcome classes")
    prevalence = float(target.mean())
    shifted_odds = odds_multiplier * prevalence / (1 - prevalence)
    requested_prevalence = shifted_odds / (1 + shifted_odds)
    event_n = min(len(target) - 1, max(1, int(round(requested_prevalence * len(target)))))
    rng = np.random.default_rng(seed)
    sampled = np.concatenate(
        [
            rng.choice(positive, size=event_n, replace=True),
            rng.choice(negative, size=len(target) - event_n, replace=True),
        ]
    )
    rng.shuffle(sampled)
    return target[sampled], probability[sampled], requested_prevalence


def run_robustness_framework(
    *,
    base_datasets: Mapping[str, pd.DataFrame],
    flags: pd.DataFrame,
    persistence: pd.DataFrame,
    tables: Mapping[str, pd.DataFrame],
    contracts: Mapping[str, Any],
    evaluation_config: Mapping[str, Any],
    validation_metrics: pd.DataFrame,
    final_scores: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Execute prespecified target, missingness, time, market, feature, and prevalence stresses."""
    by_target = {str(model["target_name"]): model for model in contracts["models"]}
    numeric = list(map(str, evaluation_config["features"]["numeric"]))
    categorical = list(map(str, evaluation_config["features"]["categorical"]))
    robustness = evaluation_config["robustness"]
    seed = int(evaluation_config["random_seed"]) + 900_000
    rows: list[dict[str, Any]] = []

    for window in map(int, robustness["initiation_windows_days"]):
        variant, _ = build_model_datasets(
            flags,
            persistence,
            tables,
            evaluation_config,
            initiation_window_days=window,
        )
        target_name = "non_initiated_within_90_days"
        result = _evaluate_robustness_variant(
            variant[target_name],
            model_id=str(by_target[target_name]["model_id"]),
            target_name=target_name,
            numeric_features=numeric,
            categorical_features=categorical,
            evaluation_config=evaluation_config,
            seed=seed + window,
        )
        rows.append(
            _robustness_row(
                result,
                robustness_type="ALTERNATIVE_INITIATION_WINDOW",
                scenario=f"{window}_days",
                interpretation="Target and evaluability are rebuilt at the named landmark.",
            )
        )

    for gap in map(int, robustness["persistence_gap_days"]):
        variant, _ = build_model_datasets(
            flags,
            persistence,
            tables,
            evaluation_config,
            persistence_gap_days=gap,
        )
        for target_name in (
            "discontinued_within_12_months",
            "switched_treatment",
            "restarted_after_gap",
        ):
            result = _evaluate_robustness_variant(
                variant[target_name],
                model_id=str(by_target[target_name]["model_id"]),
                target_name=target_name,
                numeric_features=numeric,
                categorical_features=categorical,
                evaluation_config=evaluation_config,
                seed=seed + 1_000 + 10 * gap + list(by_target).index(target_name),
            )
            rows.append(
                _robustness_row(
                    result,
                    robustness_type="ALTERNATIVE_PERSISTENCE_GAP",
                    scenario=f"{gap}_days",
                    interpretation="Outcome/risk-set construction is rebuilt under the named gap.",
                )
            )

    rng = np.random.default_rng(seed + 20_000)
    # market_code is both a candidate predictor and the prespecified external-like
    # validation partition key. Keep the structural key intact so missingness stress
    # changes model inputs without corrupting the validation design itself.
    missingness_stress_features = [
        feature for feature in numeric + categorical if feature != "market_code"
    ]
    for rate in map(float, robustness["added_feature_missingness_rates"]):
        for target_name, frame in base_datasets.items():
            stressed = frame.copy()
            for feature in missingness_stress_features:
                mask = rng.random(len(stressed)) < rate
                stressed.loc[mask, feature] = np.nan
            result = _evaluate_robustness_variant(
                stressed,
                model_id=str(by_target[target_name]["model_id"]),
                target_name=target_name,
                numeric_features=numeric,
                categorical_features=categorical,
                evaluation_config=evaluation_config,
                seed=seed + 30_000 + int(rate * 1_000) + list(base_datasets).index(target_name),
            )
            rows.append(
                _robustness_row(
                    result,
                    robustness_type="ADDED_PREDICTOR_MISSINGNESS",
                    scenario=f"MCAR_{rate:.0%}",
                    interpretation=(
                        "Additional predictor values are hidden after target derivation; "
                        "the prespecified market partition key remains intact."
                    ),
                )
            )

    for name, removed in robustness["feature_removal_sets"].items():
        retained_numeric = [feature for feature in numeric if feature not in set(removed)]
        retained_categorical = [feature for feature in categorical if feature not in set(removed)]
        for target_name, frame in base_datasets.items():
            result = _evaluate_robustness_variant(
                frame,
                model_id=str(by_target[target_name]["model_id"]),
                target_name=target_name,
                numeric_features=retained_numeric,
                categorical_features=retained_categorical,
                evaluation_config=evaluation_config,
                seed=seed + 40_000 + list(base_datasets).index(target_name),
            )
            rows.append(
                _robustness_row(
                    result,
                    robustness_type="FEATURE_REMOVAL",
                    scenario=str(name),
                    interpretation=f"Removed prespecified features: {list(removed)}.",
                )
            )

    if bool(robustness["include_simplified_model"]):
        simplified = list(map(str, evaluation_config["features"]["simplified"]))
        simplified_numeric = [feature for feature in numeric if feature in simplified]
        simplified_categorical = [feature for feature in categorical if feature in simplified]
        for target_name, frame in base_datasets.items():
            result = _evaluate_robustness_variant(
                frame,
                model_id=str(by_target[target_name]["model_id"]),
                target_name=target_name,
                numeric_features=simplified_numeric,
                categorical_features=simplified_categorical,
                evaluation_config=evaluation_config,
                seed=seed + 50_000 + list(base_datasets).index(target_name),
            )
            rows.append(
                _robustness_row(
                    result,
                    robustness_type="SIMPLIFIED_MODEL",
                    scenario="prespecified_four_feature_logistic",
                    interpretation=f"Only prespecified simplified features are used: {simplified}.",
                )
            )

    for target_name, scored in final_scores.items():
        base_target = scored.target.to_numpy(dtype=int)
        base_probability = scored.probability.to_numpy(dtype=float)
        for shift_index, multiplier in enumerate(
            map(float, robustness["prevalence_odds_multipliers"])
        ):
            target, probability, requested_prevalence = _resample_prevalence_shift(
                base_target,
                base_probability,
                odds_multiplier=multiplier,
                seed=seed + 60_000 + 100 * list(final_scores).index(target_name) + shift_index,
            )
            metrics = _metric_values(target, probability)
            intervals = bootstrap_metric_intervals(
                target,
                probability,
                repeats=min(100, int(evaluation_config["validation"]["bootstrap_repeats"])),
                seed=seed + 70_000 + 100 * list(final_scores).index(target_name) + shift_index,
            )
            result = {
                "model_id": str(by_target[target_name]["model_id"]),
                "target": target_name,
                "model": "regularized_logistic_nested_calibration",
                "status": "EVALUATED",
                "validation_n": len(target),
                "validation_event_n": int(target.sum()),
                "validation_non_event_n": int(len(target) - target.sum()),
                "event_prevalence": float(target.mean()),
                "requested_event_prevalence": requested_prevalence,
                "resampling_method": "OUTCOME_STRATIFIED_WITH_REPLACEMENT_NO_REFIT",
                **metrics,
                **intervals,
            }
            rows.append(
                _robustness_row(
                    result,
                    robustness_type="PREVALENCE_SHIFT",
                    scenario=f"observed_event_odds_x_{multiplier:g}",
                    interpretation=(
                        "Outcome-stratified resampling shifts event odds while retaining "
                        "within-class score distributions; the model is not refit."
                    ),
                )
            )

    primary = validation_metrics.loc[
        validation_metrics.model.eq("regularized_logistic_nested_calibration")
        & validation_metrics.status.eq("EVALUATED")
    ]
    for raw_row in primary.loc[
        primary.evaluation_design.isin(["ROLLING_TEMPORAL", "LEAVE_ONE_MARKET_OUT"])
    ].to_dict(orient="records"):
        row = {str(key): value for key, value in raw_row.items()}
        rows.append(
            _robustness_row(
                row,
                robustness_type=(
                    "TEMPORAL_SHIFT"
                    if row["evaluation_design"] == "ROLLING_TEMPORAL"
                    else "MARKET_HOLDOUT"
                ),
                scenario=str(row["fold_id"]),
                interpretation=(
                    "Prespecified repeated rolling temporal fold."
                    if row["evaluation_design"] == "ROLLING_TEMPORAL"
                    else "Development-period leave-one-market-out fold; do not rank markets."
                ),
            )
        )
    return pd.DataFrame(rows)


def compare_with_prior_reported_claims(
    validation_metrics: pd.DataFrame,
    evaluation_config: Mapping[str, Any],
) -> pd.DataFrame:
    """Compare final holdout results with historical claims without assuming replication."""
    prior = evaluation_config["prior_reported_claims"]
    final = validation_metrics.loc[
        validation_metrics.model.eq("regularized_logistic_nested_calibration")
        & validation_metrics.evaluation_design.eq("FINAL_TEMPORAL_HOLDOUT")
        & validation_metrics.status.eq("EVALUATED")
    ].set_index("target")
    rows: list[dict[str, Any]] = []
    for target_name, claim in prior["values"].items():
        current = final.loc[target_name] if target_name in final.index else None
        current_roc = float(current.roc_auc) if current is not None else None
        current_pr = float(current.pr_auc) if current is not None else None
        current_n = (
            int(current.outer_train_n + current.validation_n) if current is not None else None
        )
        if current_roc is None:
            assessment = "NOT EVALUABLE"
        elif current_roc >= 0.65:
            assessment = "moderate exploratory discrimination"
        elif current_roc >= 0.60:
            assessment = "limited exploratory discrimination"
        elif current_roc >= 0.55:
            assessment = "weak discrimination"
        else:
            assessment = "no useful discrimination demonstrated"
        rows.append(
            {
                "target": target_name,
                "prior_source_release": prior["source_release"],
                "prior_evidence_document": prior["evidence_document"],
                "prior_analysis_n": int(claim["analysis_n"]),
                "current_analysis_n": current_n,
                "analysis_n_difference": (
                    current_n - int(claim["analysis_n"]) if current_n is not None else None
                ),
                "prior_roc_auc": float(claim["roc_auc"]),
                "current_roc_auc": current_roc,
                "roc_auc_difference": (
                    current_roc - float(claim["roc_auc"]) if current_roc is not None else None
                ),
                "prior_pr_auc": float(claim["pr_auc"]),
                "current_pr_auc": current_pr,
                "pr_auc_difference": (
                    current_pr - float(claim["pr_auc"]) if current_pr is not None else None
                ),
                "prior_assessment": claim["assessment"],
                "current_assessment": assessment,
                "exact_reproduction_claimed": False,
                "interpretation": (
                    "Metrics are from different release/evaluation structures; differences are "
                    "reported, not optimized away."
                ),
            }
        )
    return pd.DataFrame(rows)
