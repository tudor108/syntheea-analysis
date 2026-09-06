"""Reusable censor-aware survival and competing-risk methods for synthetic evidence."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pandas as pd
import yaml

from . import DISCLAIMER

Z_975 = 1.959963984540054


def load_event_hierarchy(path: str | Path) -> dict[str, Any]:
    """Load and validate the event-priority specification."""
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Event hierarchy must be a mapping: {source}")
    required = {"version", "status", "events", "endpoints", "tie_breaking"}
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"Event hierarchy is missing: {missing}")
    events = payload["events"]
    if not isinstance(events, dict) or not events:
        raise ValueError("Event hierarchy must declare events")
    priorities = [int(spec["priority"]) for spec in events.values()]
    if len(priorities) != len(set(priorities)):
        raise ValueError("Event priorities must be unique")
    for endpoint_name, endpoint in payload["endpoints"].items():
        referenced = {
            str(endpoint["target_event"]),
            *map(str, endpoint.get("competing_events", [])),
            *map(str, endpoint.get("censoring_events", [])),
        }
        unknown = sorted(referenced - events.keys())
        if unknown:
            raise ValueError(f"Endpoint {endpoint_name} references unknown events: {unknown}")
    return payload


def _population_mask(frame: pd.DataFrame, flag: str) -> pd.Series:
    if flag == "all":
        return pd.Series(True, index=frame.index, dtype=bool)
    if flag not in frame:
        raise ValueError(f"Population flag is absent from patient_journey: {flag}")
    return frame[flag].fillna(False).astype(bool)


def _event_date(
    row: pd.Series,
    event_name: str,
    event_spec: Mapping[str, Any],
    time_zero: pd.Timestamp,
    horizon_date: pd.Timestamp,
) -> pd.Timestamp | None:
    if event_name == "analysis_horizon":
        return horizon_date
    column = str(event_spec["date_column"])
    if column not in row.index:
        if event_spec.get("availability") == "derived_only":
            return None
        raise ValueError(f"Event column is absent from patient_journey: {column}")
    value = row[column]
    if pd.isna(value):
        return None
    event_date = pd.Timestamp(value).normalize()
    if event_date < time_zero:
        raise ValueError(
            f"Event {event_name} at {event_date.date()} precedes time zero {time_zero.date()}"
        )
    if event_date > horizon_date:
        return None
    return event_date


def prepare_event_records(
    journey: pd.DataFrame,
    endpoint_name: str,
    hierarchy: Mapping[str, Any],
) -> pd.DataFrame:
    """Resolve one deterministic first-event record per analysis participant."""
    endpoints = hierarchy["endpoints"]
    if endpoint_name not in endpoints:
        raise ValueError(f"Unknown endpoint: {endpoint_name}")
    endpoint: Mapping[str, Any] = endpoints[endpoint_name]
    events: Mapping[str, Mapping[str, Any]] = hierarchy["events"]
    time_zero_column = str(endpoint["time_zero_column"])
    if time_zero_column not in journey:
        raise ValueError(f"Time-zero column is absent: {time_zero_column}")
    target_event = str(endpoint["target_event"])
    competing = tuple(map(str, endpoint.get("competing_events", [])))
    censoring = tuple(map(str, endpoint.get("censoring_events", [])))
    event_names = (target_event, *competing, *censoring)
    horizon_days = int(endpoint["horizon_days"])
    population = journey.loc[_population_mask(journey, str(endpoint["population_flag"]))].copy()
    population[time_zero_column] = pd.to_datetime(population[time_zero_column], errors="coerce")
    population = population.loc[population[time_zero_column].notna()].copy()

    rows: list[dict[str, Any]] = []
    for _, participant in population.iterrows():
        time_zero = pd.Timestamp(participant[time_zero_column]).normalize()
        horizon_date = time_zero + pd.Timedelta(days=horizon_days)
        candidates: list[tuple[pd.Timestamp, int, str]] = []
        for event_name in event_names:
            event_spec = events[event_name]
            date = _event_date(participant, event_name, event_spec, time_zero, horizon_date)
            if date is not None:
                candidates.append((date, int(event_spec["priority"]), event_name))
        if not candidates:
            raise ValueError(f"No event or censoring boundary for {participant['patient_id']}")
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        selected_date, _, selected_event = candidates[0]
        tied = sum(date == selected_date for date, _, _ in candidates)
        category = (
            "target"
            if selected_event == target_event
            else "competing"
            if selected_event in competing
            else "censor"
        )
        rows.append(
            {
                "patient_id": str(participant["patient_id"]),
                "endpoint": endpoint_name,
                "time_zero": time_zero,
                "event_or_censor_date": selected_date,
                "time_days": int((selected_date - time_zero).days),
                "event_type": selected_event,
                "event_category": category,
                "target_event": category == "target",
                "competing_event": category == "competing",
                "censored": category == "censor",
                "same_day_candidate_count": tied,
                "event_hierarchy_version": str(hierarchy["version"]),
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError(f"Endpoint {endpoint_name} has an empty study population")
    if result.patient_id.duplicated().any() or result.time_days.lt(0).any():
        raise AssertionError("Event records violate one-row-per-patient or non-negative time")
    return result.sort_values(["time_days", "patient_id"], kind="stable").reset_index(drop=True)


def _greenwood_log_log_interval(
    survival: float, greenwood_sum: float
) -> tuple[float, float, float]:
    if survival >= 1.0:
        return 0.0, 1.0, 1.0
    if survival <= 0.0:
        return 0.0, 0.0, 0.0
    standard_error = survival * math.sqrt(max(greenwood_sum, 0.0))
    log_survival = math.log(survival)
    transformed = math.log(-log_survival)
    transformed_se = math.sqrt(max(greenwood_sum, 0.0)) / abs(log_survival)
    lower = math.exp(-math.exp(transformed + Z_975 * transformed_se))
    upper = math.exp(-math.exp(transformed - Z_975 * transformed_se))
    return standard_error, max(0.0, lower), min(1.0, upper)


def estimate_kaplan_meier(records: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Estimate target-event KM and exact risk-set accounting.

    Competing events are visibly counted and leave the KM risk set. The paired
    Aalen-Johansen output, not ``1-KM``, is the absolute-probability estimate.
    """
    denominator = int(len(records))
    at_risk = denominator
    survival = 1.0
    greenwood_sum = 0.0
    cumulative_targets = 0
    curve_rows: list[dict[str, Any]] = [
        {
            "time_days": 0,
            "n_at_risk": denominator,
            "target_events": 0,
            "competing_events": 0,
            "censored": 0,
            "censoring_mark_count": 0,
            "has_censoring_mark": False,
            "cumulative_target_events": 0,
            "survival_probability": 1.0,
            "net_event_probability": 0.0,
            "greenwood_standard_error": 0.0,
            "confidence_lower": 1.0,
            "confidence_upper": 1.0,
            "uncertainty_type": "GREENWOOD_LOG_LOG_ESTIMATOR_CONFIDENCE_BAND_95",
        }
    ]
    risk_rows: list[dict[str, Any]] = []
    for time, group in records.groupby("time_days", sort=True):
        time_days = int(cast(Any, time))
        target_count = int(group.target_event.sum())
        competing_count = int(group.competing_event.sum())
        censor_count = int(group.censored.sum())
        removed = target_count + competing_count + censor_count
        if removed != len(group) or removed > at_risk:
            raise AssertionError("Invalid event partition or risk set")
        before = at_risk
        if target_count:
            survival *= 1.0 - target_count / before
            if before > target_count:
                greenwood_sum += target_count / (before * (before - target_count))
        cumulative_targets += target_count
        at_risk -= removed
        standard_error, lower, upper = _greenwood_log_log_interval(survival, greenwood_sum)
        curve_rows.append(
            {
                "time_days": time_days,
                "n_at_risk": before,
                "target_events": target_count,
                "competing_events": competing_count,
                "censored": censor_count,
                "censoring_mark_count": censor_count,
                "has_censoring_mark": censor_count > 0,
                "cumulative_target_events": cumulative_targets,
                "survival_probability": survival,
                "net_event_probability": 1.0 - survival,
                "greenwood_standard_error": standard_error,
                "confidence_lower": lower,
                "confidence_upper": upper,
                "uncertainty_type": "GREENWOOD_LOG_LOG_ESTIMATOR_CONFIDENCE_BAND_95",
            }
        )
        risk_rows.append(
            {
                "time_days": time_days,
                "n_at_risk_before": before,
                "target_events": target_count,
                "competing_events": competing_count,
                "censored": censor_count,
                "n_at_risk_after": at_risk,
                "reconciliation_difference": before - removed - at_risk,
            }
        )
    curve = pd.DataFrame(curve_rows)
    risk = pd.DataFrame(risk_rows)
    if not risk.reconciliation_difference.eq(0).all() or at_risk != 0:
        raise AssertionError("Number-at-risk table does not reconcile")
    probability_columns = [
        "survival_probability",
        "net_event_probability",
        "confidence_lower",
        "confidence_upper",
    ]
    if not curve[probability_columns].apply(lambda values: values.between(0, 1)).all().all():
        raise AssertionError("Kaplan-Meier output contains invalid probabilities")
    return curve, risk


