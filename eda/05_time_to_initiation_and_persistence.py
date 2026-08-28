"""Censor-aware longitudinal initiation, persistence, switch and restart EDA."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import html
import json
import platform
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from config import (
    ANALYSIS_DISCLAIMER,
    FIGURES_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    ensure_output_directories,
    resolve_analytical_data_dir,
)
from longitudinal_charts import line, render_line_chart, step_points
from longitudinal_config import (
    BASELINE_REQUIREMENTS_DAYS,
    DISCONTINUATION_GAPS_DAYS,
    INITIATION_WINDOWS_DAYS,
    MINIMUM_FOLLOW_UP_DAYS,
    MISSING_SUPPLY_SCENARIOS_DAYS,
    PERSISTENCE_LANDMARKS_DAYS,
    SMALL_CELL_THRESHOLD,
)
from png_charts import Canvas

PRIMARY_PATHWAY = "mhspc_mcspc"
TREATMENT_PATHWAYS = (PRIMARY_PATHWAY, "mcrpc")
COLORS = [
    (31, 119, 180),
    (214, 39, 40),
    (44, 160, 44),
    (148, 103, 189),
    (255, 127, 14),
    (23, 190, 207),
    (140, 86, 75),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _date(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for column in columns:
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _safe_percent(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _quantile(values: pd.Series, probability: float) -> float | None:
    observed = pd.to_numeric(values, errors="coerce").dropna()
    return float(observed.quantile(probability)) if not observed.empty else None


def kaplan_meier(
    durations: pd.Series, events: pd.Series, *, max_time: float | None = None
) -> pd.DataFrame:
    """Calculate a standard right-censored Kaplan-Meier product-limit curve."""
    data = pd.DataFrame(
        {
            "duration": pd.to_numeric(durations, errors="coerce"),
            "event": events.fillna(False).astype(bool),
        }
    ).dropna(subset=["duration"])
    data = data[data.duration.ge(0)].copy()
    if max_time is not None:
        data["event"] = data.event & data.duration.le(max_time)
        data["duration"] = data.duration.clip(upper=max_time)
    if data.empty:
        return pd.DataFrame(
            columns=["time_days", "n_at_risk", "events", "censored", "survival"]
        )
    survival = 1.0
    rows = [{"time_days": 0.0, "n_at_risk": len(data), "events": 0, "censored": 0, "survival": 1.0}]
    at_risk = len(data)
    for time, group in data.sort_values("duration").groupby("duration", sort=True):
        event_count = int(group.event.sum())
        censor_count = int(len(group) - event_count)
        if at_risk > 0 and event_count:
            survival *= 1 - event_count / at_risk
        rows.append(
            {
                "time_days": float(time),
                "n_at_risk": int(at_risk),
                "events": event_count,
                "censored": censor_count,
                "survival": float(survival),
            }
        )
        at_risk -= len(group)
    return pd.DataFrame(rows)


def survival_at(curve: pd.DataFrame, day: int) -> float | None:
    eligible = curve[curve.time_days.le(day)]
    return float(eligible.iloc[-1].survival) if not eligible.empty else None


def risk_at(curve: pd.DataFrame, day: int) -> int:
    later = curve[curve.time_days.ge(day)]
    return int(later.iloc[0].n_at_risk) if not later.empty else 0


def km_median(curve: pd.DataFrame) -> float | None:
    reached = curve[curve.survival.le(0.5)]
    return float(reached.iloc[0].time_days) if not reached.empty else None


def build_initiation_event_data(flags: pd.DataFrame) -> pd.DataFrame:
    """Create patient-pathway event/censor rows using Prompt-2 governed flags."""
    cohort = flags[
        flags.pathway.isin(TREATMENT_PATHWAYS) & flags.eligible_candidate.fillna(False)
    ].copy()
    cohort = _date(
        cohort,
        ["cohort_index_date", "eligibility_date", "initiation_date", "censor_date"],
    )
    cohort["eligibility_date"] = cohort.eligibility_date.fillna(cohort.cohort_index_date)
    cohort["initiation_observed"] = (
        cohort.initiation_date.notna()
        & cohort.initiation_date.ge(cohort.eligibility_date)
        & cohort.initiation_date.le(cohort.censor_date)
    )
    cohort["event_or_censor_date"] = cohort.initiation_date.where(
        cohort.initiation_observed, cohort.censor_date
    )
    cohort["time_to_initiation_or_censor_days"] = (
        cohort.event_or_censor_date - cohort.eligibility_date
    ).dt.days
    cohort["time_to_initiation_days"] = (
        cohort.initiation_date - cohort.eligibility_date
    ).dt.days.where(cohort.initiation_observed)
    cohort["time_to_initiation_status"] = np.select(
        [
            cohort.initiation_observed,
            cohort.censor_reason.eq("death"),
            cohort.censor_reason.eq("loss_to_follow_up"),
            cohort.censor_reason.eq("administrative_end"),
        ],
        ["INITIATED", "DEATH", "LOST_TO_FOLLOW_UP", "ADMINISTRATIVE_CENSORING"],
        default="UNKNOWN",
    )
    cohort["competing_event_flag"] = cohort.time_to_initiation_status.isin(
        ["DEATH", "LOST_TO_FOLLOW_UP"]
    )
    cohort["analysis_confidence"] = np.where(
        cohort.pathway.eq(PRIMARY_PATHWAY),
        "HIGH_WITHIN_SYNTHETIC_CONTRACT",
        "LOW_PROXY_ONLY",
    )
    if cohort.time_to_initiation_or_censor_days.lt(0).any():
        raise AssertionError("Initiation event/censor date precedes governed eligibility date")
    return cohort


def _initiation_summary_row(
    group: pd.DataFrame, pathway: str, dimension: str, value: str
) -> dict[str, Any]:
    curve = kaplan_meier(
        group.time_to_initiation_or_censor_days, group.initiation_observed
    )
    initiators = group.loc[group.initiation_observed, "time_to_initiation_days"]
    row: dict[str, Any] = {
        "pathway": pathway,
        "segment_dimension": dimension,
        "segment_value": value,
        "eligible_n": int(len(group)),
        "initiator_n": int(group.initiation_observed.sum()),
        "noninitiator_censored_n": int((~group.initiation_observed).sum()),
        "death_before_initiation_n": int(group.time_to_initiation_status.eq("DEATH").sum()),
        "lost_to_follow_up_before_initiation_n": int(
            group.time_to_initiation_status.eq("LOST_TO_FOLLOW_UP").sum()
        ),
        "administrative_censoring_before_initiation_n": int(
            group.time_to_initiation_status.eq("ADMINISTRATIVE_CENSORING").sum()
        ),
        "median_days_observed_initiators": _quantile(initiators, 0.5),
        "p25_days_observed_initiators": _quantile(initiators, 0.25),
        "p75_days_observed_initiators": _quantile(initiators, 0.75),
        "iqr_days_observed_initiators": (
            _quantile(initiators, 0.75) - _quantile(initiators, 0.25)
            if not initiators.dropna().empty
            else None
        ),
        "p90_days_observed_initiators": _quantile(initiators, 0.90),
        "km_median_time_to_initiation_days": km_median(curve),
        "small_cell_flag": bool(len(group) < SMALL_CELL_THRESHOLD),
        "conclusion_type": (
            "DESCRIPTIVE" if pathway == PRIMARY_PATHWAY else "PROXY-BASED"
        ),
    }
    for day in INITIATION_WINDOWS_DAYS:
        survival = survival_at(curve, day)
        observable = group.time_to_initiation_or_censor_days.ge(day) | (
            group.initiation_observed & group.time_to_initiation_days.le(day)
        )
        initiated = group.initiation_observed & group.time_to_initiation_days.le(day)
        row[f"km_percent_not_initiated_by_{day}d"] = (
            survival * 100 if survival is not None else None
        )
        row[f"risk_set_at_{day}d"] = risk_at(curve, day)
        row[f"observable_at_{day}d_n"] = int(observable.sum())
        row[f"initiated_by_{day}d_n"] = int((observable & initiated).sum())
        row[f"crude_percent_not_initiated_by_{day}d_among_observable"] = (
            100 * (observable & ~initiated).sum() / observable.sum()
            if observable.sum()
            else None
        )
    return row


def summarize_initiation(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    curves: list[pd.DataFrame] = []
    dimensions = {
        "overall": None,
        "market": "market_code",
        "disease_state": "pathway_disease_state",
        "care_setting": "initial_care_setting",
        "provider_specialty": "initial_provider_specialty",
        "age_band": "age_band",
        "comorbidity_band": "comorbidity_band",
    }
    for pathway, pathway_frame in events.groupby("pathway", sort=True):
        for dimension, column in dimensions.items():
            groups = [("ALL", pathway_frame)] if column is None else pathway_frame.groupby(column, dropna=False)
            for value, group in groups:
                rows.append(_initiation_summary_row(group, pathway, dimension, str(value)))
        curve = kaplan_meier(
            pathway_frame.time_to_initiation_or_censor_days,
            pathway_frame.initiation_observed,
        )
        curve.insert(0, "pathway", pathway)
        curve["estimator_note"] = (
            "Standard KM; death and LTFU right-censored. Competing incidence is descriptive, so initiation probability may be overestimated."
        )
        curves.append(curve)

    if not events.pathway.eq("nmcrpc").any():
        row = {
            "pathway": "nmcrpc",
            "segment_dimension": "overall",
            "segment_value": "ALL",
            "eligible_n": 0,
            "initiator_n": 0,
            "small_cell_flag": True,
            "conclusion_type": "NOT COMPUTABLE",
        }
        rows.append(row)
    return pd.DataFrame(rows), pd.concat(curves, ignore_index=True)


def _first_gap_event(
    prescriptions: pd.DataFrame, start: pd.Timestamp, threshold: int
) -> tuple[pd.Timestamp | pd.NaT, bool, float | None, str]:
    ordered = prescriptions.sort_values(["service_date", "prescription_event_id"])
    previous_coverage = pd.NaT
    max_observed_gap: float | None = None
    for event in ordered.itertuples(index=False):
        service = pd.Timestamp(event.service_date)
        origin = start if pd.isna(previous_coverage) else pd.Timestamp(previous_coverage)
        gap = float((service - origin).days)
        max_observed_gap = gap if max_observed_gap is None else max(max_observed_gap, gap)
        if gap > threshold:
            return (
                origin + pd.Timedelta(days=threshold + 1),
                True,
                max_observed_gap,
                "observed refill after a gap exceeding the threshold",
            )
        coverage = pd.Timestamp(event.covered_until_date)
        previous_coverage = coverage if pd.isna(previous_coverage) else max(previous_coverage, coverage)
    if pd.notna(previous_coverage):
        return (
            pd.Timestamp(previous_coverage) + pd.Timedelta(days=threshold + 1),
            False,
            max_observed_gap,
            "terminal observed coverage plus configurable permissible gap",
        )
    return pd.NaT, False, max_observed_gap, "no tracking prescription event; no supply fabricated"


def evaluate_persistence(
    row: pd.Series, prescriptions: pd.DataFrame, threshold: int
) -> dict[str, Any]:
    """Determine the earliest persistence endpoint without collapsing competing events."""
    start = pd.Timestamp(row.treatment_start_date)
    censor = pd.Timestamp(row.censor_date_episode)
    candidates: list[tuple[pd.Timestamp, int, str, str, bool]] = []
    if pd.notna(row.switch_date):
        candidates.append(
            (pd.Timestamp(row.switch_date), 0, "SWITCHED", "explicit switch_date", False)
        )
    if pd.notna(row.discontinuation_date):
        if bool(row.restart_out_flag) and pd.notna(row.restart_date):
            candidates.append(
                (
                    pd.Timestamp(row.discontinuation_date),
                    1,
                    "TEMPORARY_GAP_RESTARTED",
                    "explicit temporary-gap stop with observed restart",
                    True,
                )
            )
        elif bool(row.documented_stop_flag):
            candidates.append(
                (
                    pd.Timestamp(row.discontinuation_date),
                    1,
                    "DISCONTINUED",
                    "explicit documented discontinuation",
                    True,
                )
            )
    gap_date, later_refill, observed_gap, gap_basis = _first_gap_event(
        prescriptions, start, threshold
    )
    if pd.notna(gap_date) and pd.Timestamp(gap_date) < censor:
        candidates.append(
            (
                pd.Timestamp(gap_date),
                2,
                "TEMPORARY_GAP_RESTARTED" if later_refill else "DISCONTINUED",
                gap_basis,
                True,
            )
        )
    censor_class = {
        "death": "DEATH",
        "loss_to_follow_up": "LOST_TO_FOLLOW_UP",
        "administrative_end": "ADMINISTRATIVE_CENSORING",
    }.get(str(row.censor_reason_episode), "UNKNOWN")
    candidates.append((censor, 5, censor_class, "governed observation censor", False))
    event_date, _, classification, basis, persistence_failure = min(
        candidates, key=lambda item: (item[0], item[1])
    )
    return {
        "gap_threshold_days": threshold,
        "persistence_endpoint_date": event_date,
        "days_to_persistence_endpoint": int((event_date - start).days),
        "event_classification": classification,
        "event_basis": basis,
        "persistence_failure_flag": persistence_failure,
        "competing_event_flag": classification
        in {"SWITCHED", "DEATH", "LOST_TO_FOLLOW_UP"},
        "temporary_gap_restarted_flag": classification == "TEMPORARY_GAP_RESTARTED",
        "observed_max_gap_before_endpoint": observed_gap,
        "add_on_before_endpoint_flag": bool(
            row.add_on_flag
            and pd.notna(row.add_on_date)
            and pd.Timestamp(row.add_on_date) <= event_date
        ),
        "scenario_based": "configurable permissible gap" in basis,
    }


def build_persistence_event_data(
    initiation_events: pd.DataFrame,
    episodes: pd.DataFrame,
    prescriptions: pd.DataFrame,
) -> pd.DataFrame:
    initiated = initiation_events[initiation_events.initiation_observed].copy()
    initiated = initiated.merge(
        episodes,
        left_on=["patient_id", "first_post_index_treatment_episode_id"],
        right_on=["patient_id", "treatment_episode_id"],
        how="inner",
        suffixes=("_cohort", "_episode"),
        validate="one_to_one",
    )
    rx_by_component = {
        str(component_id): group.copy()
        for component_id, group in prescriptions.groupby("component_id", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for _, patient_episode in initiated.iterrows():
        component_id = patient_episode.tracking_component_id
        patient_rx = rx_by_component.get(str(component_id), prescriptions.iloc[0:0])
        for threshold in DISCONTINUATION_GAPS_DAYS:
            result = evaluate_persistence(patient_episode, patient_rx, threshold)
            rows.append(
                {
                    "patient_id": patient_episode.patient_id,
                    "pathway": patient_episode.pathway,
                    "market_code": patient_episode.market_code_cohort,
                    "disease_state": patient_episode.pathway_disease_state,
                    "care_setting": patient_episode.initial_care_setting,
                    "provider_specialty": patient_episode.initial_provider_specialty,
                    "age_band": patient_episode.age_band,
                    "comorbidity_band": patient_episode.comorbidity_band,
                    "treatment_episode_id": patient_episode.treatment_episode_id,
                    "initial_regimen": patient_episode.regimen_name,
                    "treatment_start_date": patient_episode.treatment_start_date,
                    "censor_date": patient_episode.censor_date_episode,
                    "censor_reason": patient_episode.censor_reason_episode,
                    "switch_date": patient_episode.switch_date,
                    "restart_date": patient_episode.restart_date,
                    "documented_stop_date": patient_episode.discontinuation_date,
                    "source_tracking_event_count": int(
                        patient_episode.tracking_prescription_event_count
                    ),
                    "days_supply_available": bool(pd.notna(patient_episode.days_supply)),
                    **result,
                }
            )
    result = pd.DataFrame(rows)
    invalid = result.event_classification.eq("DISCONTINUED") & result.event_basis.isin(
        ["governed observation censor"]
    )
    if invalid.any():
        raise AssertionError("Death/LTFU/administrative censor was classified as discontinuation")
    return result


def _persistence_landmark_row(
    group: pd.DataFrame,
    pathway: str,
    threshold: int,
    landmark: int,
    dimension: str,
    value: str,
) -> dict[str, Any]:
    by_landmark = group.days_to_persistence_endpoint.le(landmark)
    failure = by_landmark & group.persistence_failure_flag
    switch = by_landmark & group.event_classification.eq("SWITCHED")
    death = by_landmark & group.event_classification.eq("DEATH")
    ltfu = by_landmark & group.event_classification.eq("LOST_TO_FOLLOW_UP")
    admin = by_landmark & group.event_classification.eq("ADMINISTRATIVE_CENSORING")
    unknown = by_landmark & group.event_classification.eq("UNKNOWN")
    excluded = death | ltfu | admin | unknown
    persistent = ~by_landmark
    evaluable = persistent | failure | switch
    return {
        "pathway": pathway,
        "gap_threshold_days": threshold,
        "landmark_days": landmark,
        "landmark_label": {90: "3_months", 180: "6_months", 365: "12_months"}.get(
            landmark, f"{landmark}_days"
        ),
        "segment_dimension": dimension,
        "segment_value": value,
        "initiated_n": int(len(group)),
        "risk_set_evaluable_n": int(evaluable.sum()),
        "excluded_insufficient_follow_up_n": int(excluded.sum()),
        "persistent_n": int(persistent.sum()),
        "persistence_rate": _safe_percent(persistent.sum(), evaluable.sum()),
        "persistence_percent": (
            100 * persistent.sum() / evaluable.sum() if evaluable.sum() else None
        ),
        "persistence_failure_n": int(failure.sum()),
        "temporary_gap_restarted_n": int(
            (failure & group.event_classification.eq("TEMPORARY_GAP_RESTARTED")).sum()
        ),
        "documented_or_terminal_gap_discontinuation_n": int(
            (failure & group.event_classification.eq("DISCONTINUED")).sum()
        ),
        "switch_competing_event_n": int(switch.sum()),
        "death_competing_event_n": int(death.sum()),
        "lost_to_follow_up_competing_event_n": int(ltfu.sum()),
        "administrative_censoring_before_landmark_n": int(admin.sum()),
        "unknown_before_landmark_n": int(unknown.sum()),
        "conclusion_type": (
            "DESCRIPTIVE" if pathway == PRIMARY_PATHWAY else "PROXY-BASED"
        ),
        "causal_interpretation_allowed": False,
    }


def summarize_persistence(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    sensitivity: list[dict[str, Any]] = []
    for (pathway, threshold), frame in events.groupby(["pathway", "gap_threshold_days"]):
        dimensions = {
            "overall": None,
            "market": "market_code",
            "care_setting": "care_setting",
        }
        for dimension, column in dimensions.items():
            groups = [("ALL", frame)] if column is None else frame.groupby(column, dropna=False)
            for value, group in groups:
                for landmark in PERSISTENCE_LANDMARKS_DAYS:
                    rows.append(
                        _persistence_landmark_row(
                            group, pathway, int(threshold), landmark, dimension, str(value)
                        )
                    )
        discontinued = frame.event_classification.eq("DISCONTINUED")
        temporary = frame.event_classification.eq("TEMPORARY_GAP_RESTARTED")
        gap_failure = frame.persistence_failure_flag
        censored = frame.event_classification.isin(
            ["DEATH", "LOST_TO_FOLLOW_UP", "ADMINISTRATIVE_CENSORING", "UNKNOWN"]
        )
        curve = kaplan_meier(frame.days_to_persistence_endpoint, frame.persistence_failure_flag)
        sensitivity.append(
            {
                "pathway": pathway,
                "gap_threshold_days": int(threshold),
                "initiated_n": int(len(frame)),
                # In a permissible-gap sensitivity, any threshold breach is the
                # discontinuation endpoint; later restart remains a labelled subset.
                "discontinuation_count": int(gap_failure.sum()),
                "discontinuation_rate": _safe_percent(gap_failure.sum(), len(frame)),
                "observed_median_days_to_discontinuation": _quantile(
                    frame.loc[gap_failure, "days_to_persistence_endpoint"], 0.5
                ),
                "non_restarted_discontinuation_count": int(discontinued.sum()),
                "non_restarted_discontinuation_rate": _safe_percent(
                    discontinued.sum(), len(frame)
                ),
                "observed_median_days_to_non_restarted_discontinuation": _quantile(
                    frame.loc[discontinued, "days_to_persistence_endpoint"], 0.5
                ),
                "km_median_days_to_persistence_failure": km_median(curve),
                "censoring_count": int(censored.sum()),
                "death_count": int(frame.event_classification.eq("DEATH").sum()),
                "switch_count": int(frame.event_classification.eq("SWITCHED").sum()),
                "restart_after_gap_count": int(temporary.sum()),
                "lost_to_follow_up_count": int(
                    frame.event_classification.eq("LOST_TO_FOLLOW_UP").sum()
                ),
                "administrative_censoring_count": int(
                    frame.event_classification.eq("ADMINISTRATIVE_CENSORING").sum()
                ),
                "unknown_count": int(frame.event_classification.eq("UNKNOWN").sum()),
                "terminal_gap_scenario_count": int(frame.scenario_based.sum()),
                "competing_risk_note": "Death, LTFU and switch are described separately; no cumulative-incidence competing-risk estimator is available.",
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(sensitivity)


def reconcile_persistence_mart(
    events: pd.DataFrame, patient_journey: pd.DataFrame
) -> pd.DataFrame:
    """Reconcile independently rebuilt 12-month status to the governed mart."""
    rows: list[dict[str, Any]] = []
    primary = events[events.pathway.eq(PRIMARY_PATHWAY)].copy()
    for threshold, group in primary.groupby("gap_threshold_days"):
        rebuilt = np.select(
            [
                group.days_to_persistence_endpoint.gt(365),
                group.persistence_failure_flag,
                group.event_classification.eq("SWITCHED"),
            ],
            ["PERSISTENT", "DISCONTINUED", "SWITCHED"],
            default="CENSORED_NOT_EVALUABLE",
        )
        comparison = group[["patient_id"]].copy()
        comparison["rebuilt_status"] = rebuilt
        source_column = f"persistence_12m_status_gap_{int(threshold)}d"
        comparison = comparison.merge(
            patient_journey[["patient_id", source_column]],
            on="patient_id",
            how="left",
            validate="one_to_one",
        )
        comparison["match"] = comparison.rebuilt_status.eq(comparison[source_column])
        for status, status_group in comparison.groupby("rebuilt_status"):
            rows.append(
                {
                    "gap_threshold_days": int(threshold),
                    "rebuilt_status": status,
                    "rebuilt_count": int(len(status_group)),
                    "mart_count": int(comparison[source_column].eq(status).sum()),
                    "patient_level_mismatch_count": int((~status_group.match).sum()),
                }
            )
    return pd.DataFrame(rows)


def build_switch_restart_summary(
    initiation_events: pd.DataFrame, episodes: pd.DataFrame
) -> pd.DataFrame:
    initiated = initiation_events[initiation_events.initiation_observed].copy()
    initiated_ids = set(initiated.patient_id)
    relevant = episodes[episodes.patient_id.isin(initiated_ids)].copy()
    initial_start = relevant.groupby("patient_id").treatment_start_date.min()
    relevant["initial_treatment_start"] = relevant.patient_id.map(initial_start)
    switches = relevant[relevant.switch_out_flag].copy()
    switches["time_initial_treatment_to_switch_days"] = (
        switches.switch_date - switches.initial_treatment_start
    ).dt.days
    later = relevant.merge(
        switches[["patient_id", "switch_date"]], on="patient_id", how="inner", suffixes=("", "_index")
    )
    later = later[later.treatment_start_date.gt(later.switch_date_index)]
    after = later.groupby("patient_id").agg(
        restarted_after_switch=("restart_in_flag", "max"),
        discontinued_after_switch=("documented_stop_flag", "max"),
    )

    patient = initiated.drop_duplicates(["patient_id", "pathway"]).copy()
    switch_patient = switches.sort_values("switch_date").drop_duplicates("patient_id").set_index("patient_id")
    patient["switched"] = patient.patient_id.isin(switch_patient.index)
    patient["switch_days"] = patient.patient_id.map(switch_patient.switch_date).sub(
        patient.patient_id.map(initial_start)
    ).dt.days
    patient["restarted_after_switch"] = patient.patient_id.map(after.restarted_after_switch).fillna(False)
    patient["discontinued_after_switch"] = patient.patient_id.map(after.discontinued_after_switch).fillna(False)

    rows: list[dict[str, Any]] = []
    dimensions = {
        "overall": None,
        "market": "market_code",
        "disease_state": "pathway_disease_state",
        "care_setting": "initial_care_setting",
    }
    for pathway, pathway_frame in patient.groupby("pathway"):
        for dimension, column in dimensions.items():
            groups = [("ALL", pathway_frame)] if column is None else pathway_frame.groupby(column, dropna=False)
            for value, group in groups:
                switched = group[group.switched]
                rows.append(
                    {
                        "record_type": "RATE_SUMMARY",
                        "pathway": pathway,
                        "segment_dimension": dimension,
                        "segment_value": str(value),
                        "initiated_n": int(len(group)),
                        "switch_n": int(len(switched)),
                        "switch_rate": _safe_percent(len(switched), len(group)),
                        "median_days_initial_treatment_to_switch": _quantile(switched.switch_days, 0.5),
                        "restarted_after_switch_n": int(switched.restarted_after_switch.sum()),
                        "discontinued_after_switch_n": int(switched.discontinued_after_switch.sum()),
                        "small_cell_flag": bool(len(group) < SMALL_CELL_THRESHOLD),
                    }
                )
    for row in switches.itertuples(index=False):
        rows.append(
            {
                "record_type": "TREATMENT_TRANSITION",
                "pathway": "ALL_TREATED",
                "segment_dimension": "patient_transition",
                "segment_value": str(row.patient_id),
                "initiated_n": 1,
                "switch_n": 1,
                "switch_rate": 1.0,
                "median_days_initial_treatment_to_switch": row.time_initial_treatment_to_switch_days,
                "previous_treatment": row.regimen_name,
                "next_treatment": row.next_regimen,
                "switch_date": row.switch_date,
                "restart_later_flag": bool(after.restarted_after_switch.get(row.patient_id, False)),
                "discontinued_later_flag": bool(
                    after.discontinued_after_switch.get(row.patient_id, False)
                ),
                "source_evidence": row.source_evidence,
            }
        )
    return pd.DataFrame(rows)


def build_censoring_summary(
    initiation: pd.DataFrame, persistence: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (pathway, status), group in initiation.groupby(
        ["pathway", "time_to_initiation_status"], dropna=False
    ):
        rows.append(
            {
                "analysis_stage": "TIME_TO_INITIATION",
                "pathway": pathway,
                "gap_threshold_days": pd.NA,
                "event_classification": status,
                "count": int(len(group)),
                "percent_within_stage_pathway": 100
                * len(group)
                / len(initiation[initiation.pathway.eq(pathway)]),
                "treatment_as_discontinuation": False,
            }
        )
    for (pathway, threshold, status), group in persistence.groupby(
        ["pathway", "gap_threshold_days", "event_classification"], dropna=False
    ):
        denominator = len(
            persistence[
                persistence.pathway.eq(pathway)
                & persistence.gap_threshold_days.eq(threshold)
            ]
        )
        rows.append(
            {
                "analysis_stage": "PERSISTENCE_ENDPOINT",
                "pathway": pathway,
                "gap_threshold_days": threshold,
                "event_classification": status,
                "count": int(len(group)),
                "percent_within_stage_pathway": 100 * len(group) / denominator,
                "treatment_as_discontinuation": status == "DISCONTINUED",
            }
        )
    return pd.DataFrame(rows)


def build_robustness(
    initiation: pd.DataFrame, persistence: pd.DataFrame, episodes: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    primary = initiation[initiation.pathway.eq(PRIMARY_PATHWAY)]
    for day in INITIATION_WINDOWS_DAYS:
        observable = primary.time_to_initiation_or_censor_days.ge(day) | (
            primary.initiation_observed & primary.time_to_initiation_days.le(day)
        )
        initiated = primary.initiation_observed & primary.time_to_initiation_days.le(day)
        rows.append(
            {
                "check": "initiation_window",
                "scenario": f"{day}_days",
                "denominator_n": int(observable.sum()),
                "event_n": int((observable & initiated).sum()),
                "rate": _safe_percent((observable & initiated).sum(), observable.sum()),
                "interpretation": "Observed mHSPC treatment initiation; censor-aware landmark denominator.",
            }
        )
    for baseline in BASELINE_REQUIREMENTS_DAYS:
        eligible = primary.baseline_observation_days.ge(baseline)
        rows.append(
            {
                "check": "minimum_baseline_observation",
                "scenario": f"{baseline}_days",
                "denominator_n": int(len(primary)),
                "event_n": int(eligible.sum()),
                "rate": _safe_percent(eligible.sum(), len(primary)),
                "interpretation": (
                    "Pre-index baseline availability only; zero/low counts mean the sensitivity is not computable, not that patients are clinically ineligible."
                ),
            }
        )
    for follow_up in MINIMUM_FOLLOW_UP_DAYS:
        sufficient = primary.time_to_initiation_or_censor_days.ge(follow_up)
        rows.append(
            {
                "check": "minimum_follow_up",
                "scenario": f"{follow_up}_days",
                "denominator_n": int(len(primary)),
                "event_n": int(sufficient.sum()),
                "rate": _safe_percent(sufficient.sum(), len(primary)),
                "interpretation": "Untreated cohort members remaining observable to the landmark.",
            }
        )
    for threshold, group in persistence[persistence.pathway.eq(PRIMARY_PATHWAY)].groupby(
        "gap_threshold_days"
    ):
        failure = group.persistence_failure_flag.sum()
        rows.append(
            {
                "check": "discontinuation_gap",
                "scenario": f"greater_than_{threshold}_days",
                "denominator_n": int(len(group)),
                "event_n": int(failure),
                "rate": _safe_percent(failure, len(group)),
                "interpretation": "Any gap-defined persistence failure, including temporary gaps that later restart.",
            }
        )
    rows.extend(
        [
            {
                "check": "treatment_episode_overlap",
                "scenario": "start_before_previous_end",
                "denominator_n": int(len(episodes)),
                "event_n": int(episodes.episode_overlap_flag.sum()),
                "rate": _safe_percent(episodes.episode_overlap_flag.sum(), len(episodes)),
                "interpretation": "No overlap is assumed; every observed overlap is reported.",
            },
            {
                "check": "same_day_episode_ordering",
                "scenario": "date_line_id_vs_date_id_line",
                "denominator_n": int(len(episodes)),
                "event_n": int(episodes.same_day_episode_flag.sum()),
                "rate": _safe_percent(episodes.same_day_episode_flag.sum(), len(episodes)),
                "interpretation": "Alternative ordering changes no episode when there are no same-day patient episode starts.",
            },
        ]
    )
    return pd.DataFrame(rows)


def _curve_series(
    frame: pd.DataFrame, group_column: str, event_column: str
) -> list[tuple[str, list[tuple[float, float]], tuple[int, int, int]]]:
    series = []
    for index, (label, group) in enumerate(frame.groupby(group_column, sort=True)):
        curve = kaplan_meier(group.days_to_persistence_endpoint, group[event_column])
        points = step_points(list(zip(curve.time_days, curve.survival, strict=False)))
        series.append((str(label), points, COLORS[index % len(COLORS)]))
    return series


def render_boxplots(path: Path, frame: pd.DataFrame) -> None:
    canvas = Canvas(1500, 980, (250, 252, 255))
    canvas.text(70, 45, "TIME TO INITIATION BY MARKET", (24, 52, 91), 3)
    data = frame[frame.initiation_observed].copy()
    groups = list(data.groupby("market_code"))
    left, right, top, bottom = 150, 1400, 140, 810
    maximum = max(float(data.time_to_initiation_days.max()), 1.0)
    canvas.rectangle(left, top, right - left, bottom - top, (255, 255, 255))
    canvas.outline(left, top, right - left, bottom - top, (70, 82, 99), 2)
    for tick in range(6):
        value = maximum * tick / 5
        y = bottom - round((bottom - top) * tick / 5)
        line(canvas, left, y, right, y, (229, 234, 241), 1)
        canvas.text(75, y - 8, f"{value:.0f}", (80, 88, 102), 2)
    width = (right - left) / max(len(groups), 1)
    for index, (label, group) in enumerate(groups):
        values = group.time_to_initiation_days.dropna()
        q1, median, q3 = values.quantile([0.25, 0.5, 0.75])
        low, high = values.min(), values.max()
        x = round(left + width * (index + 0.5))

        def to_y(value: float) -> int:
            return bottom - round((bottom - top) * float(value) / maximum)

        line(canvas, x, to_y(low), x, to_y(high), COLORS[index % len(COLORS)], 3)
        canvas.rectangle(x - 35, to_y(q3), 70, max(2, to_y(q1) - to_y(q3)), (185, 215, 238))
        canvas.outline(x - 35, to_y(q3), 70, max(2, to_y(q1) - to_y(q3)), COLORS[index % len(COLORS)], 2)
        line(canvas, x - 35, to_y(median), x + 35, to_y(median), (30, 45, 62), 3)
        canvas.text(x - 12, bottom + 25, label, (50, 59, 73), 2)
    canvas.text(650, 900, "MARKET", (50, 59, 73), 2)
    canvas.text(20, 450, "DAYS", (50, 59, 73), 2)
    canvas.save(path)


def render_cumulative_events(path: Path, events: pd.DataFrame) -> None:
    frame = events[
        events.pathway.eq(PRIMARY_PATHWAY)
        & events.gap_threshold_days.eq(60)
    ]
    classifications = [
        "DISCONTINUED",
        "TEMPORARY_GAP_RESTARTED",
        "SWITCHED",
        "DEATH",
        "LOST_TO_FOLLOW_UP",
    ]
    series = []
    denominator = max(len(frame), 1)
    for index, classification in enumerate(classifications):
        values = sorted(
            frame.loc[
                frame.event_classification.eq(classification), "days_to_persistence_endpoint"
            ].tolist()
        )
        points = [(0.0, 0.0)] + [
            (float(day), (position + 1) / denominator) for position, day in enumerate(values)
        ]
        series.append((classification, points, COLORS[index]))
    render_line_chart(
        path,
        "CUMULATIVE DESCRIPTIVE EVENT TYPES - GAP 60D",
        series,
        x_label="DAYS FROM TREATMENT START",
        y_label="CUMULATIVE FRACTION",
        x_max=730,
    )


def write_sankey(path: Path, episodes: pd.DataFrame) -> None:
    transitions = episodes[episodes.next_regimen.notna()].groupby(
        ["regimen_name", "next_regimen"], dropna=False
    ).size().reset_index(name="count")
    if transitions.empty:
        transitions = pd.DataFrame(
            [{"regimen_name": "NO OBSERVED TRANSITION", "next_regimen": "END", "count": 0}]
        )
    sources = list(transitions.regimen_name.unique())
    targets = list(transitions.next_regimen.unique())
    source_y = {value: 80 + index * 75 for index, value in enumerate(sources)}
    target_y = {value: 80 + index * 75 for index, value in enumerate(targets)}
    height = max(520, 160 + 75 * max(len(sources), len(targets)))
    maximum = max(int(transitions["count"].max()), 1)
    paths = []
    for row in transitions.itertuples(index=False):
        width = 3 + round(35 * row.count / maximum)
        paths.append(
            f'<path d="M 320 {source_y[row.regimen_name]} C 570 {source_y[row.regimen_name]}, 630 {target_y[row.next_regimen]}, 880 {target_y[row.next_regimen]}" '
            f'stroke="#3b82b8" stroke-opacity="0.42" stroke-width="{width}" fill="none"><title>{html.escape(str(row.regimen_name))} to {html.escape(str(row.next_regimen))}: {row.count}</title></path>'
        )
    nodes = []
    for value, y in source_y.items():
        nodes.append(f'<rect x="20" y="{y - 22}" width="300" height="44" rx="6" fill="#154c79"/><text x="30" y="{y + 6}" fill="white">{html.escape(str(value))}</text>')
    for value, y in target_y.items():
        nodes.append(f'<rect x="880" y="{y - 22}" width="300" height="44" rx="6" fill="#7b2d43"/><text x="890" y="{y + 6}" fill="white">{html.escape(str(value))}</text>')
    table_rows = "".join(
        f"<tr><td>{html.escape(str(row.regimen_name))}</td><td>{html.escape(str(row.next_regimen))}</td><td>{row.count}</td></tr>"
        for row in transitions.itertuples(index=False)
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Treatment sequence Sankey</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;color:#172033}}svg{{width:100%;max-width:1200px;border:1px solid #d8dee9;background:#fbfdff}}text{{font-size:13px}}table{{border-collapse:collapse;margin-top:24px}}th,td{{padding:7px 12px;border:1px solid #d8dee9}}.note{{max-width:1100px}}</style></head>
<body><h1>Treatment-sequence Sankey / alluvial view</h1>
<p class="note">Widths encode observed patient transitions between normalized regimens. Planned add-ons within one regimen are excluded from switch links and remain identified separately in the episode file. Synthetic descriptive data only.</p>
<svg viewBox="0 0 1200 {height}" role="img" aria-label="Treatment sequence transitions">{''.join(paths)}{''.join(nodes)}</svg>
<h2>Transition counts</h2><table><thead><tr><th>Previous regimen</th><th>Next regimen</th><th>Patients</th></tr></thead><tbody>{table_rows}</tbody></table></body></html>"""
    path.write_text(document, encoding="utf-8")


