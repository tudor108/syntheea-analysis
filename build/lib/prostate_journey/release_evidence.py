"""Generate analytical starters and independent QA evidence for a frozen release."""

from __future__ import annotations

import html
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import DISCLAIMER
from .feature_engineering import (
    discontinuation_features,
    pathway_gap_features,
    treatment_initiation_features,
)

REQUIRED_MARKETS = {"US", "DE", "JP", "FR", "CN", "AU", "CA"}
DEEP_MARKETS = {"US", "DE", "JP"}
SCAN_MARKETS = {"FR", "CN", "AU", "CA"}
REALIZED_VALUE_PROXY_VERSION = "REALISED-VALUE-PROXY-SYN-v1.0"
SYNTHETIC_UNCERTAINTY_CAVEAT = (
    "Wilson intervals quantify finite-sample precision inside this synthetic scenario only; "
    "they are not real-world, causal, clinical, or commercial uncertainty."
)
NON_CAUSAL_CAVEAT = (
    "Descriptive synthetic prioritisation input only; it does not estimate causal impact, "
    "clinical benefit, commercial value, or addressability."
)

GRAINS = {
    "patient": "one independent synthetic patient archetype",
    "diagnosis": "one index prostate diagnosis per patient",
    "disease_state_event": "one dated disease-state event",
    "eligibility": "one eligibility assessment per patient",
    "organization": "one synthetic organization",
    "provider": "one stable provider master record",
    "encounter": "one dated patient-provider encounter",
    "referral": "one provider-to-provider referral",
    "active_surveillance": "one active-surveillance assessment per localized patient",
    "observation": "one observation and censoring record per patient",
    "treatment_episode": "one continuous treatment episode or line",
    "treatment_regimen": "one regimen per treatment episode",
    "treatment_regimen_component": "one treatment component per regimen",
    "prescription_event": "one dispensing, refill, or administration event",
    "adverse_event": "one dated adverse event",
    "outcome": "one derived outcome summary per patient",
    "patient_split": "one split assignment per patient archetype",
    "feature_timing": "one feature-governance definition",
    "patient_journey": "one derived analytical row per patient",
}

PRIMARY_KEYS = {
    "patient": "patient_id",
    "diagnosis": "diagnosis_id",
    "disease_state_event": "disease_state_event_id",
    "eligibility": "eligibility_id",
    "organization": "organization_id",
    "provider": "provider_id",
    "encounter": "encounter_id",
    "referral": "referral_id",
    "active_surveillance": "active_surveillance_id",
    "observation": "observation_id",
    "treatment_episode": "treatment_episode_id",
    "treatment_regimen": "regimen_id",
    "treatment_regimen_component": "component_id",
    "prescription_event": "prescription_event_id",
    "adverse_event": "adverse_event_id",
    "outcome": "outcome_id",
    "patient_split": "patient_split_id",
    "feature_timing": "feature_metadata_id",
    "patient_journey": "patient_id",
}

FOREIGN_KEYS = {
    ("provider", "organization_id"): "organization.organization_id",
    ("encounter", "provider_id"): "provider.provider_id",
    ("encounter", "organization_id"): "organization.organization_id",
    ("referral", "source_provider_id"): "provider.provider_id",
    ("referral", "destination_provider_id"): "provider.provider_id",
    ("referral", "source_organization_id"): "organization.organization_id",
    ("referral", "destination_organization_id"): "organization.organization_id",
    ("treatment_episode", "previous_episode_id"): "treatment_episode.treatment_episode_id",
    ("treatment_episode", "prescribing_provider_id"): "provider.provider_id",
    ("treatment_regimen", "treatment_episode_id"): "treatment_episode.treatment_episode_id",
    (
        "treatment_regimen_component",
        "treatment_episode_id",
    ): "treatment_episode.treatment_episode_id",
    ("treatment_regimen_component", "regimen_id"): "treatment_regimen.regimen_id",
    ("prescription_event", "component_id"): "treatment_regimen_component.component_id",
    ("prescription_event", "regimen_id"): "treatment_regimen.regimen_id",
    ("prescription_event", "treatment_episode_id"): "treatment_episode.treatment_episode_id",
    ("adverse_event", "treatment_episode_id"): "treatment_episode.treatment_episode_id",
}

COLUMN_DESCRIPTIONS = {
    "patient_id": "Stable synthetic patient identifier.",
    "market_code": "Configured two-letter analytical market code.",
    "market_depth": "Configured analytical depth: deep or scan.",
    "eligibility_flag": "Versioned reconstructable analytical eligibility result.",
    "initiated_within_90d": "Whether qualifying treatment began within 90 days of eligibility.",
    "eligible_not_initiated_90d": "Eligible patient without qualifying initiation by day 90.",
    "persistence_12m_status": "Event-derived 12-month persistence status with censoring semantics.",
    "censor_date": "Earliest death, loss-to-follow-up, or administrative observation boundary.",
    "censor_reason": "Reason the observable patient timeline ended.",
    "source_archetype_id": (
        "Independent source-archetype identifier used for clone and split auditing."
    ),
    "timing_rule_version": "Version of the feature-availability and leakage-governance rule.",
}


