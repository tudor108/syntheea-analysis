"""Leakage-audited exploratory driver analysis using validated EDA outputs only."""

# ruff: noqa: E501

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from config import (
    ANALYSIS_DISCLAIMER,
    FIGURES_DIR,
    OUTPUT_DIR,
    ensure_output_directories,
    resolve_analytical_data_dir,
)
from longitudinal_charts import line
from png_charts import Canvas

RANDOM_SEED = 20260828
PRIMARY_PATHWAY = "mhspc_mcspc"
GAP_THRESHOLD_DAYS = 60
TARGET_WINDOW_DAYS = 365
MIN_MODEL_EVENTS = 100
OPERATIONAL_CAPACITY = 0.20
BOOTSTRAP_REPEATS = 200

NUMERIC_MODEL_FEATURES = [
    "age_at_index",
    "comorbidity_score",
    "frailty_proxy",
    "access_index",
    "prior_healthcare_utilization_180d",
    "prior_treatment_count",
    "time_since_diagnosis_days",
    "time_since_metastasis_days",
]
CATEGORICAL_MODEL_FEATURES = [
    "prior_treatment_status",
    "disease_state",
    "metastatic_site",
    "market_code",
    "care_setting",
    "provider_specialty",
    "provider_volume_band",
    "referral_proxy",
    "prior_hospitalization",
    "insurance_type",
    "calendar_period",
]
ASSOCIATION_FEATURES = NUMERIC_MODEL_FEATURES + CATEGORICAL_MODEL_FEATURES + ["age_band"]
SUBGROUP_DIMENSIONS = [
    "market_code",
    "disease_state",
    "age_band",
    "care_setting",
    "missingness_pattern",
]


@dataclass
class FeatureEncoder:
    """Train-only median/standardization and reference-coded one-hot encoder."""

    numeric_features: list[str]
    categorical_features: list[str]
    medians: dict[str, float]
    means: dict[str, float]
    scales: dict[str, float]
    categories: dict[str, list[str]]
    encoded_names: list[str]
    source_features: list[str]

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> FeatureEncoder:
        numeric: list[str] = []
        categorical: list[str] = []
        medians: dict[str, float] = {}
        means: dict[str, float] = {}
        scales: dict[str, float] = {}
        categories: dict[str, list[str]] = {}
        encoded_names: list[str] = []
        sources: list[str] = []
        for feature in NUMERIC_MODEL_FEATURES:
            values = pd.to_numeric(frame[feature], errors="coerce")
            if values.notna().sum() == 0:
                continue
            median = float(values.median())
            filled = values.fillna(median)
            scale = float(filled.std(ddof=0))
            if not math.isfinite(scale) or scale < 1e-10:
                continue
            numeric.append(feature)
            medians[feature] = median
            means[feature] = float(filled.mean())
            scales[feature] = scale
            encoded_names.append(f"{feature} (per SD)")
            sources.append(feature)
        for feature in CATEGORICAL_MODEL_FEATURES:
            values = frame[feature].astype("string").fillna("MISSING")
            levels = sorted(values.unique().tolist())
            if len(levels) <= 1:
                continue
            categorical.append(feature)
            categories[feature] = levels
            for level in levels[1:]:
                encoded_names.append(f"{feature}={level} vs {levels[0]}")
                sources.append(feature)
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
            values = pd.to_numeric(frame[feature], errors="coerce").fillna(
                self.medians[feature]
            )
            columns.append(
                ((values.to_numpy(dtype=float) - self.means[feature]) / self.scales[feature])[
                    :, None
                ]
            )
        for feature in self.categorical_features:
            values = frame[feature].astype("string").fillna("MISSING")
            levels = self.categories[feature]
            for level in levels[1:]:
                columns.append(values.eq(level).to_numpy(dtype=float)[:, None])
        return np.hstack(columns) if columns else np.empty((len(frame), 0))


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35, 35)
    return 1 / (1 + np.exp(-clipped))