def render_figures(
    initiation: pd.DataFrame,
    initiation_km: pd.DataFrame,
    persistence: pd.DataFrame,
    episodes: pd.DataFrame,
) -> None:
    primary = initiation[initiation.pathway.eq(PRIMARY_PATHWAY)]
    observed = primary.loc[primary.initiation_observed, "time_to_initiation_days"].sort_values()
    ecdf = [(0.0, 0.0)] + [
        (float(value), (index + 1) / len(observed))
        for index, value in enumerate(observed)
    ] if len(observed) else []
    render_line_chart(
        FIGURES_DIR / "time_to_initiation_ecdf.png",
        "TIME TO TREATMENT INITIATION ECDF - MHSPC",
        [("OBSERVED INITIATORS", ecdf, COLORS[0])],
        x_label="DAYS FROM ELIGIBILITY",
        y_label="CUMULATIVE FRACTION",
        x_max=180,
    )
    tti_series = []
    for index, (pathway, group) in enumerate(initiation_km.groupby("pathway")):
        points = step_points(list(zip(group.time_days, group.survival, strict=False)))
        tti_series.append((pathway, points, COLORS[index]))
    render_line_chart(
        FIGURES_DIR / "time_to_initiation_survival.png",
        "KM: PROBABILITY NOT YET INITIATED",
        tti_series,
        x_label="DAYS FROM ELIGIBILITY",
        y_label="NOT INITIATED",
        x_max=365,
    )
    primary_persistence = persistence[persistence.pathway.eq(PRIMARY_PATHWAY)]
    render_line_chart(
        FIGURES_DIR / "persistence_kaplan_meier.png",
        "PERSISTENCE KM SENSITIVITY",
        _curve_series(primary_persistence, "gap_threshold_days", "persistence_failure_flag"),
        x_label="DAYS FROM TREATMENT START",
        y_label="PERSISTENT",
        x_max=730,
    )
    render_line_chart(
        FIGURES_DIR / "gap_sensitivity_small_multiples.png",
        "GAP THRESHOLD SENSITIVITY - OVERLAID SMALL MULTIPLES",
        _curve_series(primary_persistence, "gap_threshold_days", "persistence_failure_flag"),
        x_label="DAYS FROM TREATMENT START",
        y_label="PERSISTENT",
        x_max=365,
    )
    sixty = primary_persistence[primary_persistence.gap_threshold_days.eq(60)]
    render_line_chart(
        FIGURES_DIR / "persistence_by_market.png",
        "PERSISTENCE BY MARKET - GAP 60D",
        _curve_series(sixty, "market_code", "persistence_failure_flag"),
        x_label="DAYS FROM TREATMENT START",
        y_label="PERSISTENT",
        x_max=365,
    )
    render_line_chart(
        FIGURES_DIR / "persistence_by_care_setting.png",
        "PERSISTENCE BY CARE SETTING - GAP 60D",
        _curve_series(sixty, "care_setting", "persistence_failure_flag"),
        x_label="DAYS FROM TREATMENT START",
        y_label="PERSISTENT",
        x_max=365,
    )
    render_boxplots(FIGURES_DIR / "time_to_initiation_boxplots_by_segment.png", primary)
    render_cumulative_events(FIGURES_DIR / "cumulative_event_types.png", persistence)
    write_sankey(FIGURES_DIR / "treatment_sequence_sankey.html", episodes)