def _bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def _safe_rate(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _wilson(numerator: int, denominator: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if denominator <= 0:
        return None, None
    proportion = numerator / denominator
    scale = 1 + z**2 / denominator
    centre = (proportion + z**2 / (2 * denominator)) / scale
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / denominator + z**2 / (4 * denominator**2))
        / scale
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _confidence_grade(
    denominator: int, lower: float | None, upper: float | None, completeness: float
) -> str:
    width = 1.0 if lower is None or upper is None else upper - lower
    if denominator >= 200 and width <= 0.15 and completeness >= 0.90:
        return "HIGH"
    if denominator >= 75 and width <= 0.25 and completeness >= 0.75:
        return "MODERATE"
    return "LOW"


def _markdown_table(frame: pd.DataFrame, title: str, introduction: str = "") -> str:
    def clean(value: Any) -> str:
        if pd.isna(value):
            return ""
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [f"# {title}", ""]
    if introduction:
        lines.extend([introduction, ""])
    lines.append("| " + " | ".join(frame.columns) + " |")
    lines.append("|" + "|".join("---" for _ in frame.columns) + "|")
    lines.extend(
        "| " + " | ".join(clean(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    )
    return "\n".join(lines) + "\n"


def _description(table: str, column: str) -> str:
    if column in COLUMN_DESCRIPTIONS:
        return COLUMN_DESCRIPTIONS[column]
    readable = column.replace("_", " ")
    if column.endswith("_id"):
        return f"Synthetic identifier or reference for {readable[:-3]}."
    if column.endswith("_date") or column.endswith("_start_date") or column.endswith("_end_date"):
        return f"Dated {readable} value at the documented table grain."
    if column.endswith("_flag"):
        return f"Boolean indicator for {readable[:-5]}."
    if column.endswith("_version"):
        return f"Version identifier governing {readable[:-8]}."
    if column.endswith("_days"):
        return f"Elapsed or configured days for {readable[:-5]}."
    return f"{readable.capitalize()} recorded at the {GRAINS.get(table, 'documented')} grain."


def _controlled_values(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series.dtype):
        return "false; true"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return ""
    unique = series.dropna().unique()
    if 0 < len(unique) <= 20:
        return "; ".join(sorted(map(str, unique)))
    return ""


def _data_dictionary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    timing = tables.get("feature_timing", pd.DataFrame())
    timing_lookup = (
        timing.set_index("feature_name").to_dict(orient="index") if not timing.empty else {}
    )
    rows: list[dict[str, Any]] = []
    for table, frame in tables.items():
        for column in frame.columns:
            metadata = timing_lookup.get(column, {}) if table == "patient_journey" else {}
            missing = int(frame[column].isna().sum())
            rows.append(
                {
                    "table": table,
                    "grain": GRAINS.get(table, "documented table grain"),
                    "column": column,
                    "dtype": str(frame[column].dtype),
                    "nullable_observed": bool(missing),
                    "missing_count": missing,
                    "missing_rate": round(missing / max(len(frame), 1), 6),
                    "primary_key_flag": PRIMARY_KEYS.get(table) == column,
                    "foreign_key_target": FOREIGN_KEYS.get((table, column), ""),
                    "description": _description(table, column),
                    "controlled_values": _controlled_values(frame[column]),
                    "availability_stage": metadata.get(
                        "availability_stage", "event_or_source_table"
                    ),
                    "availability_condition": metadata.get(
                        "availability_condition", "respect_recorded_event_date"
                    ),
                    "rule_version": metadata.get("timing_rule_version", ""),
                }
            )
    return pd.DataFrame(rows)


def _series_count(frame: pd.DataFrame, condition: pd.Series | None = None) -> pd.Series:
    selected = frame if condition is None else frame.loc[condition]
    if selected.empty:
        return pd.Series(dtype="int64")
    return selected.groupby("market_code").size()


def _domain_date_range(frame: pd.DataFrame, date_columns: list[str], prefix: str) -> pd.DataFrame:
    dates = pd.DataFrame(
        {column: pd.to_datetime(frame[column], errors="coerce") for column in date_columns},
        index=frame.index,
    )
    event_dates = pd.DataFrame(
        {
            "market_code": frame.market_code,
            "event_date_min": dates.min(axis=1),
            "event_date_max": dates.max(axis=1),
        }
    )
    return event_dates.groupby("market_code").agg(
        **{
            f"{prefix}_date_min": ("event_date_min", "min"),
            f"{prefix}_date_max": ("event_date_max", "max"),
        }
    )


def _market_coverage(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    patient = tables["patient"]
    diagnosis = tables["diagnosis"]
    observation = tables["observation"]
    journey = tables["patient_journey"]
    active = tables["active_surveillance"]
    rx = tables["prescription_event"]
    base = patient.groupby(["market_code", "market_depth"]).size().rename("patients").reset_index()
    followup = observation.groupby("market_code").follow_up_days_from_diagnosis.agg(
        follow_up_mean_days="mean",
        follow_up_median_days="median",
        follow_up_p25_days=lambda values: values.quantile(0.25),
        follow_up_p75_days=lambda values: values.quantile(0.75),
    )
    dates = (
        diagnosis.groupby("market_code")
        .diagnosis_date.agg(diagnosis_date_min="min", diagnosis_date_max="max")
        .join(
            observation.groupby("market_code").censor_date.agg(
                censor_date_min="min", censor_date_max="max"
            )
        )
    )
    base = base.join(followup, on="market_code").join(dates, on="market_code")
    for frame, columns, prefix in (
        (tables["encounter"], ["encounter_date"], "encounter_event"),
        (tables["referral"], ["referral_date", "completion_date"], "referral_event"),
        (
            tables["treatment_episode"],
            [
                "treatment_start_date",
                "treatment_end_date",
                "discontinuation_date",
                "switch_date",
            ],
            "treatment_event",
        ),
        (
            tables["prescription_event"],
            ["service_date", "covered_until_date"],
            "prescription_event",
        ),
        (
            active,
            [
                "as_start_date",
                "as_exit_date",
                "as_reclassification_date",
                "planned_treatment_start_date",
            ],
            "active_surveillance_event",
        ),
    ):
        base = base.join(_domain_date_range(frame, columns, prefix), on="market_code")
    for name, frame in (
        ("providers", tables["provider"]),
        ("organizations", tables["organization"]),
        ("encounters", tables["encounter"]),
        ("treatment_episodes", tables["treatment_episode"]),
        ("prescription_events", rx),
        ("referrals", tables["referral"]),
    ):
        base[name] = base.market_code.map(_series_count(frame)).fillna(0).astype(int)
    base["as_assessments"] = base.market_code.map(_series_count(active)).fillna(0).astype(int)
    base["as_started"] = (
        base.market_code.map(_series_count(active, active.as_start_date.notna()))
        .fillna(0)
        .astype(int)
    )
    monitoring = active.groupby("market_code").monitoring_event_count.sum()
    base["as_monitoring_events"] = base.market_code.map(monitoring).fillna(0).astype(int)
    base["eligible"] = base.market_code.map(
        journey.groupby("market_code").eligibility_flag.sum()
    ).astype(int)
    base["initiated_90d"] = base.market_code.map(
        journey.groupby("market_code").initiated_within_90d.sum()
    ).astype(int)
    base["treatment_gap_90d"] = base.market_code.map(
        journey.groupby("market_code").eligible_not_initiated_90d.sum()
    ).astype(int)
    evaluable = journey.persistence_12m_status.isin(["PERSISTENT", "DISCONTINUED", "SWITCHED"])
    base["evaluable_12m"] = (
        base.market_code.map(_series_count(journey, evaluable)).fillna(0).astype(int)
    )
    product_missing = rx.groupby("market_code").product_id.apply(
        lambda values: values.isna().mean()
    )
    base["prescription_product_missing_rate"] = base.market_code.map(product_missing).fillna(0.0)
    clinical_columns = ["psa_value", "gleason_score", "isup_grade_group"]
    clinical_missing = diagnosis.groupby("market_code")[clinical_columns].apply(
        lambda frame: float(frame.isna().to_numpy().mean())
    )
    base["clinical_missing_rate"] = base.market_code.map(clinical_missing).fillna(0.0)
    journey_missing = journey.groupby("market_code").apply(
        lambda frame: float(frame.isna().to_numpy().mean()), include_groups=False
    )
    base["mart_missing_rate"] = base.market_code.map(journey_missing).fillna(0.0)
    for domain, frame in (
        ("patient", patient),
        ("diagnosis", diagnosis),
        ("encounter", tables["encounter"]),
        ("referral", tables["referral"]),
        ("active_surveillance", active),
        ("treatment_episode", tables["treatment_episode"]),
        ("prescription", rx),
        ("outcome", tables["outcome"]),
    ):
        aggregate_missing = frame.groupby("market_code").apply(
            lambda market_frame: float(market_frame.isna().to_numpy().mean()),
            include_groups=False,
        )
        base[f"{domain}_aggregate_missing_rate"] = base.market_code.map(aggregate_missing).fillna(
            0.0
        )
    for event in ("encounters", "prescription_events", "referrals"):
        base[f"{event}_per_patient"] = base[event] / base.patients
    base["evaluable_12m_rate"] = base.evaluable_12m / base.initiated_90d.replace(0, np.nan)
    return base.sort_values("market_code").reset_index(drop=True)


def _market_depth_comparison(coverage: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for depth, group in coverage.groupby("market_depth"):
        patients = int(group.patients.sum())
        initiated = int(group.initiated_90d.sum())
        rows.append(
            {
                "market_depth": depth,
                "markets": ", ".join(sorted(group.market_code)),
                "patients": patients,
                "encounters_per_patient": group.encounters.sum() / patients,
                "prescriptions_per_patient": group.prescription_events.sum() / patients,
                "referrals_per_patient": group.referrals.sum() / patients,
                "product_missing_rate": np.average(
                    group.prescription_product_missing_rate,
                    weights=group.prescription_events.clip(lower=1),
                ),
                "clinical_missing_rate": np.average(
                    group.clinical_missing_rate, weights=group.patients
                ),
                "evaluable_12m_rate": group.evaluable_12m.sum() / initiated if initiated else None,
            }
        )
    return pd.DataFrame(rows).sort_values("market_depth")


def _realized_value_masks(journey: pd.DataFrame) -> dict[str, pd.Series]:
    eligible = _bool(journey.eligibility_flag)
    initiated = eligible & _bool(journey.initiated_within_90d)
    gap = eligible & _bool(journey.eligible_not_initiated_90d)
    initiation_censored = eligible & journey.initiation_90d_status.eq("CENSORED_NOT_EVALUABLE")
    evaluable = initiated & journey.persistence_12m_status.isin(
        ["PERSISTENT", "DISCONTINUED", "SWITCHED"]
    )
    persistent = initiated & journey.persistence_12m_status.eq("PERSISTENT")
    start = pd.to_datetime(journey.treatment_start_date, errors="coerce")
    landmark = start + pd.to_timedelta(365, unit="D")

    def event_within_year(column: str) -> pd.Series:
        event_date = pd.to_datetime(journey[column], errors="coerce")
        return event_date.notna() & start.notna() & event_date.ge(start) & event_date.le(landmark)

    adverse_value_event = (
        event_within_year("progression_date")
        | event_within_year("first_hospitalisation_date")
        | event_within_year("death_date")
    )
    proxy_success = persistent & ~adverse_value_event
    return {
        "eligible": eligible,
        "initiation_90d_evaluable": initiated | gap,
        "initiated_90d": initiated,
        "treatment_gap_90d": gap,
        "initiation_90d_censored_not_evaluable": initiation_censored,
        "evaluable_12m": evaluable,
        "persistent_12m": persistent,
        "realized_value_proxy_12m": proxy_success,
    }


def _opportunity(journey: pd.DataFrame) -> pd.DataFrame:
    masks = _realized_value_masks(journey)
    rows: list[dict[str, Any]] = []
    for market, group in journey.groupby("market_code"):
        index = group.index
        eligible = int(masks["eligible"].loc[index].sum())
        initiated = int(masks["initiated_90d"].loc[index].sum())
        gap = int(masks["treatment_gap_90d"].loc[index].sum())
        initiation_censored = int(masks["initiation_90d_censored_not_evaluable"].loc[index].sum())
        initiation_evaluable = initiated + gap
        evaluable = int(masks["evaluable_12m"].loc[index].sum())
        persistent = int(masks["persistent_12m"].loc[index].sum())
        value = int(masks["realized_value_proxy_12m"].loc[index].sum())
        censored = int(
            (
                masks["initiated_90d"].loc[index]
                & group.persistence_12m_status.eq("CENSORED_NOT_EVALUABLE")
            ).sum()
        )
        initiation_eligible_ci = _wilson(initiated, eligible)
        initiation_evaluable_ci = _wilson(initiated, initiation_evaluable)
        persistence_ci = _wilson(persistent, evaluable)
        value_ci = _wilson(value, persistent)
        rows.append(
            {
                "market_code": market,
                "market_depth": group.market_depth.iloc[0],
                "patients": len(group),
                "eligible": eligible,
                "initiated_90d": initiated,
                "treatment_gap_90d": gap,
                "initiation_90d_evaluable": initiation_evaluable,
                "initiation_90d_censored_not_evaluable": initiation_censored,
                "evaluable_12m": evaluable,
                "persistent_12m": persistent,
                "discontinued_or_switched_12m": evaluable - persistent,
                "censored_12m": censored,
                "realized_value_proxy_12m": value,
                "initiation_rate_90d_eligible_denominator": _safe_rate(initiated, eligible),
                "initiation_eligible_ci95_low": initiation_eligible_ci[0],
                "initiation_eligible_ci95_high": initiation_eligible_ci[1],
                "initiation_rate_90d_evaluable_denominator": _safe_rate(
                    initiated, initiation_evaluable
                ),
                "initiation_evaluable_ci95_low": initiation_evaluable_ci[0],
                "initiation_evaluable_ci95_high": initiation_evaluable_ci[1],
                "treatment_gap_rate_90d_eligible_denominator": _safe_rate(gap, eligible),
                "treatment_gap_rate_90d_evaluable_denominator": _safe_rate(
                    gap, initiation_evaluable
                ),
                "persistence_rate_12m": _safe_rate(persistent, evaluable),
                "persistence_ci95_low": persistence_ci[0],
                "persistence_ci95_high": persistence_ci[1],
                "realized_value_proxy_rate_12m": _safe_rate(value, persistent),
                "realized_value_proxy_ci95_low": value_ci[0],
                "realized_value_proxy_ci95_high": value_ci[1],
                "realized_value_proxy_version": REALIZED_VALUE_PROXY_VERSION,
                "realized_value_proxy_definition": (
                    "Eligible initiation by day 90, persistent at 12 months, and no dated "
                    "progression, hospitalisation, or death from treatment start through day 365."
                ),
                "interpretation_caveat": (
                    "Synthetic operational proxy only; not causal effectiveness or "
                    "commercial value."
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("market_code").reset_index(drop=True)


def _uncertainty(opportunity: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    completeness = coverage.set_index("market_code").apply(
        lambda row: (
            1 - float(np.mean([row.prescription_product_missing_rate, row.clinical_missing_rate]))
        ),
        axis=1,
    )
    definitions = (
        ("eligibility", "eligible", "patients"),
        ("initiation_90d_eligible_denominator", "initiated_90d", "eligible"),
        (
            "initiation_90d_evaluable_denominator",
            "initiated_90d",
            "initiation_90d_evaluable",
        ),
        ("treatment_gap_90d_eligible_denominator", "treatment_gap_90d", "eligible"),
        (
            "treatment_gap_90d_evaluable_denominator",
            "treatment_gap_90d",
            "initiation_90d_evaluable",
        ),
        (
            "initiation_90d_censored_not_evaluable",
            "initiation_90d_censored_not_evaluable",
            "eligible",
        ),
        ("persistence_12m", "persistent_12m", "evaluable_12m"),
        ("realized_value_proxy_12m", "realized_value_proxy_12m", "persistent_12m"),
    )
    rows = []
    for record in opportunity.itertuples(index=False):
        market_completeness = float(completeness.loc[record.market_code])
        for metric, numerator_field, denominator_field in definitions:
            numerator = int(getattr(record, numerator_field))
            denominator = int(getattr(record, denominator_field))
            lower, upper = _wilson(numerator, denominator)
            rows.append(
                {
                    "market_code": record.market_code,
                    "market_depth": record.market_depth,
                    "metric": metric,
                    "numerator": numerator,
                    "denominator": denominator,
                    "rate": _safe_rate(numerator, denominator),
                    "wilson_ci95_low": lower,
                    "wilson_ci95_high": upper,
                    "data_completeness_rate": market_completeness,
                    "confidence_grade": _confidence_grade(
                        denominator, lower, upper, market_completeness
                    ),
                    "confidence_rule_version": "SYNTHETIC-CONFIDENCE-v1.0",
                    "caveat": SYNTHETIC_UNCERTAINTY_CAVEAT,
                }
            )
    return pd.DataFrame(rows)


def _treatment_gap_heatmap(journey: pd.DataFrame) -> pd.DataFrame:
    frame = journey.loc[_bool(journey.eligibility_flag)].copy()
    frame["age_group"] = pd.cut(
        frame.age_at_index,
        bins=[0, 64, 74, np.inf],
        labels=["<65", "65-74", "75+"],
    ).astype(str)
    dimensions = [
        "market_code",
        "market_depth",
        "region",
        "initial_care_setting",
        "complexity_segment",
        "age_group",
    ]
    rows = []
    for keys, group in frame.groupby(dimensions, dropna=False, observed=True):
        eligible = len(group)
        initiated = int(_bool(group.initiated_within_90d).sum())
        gap = int(_bool(group.eligible_not_initiated_90d).sum())
        censored = int(group.initiation_90d_status.eq("CENSORED_NOT_EVALUABLE").sum())
        evaluable = initiated + gap
        lower, upper = _wilson(gap, evaluable)
        eligible_lower, eligible_upper = _wilson(gap, eligible)
        rows.append(
            {
                **dict(zip(dimensions, keys, strict=True)),
                "eligible": eligible,
                "initiation_90d_evaluable": evaluable,
                "initiated_90d": initiated,
                "treatment_gap_90d": gap,
                "initiation_90d_censored_not_evaluable": censored,
                "initiation_90d_partition_unexplained": eligible - initiated - gap - censored,
                "treatment_gap_rate_90d": _safe_rate(gap, evaluable),
                "treatment_gap_rate_90d_evaluable_denominator": _safe_rate(gap, evaluable),
                "treatment_gap_rate_90d_eligible_denominator": _safe_rate(gap, eligible),
                "wilson_ci95_low": lower,
                "wilson_ci95_high": upper,
                "eligible_denominator_ci95_low": eligible_lower,
                "eligible_denominator_ci95_high": eligible_upper,
                "confidence_grade": _confidence_grade(evaluable, lower, upper, 1.0),
                "small_cell_flag": evaluable < 10,
                "caveat": SYNTHETIC_UNCERTAINTY_CAVEAT,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["market_code", "region", "initial_care_setting", "complexity_segment", "age_group"]
    )


def _heatmap_html(frame: pd.DataFrame) -> str:
    rows = []
    for record in frame.itertuples(index=False):
        rate = float(record.treatment_gap_rate_90d)
        red = int(245 - 25 * rate)
        green = int(250 - 150 * rate)
        colour = f"rgb({red},{green},105)"
        cells = [
            record.market_code,
            record.region,
            record.initial_care_setting,
            record.complexity_segment,
            record.age_group,
            record.eligible,
            record.initiation_90d_evaluable,
            record.treatment_gap_90d,
            record.initiation_90d_censored_not_evaluable,
        ]
        prefix = "".join(f"<td>{html.escape(str(value))}</td>" for value in cells)
        rows.append(
            f"<tr>{prefix}<td style='background:{colour}'>{rate:.1%}</td>"
            f"<td>{record.confidence_grade}</td></tr>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Treatment-gap heatmap</title>"
        "<style>body{font-family:Segoe UI,Arial;margin:24px;color:#172033}table{border-collapse:"
        "collapse;width:100%;font-size:12px}th,td{border:1px solid #dbe2ea;padding:6px}th{"
        "position:sticky;top:0;background:#13294b;color:white}.caveat{padding:12px;background:"
        "#fff4ce;margin-bottom:14px}</style></head><body><h1>Treatment-gap heatmap</h1>"
        f"<div class='caveat'>{html.escape(SYNTHETIC_UNCERTAINTY_CAVEAT)}</div><table><thead>"
        "<tr><th>Market</th><th>Region</th><th>Care setting</th><th>Complexity</th><th>Age</th>"
        "<th>Eligible</th><th>Initiation evaluable</th><th>Gap</th><th>Initiation censored</th>"
        "<th>Gap rate (evaluable)</th><th>Confidence</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )


def _sensitivity(journey: pd.DataFrame) -> pd.DataFrame:
    persistence_versions = sorted(journey.persistence_rule_version.dropna().astype(str).unique())
    if len(persistence_versions) != 1:
        raise ValueError(
            "Sensitivity evidence requires one persistence definition; "
            f"found {persistence_versions}"
        )
    persistence_version = persistence_versions[0]
    rows = []
    markets = ["ALL", *sorted(journey.market_code.unique())]
    for market in markets:
        group = journey if market == "ALL" else journey.loc[journey.market_code.eq(market)]
        eligible = _bool(group.eligibility_flag)
        eligibility_date = pd.to_datetime(group.eligibility_date, errors="coerce")
        treatment_start = pd.to_datetime(group.treatment_start_date, errors="coerce")
        censor_date = pd.to_datetime(group.censor_date, errors="coerce")
        for window in (30, 60, 90):
            landmark = eligibility_date + pd.to_timedelta(window, unit="D")
            initiated = eligible & treatment_start.notna() & treatment_start.le(landmark)
            censored = eligible & ~initiated & censor_date.lt(landmark)
            gap = (
                eligible & _bool(group.eligible_not_initiated_90d)
                if window == 90
                else eligible & ~initiated & ~censored
            )
            eligible_denominator = int(eligible.sum())
            evaluable_denominator = int((initiated | gap).sum())
            censored_count = int(censored.sum())
            numerator = int(initiated.sum())
            lower, upper = _wilson(numerator, evaluable_denominator)
            eligible_lower, eligible_upper = _wilson(numerator, eligible_denominator)
            precomputed = eligible & _bool(group[f"initiated_within_{window}d"])
            rows.append(
                {
                    "market_code": market,
                    "sensitivity_domain": "initiation_window",
                    "parameter_days": window,
                    "definition": f"Eligible patient initiated within {window} days",
                    "numerator": numerator,
                    "denominator": evaluable_denominator,
                    "eligible_denominator": eligible_denominator,
                    "evaluable_denominator": evaluable_denominator,
                    "censored_not_evaluable": censored_count,
                    "unexplained_partition": eligible_denominator
                    - evaluable_denominator
                    - censored_count,
                    "rate": _safe_rate(numerator, evaluable_denominator),
                    "rate_evaluable_denominator": _safe_rate(numerator, evaluable_denominator),
                    "rate_eligible_denominator": _safe_rate(numerator, eligible_denominator),
                    "wilson_ci95_low": lower,
                    "wilson_ci95_high": upper,
                    "eligible_denominator_ci95_low": eligible_lower,
                    "eligible_denominator_ci95_high": eligible_upper,
                    "precomputed_flag_mismatch_count": int((initiated != precomputed).sum()),
                    "definition_version": "INITIATION-WINDOW-SYN-v1.0",
                    "caveat": SYNTHETIC_UNCERTAINTY_CAVEAT,
                }
            )
        initiated_90d = eligible & _bool(group.initiated_within_90d)
        for gap in (30, 60, 90):
            status = group[f"persistence_12m_status_gap_{gap}d"]
            evaluable = initiated_90d & status.isin(["PERSISTENT", "DISCONTINUED", "SWITCHED"])
            persistent = evaluable & status.eq("PERSISTENT")
            censored = initiated_90d & status.eq("CENSORED_NOT_EVALUABLE")
            at_risk = int(initiated_90d.sum())
            numerator, denominator = int(persistent.sum()), int(evaluable.sum())
            lower, upper = _wilson(numerator, denominator)
            at_risk_lower, at_risk_upper = _wilson(numerator, at_risk)
            rows.append(
                {
                    "market_code": market,
                    "sensitivity_domain": "persistence_permissible_gap",
                    "parameter_days": gap,
                    "definition": f"12-month persistence with a {gap}-day permissible gap",
                    "numerator": numerator,
                    "denominator": denominator,
                    "eligible_denominator": at_risk,
                    "evaluable_denominator": denominator,
                    "censored_not_evaluable": int(censored.sum()),
                    "unexplained_partition": at_risk - denominator - int(censored.sum()),
                    "rate": _safe_rate(numerator, denominator),
                    "rate_evaluable_denominator": _safe_rate(numerator, denominator),
                    "rate_eligible_denominator": _safe_rate(numerator, at_risk),
                    "wilson_ci95_low": lower,
                    "wilson_ci95_high": upper,
                    "eligible_denominator_ci95_low": at_risk_lower,
                    "eligible_denominator_ci95_high": at_risk_upper,
                    "precomputed_flag_mismatch_count": 0,
                    "definition_version": persistence_version,
                    "caveat": SYNTHETIC_UNCERTAINTY_CAVEAT,
                }
            )
    return pd.DataFrame(rows)


def _driver_tree(journey: pd.DataFrame) -> pd.DataFrame:
    masks = _realized_value_masks(journey)
    rows = []
    for market in ["ALL", *sorted(journey.market_code.unique())]:
        selected = (
            pd.Series(True, index=journey.index)
            if market == "ALL"
            else journey.market_code.eq(market)
        )
        counts = {
            "total_patients": int(selected.sum()),
            **{name: int((mask & selected).sum()) for name, mask in masks.items()},
        }
        nodes = [
            ("total_patients", "", "Total patients", "Synthetic cohort"),
            ("eligible", "total_patients", "Eligible", "Versioned ARPI eligibility"),
            (
                "initiation_90d_evaluable",
                "eligible",
                "Initiation evaluable at day 90",
                "Initiated by day 90 or observed through day 90 without initiation",
            ),
            (
                "initiated_90d",
                "initiation_90d_evaluable",
                "Initiated <=90d",
                "Qualifying treatment by day 90",
            ),
            (
                "evaluable_12m",
                "initiated_90d",
                "12m evaluable",
                "Persistent, discontinued, or switched before/at the 12m landmark",
            ),
            (
                "persistent_12m",
                "evaluable_12m",
                "Sustained at 12m",
                "Event-derived PERSISTENT status",
            ),
            (
                "realized_value_proxy_12m",
                "persistent_12m",
                "Synthetic realised-value proxy",
                "No progression, hospitalisation, or death through day 365 among "
                "sustained patients",
            ),
            (
                "treatment_gap_90d",
                "initiation_90d_evaluable",
                "Eligible treatment gap at day 90",
                "Explicit eligible_not_initiated_90d flag",
            ),
            (
                "initiation_90d_censored_not_evaluable",
                "eligible",
                "Initiation censored before day 90",
                "Observation ended before the initiation landmark without observed initiation",
            ),
        ]
        for sequence, (node, parent, label, definition) in enumerate(nodes):
            denominator = counts[parent] if parent else counts[node]
            rows.append(
                {
                    "market_code": market,
                    "sequence": sequence,
                    "node_id": node,
                    "parent_node_id": parent,
                    "node_label": label,
                    "count": counts[node],
                    "parent_denominator": denominator,
                    "conversion_rate": _safe_rate(counts[node], denominator),
                    "definition": definition,
                    "definition_version": (
                        REALIZED_VALUE_PROXY_VERSION
                        if node == "realized_value_proxy_12m"
                        else "DIAGNOSTIC-CHAIN-SYN-v1.0"
                    ),
                    "caveat": (
                        "The terminal node is a synthetic operational proxy, not causal "
                        "or commercial value."
                    ),
                }
            )
    return pd.DataFrame(rows)


def _intervention_inputs(journey: pd.DataFrame) -> pd.DataFrame:
    frame = journey.loc[_bool(journey.eligibility_flag)].copy()
    dimensions = [
        "market_code",
        "market_depth",
        "region",
        "initial_care_setting",
        "complexity_segment",
    ]
    rows = []
    for keys, group in frame.groupby(dimensions, dropna=False):
        eligible = len(group)
        initiated = int(_bool(group.initiated_within_90d).sum())
        gap = int(_bool(group.eligible_not_initiated_90d).sum())
        initiation_censored = int(group.initiation_90d_status.eq("CENSORED_NOT_EVALUABLE").sum())
        initiation_evaluable = initiated + gap
        evaluable_mask = group.persistence_12m_status.isin(
            ["PERSISTENT", "DISCONTINUED", "SWITCHED"]
        )
        evaluable = int(evaluable_mask.sum())
        persistent = int((evaluable_mask & group.persistence_12m_status.eq("PERSISTENT")).sum())
        referral_known = group.referral_status.ne("not_referred") & group.referral_status.notna()
        referral_denominator = int(referral_known.sum())
        completed = int((referral_known & _bool(group.referral_completed_flag)).sum())
        referral_delays = pd.to_numeric(group.referral_delay_days, errors="coerce").dropna()
        lower, upper = _wilson(gap, initiation_evaluable)
        eligible_lower, eligible_upper = _wilson(gap, eligible)
        rows.append(
            {
                **dict(zip(dimensions, keys, strict=True)),
                "eligible": eligible,
                "initiation_90d_evaluable": initiation_evaluable,
                "initiated_90d": initiated,
                "treatment_gap_90d": gap,
                "initiation_90d_censored_not_evaluable": initiation_censored,
                "initiation_90d_partition_unexplained": eligible
                - initiation_evaluable
                - initiation_censored,
                "treatment_gap_rate_90d": _safe_rate(gap, initiation_evaluable),
                "treatment_gap_rate_90d_evaluable_denominator": _safe_rate(
                    gap, initiation_evaluable
                ),
                "treatment_gap_rate_90d_eligible_denominator": _safe_rate(gap, eligible),
                "treatment_gap_ci95_low": lower,
                "treatment_gap_ci95_high": upper,
                "treatment_gap_eligible_ci95_low": eligible_lower,
                "treatment_gap_eligible_ci95_high": eligible_upper,
                "referral_evaluable": referral_denominator,
                "referral_completed": completed,
                "referral_noncompletion_rate": (
                    1 - completed / referral_denominator if referral_denominator else None
                ),
                "median_referral_delay_days": (
                    float(referral_delays.median()) if not referral_delays.empty else None
                ),
                "mean_access_index": pd.to_numeric(group.access_index, errors="coerce").mean(),
                "persistence_evaluable_12m": evaluable,
                "persistent_12m": persistent,
                "persistence_attrition_count": evaluable - persistent,
                "persistence_attrition_rate": (1 - persistent / evaluable if evaluable else None),
                "confidence_grade": _confidence_grade(initiation_evaluable, lower, upper, 1.0),
                "caveat": NON_CAUSAL_CAVEAT,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["market_code", "region", "initial_care_setting", "complexity_segment"]
    )


def _target_vector(frame: pd.DataFrame, target: str) -> tuple[pd.Series, pd.Series]:
    if target == "persistence_12m_status":
        valid = frame[target].isin(["PERSISTENT", "DISCONTINUED", "SWITCHED"])
        return frame[target].isin(["DISCONTINUED", "SWITCHED"]).astype(int), valid
    valid = frame[target].notna()
    return _bool(frame[target]).astype(int), valid


def _feature_diagnostics(
    frame: pd.DataFrame, predictors: list[str], target: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target_values, valid_target = _target_vector(frame, target)
    diagnostics = []
    for feature in predictors:
        series = frame[feature]
        valid = valid_target & series.notna()
        correlation: float | None = None
        if pd.api.types.is_numeric_dtype(series.dtype) and valid.sum() >= 3:
            numeric = pd.to_numeric(series.loc[valid], errors="coerce")
            y = target_values.loc[valid]
            if numeric.nunique() > 1 and y.nunique() > 1:
                correlation = float(numeric.corr(y))
        deterministic_fraction: float | None = None
        unique = int(series.loc[valid].nunique(dropna=True))
        if 2 <= unique <= 50 and valid.sum() > 0 and target_values.loc[valid].nunique() > 1:
            mapping = pd.DataFrame(
                {"feature": series.loc[valid].astype(str), "target": target_values.loc[valid]}
            )
            purity = mapping.groupby("feature").target.nunique().eq(1)
            pure_values = set(purity.index[purity])
            deterministic_fraction = float(mapping.feature.isin(pure_values).mean())
        diagnostics.append(
            {
                "feature": feature,
                "dtype": str(series.dtype),
                "missing_rate": float(series.isna().mean()),
                "unique_values": int(series.nunique(dropna=True)),
                "absolute_numeric_correlation": (
                    abs(correlation)
                    if correlation is not None and not math.isnan(correlation)
                    else None
                ),
                "deterministic_mapping_fraction": deterministic_fraction,
                "perfect_numeric_prediction": bool(
                    correlation is not None and abs(correlation) >= 0.999999
                ),
                "perfect_mapping_prediction": bool(
                    deterministic_fraction is not None and deterministic_fraction >= 0.999999
                ),
            }
        )
    numeric = [row for row in diagnostics if row["absolute_numeric_correlation"] is not None]
    mapping = [row for row in diagnostics if row["deterministic_mapping_fraction"] is not None]
    maximum_numeric = max(
        numeric, key=lambda row: row["absolute_numeric_correlation"], default=None
    )
    maximum_mapping = max(
        mapping, key=lambda row: row["deterministic_mapping_fraction"], default=None
    )
    return diagnostics, {
        "max_abs_numeric_correlation": (
            maximum_numeric["absolute_numeric_correlation"] if maximum_numeric else None
        ),
        "max_correlation_feature": maximum_numeric["feature"] if maximum_numeric else None,
        "max_deterministic_mapping_fraction": (
            maximum_mapping["deterministic_mapping_fraction"] if maximum_mapping else None
        ),
        "max_mapping_feature": maximum_mapping["feature"] if maximum_mapping else None,
        "perfect_prediction_count": sum(
            row["perfect_numeric_prediction"] or row["perfect_mapping_prediction"]
            for row in diagnostics
        ),
    }


def _leakage_report(
    tables: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    journey = tables["patient_journey"]
    timing = tables["feature_timing"].set_index("feature_name")
    task_specs: list[tuple[str, str, str, Callable[[pd.DataFrame], pd.DataFrame]]] = [
        (
            "treatment_initiation_90d",
            "eligibility_date",
            "eligible_not_initiated_90d",
            treatment_initiation_features,
        ),
        (
            "discontinuation_12m",
            "treatment_start_date",
            "persistence_12m_status",
            discontinuation_features,
        ),
        (
            "referral_completion_pathway",
            "diagnosis_and_first_encounter",
            "referral_completed_flag",
            pathway_gap_features,
        ),
    ]
    rows = []
    detail: dict[str, Any] = {}
    for task, cutoff, target, builder in task_specs:
        feature_set = builder(journey)
        predictors = [
            column for column in feature_set.columns if column not in {"patient_id", target}
        ]
        timing_violations = []
        for feature in predictors:
            if feature not in timing.index:
                timing_violations.append(f"{feature}:missing_metadata")
                continue
            record = timing.loc[feature]
            if bool(record.future_information_flag) or not bool(record.predictor_allowed_flag):
                timing_violations.append(f"{feature}:forbidden_at_cutoff")
        diagnostics, maxima = _feature_diagnostics(feature_set, predictors, target)
        violations = len(timing_violations) + int(maxima["perfect_prediction_count"])
        rows.append(
            {
                "task": task,
                "prediction_cutoff": cutoff,
                "target": target,
                "rows": len(feature_set),
                "predictor_count": len(predictors),
                "actual_feature_set_columns": json.dumps(list(feature_set.columns)),
                "actual_predictor_columns": json.dumps(predictors),
                "timing_violation_count": len(timing_violations),
                **maxima,
                "leakage_violation_count": violations,
                "status": "PASS" if violations == 0 else "FAIL",
                "caveat": (
                    "Correlation and deterministic mapping are diagnostics, not causal analysis."
                ),
            }
        )
        detail[task] = {
            "prediction_cutoff": cutoff,
            "target": target,
            "feature_set_columns": list(feature_set.columns),
            "predictor_columns": predictors,
            "timing_violations": timing_violations,
            "feature_diagnostics": diagnostics,
        }
    summary = pd.DataFrame(rows)
    return summary, {"all_tasks_pass": bool(summary.status.eq("PASS").all()), "tasks": detail}


def _synthetic_realism(
    tables: dict[str, pd.DataFrame], coverage: pd.DataFrame, leakage: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    patient = tables["patient"]
    diagnosis = tables["diagnosis"]
    regimen = tables["treatment_regimen"]
    provider = tables["provider"]
    rx = tables["prescription_event"]
    journey = tables["patient_journey"]
    deep = coverage.loc[coverage.market_depth.eq("deep")]
    scan = coverage.loc[coverage.market_depth.eq("scan")]
    deep_encounters = deep.encounters.sum() / deep.patients.sum()
    scan_encounters = scan.encounters.sum() / scan.patients.sum()
    progression = journey.groupby("metastatic_flag").progression_event.mean()
    refill = pd.to_numeric(rx.refill_gap_days, errors="coerce").dropna()
    product_missing = rx.groupby("market_code").product_id.apply(
        lambda values: values.isna().mean()
    )
    deep_missing = float(product_missing.reindex(sorted(DEEP_MARKETS)).dropna().mean())
    scan_missing = float(product_missing.reindex(sorted(SCAN_MARKETS)).dropna().mean())
    checks = [
        (
            "SR01",
            "patient_independence",
            patient.source_archetype_id.nunique() == len(patient),
            f"unique archetypes={patient.source_archetype_id.nunique()}; patients={len(patient)}",
            "one archetype per patient",
        ),
        (
            "SR02",
            "continuous_support",
            patient.age_at_index.nunique() >= 20
            and patient.access_index.nunique() >= 50
            and patient.frailty_proxy.nunique() >= 50,
            f"age/access/frailty support={patient.age_at_index.nunique()}/"
            f"{patient.access_index.nunique()}/{patient.frailty_proxy.nunique()}",
            "non-toy support",
        ),
        (
            "SR03",
            "age_and_comorbidity",
            patient.age_at_index.between(50, 90).all() and patient.comorbidity_score.nunique() >= 3,
            f"age={patient.age_at_index.min()}-{patient.age_at_index.max()}; "
            f"comorbidity levels={patient.comorbidity_score.nunique()}",
            "configured age range and varied comorbidity",
        ),
        (
            "SR04",
            "disease_state_variation",
            diagnosis.prostate_stage.nunique() >= 3
            and diagnosis.groupby("market_code").metastatic_flag.mean().std() > 0.02,
            f"stages={diagnosis.prostate_stage.nunique()}; market metastatic-rate "
            f"sd={diagnosis.groupby('market_code').metastatic_flag.mean().std():.3f}",
            "multiple states and market variation",
        ),
        (
            "SR05",
            "treatment_variation",
            regimen.regimen_name.nunique() >= 3,
            f"regimens={regimen.regimen_name.nunique()}",
            "at least three regimen patterns",
        ),
        (
            "SR06",
            "provider_patterns",
            provider.provider_specialty.nunique() >= 3
            and provider.groupby("market_code").size().nunique() > 1,
            f"specialties={provider.provider_specialty.nunique()}; market provider counts="
            f"{provider.groupby('market_code').size().to_dict()}",
            "specialty and capacity variation",
        ),
        (
            "SR07",
            "refill_gap_variation",
            refill.nunique() >= 10 and refill.min() < 0 and refill.max() > 0,
            f"support={refill.nunique()}; range={refill.min()} to {refill.max()}",
            "early and late refill behavior",
        ),
        (
            "SR08",
            "outcome_structure_without_determinism",
            len(progression) == 2
            and progression.between(0.01, 0.95).all()
            and progression.loc[True] > progression.loc[False] + 0.03,
            f"progression by metastatic flag={progression.to_dict()}",
            "meaningful imperfect conditional signal",
        ),
        (
            "SR09",
            "deep_scan_depth",
            deep_encounters > scan_encounters * 1.35,
            f"deep/scan encounters per patient={deep_encounters:.3f}/{scan_encounters:.3f}",
            "deep markets at least 1.35x richer",
        ),
        (
            "SR10",
            "market_missingness",
            scan_missing > deep_missing,
            f"deep/scan product missingness={deep_missing:.3f}/{scan_missing:.3f}",
            "scan missingness exceeds deep",
        ),
        (
            "SR11",
            "correlation_and_leakage",
            leakage.status.eq("PASS").all(),
            f"failed leakage tasks={leakage.loc[leakage.status.ne('PASS'), 'task'].tolist()}",
            "no task-specific timing or perfect-prediction violation",
        ),
    ]
    frame = pd.DataFrame(
        [
            {
                "check_id": check_id,
                "diagnostic": diagnostic,
                "status": "PASS" if passed else "FAIL",
                "observed": observed,
                "acceptance_threshold": threshold,
                "caveat": "Synthetic scenario diagnostic; not population calibration.",
            }
            for check_id, diagnostic, passed, observed, threshold in checks
        ]
    )
    return frame, {
        "all_checks_pass": bool(frame.status.eq("PASS").all()),
        "failed_checks": frame.loc[frame.status.ne("PASS"), "check_id"].tolist(),
        "diagnostics": frame.to_dict(orient="records"),
    }


def _flatten_config(value: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        rows = []
        for key, child in value.items():
            rows.extend(_flatten_config(child, f"{path}.{key}" if path else str(key)))
        return rows
    return [(path, value)]


def _assumptions_register(config: dict[str, Any]) -> pd.DataFrame:
    clinical = config.get("clinical_rule_configuration", {}).get("clinical_rules", {})
    rows = []
    for number, (path, value) in enumerate(_flatten_config(config), start=1):
        parts = path.split(".")
        market = (
            parts[2]
            if len(parts) > 2 and parts[:2] == ["market_configuration", "markets"]
            else "ALL"
        )
        rule_name = (
            parts[2]
            if len(parts) > 2 and parts[:2] == ["clinical_rule_configuration", "clinical_rules"]
            else None
        )
        rule = clinical.get(rule_name, {}) if rule_name else {}
        if path.startswith("market_configuration"):
            version = config.get("market_configuration", {}).get("version", "")
            source = "Version-controlled synthetic market profile; requires local validation."
        elif rule_name:
            version = rule.get("version", "")
            source = rule.get("source_assumption", "Synthetic clinical rule assumption.")
        else:
            version = config.get("scenario_version", "")
            source = config.get("disclaimer", "Synthetic scenario assumption.")
        serialized = (
            json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else str(value)
        )
        sensitivity = any(
            token in path
            for token in (
                "sensitivity",
                "probability",
                "distribution",
                "gap",
                "delay",
                "missingness",
            )
        )
        rows.append(
            {
                "assumption_id": f"ASM-{number:04d}",
                "domain": parts[0],
                "parameter_path": path,
                "configured_value": serialized,
                "market_applicability": market,
                "version": version,
                "source_or_rationale": source,
                "validation_status": (
                    "TECHNICAL_CONTRACT"
                    if path in {"random_seed", "target_cohort_size", "scenario_version", "profile"}
                    else "REQUIRES_BAYER_REVIEW"
                ),
                "sensitivity_supported": sensitivity,
                "caveat": (
                    "Configured synthetic assumption; not empirical Bayer or population evidence."
                ),
            }
        )
    return pd.DataFrame(rows)


def _schema_checks(tables: dict[str, pd.DataFrame]) -> tuple[bool, bool, list[str]]:
    issues = []
    for table, key in PRIMARY_KEYS.items():
        if table not in tables or key not in tables[table]:
            issues.append(f"missing_pk:{table}.{key}")
        elif tables[table][key].isna().any() or tables[table][key].duplicated().any():
            issues.append(f"invalid_pk:{table}.{key}")
    pk_clear = not any("pk:" in issue for issue in issues)
    for (table, column), target in FOREIGN_KEYS.items():
        if table not in tables or column not in tables[table]:
            issues.append(f"missing_fk:{table}.{column}")
            continue
        target_table, target_column = target.split(".")
        values = tables[table][column].dropna()
        if not values.isin(tables[target_table][target_column]).all():
            issues.append(f"orphan_fk:{table}.{column}")
    for table, frame in tables.items():
        if table in {"patient", "organization", "provider", "feature_timing"}:
            continue
        if (
            "patient_id" in frame
            and not frame.patient_id.dropna().isin(tables["patient"].patient_id).all()
        ):
            issues.append(f"orphan_fk:{table}.patient_id")
    fk_clear = not any("fk:" in issue for issue in issues)
    return pk_clear, fk_clear, issues


def _reconciliation_issues(summary: Any, path: str = "reconciliation") -> list[str]:
    if summary is None or summary == {}:
        return ["reconciliation_summary_missing"]
    issues = []
    if isinstance(summary, dict):
        for key, value in summary.items():
            key_path = f"{path}.{key}"
            lowered = key.lower()
            if isinstance(value, str) and lowered in {"status", "result"}:
                if value.upper() not in {"PASS", "PASSED", "OK"}:
                    issues.append(f"{key_path}={value}")
            elif isinstance(value, bool) and any(
                token in lowered for token in ("pass", "clear", "valid", "reconcil")
            ):
                if not value:
                    issues.append(f"{key_path}=false")
            elif isinstance(value, (int, float)) and any(
                token in lowered
                for token in (
                    "mismatch",
                    "failure",
                    "orphan",
                    "duplicate",
                    "invalid",
                    "violation",
                    "blocker",
                    "issue",
                    "after_censor",
                )
            ):
                if value != 0:
                    issues.append(f"{key_path}={value}")
            elif isinstance(value, list) and any(
                token in lowered for token in ("failure", "blocker", "issue", "mismatch")
            ):
                if value:
                    issues.append(f"{key_path}={value}")
            else:
                issues.extend(
                    _reconciliation_issues(value, key_path) if isinstance(value, dict) else []
                )
    return issues


def _score_dimension(
    dimension: str, tests: list[tuple[str, bool]], additional_deficiency: str = ""
) -> dict[str, Any]:
    passed = sum(result for _, result in tests)
    score = round(100 * passed / len(tests)) if tests else 0
    failed = [test for test, result in tests if not result]
    if additional_deficiency:
        failed.append(additional_deficiency)
        score = min(score, 99)
    return {
        "dimension": dimension,
        "score_0_100": score,
        "status": "PASS" if score == 100 else "PARTIAL" if score > 0 else "FAIL",
        "supporting_test_ids": "; ".join(test for test, _ in tests),
        "remaining_deficiency": "NONE" if score == 100 else "; ".join(failed),
    }


def _scorecard(
    tables: dict[str, pd.DataFrame],
    dictionary: pd.DataFrame,
    coverage: pd.DataFrame,
    opportunity: pd.DataFrame,
    uncertainty: pd.DataFrame,
    sensitivity: pd.DataFrame,
    driver_tree: pd.DataFrame,
    intervention: pd.DataFrame,
    leakage: pd.DataFrame,
    realism: pd.DataFrame,
    reconciliation_summary: Any,
    artifact_paths: dict[str, Path],
) -> pd.DataFrame:
    pk_clear, fk_clear, _ = _schema_checks(tables)
    expected_fields = sum(len(frame.columns) for frame in tables.values())
    dictionary_complete = (
        len(dictionary) == expected_fields and not dictionary.duplicated(["table", "column"]).any()
    )
    reconciliation_clear = not _reconciliation_issues(reconciliation_summary)
    markets_clear = set(coverage.market_code) == REQUIRED_MARKETS
    deep = coverage.loc[coverage.market_depth.eq("deep")]
    scan = coverage.loc[coverage.market_depth.eq("scan")]
    depth_clear = (
        deep.encounters.sum() / deep.patients.sum()
        > 1.35 * scan.encounters.sum() / scan.patients.sum()
    )
    opportunity_clear = bool(
        opportunity.eligible.eq(
            opportunity.initiated_90d
            + opportunity.treatment_gap_90d
            + opportunity.initiation_90d_censored_not_evaluable
        ).all()
        and opportunity.initiation_90d_evaluable.eq(
            opportunity.initiated_90d + opportunity.treatment_gap_90d
        ).all()
        and opportunity.persistent_12m.le(opportunity.evaluable_12m).all()
        and opportunity.evaluable_12m.le(opportunity.initiated_90d).all()
    )
    sensitivity_clear = set(sensitivity.sensitivity_domain) == {
        "initiation_window",
        "persistence_permissible_gap",
    } and set(sensitivity.parameter_days) == {30, 60, 90}
    sensitivity_clear &= bool(
        sensitivity.unexplained_partition.eq(0).all()
        and sensitivity.precomputed_flag_mismatch_count.eq(0).all()
    )
    driver_nested = True
    for _, group in driver_tree.groupby("market_code"):
        counts = group.set_index("node_id")["count"]
        driver_nested &= bool(
            counts.total_patients
            >= counts.eligible
            >= counts.initiation_90d_evaluable
            >= counts.initiated_90d
            >= counts.evaluable_12m
            >= counts.persistent_12m
            >= counts.realized_value_proxy_12m
        )
        driver_nested &= bool(
            counts.eligible
            == counts.initiation_90d_evaluable + counts.initiation_90d_censored_not_evaluable
            and counts.initiation_90d_evaluable == counts.initiated_90d + counts.treatment_gap_90d
        )
    artifact_complete = bool(artifact_paths) and all(
        path.exists() for path in artifact_paths.values()
    )
    rows = [
        _score_dimension(
            "Schema quality",
            [
                ("PK_UNIQUENESS", pk_clear),
                ("FK_RESOLUTION", fk_clear),
                ("FIELD_DICTIONARY", dictionary_complete),
            ],
        ),
        _score_dimension(
            "Data quality",
            [
                ("RECONCILIATION_CLEAR", reconciliation_clear),
                ("PK_FK_CLEAR", pk_clear and fk_clear),
            ],
        ),
        _score_dimension(
            "Clinical/pathway coherence",
            [
                ("RECONCILIATION_CLEAR", reconciliation_clear),
                (
                    "OUTCOME_STRUCTURE",
                    realism.set_index("check_id").loc["SR08", "status"] == "PASS",
                ),
                (
                    "PROVIDER_PATTERNS",
                    realism.set_index("check_id").loc["SR06", "status"] == "PASS",
                ),
            ],
        ),
        _score_dimension(
            "Longitudinal readiness",
            [
                (
                    "DATE_COVERAGE_COMPLETE",
                    bool(coverage[["diagnosis_date_min", "censor_date_max"]].notna().all().all()),
                ),
                ("NESTED_12M_CHAIN", opportunity_clear),
                ("RECONCILIATION_CLEAR", reconciliation_clear),
            ],
        ),
        _score_dimension(
            "Eligibility analysis readiness",
            [
                ("ELIGIBLE_DECOMPOSITION", opportunity_clear),
                ("RECONCILIATION_CLEAR", reconciliation_clear),
            ],
        ),
        _score_dimension(
            "Treatment initiation readiness",
            [
                ("INITIATION_WINDOWS_30_60_90", sensitivity_clear),
                ("ELIGIBLE_INITIATION_CHAIN", opportunity_clear),
            ],
        ),
        _score_dimension(
            "Persistence/discontinuation readiness",
            [
                ("PERSISTENCE_GAPS_30_60_90", sensitivity_clear),
                ("CENSOR_AWARE_NESTING", opportunity_clear),
            ],
        ),
        _score_dimension(
            "Market segmentation readiness",
            [
                ("SEVEN_MARKETS", markets_clear),
                ("DEEP_SCAN_DEPTH", depth_clear),
                ("MARKET_CONFIDENCE", len(uncertainty) > 0),
            ],
        ),
        _score_dimension(
            "Driver-analysis readiness",
            [
                ("TASK_SPECIFIC_LEAKAGE", bool(leakage.status.eq("PASS").all())),
                ("DRIVER_TREE_NESTED", driver_nested),
                ("INTERVENTION_INPUTS", not intervention.empty),
            ],
        ),
        _score_dimension(
            "Synthetic realism",
            [("SYNTHETIC_REALISM_CHECKS", bool(realism.status.eq("PASS").all()))],
        ),
    ]
    preceding_clear = all(row["score_0_100"] == 100 for row in rows)
    rows.append(
        _score_dimension(
            "Overall diagnostic readiness",
            [
                ("ALL_DIMENSIONS_100", preceding_clear),
                ("RELEASE_ARTIFACTS_COMPLETE", artifact_complete),
                ("RECONCILIATION_CLEAR", reconciliation_clear),
            ],
        )
    )
    return pd.DataFrame(rows)


def write_release_evidence(
    tables: dict[str, pd.DataFrame],
    config: dict[str, Any],
    analytical_dir: str | Path,
    qa_dir: str | Path,
    reconciliation_summary: Any,
) -> dict[str, Path]:
    """Write the complete Prompt-3 analytical starter and QA evidence contract."""
    analytical_root = Path(analytical_dir)
    qa_root = Path(qa_dir)
    analytical_root.mkdir(parents=True, exist_ok=True)
    qa_root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    dictionary = _data_dictionary(tables)
    paths["data_dictionary_csv"] = analytical_root / "DATA_DICTIONARY.csv"
    dictionary.to_csv(paths["data_dictionary_csv"], index=False)

    coverage = _market_coverage(tables)
    paths["market_coverage_csv"] = qa_root / "market_coverage.csv"
    paths["market_coverage_md"] = qa_root / "market_coverage.md"
    coverage.to_csv(paths["market_coverage_csv"], index=False)
    depth_comparison = _market_depth_comparison(coverage)
    depth_markdown = _markdown_table(
        depth_comparison.round(4),
        "Deep vs Scan Quantitative Comparison",
        "Weighted event depth, missingness, and evaluability evidence.",
    ).replace("# Deep vs Scan", "## Deep vs Scan", 1)
    coverage_display = coverage.copy()
    numeric_columns = coverage_display.select_dtypes(include=["number"]).columns
    coverage_display[numeric_columns] = coverage_display[numeric_columns].round(4)
    paths["market_coverage_md"].write_text(
        _markdown_table(
            coverage_display,
            "Market Coverage",
            "Complete per-market population, time, provider, event, missingness, and "
            "12-month coverage. "
            "Deep/Scan differences are configuration-driven synthetic properties.",
        )
        + "\n"
        + depth_markdown,
        encoding="utf-8",
    )

    opportunity = _opportunity(tables["patient_journey"])
    paths["market_opportunity_csv"] = analytical_root / "market_opportunity.csv"
    opportunity.to_csv(paths["market_opportunity_csv"], index=False)

    uncertainty = _uncertainty(opportunity, coverage)
    paths["uncertainty_confidence_csv"] = qa_root / "uncertainty_confidence.csv"
    uncertainty.to_csv(paths["uncertainty_confidence_csv"], index=False)

    heatmap = _treatment_gap_heatmap(tables["patient_journey"])
    paths["treatment_gap_heatmap_csv"] = analytical_root / "treatment_gap_heatmap.csv"
    paths["treatment_gap_heatmap_html"] = analytical_root / "treatment_gap_heatmap.html"
    heatmap.to_csv(paths["treatment_gap_heatmap_csv"], index=False)
    paths["treatment_gap_heatmap_html"].write_text(_heatmap_html(heatmap), encoding="utf-8")

    sensitivity = _sensitivity(tables["patient_journey"])
    paths["sensitivity_analysis_csv"] = analytical_root / "sensitivity_analysis.csv"
    sensitivity.to_csv(paths["sensitivity_analysis_csv"], index=False)

    driver_tree = _driver_tree(tables["patient_journey"])
    paths["driver_tree_csv"] = analytical_root / "driver_tree.csv"
    driver_tree.to_csv(paths["driver_tree_csv"], index=False)

    intervention = _intervention_inputs(tables["patient_journey"])
    paths["intervention_inputs_csv"] = analytical_root / "intervention_prioritisation_inputs.csv"
    intervention.to_csv(paths["intervention_inputs_csv"], index=False)

    leakage, leakage_payload = _leakage_report(tables)
    paths["leakage_report_csv"] = qa_root / "leakage_report.csv"
    paths["leakage_report_json"] = qa_root / "leakage_report.json"
    paths["leakage_report_md"] = qa_root / "leakage_report.md"
    leakage.to_csv(paths["leakage_report_csv"], index=False)
    paths["leakage_report_json"].write_text(
        json.dumps(leakage_payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    paths["leakage_report_md"].write_text(
        _markdown_table(
            leakage.drop(columns=["actual_feature_set_columns", "actual_predictor_columns"]).round(
                6
            ),
            "Task-specific Leakage Report",
            "Feature sets are materialized from the production builders and checked at "
            "their exact prediction cutoffs.",
        ),
        encoding="utf-8",
    )

    realism, realism_payload = _synthetic_realism(tables, coverage, leakage)
    paths["synthetic_realism_csv"] = qa_root / "synthetic_realism_report.csv"
    paths["synthetic_realism_json"] = qa_root / "synthetic_realism_report.json"
    paths["synthetic_realism_md"] = qa_root / "synthetic_realism_report.md"
    realism.to_csv(paths["synthetic_realism_csv"], index=False)
    paths["synthetic_realism_json"].write_text(
        json.dumps(realism_payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    paths["synthetic_realism_md"].write_text(
        _markdown_table(realism, "Synthetic Realism Report"), encoding="utf-8"
    )

    assumptions = _assumptions_register(config)
    paths["assumptions_register_csv"] = qa_root / "assumptions_register.csv"
    assumptions.to_csv(paths["assumptions_register_csv"], index=False)

    scorecard = _scorecard(
        tables,
        dictionary,
        coverage,
        opportunity,
        uncertainty,
        sensitivity,
        driver_tree,
        intervention,
        leakage,
        realism,
        reconciliation_summary,
        paths,
    )
    paths["final_scorecard_csv"] = qa_root / "final_scorecard.csv"
    paths["final_scorecard_md"] = qa_root / "final_scorecard.md"
    scorecard.to_csv(paths["final_scorecard_csv"], index=False)
    paths["final_scorecard_md"].write_text(
        _markdown_table(
            scorecard,
            "Final Release Scorecard",
            f"> {DISCLAIMER}\n\nA score of 100 is emitted only when every supporting check passes.",
        ),
        encoding="utf-8",
    )
    return paths