def fit_logistic(
    matrix: np.ndarray,
    target: np.ndarray,
    *,
    l2_penalty: float = 1.0,
    max_iterations: int = 100,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Fit penalized logistic regression with transparent Newton/IRLS updates."""
    design = np.column_stack([np.ones(len(matrix)), matrix])
    coefficients = np.zeros(design.shape[1], dtype=float)
    prevalence = float(np.clip(target.mean(), 1e-6, 1 - 1e-6))
    coefficients[0] = math.log(prevalence / (1 - prevalence))
    penalty = np.eye(design.shape[1]) * l2_penalty
    penalty[0, 0] = 0.0
    information = design.T @ design + penalty
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
    covariance = np.linalg.pinv(information)
    return coefficients, covariance, iterations


def predict_logistic(matrix: np.ndarray, coefficients: np.ndarray) -> np.ndarray:
    return _sigmoid(np.column_stack([np.ones(len(matrix)), matrix]) @ coefficients)


def pr_auc(target: np.ndarray, probability: np.ndarray) -> float | None:
    positives = int(target.sum())
    if positives == 0:
        return None
    order = np.argsort(-probability, kind="stable")
    ordered = target[order]
    true_positive = np.cumsum(ordered)
    precision = true_positive / np.arange(1, len(ordered) + 1)
    return float(precision[ordered == 1].sum() / positives)


def roc_auc(target: np.ndarray, probability: np.ndarray) -> float | None:
    positives = int(target.sum())
    negatives = len(target) - positives
    if positives == 0 or negatives == 0:
        return None
    ranks = pd.Series(probability).rank(method="average").to_numpy()
    rank_sum = float(ranks[target == 1].sum())
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def brier_score(target: np.ndarray, probability: np.ndarray) -> float:
    return float(np.mean((probability - target) ** 2))


def classification_metrics(
    target: np.ndarray, probability: np.ndarray, threshold: float
) -> dict[str, Any]:
    predicted = probability >= threshold
    positive = target == 1
    tp = int((predicted & positive).sum())
    fp = int((predicted & ~positive).sum())
    fn = int((~predicted & positive).sum())
    tn = int((~predicted & ~positive).sum())
    return {
        "pr_auc": pr_auc(target, probability),
        "roc_auc": roc_auc(target, probability),
        "brier_score": brier_score(target, probability),
        "threshold": float(threshold),
        "actual_capacity_fraction": float(predicted.mean()),
        "recall_at_capacity": tp / (tp + fn) if tp + fn else None,
        "precision_at_capacity": tp / (tp + fp) if tp + fp else None,
        "specificity_at_capacity": tn / (tn + fp) if tn + fp else None,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "true_positive": tp,
    }


def bootstrap_interval(
    target: np.ndarray,
    probability: np.ndarray,
    metric: Callable[[np.ndarray, np.ndarray], float | None],
    rng: np.random.Generator,
) -> tuple[float | None, float | None]:
    values: list[float] = []
    for _ in range(BOOTSTRAP_REPEATS):
        sample = rng.integers(0, len(target), len(target))
        value = metric(target[sample], probability[sample])
        if value is not None and math.isfinite(value):
            values.append(float(value))
    if len(values) < BOOTSTRAP_REPEATS // 2:
        return None, None
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def _volume_band(value: Any) -> str:
    if pd.isna(value):
        return "MISSING"
    if float(value) < 150:
        return "LOW_LT_150"
    if float(value) < 300:
        return "MEDIUM_150_299"
    return "HIGH_GE_300"


def _age_band(value: Any) -> str:
    if pd.isna(value):
        return "MISSING"
    age = float(value)
    if age < 65:
        return "LT_65"
    if age < 75:
        return "65_74"
    return "GE_75"


def _calendar_period(date: pd.Timestamp) -> str:
    year = date.year
    if year <= 2020:
        return "2019_2020"
    if year <= 2022:
        return "2021_2022"
    return "2023_2024"


def load_validated_tables(analytical_dir: Path) -> dict[str, pd.DataFrame]:
    names = [
        "patient",
        "diagnosis",
        "encounter",
        "referral",
        "provider",
        "treatment_episode",
        "feature_timing",
    ]
    tables = {name: pd.read_parquet(analytical_dir / f"{name}.parquet") for name in names}
    for frame, columns in [
        (tables["diagnosis"], ["diagnosis_date", "metastatic_date"]),
        (tables["encounter"], ["encounter_date"]),
        (tables["referral"], ["referral_date", "completion_date"]),
        (
            tables["treatment_episode"],
            ["treatment_start_date", "discontinuation_date", "switch_date", "restart_date"],
        ),
    ]:
        for column in columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return tables


def build_feature_frame(
    base: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    *,
    prediction_stage: str,
) -> pd.DataFrame:
    """Derive features observable no later than each row's prediction index."""
    frame = base.copy()
    frame["prediction_index_date"] = pd.to_datetime(frame.prediction_index_date)
    patient_columns = [
        "patient_id",
        "age_at_index",
        "comorbidity_score",
        "frailty_proxy",
        "access_index",
        "insurance_type",
        "market_code",
    ]
    frame = frame.merge(
        tables["patient"][patient_columns],
        on="patient_id",
        how="left",
        validate="one_to_one",
    )
    frame = frame.merge(
        tables["diagnosis"][
            ["patient_id", "diagnosis_date", "metastatic_date", "metastatic_site"]
        ],
        on="patient_id",
        how="left",
        validate="one_to_one",
    )

    encounters = tables["encounter"].merge(
        frame[["patient_id", "prediction_index_date"]], on="patient_id", how="inner"
    )
    prior_encounters = encounters[
        encounters.encounter_date.lt(encounters.prediction_index_date)
    ].copy()
    prior_180 = prior_encounters[
        prior_encounters.encounter_date.ge(
            prior_encounters.prediction_index_date - pd.Timedelta(days=180)
        )
    ]
    utilization = prior_180.groupby("patient_id").size()
    hospitalization = (
        prior_encounters.encounter_type.astype(str)
        .str.lower()
        .str.contains("hospital|inpatient|emergency|\bed\b", regex=True)
    )
    prior_hospital = prior_encounters.assign(_hospital=hospitalization).groupby(
        "patient_id"
    )._hospital.max()
    baseline_encounters = encounters[
        encounters.encounter_date.le(encounters.prediction_index_date)
    ].sort_values(["patient_id", "encounter_date", "sequence_number", "encounter_id"])
    last_encounter = baseline_encounters.drop_duplicates("patient_id", keep="last").set_index(
        "patient_id"
    )

    frame["prior_healthcare_utilization_180d"] = frame.patient_id.map(utilization).fillna(0).astype(int)
    frame["prior_hospitalization"] = (
        frame.patient_id.map(prior_hospital).fillna(False).map({True: "YES", False: "NO"})
    )
    frame["care_setting"] = frame.patient_id.map(last_encounter.care_setting)
    frame["provider_specialty"] = frame.patient_id.map(last_encounter.provider_specialty)
    frame["safe_provider_id"] = frame.patient_id.map(last_encounter.provider_id)

    if prediction_stage == "treatment_start":
        episode_provider = tables["treatment_episode"].set_index("treatment_episode_id").prescribing_provider_id
        supplied = frame.treatment_episode_id.map(episode_provider)
        frame["safe_provider_id"] = supplied.fillna(frame.safe_provider_id)
    provider = tables["provider"].set_index("provider_id")
    frame["care_setting"] = frame.safe_provider_id.map(provider.care_setting).fillna(
        frame.care_setting
    )
    frame["provider_specialty"] = frame.safe_provider_id.map(
        provider.provider_specialty
    ).fillna(frame.provider_specialty)
    frame["provider_volume_band"] = frame.safe_provider_id.map(
        provider.annual_prostate_volume
    ).map(_volume_band)

    referrals = tables["referral"].merge(
        frame[["patient_id", "prediction_index_date"]], on="patient_id", how="inner"
    )
    baseline_referrals = referrals[
        referrals.referral_date.le(referrals.prediction_index_date)
    ].copy()
    baseline_referrals["completed_by_index"] = (
        baseline_referrals.referral_status.eq("completed")
        & baseline_referrals.completion_date.le(baseline_referrals.prediction_index_date)
    )
    referral_rows: dict[str, str] = {}
    for patient_id, group in baseline_referrals.groupby("patient_id"):
        referral_rows[str(patient_id)] = (
            "COMPLETED_BY_INDEX"
            if group.completed_by_index.any()
            else "RECORDED_NOT_COMPLETED_BY_INDEX"
        )
    frame["referral_proxy"] = frame.patient_id.astype(str).map(referral_rows).fillna(
        "NO_PRE_INDEX_REFERRAL"
    )

    episodes = tables["treatment_episode"].merge(
        frame[["patient_id", "prediction_index_date"]], on="patient_id", how="inner"
    )
    prior_treatment = episodes[
        episodes.treatment_start_date.lt(episodes.prediction_index_date)
    ].groupby("patient_id").size()
    frame["prior_treatment_count"] = frame.patient_id.map(prior_treatment).fillna(0).astype(int)
    frame["prior_treatment_status"] = np.where(
        frame.prior_treatment_count.gt(0), "PRIOR_TREATMENT", "NO_PRIOR_TREATMENT"
    )
    frame["disease_state"] = frame.get("pathway_disease_state", "mHSPC")
    frame["age_band"] = frame.age_at_index.map(_age_band)
    frame["time_since_diagnosis_days"] = (
        frame.prediction_index_date - frame.diagnosis_date
    ).dt.days.clip(lower=0)
    frame["time_since_metastasis_days"] = (
        frame.prediction_index_date - frame.metastatic_date
    ).dt.days.clip(lower=0)
    frame["calendar_period"] = frame.prediction_index_date.map(_calendar_period)
    missing_count = frame[NUMERIC_MODEL_FEATURES + CATEGORICAL_MODEL_FEATURES].isna().sum(axis=1)
    frame["missingness_pattern"] = np.select(
        [missing_count.eq(0), missing_count.eq(1)],
        ["NO_MISSING", "ONE_MISSING"],
        default="TWO_PLUS_MISSING",
    )
    frame = frame.drop(columns=["safe_provider_id"])
    return frame


def build_target_datasets(
    flags: pd.DataFrame,
    persistence: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    flags = flags.copy()
    for column in ["cohort_index_date", "censor_date"]:
        flags[column] = pd.to_datetime(flags[column], errors="coerce")
    primary = flags[
        flags.pathway.eq(PRIMARY_PATHWAY)
        & flags.eligible_candidate.fillna(False)
        & flags.observable_for_90d.fillna(False)
    ].copy()
    initiation_base = primary[
        ["patient_id", "cohort_index_date", "pathway_disease_state"]
    ].rename(columns={"cohort_index_date": "prediction_index_date"})
    initiation_base["target"] = (~primary.initiated_within_90d.fillna(False)).astype(int).to_numpy()
    initiation_base["target_name"] = "non_initiated_within_90_days"
    initiation_features = build_feature_frame(
        initiation_base, tables, prediction_stage="eligibility"
    )

    p60 = persistence[
        persistence.pathway.eq(PRIMARY_PATHWAY)
        & persistence.gap_threshold_days.eq(GAP_THRESHOLD_DAYS)
    ].copy()
    for column in ["treatment_start_date", "persistence_endpoint_date"]:
        p60[column] = pd.to_datetime(p60[column], errors="coerce")
    treatment_base = p60[
        ["patient_id", "treatment_episode_id", "treatment_start_date", "disease_state"]
    ].rename(
        columns={
            "treatment_start_date": "prediction_index_date",
            "disease_state": "pathway_disease_state",
        }
    )
    treatment_features = build_feature_frame(
        treatment_base, tables, prediction_stage="treatment_start"
    )
    outcome = p60[
        [
            "patient_id",
            "days_to_persistence_endpoint",
            "event_classification",
            "persistence_failure_flag",
        ]
    ].copy()
    by_12m = outcome.days_to_persistence_endpoint.le(TARGET_WINDOW_DAYS)

    persistent_through_12m = outcome.days_to_persistence_endpoint.gt(TARGET_WINDOW_DAYS)
    discontinuation_known = (by_12m & outcome.persistence_failure_flag) | persistent_through_12m
    discontinuation_labels = outcome.loc[discontinuation_known, ["patient_id"]].copy()
    discontinuation_labels["target"] = (
        by_12m & outcome.persistence_failure_flag
    ).loc[discontinuation_known].astype(int).to_numpy()
    discontinuation = treatment_features.merge(
        discontinuation_labels, on="patient_id", how="inner", validate="one_to_one"
    )
    discontinuation["target_name"] = "discontinued_within_12_months"

    switched_by_12m = by_12m & outcome.event_classification.eq("SWITCHED")
    switch_known = switched_by_12m | persistent_through_12m
    switch_labels = outcome.loc[switch_known, ["patient_id"]].copy()
    switch_labels["target"] = switched_by_12m.loc[switch_known].astype(int).to_numpy()
    switch = treatment_features.merge(
        switch_labels, on="patient_id", how="inner", validate="one_to_one"
    )
    switch["target_name"] = "switched_treatment"

    gap_failure_by_12m = by_12m & outcome.persistence_failure_flag
    restart_labels = outcome.loc[gap_failure_by_12m, ["patient_id"]].copy()
    restart_labels["target"] = (
        outcome.event_classification.eq("TEMPORARY_GAP_RESTARTED")
        .loc[gap_failure_by_12m]
        .astype(int)
        .to_numpy()
    )
    restart = treatment_features.merge(
        restart_labels, on="patient_id", how="inner", validate="one_to_one"
    )
    restart["target_name"] = "restarted_after_gap"

    datasets = {
        "non_initiated_within_90_days": initiation_features,
        "discontinued_within_12_months": discontinuation,
        "switched_treatment": switch,
        "restarted_after_gap": restart,
    }
    target_audit_rows = [
        {
            "target": name,
            "computability": "COMPUTABLE",
            "analysis_population_n": len(frame),
            "positive_n": int(frame.target.sum()),
            "prevalence": float(frame.target.mean()),
            "model_status": (
                "MODELLED" if int(frame.target.sum()) >= MIN_MODEL_EVENTS else "NOT_MODELLED_LOW_EVENT_COUNT"
            ),
            "definition": {
                "non_initiated_within_90_days": "Eligible/observable primary mHSPC cohort without qualifying treatment initiation by day 90.",
                "discontinued_within_12_months": "60-day permissible-gap persistence failure by day 365; competing events before day 365 excluded.",
                "switched_treatment": "Explicit switch by day 365 versus remaining event-free through day 365; early competing events excluded.",
                "restarted_after_gap": "Temporary gap with observed restart versus non-restarted discontinuation among 60-day gap failures by day 365.",
            }[name],
            "proxy_limitation": {
                "non_initiated_within_90_days": "Synthetic governed eligibility and normalized treatment start; not clinical eligibility.",
                "discontinued_within_12_months": "Gap-based endpoint is assumption-dependent and dispensing is not ingestion.",
                "switched_treatment": "Conditional risk set excludes early competing events and is not treatment effectiveness.",
                "restarted_after_gap": "Conditional on an observed/assumed 60-day gap failure; threshold-dependent.",
            }[name],
        }
        for name, frame in datasets.items()
    ]
    target_audit_rows.append(
        {
            "target": "initiated_within_90_days",
            "computability": "COMPUTABLE",
            "analysis_population_n": len(initiation_features),
            "positive_n": int((1 - initiation_features.target).sum()),
            "prevalence": float((1 - initiation_features.target).mean()),
            "model_status": "NOT_SEPARATELY_MODELLED_EXACT_COMPLEMENT",
            "definition": "Exact complement of non_initiated_within_90_days in the same risk set.",
            "proxy_limitation": "A duplicate model would contain identical information with reversed signs.",
        }
    )
    return datasets, pd.DataFrame(target_audit_rows)


def feature_dictionary(datasets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    combined = pd.concat(datasets.values(), ignore_index=True)
    definitions = [
        ("age_at_index", "patient.age_at_index", "baseline", "ALLOWED", "Available at index", "LOW", "Age at governed index", "Synthetic age; not a treatment recommendation"),
        ("age_band", "derived from patient.age_at_index", "baseline", "ALLOWED_SUBGROUP_ONLY", "Redundant with continuous age in model", "LOW", "Operational age segment", "Band boundaries are analytic"),
        ("comorbidity_score", "patient.comorbidity_score", "baseline", "ALLOWED", "Available at index", "MEDIUM", "Synthetic comorbidity burden", "Not a validated clinical index"),
        ("frailty_proxy", "patient.frailty_proxy", "baseline", "ALLOWED", "Available at index", "MEDIUM", "Synthetic frailty proxy", "Not a clinical frailty assessment"),
        ("access_index", "patient.access_index", "baseline", "ALLOWED", "Governed feature timing allows prediction", "MEDIUM", "Synthetic access proxy", "May encode market/scenario generation rules"),
        ("prior_healthcare_utilization_180d", "encounter.encounter_date < prediction index", "baseline", "ALLOWED", "Strict pre-index count", "LOW", "Encounter count in prior 180 days", "Only captured synthetic encounters"),
        ("prior_treatment_count", "treatment_episode.start < prediction index", "baseline", "ALLOWED", "Strict pre-index episodes", "LOW", "Prior normalized treatment lines", "Often zero in initial-treatment cohort"),
        ("prior_treatment_status", "derived prior_treatment_count", "baseline", "ALLOWED", "Safe derived category", "LOW", "Prior treatment yes/no", "Zero variance may limit use"),
        ("disease_state", "cohort_patient_flags.pathway_disease_state", "baseline", "ALLOWED", "Governed cohort state at index", "LOW", "Disease pathway state", "Constant in primary mHSPC model"),
        ("metastatic_site", "diagnosis.metastatic_site", "baseline", "ALLOWED", "Available at diagnosis", "MEDIUM", "Synthetic metastatic site", "Unknown/not-applicable are data categories"),
        ("market_code", "patient.market_code", "baseline", "ALLOWED", "Available at index", "MEDIUM", "Synthetic market", "May capture unmeasured market construction effects"),
        ("care_setting", "last encounter/provider available by index", "baseline", "ALLOWED", "No post-index encounter used", "MEDIUM", "Care setting proxy", "Setting is synthetic and target-stage-specific"),
        ("provider_specialty", "last safe provider available by index", "baseline", "ALLOWED", "No provider ID used", "MEDIUM", "Provider specialty", "May be constant at eligibility"),
        ("provider_volume_band", "provider.annual_prostate_volume transformed to band", "baseline", "ALLOWED", "Safe aggregate; provider ID excluded", "MEDIUM", "Provider volume band", "Fixed analytic bands are not validated capacity thresholds"),
        ("referral_proxy", "referral dates/status observed by index", "baseline", "ALLOWED_STAGE_CONDITIONAL", "Initiation referrals after eligibility are excluded; pre-treatment referrals allowed for later targets", "MEDIUM", "Referral completion proxy", "No causal barrier interpretation"),
        ("prior_hospitalization", "pre-index encounter type", "baseline", "ALLOWED_IF_OBSERVED", "Outcome hospitalisation_flag excluded", "HIGH", "Prior captured hospital encounter", "No qualifying baseline hospital encounter types in primary release"),
        ("insurance_type", "patient.insurance_type", "baseline", "ALLOWED", "Available at index", "HIGH", "Synthetic payer category", "Missingness/category meaning differs by market"),
        ("calendar_period", "derived prediction index year", "baseline", "ALLOWED", "Available at index", "LOW", "Calendar cohort", "May reflect simulation version rather than temporal practice"),
        ("time_since_diagnosis_days", "prediction index - diagnosis_date", "baseline", "ALLOWED", "Uses dates no later than index", "LOW", "Time from diagnosis", "Often zero for initiation"),
        ("time_since_metastasis_days", "prediction index - metastatic_date", "baseline", "ALLOWED", "Uses dates no later than index", "MEDIUM", "Time from metastatic evidence", "Synthetic state timing"),
        ("distance_or_rurality", "NOT AVAILABLE", "baseline", "EXCLUDED", "No legally/analytically justified field", "HIGH", "Potential geographic access factor", "Postal prefix is not transformed or used"),
        ("patient_id", "all patient-level tables", "identifier", "EXCLUDED", "Identifier; split grouping only", "CRITICAL", "Record linkage only", "Never a predictor"),
        ("provider_id", "encounter/provider tables", "identifier", "EXCLUDED", "Replaced by safe specialty/setting/volume aggregates", "CRITICAL", "Provider linkage only", "Never a predictor"),
        ("treatment_start_date", "treatment_episode", "post-outcome for initiation", "EXCLUDED_AS_FEATURE", "Target/future information for initiation; index only for persistence", "CRITICAL", "Treatment timing", "Never entered design matrix"),
        ("days_to_initiation", "cohort flags/patient_journey", "target-derived", "EXCLUDED", "Directly encodes initiation target", "CRITICAL", "Outcome timing", "Leakage"),
        ("discontinuation_flag", "treatment_episode/patient_journey", "post-outcome", "EXCLUDED", "Target-derived future outcome", "CRITICAL", "Documented stop", "Leakage"),
        ("switch_flag", "treatment_episode/patient_journey", "post-outcome", "EXCLUDED", "Target-derived future outcome", "CRITICAL", "Treatment switch", "Leakage"),
        ("restart_flag", "treatment_episode/patient_journey", "post-outcome", "EXCLUDED", "Target-derived future outcome", "CRITICAL", "Treatment restart", "Leakage"),
        ("hospitalisation_flag", "patient_journey outcome", "post-outcome", "EXCLUDED", "Final outcome flag; only pre-index encounter evidence allowed", "CRITICAL", "Hospitalisation outcome", "Leakage"),
        ("post_index_encounters", "encounter after prediction index", "future", "EXCLUDED", "Strict temporal leakage rule", "CRITICAL", "Later utilization", "Unavailable at prediction time"),
        ("censor_reason", "observation/persistence outputs", "post-outcome", "EXCLUDED", "Used only for risk-set construction", "CRITICAL", "Follow-up endpoint", "Selection/target construction only"),
    ]
    rows = []
    model_features = set(NUMERIC_MODEL_FEATURES + CATEGORICAL_MODEL_FEATURES)
    for name, source, timing, allowed, reason, risk, interpretation, limitation in definitions:
        missingness = float(combined[name].isna().mean()) if name in combined else None
        rows.append(
            {
                "feature_name": name,
                "source_column": source,
                "baseline_or_post_outcome": timing,
                "allowed_or_excluded": allowed,
                "reason": reason,
                "missingness": missingness,
                "leakage_risk": risk,
                "clinical_interpretation": interpretation,
                "proxy_limitation": limitation,
                "entered_model_design_matrix": name in model_features and allowed.startswith("ALLOWED"),
            }
        )
    return pd.DataFrame(rows)


def _continuous_association(target_name: str, frame: pd.DataFrame, feature: str) -> dict[str, Any]:
    values = pd.to_numeric(frame[feature], errors="coerce")
    missingness = float(values.isna().mean())
    median = float(values.median())
    filled = values.fillna(median)
    scale = float(filled.std(ddof=0))
    if scale < 1e-10:
        return {
            "analysis_type": "UNIVARIATE_ASSOCIATION",
            "target": target_name,
            "feature_name": feature,
            "feature_type": "numeric",
            "level": "PER_SD",
            "n": len(frame),
            "event_n": int(frame.target.sum()),
            "event_rate": float(frame.target.mean()),
            "odds_ratio": 1.0,
            "ci_lower": 1.0,
            "ci_upper": 1.0,
            "association_direction": "NO_VARIATION",
            "magnitude": 0.0,
            "missingness": missingness,
            "evidence_type": "NOT VERIFIED",
            "limitation": "Feature has zero variance in this target risk set.",
        }
    standardized = ((filled - filled.mean()) / scale).to_numpy()[:, None]
    coefficients, covariance, _ = fit_logistic(
        standardized, frame.target.to_numpy(dtype=float), l2_penalty=1e-6
    )
    coefficient = float(coefficients[1])
    standard_error = float(math.sqrt(max(covariance[1, 1], 0)))
    ci_lower = float(math.exp(np.clip(coefficient - 1.96 * standard_error, -20, 20)))
    ci_upper = float(math.exp(np.clip(coefficient + 1.96 * standard_error, -20, 20)))
    negative_mean = float(filled[frame.target.eq(0)].mean())
    positive_mean = float(filled[frame.target.eq(1)].mean())
    return {
        "analysis_type": "UNIVARIATE_ASSOCIATION",
        "target": target_name,
        "feature_name": feature,
        "feature_type": "numeric",
        "level": "PER_SD",
        "n": len(frame),
        "event_n": int(frame.target.sum()),
        "event_rate": float(frame.target.mean()),
        "reference_n": int(frame.target.eq(0).sum()),
        "reference_event_rate": 0.0,
        "positive_group_mean": positive_mean,
        "negative_group_mean": negative_mean,
        "standardized_mean_difference": (positive_mean - negative_mean) / scale,
        "log_odds_coefficient": coefficient,
        "odds_ratio": float(math.exp(np.clip(coefficient, -20, 20))),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "association_direction": "HIGHER_RISK" if coefficient > 0 else "LOWER_RISK",
        "magnitude": abs(coefficient),
        "missingness": missingness,
        "small_cell_flag": False,
        "evidence_type": (
            "ASSOCIATED" if ci_lower > 1 or ci_upper < 1 else "OBSERVED DESCRIPTIVE"
        ),
        "causal_interpretation_allowed": False,
        "limitation": "Univariate association; confounding and synthetic generation effects remain.",
    }


def _categorical_associations(
    target_name: str, frame: pd.DataFrame, feature: str
) -> list[dict[str, Any]]:
    values = frame[feature].astype("string").fillna("MISSING")
    target = frame.target.astype(int)
    levels = sorted(values.unique())
    if len(levels) <= 1:
        return [
            {
                "analysis_type": "UNIVARIATE_ASSOCIATION",
                "target": target_name,
                "feature_name": feature,
                "feature_type": "categorical",
                "level": str(levels[0]),
                "n": len(frame),
                "event_n": int(target.sum()),
                "event_rate": float(target.mean()),
                "reference_n": 0,
                "reference_event_rate": None,
                "risk_difference": None,
                "log_odds_coefficient": 0.0,
                "odds_ratio": 1.0,
                "ci_lower": 1.0,
                "ci_upper": 1.0,
                "association_direction": "NO_VARIATION",
                "magnitude": 0.0,
                "missingness": float(frame[feature].isna().mean()),
                "small_cell_flag": False,
                "evidence_type": "NOT VERIFIED",
                "causal_interpretation_allowed": False,
                "limitation": "Feature has one observed level and cannot estimate an association.",
            }
        ]
    rows = []
    for level in levels:
        exposed = values.eq(level)
        a = int((exposed & target.eq(1)).sum())
        b = int((exposed & target.eq(0)).sum())
        c = int((~exposed & target.eq(1)).sum())
        d = int((~exposed & target.eq(0)).sum())
        corrected = [value + 0.5 for value in [a, b, c, d]]
        odds_ratio = corrected[0] * corrected[3] / (corrected[1] * corrected[2])
        standard_error = math.sqrt(sum(1 / value for value in corrected))
        log_or = math.log(odds_ratio)
        ci_lower = math.exp(log_or - 1.96 * standard_error)
        ci_upper = math.exp(log_or + 1.96 * standard_error)
        small_cell = bool(exposed.sum() < 30 or min(a, b) < 5)
        rows.append(
            {
                "analysis_type": "UNIVARIATE_ASSOCIATION",
                "target": target_name,
                "feature_name": feature,
                "feature_type": "categorical",
                "level": str(level),
                "n": int(exposed.sum()),
                "event_n": a,
                "event_rate": a / (a + b) if a + b else None,
                "reference_n": int((~exposed).sum()),
                "reference_event_rate": c / (c + d) if c + d else None,
                "risk_difference": (
                    a / (a + b) - c / (c + d) if a + b and c + d else None
                ),
                "log_odds_coefficient": log_or,
                "odds_ratio": odds_ratio,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "association_direction": "HIGHER_RISK" if odds_ratio > 1 else "LOWER_RISK",
                "magnitude": abs(log_or),
                "missingness": float(frame[feature].isna().mean()),
                "small_cell_flag": small_cell,
                "evidence_type": (
                    "NOT VERIFIED"
                    if small_cell
                    else "ASSOCIATED"
                    if ci_lower > 1 or ci_upper < 1
                    else "OBSERVED DESCRIPTIVE"
                ),
                "causal_interpretation_allowed": False,
                "limitation": "One-versus-rest descriptive odds ratio with 0.5 continuity correction; not adjusted or causal.",
            }
        )
    return rows


def association_table(datasets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target_name, frame in datasets.items():
        if int(frame.target.sum()) < MIN_MODEL_EVENTS:
            continue
        for feature in ASSOCIATION_FEATURES:
            if feature in NUMERIC_MODEL_FEATURES:
                rows.append(_continuous_association(target_name, frame, feature))
            else:
                rows.extend(_categorical_associations(target_name, frame, feature))
    return pd.DataFrame(rows)


def temporal_split(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Timestamp]:
    unique_dates = np.sort(frame.prediction_index_date.dropna().unique())
    cutoff = pd.Timestamp(unique_dates[max(0, round(0.75 * len(unique_dates)) - 1)])
    train = frame.prediction_index_date.le(cutoff)
    test = frame.prediction_index_date.gt(cutoff)
    if train.sum() == 0 or test.sum() == 0 or frame.loc[test, "target"].nunique() < 2:
        ordered = frame.sort_values(["prediction_index_date", "patient_id"]).index
        split = round(0.75 * len(ordered))
        train = frame.index.isin(ordered[:split])
        test = ~train
        cutoff = pd.Timestamp(frame.loc[train, "prediction_index_date"].max())
    return pd.Series(train, index=frame.index), pd.Series(test, index=frame.index), cutoff


def calibration_bins(
    target_name: str, target: np.ndarray, probability: np.ndarray
) -> pd.DataFrame:
    frame = pd.DataFrame({"target": target, "probability": probability})
    try:
        frame["bin"] = pd.qcut(frame.probability.rank(method="first"), 10, labels=False)
    except ValueError:
        frame["bin"] = 0
    result = frame.groupby("bin").agg(
        n=("target", "size"),
        mean_predicted_probability=("probability", "mean"),
        observed_event_rate=("target", "mean"),
    ).reset_index()
    result.insert(0, "target_name", target_name)
    return result


def subgroup_metrics(
    target_name: str,
    test: pd.DataFrame,
    probability: np.ndarray,
    threshold: float,
) -> pd.DataFrame:
    scored = test.copy()
    scored["probability"] = probability
    rows: list[dict[str, Any]] = []
    for dimension in SUBGROUP_DIMENSIONS:
        for value, group in scored.groupby(dimension, dropna=False):
            y = group.target.to_numpy(dtype=int)
            p = group.probability.to_numpy(dtype=float)
            metrics = classification_metrics(y, p, threshold)
            rows.append(
                {
                    "target": target_name,
                    "model": "logistic_regression",
                    "split": "temporal_test",
                    "subgroup_dimension": dimension,
                    "subgroup_value": str(value),
                    "n": len(group),
                    "positive_n": int(y.sum()),
                    "prevalence": float(y.mean()),
                    "small_cell_flag": bool(len(group) < 30 or min(y.sum(), len(y) - y.sum()) < 5),
                    **metrics,
                    "interpretation": "Predictive subgroup performance only; differences may reflect sample size, measurement or synthetic construction.",
                }
            )
    return pd.DataFrame(rows)


def permutation_importance(
    frame: pd.DataFrame,
    target: np.ndarray,
    encoder: FeatureEncoder,
    coefficients: np.ndarray,
    rng: np.random.Generator,
) -> pd.DataFrame:
    baseline_probability = predict_logistic(encoder.transform(frame), coefficients)
    baseline = pr_auc(target, baseline_probability)
    rows = []
    for feature in encoder.numeric_features + encoder.categorical_features:
        drops: list[float] = []
        for _ in range(20):
            shuffled = frame.copy()
            shuffled[feature] = rng.permutation(shuffled[feature].to_numpy())
            score = pr_auc(target, predict_logistic(encoder.transform(shuffled), coefficients))
            if baseline is not None and score is not None:
                drops.append(baseline - score)
        rows.append(
            {
                "feature_name": feature,
                "permutation_importance_mean_pr_auc_drop": float(np.mean(drops)) if drops else None,
                "permutation_importance_sd": float(np.std(drops)) if drops else None,
                "repeats": len(drops),
            }
        )
    return pd.DataFrame(rows)


def run_models(
    datasets: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metrics_rows: list[dict[str, Any]] = []
    subgroup_frames: list[pd.DataFrame] = []
    coefficient_rows: list[dict[str, Any]] = []
    importance_frames: list[pd.DataFrame] = []
    calibration_frames: list[pd.DataFrame] = []
    for target_index, (target_name, frame) in enumerate(datasets.items()):
        positive_n = int(frame.target.sum())
        if positive_n < MIN_MODEL_EVENTS:
            metrics_rows.append(
                {
                    "target": target_name,
                    "model": "logistic_regression",
                    "model_status": "NOT_RUN",
                    "reason": f"Only {positive_n} positive events; minimum is {MIN_MODEL_EVENTS}.",
                    "analysis_population_n": len(frame),
                    "positive_n": positive_n,
                }
            )
            continue
        train_mask, test_mask, cutoff = temporal_split(frame)
        train = frame.loc[train_mask].copy()
        test = frame.loc[test_mask].copy()
        encoder = FeatureEncoder.fit(train)
        train_matrix = encoder.transform(train)
        test_matrix = encoder.transform(test)
        coefficients, covariance, iterations = fit_logistic(
            train_matrix, train.target.to_numpy(dtype=float)
        )
        probability = predict_logistic(test_matrix, coefficients)
        y_test = test.target.to_numpy(dtype=int)
        threshold = float(np.quantile(probability, 1 - OPERATIONAL_CAPACITY))
        evaluated = classification_metrics(y_test, probability, threshold)
        rng = np.random.default_rng(RANDOM_SEED + target_index)
        pr_lower, pr_upper = bootstrap_interval(y_test, probability, pr_auc, rng)
        roc_lower, roc_upper = bootstrap_interval(y_test, probability, roc_auc, rng)
        brier_lower, brier_upper = bootstrap_interval(
            y_test, probability, lambda y, p: brier_score(y, p), rng
        )
        metrics_rows.append(
            {
                "target": target_name,
                "model": "logistic_regression",
                "model_status": "FITTED",
                "reason": "Transparent NumPy IRLS logistic baseline; L2 penalty=1.0.",
                "analysis_population_n": len(frame),
                "positive_n": positive_n,
                "prevalence": float(frame.target.mean()),
                "split_method": "patient-grouped temporal holdout",
                "temporal_cutoff": cutoff.date(),
                "train_n": len(train),
                "test_n": len(test),
                "test_positive_n": int(y_test.sum()),
                "operational_capacity_fraction": OPERATIONAL_CAPACITY,
                "iterations": iterations,
                "pr_auc_ci_lower": pr_lower,
                "pr_auc_ci_upper": pr_upper,
                "roc_auc_ci_lower": roc_lower,
                "roc_auc_ci_upper": roc_upper,
                "brier_ci_lower": brier_lower,
                "brier_ci_upper": brier_upper,
                **evaluated,
                "causal_interpretation_allowed": False,
            }
        )
        standard_errors = np.sqrt(np.clip(np.diag(covariance), 0, None))
        for index, (encoded_name, source_feature) in enumerate(
            zip(encoder.encoded_names, encoder.source_features, strict=True), start=1
        ):
            coefficient = float(coefficients[index])
            standard_error = float(standard_errors[index])
            coefficient_rows.append(
                {
                    "analysis_type": "MULTIVARIABLE_LOGISTIC_COEFFICIENT",
                    "target": target_name,
                    "feature_name": source_feature,
                    "feature_type": "standardized_numeric_or_reference_coded_category",
                    "level": encoded_name,
                    "n": len(train),
                    "event_n": int(train.target.sum()),
                    "log_odds_coefficient": coefficient,
                    "odds_ratio": float(math.exp(np.clip(coefficient, -20, 20))),
                    "ci_lower": float(
                        math.exp(np.clip(coefficient - 1.96 * standard_error, -20, 20))
                    ),
                    "ci_upper": float(
                        math.exp(np.clip(coefficient + 1.96 * standard_error, -20, 20))
                    ),
                    "association_direction": "HIGHER_PREDICTED_RISK" if coefficient > 0 else "LOWER_PREDICTED_RISK",
                    "magnitude": abs(coefficient),
                    "evidence_type": "PREDICTIVE",
                    "causal_interpretation_allowed": False,
                    "limitation": "Penalized multivariable coefficient; Hessian interval is approximate and not a causal confidence interval.",
                }
            )
        importance = permutation_importance(test, y_test, encoder, coefficients, rng)
        importance.insert(0, "target", target_name)
        importance_frames.append(importance)
        subgroup_frames.append(subgroup_metrics(target_name, test, probability, threshold))
        calibration_frames.append(calibration_bins(target_name, y_test, probability))

        metrics_rows.extend(
            [
                {
                    "target": target_name,
                    "model": "tree_based_challenger",
                    "model_status": "NOT_RUN",
                    "reason": "Optional challenger omitted because no validated tree library is installed; no dependency was added to the controlled environment.",
                    "analysis_population_n": len(frame),
                    "positive_n": positive_n,
                },
                {
                    "target": target_name,
                    "model": "survival_model",
                    "model_status": "NOT_RUN",
                    "reason": "Competing-risk/survival library unavailable; gap-defined persistence and competing events do not justify a home-grown survival model.",
                    "analysis_population_n": len(frame),
                    "positive_n": positive_n,
                },
            ]
        )
    return (
        pd.DataFrame(metrics_rows),
        pd.concat(subgroup_frames, ignore_index=True) if subgroup_frames else pd.DataFrame(),
        pd.DataFrame(coefficient_rows),
        pd.concat(importance_frames, ignore_index=True) if importance_frames else pd.DataFrame(),
        pd.concat(calibration_frames, ignore_index=True) if calibration_frames else pd.DataFrame(),
    )


def _driver_category(feature: str) -> str:
    if feature in {"comorbidity_score", "frailty_proxy", "metastatic_site", "disease_state"}:
        return "clinical"
    if feature in {"age_at_index", "age_band", "insurance_type"}:
        return "patient"
    if feature in {"care_setting", "provider_specialty", "provider_volume_band"}:
        return "provider"
    if feature in {"access_index", "referral_proxy"}:
        return "access"
    if feature in {
        "prior_healthcare_utilization_180d",
        "prior_treatment_count",
        "prior_treatment_status",
        "time_since_diagnosis_days",
        "time_since_metastasis_days",
    }:
        return "pathway"
    return "administrative"


def _driver_actions(feature: str) -> tuple[str, str, str]:
    if feature in {"comorbidity_score", "frailty_proxy", "metastatic_site", "disease_state"}:
        return (
            "Medical review of proxy definition and confounding; no treatment recommendation",
            "Medical + Data Strategy",
            "Validated eligibility/measurement completeness by segment",
        )
    if feature in {"care_setting", "provider_specialty", "provider_volume_band", "referral_proxy"}:
        return (
            "Audit pathway handoffs and timestamp completeness in the affected segment",
            "Commercial Operations + Data Strategy",
            "Documented referral/handoff completion and 90-day outcome coverage",
        )
    if feature in {"access_index", "insurance_type", "market_code"}:
        return (
            "Validate access proxy and measure administrative pathway delay",
            "Market Access + Data Strategy",
            "Censor-aware time-to-initiation and missingness by segment",
        )
    return (
        "Validate the operational measurement and reproduce association in an independent period",
        "Data Strategy",
        "Reproducible association and calibrated subgroup performance",
    )


def build_driver_tree(
    associations: pd.DataFrame, importance: pd.DataFrame
) -> pd.DataFrame:
    eligible = associations[
        associations.analysis_type.eq("UNIVARIATE_ASSOCIATION")
        & associations.evidence_type.eq("ASSOCIATED")
        & ~associations.small_cell_flag.fillna(False)
        & associations.magnitude.notna()
        & (associations.ci_lower.gt(1) | associations.ci_upper.lt(1))
    ].copy()
    eligible = eligible.sort_values("magnitude", ascending=False).drop_duplicates(
        ["target", "feature_name"]
    ).head(20)
    rows: list[dict[str, Any]] = []
    for row in eligible.itertuples(index=False):
        intervention, owner, kpi = _driver_actions(row.feature_name)
        confidence = (
            "MEDIUM"
            if row.ci_lower > 1 or row.ci_upper < 1
            else "LOW"
        )
        rows.append(
            {
                "driver_category": _driver_category(row.feature_name),
                "observed_proxy": row.feature_name,
                "affected_outcome": row.target,
                "segment": row.level,
                "evidence_type": "ASSOCIATED",
                "association_direction": row.association_direction,
                "magnitude": f"OR={row.odds_ratio:.3f} (95% approximate {row.ci_lower:.3f}-{row.ci_upper:.3f})",
                "confidence": confidence,
                "limitation": row.limitation,
                "required_validation": "Reproduce in independent non-synthetic data; review confounding, target validity and segment coding.",
                "possible_intervention": intervention,
                "owner": owner,
                "success_KPI": kpi,
            }
        )
    top_importance = importance[
        importance.permutation_importance_mean_pr_auc_drop.gt(0)
    ].sort_values("permutation_importance_mean_pr_auc_drop", ascending=False).head(12)
    for row in top_importance.itertuples(index=False):
        intervention, owner, kpi = _driver_actions(row.feature_name)
        rows.append(
            {
                "driver_category": _driver_category(row.feature_name),
                "observed_proxy": row.feature_name,
                "affected_outcome": row.target,
                "segment": "ALL",
                "evidence_type": "PREDICTIVE",
                "association_direction": "MODEL_DEPENDENT",
                "magnitude": f"Mean PR-AUC drop={row.permutation_importance_mean_pr_auc_drop:.4f}",
                "confidence": "MEDIUM" if row.permutation_importance_mean_pr_auc_drop >= 0.01 else "LOW",
                "limitation": "Permutation importance measures predictive dependence, not direction or causality; correlated features share importance.",
                "required_validation": "Repeat on a locked external period and inspect calibration/subgroup stability.",
                "possible_intervention": intervention,
                "owner": owner,
                "success_KPI": kpi,
            }
        )
    rows.extend(
        [
            {
                "driver_category": "data quality",
                "observed_proxy": "referral_proxy_at_eligibility",
                "affected_outcome": "non_initiated_within_90_days",
                "segment": "ALL",
                "evidence_type": "DATA QUALITY SIGNAL",
                "association_direction": "NOT VERIFIED",
                "magnitude": "0 pre-index referral records in the primary initiation cohort",
                "confidence": "HIGH",
                "limitation": "Referral events occur after eligibility, so using them for initiation prediction would leak future pathway information.",
                "required_validation": "Confirm real operational timestamp availability and prediction moment with Commercial and Data Strategy.",
                "possible_intervention": "Improve referral timestamp capture before any future predictive use",
                "owner": "Data Strategy + Commercial Operations",
                "success_KPI": "Percentage of referrals timestamped before prediction index",
            },
            {
                "driver_category": "data quality",
                "observed_proxy": "baseline_utilization_and_provider_specialty",
                "affected_outcome": "non_initiated_within_90_days",
                "segment": "ALL",
                "evidence_type": "DATA QUALITY SIGNAL",
                "association_direction": "NO_VARIATION",
                "magnitude": "Only diagnosis encounter at eligibility; provider specialty is urology for all rows",
                "confidence": "HIGH",
                "limitation": "Lack of pre-index history prevents meaningful utilization or specialty driver estimation.",
                "required_validation": "Assess availability of 180/365-day pre-index claims/encounters.",
                "possible_intervention": "Extend governed baseline data collection before driver re-estimation",
                "owner": "Data Strategy",
                "success_KPI": "Baseline observation completeness at 180 and 365 days",
            },
        ]
    )
    return pd.DataFrame(rows)


def render_calibration_plot(calibration: pd.DataFrame) -> None:
    colors = [(31, 119, 180), (214, 39, 40), (44, 160, 44), (148, 103, 189)]
    canvas = Canvas(1500, 980, (250, 252, 255))
    left, top, right, bottom = 150, 125, 1420, 815
    canvas.text(70, 45, "TEMPORAL HOLDOUT CALIBRATION", (24, 52, 91), 3)
    canvas.rectangle(left, top, right - left, bottom - top, (255, 255, 255))
    canvas.outline(left, top, right - left, bottom - top, (70, 82, 99), 2)
    for tick in range(6):
        value = tick / 5
        x = left + round((right - left) * value)
        y = bottom - round((bottom - top) * value)
        line(canvas, left, y, right, y, (225, 231, 239), 1)
        line(canvas, x, top, x, bottom, (238, 241, 246), 1)
        canvas.text(x - 18, bottom + 18, f"{value:.1f}", (80, 88, 102), 2)
        canvas.text(72, y - 8, f"{value:.1f}", (80, 88, 102), 2)
    line(canvas, left, bottom, right, top, (110, 118, 130), 3)
    canvas.text(830, 66, "IDEAL", (70, 78, 90), 2)
    aliases = {
        "non_initiated_within_90_days": "NON_INITIATED_90D",
        "discontinued_within_12_months": "DISCONTINUED_12M",
        "switched_treatment": "SWITCHED_12M",
        "restarted_after_gap": "RESTARTED_AFTER_GAP",
    }
    for index, (target, group) in enumerate(calibration.groupby("target_name")):
        color = colors[index % len(colors)]
        coordinates = []
        for row in group.sort_values("mean_predicted_probability").itertuples(index=False):
            x = left + round((right - left) * float(row.mean_predicted_probability))
            y = bottom - round((bottom - top) * float(row.observed_event_rate))
            coordinates.append((x, y))
        for first, second in zip(coordinates, coordinates[1:], strict=False):
            line(canvas, *first, *second, color, 3)
        for x, y in coordinates:
            canvas.rectangle(x - 3, y - 3, 7, 7, color)
        legend_y = 94 + index * 27
        line(canvas, 830, legend_y + 6, 870, legend_y + 6, color, 4)
        canvas.text(882, legend_y, aliases.get(target, target[:24]), (35, 43, 56), 2)
    canvas.text(560, 900, "MEAN PREDICTED PROBABILITY", (50, 59, 73), 2)
    canvas.text(20, 450, "OBSERVED RATE", (50, 59, 73), 2)
    canvas.save(FIGURES_DIR / "calibration_plot.png")


def render_feature_importance(importance: pd.DataFrame) -> None:
    top = importance.sort_values(
        "permutation_importance_mean_pr_auc_drop", ascending=False
    ).head(18).iloc[::-1]
    canvas = Canvas(1600, 1100, (250, 252, 255))
    canvas.text(55, 40, "PERMUTATION IMPORTANCE - PR AUC DROP", (24, 52, 91), 3)
    left, top_y, right, bottom = 610, 120, 1510, 1010
    canvas.rectangle(left, top_y, right - left, bottom - top_y, (255, 255, 255))
    canvas.outline(left, top_y, right - left, bottom - top_y, (70, 82, 99), 2)
    maximum = max(float(top.permutation_importance_mean_pr_auc_drop.max()), 0.001)
    row_height = (bottom - top_y) / max(len(top), 1)
    colors = [(31, 119, 180), (214, 39, 40), (44, 160, 44), (148, 103, 189)]
    target_colors = {
        value: colors[index % len(colors)]
        for index, value in enumerate(sorted(top.target.unique()))
    }
    aliases = {
        "non_initiated_within_90_days": "NON_INIT90",
        "discontinued_within_12_months": "DISC_12M",
        "switched_treatment": "SWITCH_12M",
        "restarted_after_gap": "RESTART_GAP",
    }
    for index, row in enumerate(top.itertuples(index=False)):
        y = round(top_y + index * row_height + 5)
        value = max(0.0, float(row.permutation_importance_mean_pr_auc_drop))
        width = round((right - left - 80) * value / maximum)
        label = f"{aliases.get(row.target, row.target[:10])} | {row.feature_name[:34]}"
        canvas.text(20, y + 5, label, (40, 48, 61), 2)
        canvas.rectangle(left, y, width, max(8, round(row_height - 10)), target_colors[row.target])
        canvas.text(left + width + 8, y + 5, f"{value:.3f}", (40, 48, 61), 2)
    canvas.save(FIGURES_DIR / "feature_importance.png")


def write_model_card(
    target_audit: pd.DataFrame,
    metrics: pd.DataFrame,
    associations: pd.DataFrame,
    importance: pd.DataFrame,
    subgroup: pd.DataFrame,
    feature_audit: pd.DataFrame,
) -> None:
    fitted = metrics[metrics.model_status.eq("FITTED")]
    top_associations = associations[
        associations.analysis_type.eq("UNIVARIATE_ASSOCIATION")
        & associations.evidence_type.eq("ASSOCIATED")
        & ~associations.small_cell_flag.fillna(False)
    ].sort_values("magnitude", ascending=False).head(8)
    top_predictive = importance.sort_values(
        "permutation_importance_mean_pr_auc_drop", ascending=False
    ).head(8)
    unstable = []
    for (target, dimension), group in subgroup[
        ~subgroup.small_cell_flag.fillna(True) & subgroup.roc_auc.notna()
    ].groupby(["target", "subgroup_dimension"]):
        spread = float(group.roc_auc.max() - group.roc_auc.min())
        if spread >= 0.10:
            unstable.append(f"{target}/{dimension}: ROC-AUC spread {spread:.3f}")
    metric_lines = [
        f"- `{row.target}`: n={int(row.analysis_population_n):,}, temporal test n={int(row.test_n):,}, PR-AUC={row.pr_auc:.3f} ({row.pr_auc_ci_lower:.3f}-{row.pr_auc_ci_upper:.3f}), ROC-AUC={row.roc_auc:.3f}, Brier={row.brier_score:.3f}, recall at ~20% capacity={row.recall_at_capacity:.3f}."
        for row in fitted.itertuples(index=False)
    ]
    utility_lines = [
        (
            f"- `{row.target}`: "
            + (
                "limited temporal discrimination; investigate measurement/target stability before operational use."
                if row.roc_auc < 0.60
                else "directional temporal discrimination only; calibration and external validation remain required."
            )
        )
        for row in fitted.itertuples(index=False)
    ]
    target_lines = [
        f"- `{row.target}` — {row.model_status}; n={int(row.analysis_population_n):,}, positives={int(row.positive_n):,} ({100 * row.prevalence:.1f}%): {row.definition} Limitation: {row.proxy_limitation}"
        for row in target_audit.itertuples(index=False)
    ]
    association_lines = [
        f"- `{row.target}` / `{row.feature_name}` / `{row.level}`: OR {row.odds_ratio:.3f} ({row.ci_lower:.3f}-{row.ci_upper:.3f}), {row.association_direction}."
        for row in top_associations.itertuples(index=False)
    ]
    importance_lines = [
        f"- `{row.target}` / `{row.feature_name}`: mean temporal-test PR-AUC drop {row.permutation_importance_mean_pr_auc_drop:.4f}."
        for row in top_predictive.itertuples(index=False)
    ]
    excluded = feature_audit[feature_audit.allowed_or_excluded.str.startswith("EXCLUDED")]
    excluded_lines = [
        f"- `{row.feature_name}`: {row.reason} (leakage risk {row.leakage_risk})."
        for row in excluded.itertuples(index=False)
    ]
    report = f"""# Exploratory driver-analysis model card

> **{ANALYSIS_DISCLAIMER}**

## Intended use and prohibited use

This layer ranks transparent baseline associations and tests whether a simple logistic model can predict governed synthetic EDA targets on a later temporal holdout. **This is not causal inference and is not a clinical decision-support model.** It must not be used to recommend treatment, rank patients for care, infer clinical barriers, evaluate provider quality, or estimate commercial/financial impact.

Association, prediction and causality are separate: odds ratios are univariate associations; standardized multivariable coefficients and permutation importance are predictive/model-dependent; **causality is not established** for any row. SHAP/feature importance would not change that interpretation.

## Target audit

{chr(10).join(target_lines)}

`initiated_within_90_days` is not fitted separately because it is the exact complement of the non-initiation target. mCRPC and nmCRPC are not combined with the governed primary mHSPC cohort.

## Leakage controls

- Patient/provider IDs never enter a design matrix. Provider identity is reduced to specialty, setting and a fixed volume band.
- All encounter, referral and prior-treatment features are reconstructed with timestamps no later than the prediction index.
- Initiation prediction excludes all post-eligibility encounters and referrals. In this release every referral for the primary initiation cohort occurs after eligibility.
- Discontinuation, switch, restart, censoring, future treatment dates, final outcomes and outcome-derived flags are target/risk-set construction only.
- Temporal splitting uses the latest approximately 25% of prediction-index dates as the locked holdout; each patient appears in only one split.
- Imputation, standardization, category references and zero-variance filtering are fit on training data only.

## Model and evaluation

The baseline is an L2-regularized logistic regression implemented with transparent NumPy IRLS because the controlled environment contains no scikit-learn/statsmodels. Numeric coefficients are per training-set standard deviation; categories are reference-coded. Coefficient intervals are approximate penalized-Hessian intervals, not causal/inferential confidence intervals. Metric intervals use {BOOTSTRAP_REPEATS} temporal-test bootstrap samples.

{chr(10).join(metric_lines)}

Predictive-readiness interpretation:

{chr(10).join(utility_lines)}

The operational threshold is the temporal-test top {100 * OPERATIONAL_CAPACITY:.0f}% predicted-risk capacity, reported transparently with its confusion matrix. ROC-AUC is secondary to PR-AUC. Calibration and Brier score are reported because ranking alone is insufficient.

Tree challengers were not run because no validated tree library is installed; dependencies were not added. A home-grown tree would add opaque implementation risk. Survival models were not run because competing-risk tooling is unavailable and the discontinuation endpoint is gap-assumption-dependent. SHAP is unavailable and inappropriate without a justified challenger, so `shap_summary.png` is intentionally absent.

## Top associated drivers

{chr(10).join(association_lines) if association_lines else '- No stable non-small-cell association was verified.'}

These are synthetic unadjusted associations. A feature cannot be called a clinical barrier without external temporal, clinical and operational validation.

## Top predictive features

{chr(10).join(importance_lines) if importance_lines else '- No positive permutation importance was observed.'}

Permutation importance is model- and correlation-dependent. It does not supply direction, mechanism or causal attribution.

## Subgroup disparities and instability

{chr(10).join(f'- {value}' for value in unstable) if unstable else '- No non-small-cell subgroup ROC-AUC spread exceeded 0.10; small cells remain separately flagged.'}

Subgroup differences may be measurement artifacts, simulation effects or sampling noise. Performance is reported by market, disease state, age band, care setting and missingness pattern, including small-cell flags.

## Data-quality signals that may look like drivers

- At eligibility, only the diagnosis encounter is available for the primary cohort; pre-index utilization is zero and provider specialty is uniformly urology. These cannot support a meaningful utilization/specialty driver conclusion.
- Referrals occur after eligibility. Using referral completion for 90-day initiation prediction would be direct future-pathway leakage.
- Market, insurance and access categories may partly encode synthetic generation logic rather than modifiable real-world mechanisms.
- Gap-based discontinuation depends on the 60-day scenario and dispensing coverage is not ingestion.
- Missingness pattern performance can reflect data capture rather than patient risk.

## Features that must not be used

{chr(10).join(excluded_lines)}

## Candidate interventions for validation, not recommendations

- Validate referral timestamp completeness and define the operational prediction moment before testing any handoff intervention.
- Audit access/insurance proxy meaning and censor-aware delays by market; do not assume the association is an access barrier.
- Extend governed 180/365-day pre-index utilization history before reassessing pathway or provider drivers.
- Review comorbidity/frailty proxy validity with Medical before interpreting segment differences.
- Lock a future time period or independent dataset for calibration and subgroup validation.

No financial values, success probabilities or clinical-effectiveness estimates are provided. The separate intervention backlog assigns validation owners and measurable leading/outcome indicators only.

## Required validation ownership

- **Medical:** clinical coherence of eligibility, comorbidity/frailty, metastatic-site and gap endpoint definitions.
- **Commercial/Operations:** referral/handoff timestamps, operational capacity threshold and whether candidate workflow measures are actionable.
- **Data Strategy:** leakage audit, external temporal validation, baseline coverage, payer/market semantics, calibration and subgroup stability.
"""
    (OUTPUT_DIR / "model_card.md").write_text(report, encoding="utf-8")


def main() -> int:
    ensure_output_directories()
    analytical_dir, selection = resolve_analytical_data_dir()
    flags_path = OUTPUT_DIR / "cohort_patient_flags.parquet"
    persistence_path = OUTPUT_DIR / "persistence_event_data.parquet"
    if not flags_path.is_file() or not persistence_path.is_file():
        raise FileNotFoundError("Validated Prompt-2/3 cohort and persistence outputs are required")
    flags = pd.read_parquet(flags_path)
    persistence = pd.read_parquet(persistence_path)
    tables = load_validated_tables(analytical_dir)
    datasets, target_audit = build_target_datasets(flags, persistence, tables)
    feature_audit = feature_dictionary(datasets)
    associations = association_table(datasets)
    metrics, subgroup, coefficients, importance, calibration = run_models(datasets)
    association_output = pd.concat([associations, coefficients], ignore_index=True, sort=False)
    driver_tree = build_driver_tree(association_output, importance)

    outputs = {
        "driver_association_table.csv": association_output,
        "model_metrics.csv": metrics,
        "subgroup_metrics.csv": subgroup,
        "feature_dictionary_for_models.csv": feature_audit,
        "driver_tree.csv": driver_tree,
        "target_audit.csv": target_audit,
        "permutation_importance.csv": importance,
        "calibration_data.csv": calibration,
    }
    for filename, frame in outputs.items():
        frame.to_csv(OUTPUT_DIR / filename, index=False)
    render_calibration_plot(calibration)
    render_feature_importance(importance)
    write_model_card(target_audit, metrics, association_output, importance, subgroup, feature_audit)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "analytical_dataset": str(analytical_dir),
        "selection_method": selection.get("selection_method"),
        "targets": target_audit.to_dict(orient="records"),
        "fitted_logistic_models": int(
            (metrics.model.eq("logistic_regression") & metrics.model_status.eq("FITTED")).sum()
        ),
        "tree_models_fitted": 0,
        "survival_models_fitted": 0,
        "shap_generated": False,
        "source_data_modified": False,
    }
    (OUTPUT_DIR / "driver_analysis_run_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