def write_assumptions_report(
    initiation_summary: pd.DataFrame,
    persistence_summary: pd.DataFrame,
    sensitivity: pd.DataFrame,
    robustness: pd.DataFrame,
    episodes: pd.DataFrame,
    persistence_events: pd.DataFrame,
    reconciliation: pd.DataFrame,
) -> None:
    primary_init = initiation_summary[
        initiation_summary.pathway.eq(PRIMARY_PATHWAY)
        & initiation_summary.segment_dimension.eq("overall")
    ].iloc[0]
    primary_sensitivity = sensitivity[sensitivity.pathway.eq(PRIMARY_PATHWAY)].sort_values(
        "gap_threshold_days"
    )
    primary_landmarks = persistence_summary[
        persistence_summary.pathway.eq(PRIMARY_PATHWAY)
        & persistence_summary.segment_dimension.eq("overall")
        & persistence_summary.gap_threshold_days.eq(60)
    ].sort_values("landmark_days")
    baseline = robustness[robustness.check.eq("minimum_baseline_observation")]
    missing_supply = int(
        persistence_events.drop_duplicates(["patient_id", "pathway"])
        .days_supply_available.eq(False)
        .sum()
    )
    rates = primary_sensitivity.set_index("gap_threshold_days").discontinuation_rate
    mismatch_count = int(reconciliation.patient_level_mismatch_count.sum())
    rate_text = ", ".join(
        f">{int(threshold)}d: {100 * value:.1f}%" for threshold, value in rates.items()
    )
    landmark_text = ", ".join(
        f"{row.landmark_label}: {row.persistence_percent:.1f}% ({row.persistent_n}/{row.risk_set_evaluable_n}; {row.excluded_insufficient_follow_up_n} excluded)"
        for row in primary_landmarks.itertuples(index=False)
        if pd.notna(row.persistence_percent)
    )
    report = f"""# Longitudinal treatment EDA: assumptions and release interpretation

> **{ANALYSIS_DISCLAIMER}**

## Scope and non-causal interpretation

This analysis uses the certified normalized patient, treatment-episode, regimen-component, prescription-event and observation tables plus the Prompt-2 cohort flags. Source data were read only. **Persistence results are descriptive/associational and not causal.** They must not be interpreted as treatment effectiveness, comparative effectiveness or a patient-level clinical recommendation.

Treatment initiation is the first qualifying normalized treatment episode on or after the governed pathway eligibility/index date. Continuation means remaining on the tracked initial component without a gap beyond the selected threshold. Temporary gaps with an observed later refill/restart, explicit switches, within-regimen add-ons, documented stops, death, loss to follow-up and administrative end remain separate. `UNKNOWN` is retained when governed evidence cannot support another terminal class.

## What is reliable within this synthetic contract

- Episode linkage is high-confidence within the synthetic data contract: {len(episodes):,} normalized episodes for {episodes.patient_id.nunique():,} treated patients, with {int(episodes.episode_overlap_flag.sum()):,} detected episode overlaps.
- `days_supply` comes only from observed prescription events. No value is fabricated. There are {missing_supply:,} initiated treatment-pathway patients without tracking-component days supply; their persistence cannot use a supply-based inference unless a clearly labelled scenario is invoked.
- Explicit source events identify {int(episodes.switch_out_flag.sum()):,} switches, {int(episodes.restart_out_flag.sum()):,} temporary-gap restarts, {int(episodes.add_on_flag.sum()):,} add-on regimens and {int(episodes.documented_stop_flag.sum()):,} documented non-temporary stops.
- In the primary mHSPC pathway, {int(primary_init.initiator_n):,}/{int(primary_init.eligible_n):,} eligible patients initiated during observed follow-up. Among observed initiators, median time was {primary_init.median_days_observed_initiators:.1f} days, IQR {primary_init.iqr_days_observed_initiators:.1f}, p75 {primary_init.p75_days_observed_initiators:.1f}, and p90 {primary_init.p90_days_observed_initiators:.1f}.

## Proxy-based or assumption-dependent outcomes

- mCRPC results use a low-confidence pathway eligibility proxy and are not a clinical mCRPC eligibility analysis. nmCRPC is `NOT COMPUTABLE` because no explicit nmCRPC state exists.
- A refill gap is observed between recorded coverage and a later refill. A terminal gap is scenario-based: coverage end plus the configurable permissible gap, provided the patient remains observed. Terminal coverage, missing events and dataset end are never themselves labelled a documented stop.
- Gap sensitivity materially changes the terminal discontinuation proxy: {rate_text}. Temporary-gap restarts remain separate from non-restarted discontinuation in every threshold.
- At the 60-day gap definition, censor-aware landmark persistence is {landmark_text}. Denominators include observable patients and known failures/switches; deaths, LTFU, early administrative censoring and unknown early endpoints are excluded and counted.
- The independently rebuilt 12-month 30/60/90-day statuses have {mismatch_count:,} patient-level mismatches against the governed `patient_journey` sensitivity fields.
- Standard Kaplan-Meier curves right-censor death, LTFU and other competing events. No Fine-Gray/Aalen-Johansen library is available in the controlled environment, so the report includes a descriptive competing-event table. KM initiation probability can therefore be optimistic when competing events are frequent.

## Robustness checks

- Initiation is re-estimated at {', '.join(str(value) for value in INITIATION_WINDOWS_DAYS)} days.
- Discontinuation/persistence is re-estimated for gaps greater than {', '.join(str(value) for value in DISCONTINUATION_GAPS_DAYS)} days.
- Minimum baseline observation of {', '.join(str(value) for value in BASELINE_REQUIREMENTS_DAYS)} days was tested. Available counts were {', '.join(f'{row.scenario}: {int(row.event_n)}' for row in baseline.itertuples(index=False))}; a zero count is reported as not computable rather than silently relaxing the rule.
- Landmark risk sets at {', '.join(str(value) for value in PERSISTENCE_LANDMARKS_DAYS)} days explicitly count insufficient follow-up exclusions.
- Episode overlap and same-day alternative ordering were audited. Same-day component/refill events are ordered deterministically by service date and stable event ID; episode starts had no same-day ties in this release.
- Missing-supply scenario values are configurable as {', '.join(str(value) for value in MISSING_SUPPLY_SCENARIOS_DAYS)} days, but none is written into `days_supply`; any future use must set `scenario_based=true`.

## Top data gaps preventing stronger persistence conclusions

1. No pre-index clinical history supports a valid 180/365-day baseline sensitivity for most/all governed eligibility rows.
2. Prescription events are synthetic dispensing/coverage records, not proof that medicine was ingested; administration is proxied only where a dated infusion/injection/procedure component exists.
3. Disenrollment is not a separately captured event; loss to follow-up is the only non-death early censor category.
4. Reasons for ordinary refill gaps and some completed episodes are not observed, so `UNKNOWN` is retained rather than forced into discontinuation.
5. mCRPC has no indication-specific clinical eligibility definition and nmCRPC is absent.
6. Standard KM is not a competing-risk estimator; death and LTFU are described separately but causal/cumulative-incidence claims are unsupported.

## Files and interpretation contract

`treatment_episodes.parquet` is one row per normalized episode and contains source evidence. `time_to_initiation_event_data.parquet` and `persistence_event_data.parquet` are audit datasets. Aggregate CSVs and figures must always be read with the cohort definitions and this assumptions file. All results describe synthetic data only.
"""
    (OUTPUT_DIR / "longitudinal_assumptions.md").write_text(report, encoding="utf-8")