def estimate_aalen_johansen(
    records: pd.DataFrame,
    causes: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Estimate non-parametric cumulative incidence for target and competing causes."""
    observed_causes = set(records.loc[~records.censored, "event_type"].astype(str).unique())
    event_causes = sorted(set(map(str, causes)) if causes is not None else observed_causes)
    unknown_causes = observed_causes - set(event_causes)
    if unknown_causes:
        raise ValueError(f"Event records contain undeclared causes: {sorted(unknown_causes)}")
    if not event_causes:
        raise ValueError("At least one target or competing cause must be declared")
    cumulative = {cause: 0.0 for cause in event_causes}
    at_risk = int(len(records))
    event_free_survival = 1.0
    rows: list[dict[str, Any]] = []
    for cause in event_causes:
        rows.append(
            {
                "time_days": 0,
                "cause": cause,
                "cause_events": 0,
                "n_at_risk": at_risk,
                "cumulative_incidence": 0.0,
                "all_event_survival": 1.0,
                "estimator": "AALEN_JOHANSEN",
                "uncertainty_type": "POINT_ESTIMATE_NO_INTERVAL",
            }
        )
    for time, group in records.groupby("time_days", sort=True):
        time_days = int(cast(Any, time))
        before = at_risk
        cause_counts = {
            cause: int((group.event_type.eq(cause) & ~group.censored).sum())
            for cause in event_causes
        }
        all_events = sum(cause_counts.values())
        survival_before = event_free_survival
        if before <= 0:
            raise AssertionError("Aalen-Johansen risk set exhausted prematurely")
        for cause, count in cause_counts.items():
            cumulative[cause] += survival_before * count / before
        event_free_survival *= 1.0 - all_events / before
        at_risk -= len(group)
        for cause in event_causes:
            rows.append(
                {
                    "time_days": time_days,
                    "cause": cause,
                    "cause_events": cause_counts[cause],
                    "n_at_risk": before,
                    "cumulative_incidence": cumulative[cause],
                    "all_event_survival": event_free_survival,
                    "estimator": "AALEN_JOHANSEN",
                    "uncertainty_type": "POINT_ESTIMATE_NO_INTERVAL",
                }
            )
        mass = event_free_survival + sum(cumulative.values())
        if abs(mass - 1.0) > 1e-10:
            raise AssertionError(f"Aalen-Johansen probability mass does not reconcile: {mass}")
    result = pd.DataFrame(rows)
    if not result.cumulative_incidence.between(0, 1).all():
        raise AssertionError("Aalen-Johansen cumulative incidence is outside [0, 1]")
    return result


def _metadata(
    endpoint: Mapping[str, Any],
    *,
    numerator: str,
    denominator: int,
    scenario: str,
    seed_summary: str,
    release: str,
) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "population_definition": str(endpoint["population_definition"]),
        "time_zero": str(endpoint["time_zero_column"]),
        "horizon_days": int(endpoint["horizon_days"]),
        "scenario": scenario,
        "seed_summary": seed_summary,
        "release": release,
        "assumptions": json.dumps(endpoint.get("assumptions", []), sort_keys=True),
        "limitation": str(endpoint["limitation"]),
        "synthetic_data_only": True,
    }


def build_survival_outputs(
    journey: pd.DataFrame,
    hierarchy: Mapping[str, Any],
    *,
    scenario: str,
    seed_summary: str,
    release: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build event records, KM curves, risk tables, and Aalen-Johansen estimates."""
    all_records: list[pd.DataFrame] = []
    all_curves: list[pd.DataFrame] = []
    all_risk: list[pd.DataFrame] = []
    all_cif: list[pd.DataFrame] = []
    for endpoint_name, endpoint_value in hierarchy["endpoints"].items():
        endpoint: Mapping[str, Any] = endpoint_value
        records = prepare_event_records(journey, str(endpoint_name), hierarchy)
        curve, risk = estimate_kaplan_meier(records)
        target_event = str(endpoint["target_event"])
        cif = estimate_aalen_johansen(
            records,
            causes=(target_event, *map(str, endpoint.get("competing_events", []))),
        )
        common = _metadata(
            endpoint,
            numerator=f"cumulative observed {target_event} events",
            denominator=len(records),
            scenario=scenario,
            seed_summary=seed_summary,
            release=release,
        )
        for frame in (curve, risk, cif):
            frame.insert(0, "analysis_id", str(endpoint["analysis_id"]))
            frame.insert(1, "endpoint", str(endpoint_name))
        records.insert(0, "analysis_id", str(endpoint["analysis_id"]))
        curve = curve.assign(**common)
        risk = risk.assign(**common)
        cif = cif.assign(**common)
        records = records.assign(
            scenario=scenario,
            seed_summary=seed_summary,
            release=release,
            population_definition=str(endpoint["population_definition"]),
            horizon_days=int(endpoint["horizon_days"]),
            synthetic_data_only=True,
        )
        all_records.append(records)
        all_curves.append(curve)
        all_risk.append(risk)
        all_cif.append(cif)
    return (
        pd.concat(all_records, ignore_index=True),
        pd.concat(all_curves, ignore_index=True),
        pd.concat(all_risk, ignore_index=True),
        pd.concat(all_cif, ignore_index=True),
    )


def write_survival_outputs(
    journey: pd.DataFrame,
    hierarchy: Mapping[str, Any],
    output_dir: str | Path,
    *,
    scenario: str,
    seed_summary: str,
    release: str,
) -> dict[str, Path]:
    """Write aggregate chart-ready survival evidence and plain-language guidance."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    records, curves, risk, cif = build_survival_outputs(
        journey,
        hierarchy,
        scenario=scenario,
        seed_summary=seed_summary,
        release=release,
    )
    paths = {
        "event_records": output / "time_to_event_records.parquet",
        "survival_curves": output / "survival_curves.csv",
        "number_at_risk": output / "number_at_risk.csv",
        "cumulative_incidence": output / "cumulative_incidence.csv",
        "explanation": output / "survival_plain_language.json",
    }
    records.to_parquet(paths["event_records"], index=False)
    curves.to_csv(paths["survival_curves"], index=False)
    risk.to_csv(paths["number_at_risk"], index=False)
    cif.to_csv(paths["cumulative_incidence"], index=False)
    explanation = {
        "synthetic_data_only": True,
        "disclaimer": DISCLAIMER,
        "kaplan_meier": (
            "Kaplan-Meier describes net target-event timing under an explicit censoring "
            "assumption. "
            "When a competing event exists, 1-KM is not presented as absolute probability."
        ),
        "greenwood": (
            "The shaded estimator band uses Greenwood variance with a log-log transformation. "
            "It is estimator uncertainty, not seed-to-seed or scenario uncertainty."
        ),
        "aalen_johansen": (
            "Aalen-Johansen estimates absolute cumulative incidence while retaining death or "
            "other configured competing events as events, not ordinary censoring."
        ),
        "risk_table": (
            "At every event time: risk set before = target events + competing events + censored "
            "+ risk set after."
        ),
        "clinical_boundary": (
            "All event definitions and same-day priorities are synthetic engineering proposals "
            "requiring oncology, RWE, and biostatistics review."
        ),
    }
    paths["explanation"].write_text(json.dumps(explanation, indent=2), encoding="utf-8")
    return paths