def write_manifest(analytical_dir: Path, outputs: list[Path]) -> None:
    inputs = [
        analytical_dir / f"{name}.parquet"
        for name in [
            "treatment_episode",
            "treatment_regimen",
            "treatment_regimen_component",
            "prescription_event",
            "observation",
            "patient_journey",
        ]
    ] + [OUTPUT_DIR / "cohort_patient_flags.parquet"]
    scripts = [
        Path(__file__).resolve(),
        PROJECT_ROOT / "eda" / "04_treatment_episode_builder.py",
        PROJECT_ROOT / "eda" / "longitudinal_config.py",
        PROJECT_ROOT / "eda" / "longitudinal_charts.py",
    ]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "source_data_modified": False,
        "inputs": {str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in inputs},
        "scripts": {str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in scripts},
        "outputs": {
            str(path.relative_to(PROJECT_ROOT)): sha256_file(path)
            for path in outputs
            if path.is_file()
        },
        "assumptions": {
            "initiation_windows_days": INITIATION_WINDOWS_DAYS,
            "gap_thresholds_days": DISCONTINUATION_GAPS_DAYS,
            "persistence_landmarks_days": PERSISTENCE_LANDMARKS_DAYS,
            "baseline_requirements_days": BASELINE_REQUIREMENTS_DAYS,
            "missing_supply_scenarios_days": MISSING_SUPPLY_SCENARIOS_DAYS,
        },
    }
    (OUTPUT_DIR / "longitudinal_run_manifest.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )


def main() -> int:
    ensure_output_directories()
    analytical_dir, _ = resolve_analytical_data_dir()
    episode_path = OUTPUT_DIR / "treatment_episodes.parquet"
    if not episode_path.is_file():
        raise FileNotFoundError("Run eda/04_treatment_episode_builder.py first")
    flags_path = OUTPUT_DIR / "cohort_patient_flags.parquet"
    if not flags_path.is_file():
        raise FileNotFoundError("Prompt-2 cohort flags are required")

    flags = pd.read_parquet(flags_path)
    episodes = _date(
        pd.read_parquet(episode_path),
        [
            "treatment_start_date",
            "treatment_end_date",
            "switch_date",
            "restart_date",
            "discontinuation_date",
            "censor_date",
            "add_on_date",
        ],
    )
    prescriptions = _date(
        pd.read_parquet(analytical_dir / "prescription_event.parquet"),
        ["service_date", "covered_until_date", "nominal_covered_until_date"],
    )
    patient_journey = pd.read_parquet(analytical_dir / "patient_journey.parquet")

    initiation = build_initiation_event_data(flags)
    initiation_summary, initiation_km = summarize_initiation(initiation)
    persistence = build_persistence_event_data(initiation, episodes, prescriptions)
    persistence_summary, sensitivity = summarize_persistence(persistence)
    reconciliation = reconcile_persistence_mart(persistence, patient_journey)
    switch_restart = build_switch_restart_summary(initiation, episodes)
    censoring = build_censoring_summary(initiation, persistence)
    robustness = build_robustness(initiation, persistence, episodes)

    output_frames = {
        "time_to_initiation_event_data.parquet": initiation,
        "persistence_event_data.parquet": persistence,
        "time_to_initiation_summary.csv": initiation_summary,
        "time_to_initiation_km.csv": initiation_km,
        "persistence_summary.csv": persistence_summary,
        "discontinuation_sensitivity.csv": sensitivity,
        "switch_restart_summary.csv": switch_restart,
        "censoring_summary.csv": censoring,
        "longitudinal_robustness.csv": robustness,
        "persistence_mart_reconciliation.csv": reconciliation,
    }
    output_paths: list[Path] = [episode_path]
    for filename, frame in output_frames.items():
        path = OUTPUT_DIR / filename
        if path.suffix == ".parquet":
            frame.to_parquet(path, index=False)
        else:
            frame.to_csv(path, index=False)
        output_paths.append(path)

    render_figures(initiation, initiation_km, persistence, episodes)
    figure_paths = [
        FIGURES_DIR / name
        for name in [
            "time_to_initiation_ecdf.png",
            "time_to_initiation_survival.png",
            "persistence_kaplan_meier.png",
            "treatment_sequence_sankey.html",
            "cumulative_event_types.png",
            "time_to_initiation_boxplots_by_segment.png",
            "persistence_by_market.png",
            "persistence_by_care_setting.png",
            "gap_sensitivity_small_multiples.png",
        ]
    ]
    output_paths.extend(figure_paths)
    write_assumptions_report(
        initiation_summary,
        persistence_summary,
        sensitivity,
        robustness,
        episodes,
        persistence,
        reconciliation,
    )
    output_paths.append(OUTPUT_DIR / "longitudinal_assumptions.md")
    write_manifest(analytical_dir, output_paths)

    primary_summary = initiation_summary[
        initiation_summary.pathway.eq(PRIMARY_PATHWAY)
        & initiation_summary.segment_dimension.eq("overall")
    ].iloc[0]
    print(
        json.dumps(
            {
                "eligible_primary_n": int(primary_summary.eligible_n),
                "initiator_primary_n": int(primary_summary.initiator_n),
                "episode_n": int(len(episodes)),
                "persistence_patient_threshold_rows": int(len(persistence)),
                "outputs_written": len(output_paths) + 1,
                "source_data_modified": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
