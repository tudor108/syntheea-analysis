"""Independent row-level reconciliation gate for the release analytical mart.

This module deliberately does not import the mart-building implementation.  It
reconstructs release-critical concepts directly from normalized tables so that
the release gate cannot pass merely because it repeats a derived mart field.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

CONCEPTS = (
    "eligibility",
    "first_treatment",
    "initiation_windows",
    "regimen_and_intensification",
    "persistence",
    "discontinuation",
    "switch_restart",
    "active_surveillance",
    "referral_transition",
    "censoring_and_outcomes",
)


def _missing(value: Any) -> bool:
    """Return scalar missingness without treating containers as scalars."""
    result = pd.isna(value)
    return bool(result) if not hasattr(result, "__len__") else False


def _equal(expected: Any, actual: Any) -> bool:
    if _missing(expected) and _missing(actual):
        return True
    if _missing(expected) or _missing(actual):
        return False
    if isinstance(expected, pd.Timestamp) or isinstance(actual, pd.Timestamp):
        return pd.Timestamp(expected) == pd.Timestamp(actual)
    return bool(expected == actual)


def _json_value(value: Any) -> Any:
    if _missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _regimen_state(components: pd.DataFrame, episode: pd.Series) -> dict[str, Any]:
    """Derive regimen labels exclusively from component classes and dates."""
    if components.empty:
        return {
            "regimen_name": pd.NA,
            "regimen_type": pd.NA,
            "combination_strategy": pd.NA,
            "intensification_flag": False,
            "component_count": 0,
        }
    classes = set(components.drug_class)
    if "procedure" in classes:
        regimen_name = f"localized_{components.iloc[0].drug_name}"
    elif {"ADT", "ARPI", "chemotherapy"}.issubset(classes):
        regimen_name = "adt_arpi_chemotherapy_triplet"
    elif {"ADT", "ARPI"}.issubset(classes):
        regimen_name = "adt_arpi_doublet"
    elif {"ADT", "chemotherapy"}.issubset(classes):
        regimen_name = "adt_chemotherapy_doublet"
    else:
        regimen_name = "adt_monotherapy"
    count = int(len(components))
    regimen_type = "triplet" if count >= 3 else "doublet" if count == 2 else "monotherapy"
    start = pd.Timestamp(episode.treatment_start_date)
    strategy = (
        "monotherapy"
        if count == 1
        else "add_on"
        if pd.to_datetime(components.component_start_date).gt(start).any()
        else "planned_combination"
    )
    return {
        "regimen_name": regimen_name,
        "regimen_type": regimen_type,
        "combination_strategy": strategy,
        "intensification_flag": bool(
            episode.episode_reason == "mhspc_eligible" and bool(classes & {"ARPI", "chemotherapy"})
        ),
        "component_count": count,
    }


def _persistence_clock(
    events: pd.DataFrame,
    start: pd.Timestamp,
    censor: pd.Timestamp,
    target_days: int,
    permissible_gap: int,
    discontinuation_date: Any,
    switch_date: Any,
) -> tuple[str, pd.Timestamp | pd.NaT, str | None]:
    """Independently evaluate persistence from dated coverage boundaries."""
    if events.empty:
        return "NOT_APPLICABLE", pd.NaT, None

    boundaries: list[tuple[pd.Timestamp, int, str, str]] = []
    if pd.notna(switch_date):
        boundaries.append((pd.Timestamp(switch_date), 0, "SWITCHED", "explicit_switch"))
    if pd.notna(discontinuation_date):
        boundaries.append(
            (
                pd.Timestamp(discontinuation_date),
                1,
                "DISCONTINUED",
                "explicit_discontinuation",
            )
        )

    coverage = pd.NaT
    for event in events.sort_values(["service_date", "prescription_event_id"]).itertuples():
        service = pd.Timestamp(event.service_date)
        gap_origin = start if pd.isna(coverage) else pd.Timestamp(coverage)
        if service > gap_origin + pd.Timedelta(days=permissible_gap):
            boundaries.append(
                (
                    gap_origin + pd.Timedelta(days=permissible_gap + 1),
                    2,
                    "DISCONTINUED",
                    "observed_gap_exhaustion",
                )
            )
            break
        supplied_through = pd.Timestamp(event.covered_until_date)
        coverage = supplied_through if pd.isna(coverage) else max(coverage, supplied_through)
    if pd.notna(coverage):
        boundaries.append(
            (
                pd.Timestamp(coverage) + pd.Timedelta(days=permissible_gap + 1),
                2,
                "DISCONTINUED",
                "observed_gap_exhaustion",
            )
        )

    target = start + pd.Timedelta(days=target_days)
    boundaries.extend(
        [
            (target, 3, "PERSISTENT", "landmark_reached"),
            (censor, 4, "CENSORED_NOT_EVALUABLE", "right_censor"),
        ]
    )
    boundary = min(boundaries, key=lambda value: (value[0], value[1]))
    operational_date = boundary[0] if boundary[2] == "DISCONTINUED" else pd.NaT
    return boundary[2], operational_date, boundary[3]


def reconcile_release_tables(
    tables: dict[str, pd.DataFrame], config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Rebuild ten release-critical concepts and return every row-level mismatch."""
    patient = tables["patient"]
    diagnosis = tables["diagnosis"]
    eligibility = tables["eligibility"]
    observation = tables["observation"]
    episode = tables["treatment_episode"]
    regimen = tables["treatment_regimen"]
    component = tables["treatment_regimen_component"]
    prescription = tables["prescription_event"]
    active = tables["active_surveillance"]
    encounter = tables["encounter"]
    referral = tables["referral"]
    outcome = tables["outcome"]
    adverse = tables["adverse_event"]
    journey = tables["patient_journey"]

    patient_index = patient.set_index("patient_id")
    diagnosis_index = diagnosis.set_index("patient_id")
    eligibility_index = eligibility.set_index("patient_id")
    observation_index = observation.set_index("patient_id")
    outcome_index = outcome.set_index("patient_id")
    journey_index = journey.set_index("patient_id")
    episode_lookup = episode.set_index("treatment_episode_id")
    regimen_by_episode = regimen.set_index("treatment_episode_id")
    components_by_episode = {
        key: frame for key, frame in component.groupby("treatment_episode_id", sort=False)
    }
    events_by_component = {
        key: frame for key, frame in prescription.groupby("component_id", sort=False)
    }
    empty_components = component.iloc[0:0]
    empty_events = prescription.iloc[0:0]
    first_episode = (
        episode.sort_values(["patient_id", "treatment_start_date", "treatment_episode_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
    )
    first_referral = (
        referral.sort_values(["patient_id", "referral_date", "referral_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
    )
    active_index = active.set_index("patient_id")

    details: list[dict[str, Any]] = []
    comparisons: Counter[str] = Counter()
    evidence: dict[str, dict[str, Any]] = defaultdict(dict)

    def compare(
        concept: str,
        patient_id: Any,
        field: str,
        expected: Any,
        actual: Any,
        *,
        entity_id: Any = None,
        message: str = "",
    ) -> None:
        comparisons[concept] += 1
        if _equal(expected, actual):
            return
        details.append(
            {
                "concept": concept,
                "patient_id": patient_id,
                "entity_id": entity_id,
                "field": field,
                "expected": _json_value(expected),
                "actual": _json_value(actual),
                "message": message,
            }
        )

    # 1. Eligibility: derive clinical state, data sufficiency, dates and reason semantics.
    eligible_count = 0
    for patient_id, person in patient_index.iterrows():
        dx = diagnosis_index.loc[patient_id]
        exported = eligibility_index.loc[patient_id]
        mart = journey_index.loc[patient_id]
        mhspc = bool(
            dx.prostate_cancer_flag
            and dx.metastatic_flag
            and dx.hormone_sensitive_flag
            and not dx.castration_resistant_flag
        )
        sufficient_evidence = bool(
            dx.prostate_stage != "unknown"
            and not (
                dx.metastatic_flag
                and not dx.hormone_sensitive_flag
                and not dx.castration_resistant_flag
            )
        )
        possible_followup = (
            pd.Timestamp(config["observation_end_date"]) - pd.Timestamp(dx.diagnosis_date)
        ).days
        sufficient_followup = possible_followup >= int(config["minimum_follow_up_days"])
        expected_eligible = bool(
            mhspc
            and person.age_at_index >= 18
            and not exported.contraindication_flag
            and sufficient_evidence
            and sufficient_followup
        )
        if expected_eligible:
            eligible_count += 1
            status = "ELIGIBLE"
            date = max(
                pd.Timestamp(dx.diagnosis_date),
                pd.Timestamp(dx.metastatic_date),
                pd.Timestamp(dx.hormone_sensitive_confirmation_date),
            )
            eligibility_reason = "meets_configured_mhspc_denominator"
            ineligibility_reason = pd.NA
            exclusion_reason = pd.NA
        elif not sufficient_evidence or not sufficient_followup:
            status = "INSUFFICIENT_DATA"
            date = pd.NaT
            eligibility_reason = pd.NA
            ineligibility_reason = (
                "insufficient_clinical_state_evidence"
                if not sufficient_evidence
                else "insufficient_followup_potential"
            )
            exclusion_reason = pd.NA
        else:
            status = "CLINICALLY_INELIGIBLE"
            date = pd.NaT
            eligibility_reason = pd.NA
            if exported.contraindication_flag:
                ineligibility_reason = "configured_contraindication"
                exclusion_reason = exported.contraindication_reason
            elif not mhspc:
                ineligibility_reason = "does_not_meet_mhspc_state"
                exclusion_reason = "disease_state_outside_configured_denominator"
            else:
                ineligibility_reason = "age_outside_rule"
                exclusion_reason = "age"

        normalized_expectations = {
            "mhspc_flag": mhspc,
            "data_sufficiency_flag": sufficient_evidence,
            "possible_followup_days": possible_followup,
            "minimum_followup_required_days": int(config["minimum_follow_up_days"]),
            "eligibility_flag": expected_eligible,
            "eligible_for_arpi": expected_eligible,
            "eligibility_status": status,
            "eligibility_date": date,
            "eligibility_reason": eligibility_reason,
            "ineligibility_reason": ineligibility_reason,
            "clinical_exclusion_reason": exclusion_reason,
            "censor_date_at_generation": observation_index.loc[patient_id, "censor_date"],
        }
        for field, expected in normalized_expectations.items():
            compare("eligibility", patient_id, f"eligibility.{field}", expected, exported[field])
        mart_expectations = {
            "mhspc_flag": mhspc,
            "denominator_status": status,
            "eligibility_flag": expected_eligible,
            "eligible_for_arpi": expected_eligible,
            "eligibility_date": date,
            "eligibility_reason": eligibility_reason,
            "ineligibility_reason": ineligibility_reason,
            "clinical_exclusion_reason": exclusion_reason,
            "contraindication_flag": bool(exported.contraindication_flag),
            "data_sufficiency_flag": sufficient_evidence,
        }
        for field, expected in mart_expectations.items():
            compare("eligibility", patient_id, f"patient_journey.{field}", expected, mart[field])
    evidence["eligibility"] = {"independently_eligible": eligible_count}

    # 2. First treatment: identify the earliest normalized episode and reconcile the mart grain.
    treated_count = 0
    for patient_id, mart in journey_index.iterrows():
        treated = patient_id in first_episode.index
        treated_count += int(treated)
        first = first_episode.loc[patient_id] if treated else None
        compare(
            "first_treatment",
            patient_id,
            "patient_journey.treatment_initiated",
            treated,
            mart.treatment_initiated,
        )
        compare(
            "first_treatment",
            patient_id,
            "patient_journey.treatment_episode_id",
            first.treatment_episode_id if treated else pd.NA,
            mart.treatment_episode_id,
        )
        compare(
            "first_treatment",
            patient_id,
            "patient_journey.treatment_start_date",
            first.treatment_start_date if treated else pd.NaT,
            mart.treatment_start_date,
        )
    evidence["first_treatment"] = {"independently_treated": treated_count}

    # 3. Initiation windows: rebuild landmark status and all mart flags from event dates.
    initiation_distributions: dict[str, Counter[str]] = {
        f"{days}d": Counter() for days in (30, 60, 90)
    }
    for patient_id, mart in journey_index.iterrows():
        exported = eligibility_index.loc[patient_id]
        treated = patient_id in first_episode.index
        start = (
            pd.Timestamp(first_episode.loc[patient_id, "treatment_start_date"])
            if treated
            else pd.NaT
        )
        censor = pd.Timestamp(observation_index.loc[patient_id, "censor_date"])
        days_to_start = (
            (start - pd.Timestamp(exported.eligibility_date)).days
            if treated and exported.eligibility_flag
            else pd.NA
        )
        compare(
            "initiation_windows",
            patient_id,
            "patient_journey.days_to_initiation",
            days_to_start,
            mart.days_to_initiation,
        )
        statuses: dict[int, str] = {}
        for window in (30, 60, 90):
            target = (
                pd.Timestamp(exported.eligibility_date) + pd.Timedelta(days=window)
                if exported.eligibility_flag
                else pd.NaT
            )
            status = (
                "NOT_ELIGIBLE"
                if not exported.eligibility_flag
                else f"INITIATED_WITHIN_{window}D"
                if treated and days_to_start <= window
                else "CENSORED_NOT_EVALUABLE"
                if censor < target
                else f"NOT_INITIATED_WITHIN_{window}D"
            )
            statuses[window] = status
            initiation_distributions[f"{window}d"][status] += 1
            compare(
                "initiation_windows",
                patient_id,
                f"patient_journey.initiated_within_{window}d",
                status == f"INITIATED_WITHIN_{window}D",
                mart[f"initiated_within_{window}d"],
            )
        compare(
            "initiation_windows",
            patient_id,
            "patient_journey.initiation_90d_status",
            statuses[90],
            mart.initiation_90d_status,
        )
        compare(
            "initiation_windows",
            patient_id,
            "patient_journey.eligible_not_initiated_90d",
            statuses[90] == "NOT_INITIATED_WITHIN_90D",
            mart.eligible_not_initiated_90d,
        )
    evidence["initiation_windows"] = {
        key: dict(value) for key, value in initiation_distributions.items()
    }

    # 4. Full-regimen and treatment-start snapshots from normalized components.
    for episode_id, tx in episode_lookup.iterrows():
        components = components_by_episode.get(episode_id, empty_components)
        expected = _regimen_state(components, tx)
        if episode_id not in regimen_by_episode.index:
            compare(
                "regimen_and_intensification",
                tx.patient_id,
                "treatment_regimen.present",
                True,
                False,
                entity_id=episode_id,
            )
            continue
        exported_regimen = regimen_by_episode.loc[episode_id]
        for normalized_field, expected_key in (
            ("regimen_name", "regimen_name"),
            ("regimen_type", "regimen_type"),
            ("combination_strategy", "combination_strategy"),
            ("intensification_flag", "intensification_flag"),
        ):
            compare(
                "regimen_and_intensification",
                tx.patient_id,
                f"treatment_regimen.{normalized_field}",
                expected[expected_key],
                exported_regimen[normalized_field],
                entity_id=episode_id,
            )
    for patient_id, mart in journey_index.iterrows():
        treated = patient_id in first_episode.index
        if not treated:
            expectations = {
                "initial_regimen": pd.NA,
                "initial_regimen_type": pd.NA,
                "combination_strategy": pd.NA,
                "intensification_flag": False,
                "regimen_component_count": 0,
                "regimen_at_treatment_start": pd.NA,
                "regimen_type_at_treatment_start": pd.NA,
                "combination_strategy_at_treatment_start": pd.NA,
                "intensification_at_treatment_start_flag": False,
                "regimen_component_count_at_treatment_start": 0,
            }
        else:
            first = first_episode.loc[patient_id]
            components = components_by_episode.get(first.treatment_episode_id, empty_components)
            full = _regimen_state(components, first)
            started = components.loc[
                pd.to_datetime(components.component_start_date).le(
                    pd.Timestamp(first.treatment_start_date)
                )
            ]
            snapshot = _regimen_state(started, first)
            expectations = {
                "initial_regimen": full["regimen_name"],
                "initial_regimen_type": full["regimen_type"],
                "combination_strategy": full["combination_strategy"],
                "intensification_flag": full["intensification_flag"],
                "regimen_component_count": full["component_count"],
                "regimen_at_treatment_start": snapshot["regimen_name"],
                "regimen_type_at_treatment_start": snapshot["regimen_type"],
                "combination_strategy_at_treatment_start": snapshot["combination_strategy"],
                "intensification_at_treatment_start_flag": snapshot["intensification_flag"],
                "regimen_component_count_at_treatment_start": snapshot["component_count"],
            }
        for field, expected in expectations.items():
            compare(
                "regimen_and_intensification",
                patient_id,
                f"patient_journey.{field}",
                expected,
                mart[field],
            )
    evidence["regimen_and_intensification"] = {
        "episodes": int(len(episode)),
        "components": int(len(component)),
    }

    # 5. Persistence: six independent event clocks plus nullable flag semantics.
    persistence_specs = (
        ("persistence_3m_status", "persistent_3m", 90, 60),
        ("persistence_6m_status", "persistent_6m", 180, 60),
        ("persistence_12m_status", "persistent_12m", 365, 60),
        ("persistence_12m_status_gap_30d", "persistent_12m_gap_30d", 365, 30),
        ("persistence_12m_status_gap_60d", "persistent_12m_gap_60d", 365, 60),
        ("persistence_12m_status_gap_90d", "persistent_12m_gap_90d", 365, 90),
    )
    persistence_distributions: dict[str, Counter[str]] = {
        spec[0]: Counter() for spec in persistence_specs
    }
    operational_12m: dict[str, tuple[pd.Timestamp | pd.NaT, str | None, str]] = {}
    for patient_id, mart in journey_index.iterrows():
        treated = patient_id in first_episode.index
        first = first_episode.loc[patient_id] if treated else None
        if treated and pd.notna(first.tracking_component_id):
            events = events_by_component.get(first.tracking_component_id, empty_events)
        else:
            events = empty_events
        for status_field, flag_field, target_days, gap in persistence_specs:
            if treated:
                status, operational_date, cause = _persistence_clock(
                    events,
                    pd.Timestamp(first.treatment_start_date),
                    pd.Timestamp(observation_index.loc[patient_id, "censor_date"]),
                    target_days,
                    gap,
                    first.discontinuation_date,
                    first.switch_date,
                )
            else:
                status, operational_date, cause = "NOT_APPLICABLE", pd.NaT, None
            persistence_distributions[status_field][status] += 1
            expected_flag = (
                True
                if status == "PERSISTENT"
                else pd.NA
                if status in {"CENSORED_NOT_EVALUABLE", "NOT_APPLICABLE"}
                else False
            )
            compare(
                "persistence",
                patient_id,
                f"patient_journey.{status_field}",
                status,
                mart[status_field],
            )
            compare(
                "persistence",
                patient_id,
                f"patient_journey.{flag_field}",
                expected_flag,
                mart[flag_field],
            )
            if status_field == "persistence_12m_status":
                operational_12m[patient_id] = (operational_date, cause, status)
    evidence["persistence"] = {key: dict(value) for key, value in persistence_distributions.items()}

    # 6. Explicit stops remain distinct from operational gap-based discontinuation.
    discontinuation_causes: Counter[str] = Counter()
    for patient_id, mart in journey_index.iterrows():
        treated = patient_id in first_episode.index
        first = first_episode.loc[patient_id] if treated else None
        expected_flag = bool(treated and pd.notna(first.discontinuation_date))
        expected_date = first.discontinuation_date if treated else pd.NaT
        if treated:
            compare(
                "discontinuation",
                patient_id,
                "treatment_episode.discontinuation_flag",
                pd.notna(first.discontinuation_date),
                first.discontinuation_flag,
                entity_id=first.treatment_episode_id,
            )
            if pd.notna(first.discontinuation_date):
                compare(
                    "discontinuation",
                    patient_id,
                    "treatment_episode.discontinuation_within_episode",
                    True,
                    pd.Timestamp(first.treatment_start_date)
                    <= pd.Timestamp(first.discontinuation_date)
                    <= pd.Timestamp(first.treatment_end_date),
                    entity_id=first.treatment_episode_id,
                )
        compare(
            "discontinuation",
            patient_id,
            "patient_journey.discontinuation_flag",
            expected_flag,
            mart.discontinuation_flag,
        )
        compare(
            "discontinuation",
            patient_id,
            "patient_journey.discontinuation_date",
            expected_date,
            mart.discontinuation_date,
        )
        operational_date, cause, status = operational_12m[patient_id]
        discontinuation_causes[cause or "not_applicable"] += 1
        compare(
            "discontinuation",
            patient_id,
            "operational_12m_discontinuation_has_date",
            status == "DISCONTINUED",
            pd.notna(operational_date),
            message="Operational gaps are derived independently from explicit stop flags.",
        )
    evidence["discontinuation"] = {"12m_boundary_causes": dict(discontinuation_causes)}

    # 7. Switch/restart lineage, transition dates and closure of old coverage.
    children_by_previous: dict[str, list[pd.Series]] = defaultdict(list)
    for _, child in episode.loc[episode.previous_episode_id.notna()].iterrows():
        children_by_previous[str(child.previous_episode_id)].append(child)
        if child.previous_episode_id not in episode_lookup.index:
            compare(
                "switch_restart",
                child.patient_id,
                "treatment_episode.previous_episode_id_resolves",
                True,
                False,
                entity_id=child.treatment_episode_id,
            )
            continue
        prior = episode_lookup.loc[child.previous_episode_id]
        compare(
            "switch_restart",
            child.patient_id,
            "linked_episode.same_patient",
            prior.patient_id,
            child.patient_id,
            entity_id=child.treatment_episode_id,
        )
        compare(
            "switch_restart",
            child.patient_id,
            "linked_episode.nonoverlap",
            True,
            pd.Timestamp(child.treatment_start_date) > pd.Timestamp(prior.treatment_end_date),
            entity_id=child.treatment_episode_id,
        )
        if child.transition_type == "switch":
            compare(
                "switch_restart",
                child.patient_id,
                "switch.prior_flag",
                True,
                prior.switch_flag,
                entity_id=child.treatment_episode_id,
            )
            compare(
                "switch_restart",
                child.patient_id,
                "switch.child_start",
                pd.Timestamp(prior.switch_date) + pd.Timedelta(days=1),
                child.treatment_start_date,
                entity_id=child.treatment_episode_id,
            )
            old_arpi = set(
                components_by_episode.get(child.previous_episode_id, empty_components).loc[
                    lambda frame: frame.drug_class.eq("ARPI"), "drug_name"
                ]
            )
            new_arpi = set(
                components_by_episode.get(child.treatment_episode_id, empty_components).loc[
                    lambda frame: frame.drug_class.eq("ARPI"), "drug_name"
                ]
            )
            compare(
                "switch_restart",
                child.patient_id,
                "switch.prior_arpi_present",
                True,
                bool(old_arpi),
                entity_id=child.treatment_episode_id,
            )
            compare(
                "switch_restart",
                child.patient_id,
                "switch.replacement_arpi_present",
                True,
                bool(new_arpi),
                entity_id=child.treatment_episode_id,
            )
            compare(
                "switch_restart",
                child.patient_id,
                "switch.replacement_arpi_differs",
                True,
                bool(old_arpi and new_arpi and old_arpi.isdisjoint(new_arpi)),
                entity_id=child.treatment_episode_id,
            )
            old_events = prescription.loc[
                prescription.treatment_episode_id.eq(child.previous_episode_id)
            ]
            for event in old_events.itertuples():
                compare(
                    "switch_restart",
                    child.patient_id,
                    "switch.old_service_not_after_switch",
                    True,
                    pd.Timestamp(event.service_date) <= pd.Timestamp(prior.switch_date),
                    entity_id=event.prescription_event_id,
                )
                compare(
                    "switch_restart",
                    child.patient_id,
                    "switch.old_coverage_not_after_switch",
                    True,
                    pd.Timestamp(event.covered_until_date) <= pd.Timestamp(prior.switch_date),
                    entity_id=event.prescription_event_id,
                )
        elif child.transition_type == "restart":
            compare(
                "switch_restart",
                child.patient_id,
                "restart.prior_flag",
                True,
                prior.restart_flag,
                entity_id=child.treatment_episode_id,
            )
            compare(
                "switch_restart",
                child.patient_id,
                "restart.child_start",
                prior.restart_date,
                child.treatment_start_date,
                entity_id=child.treatment_episode_id,
            )
            compare(
                "switch_restart",
                child.patient_id,
                "restart.prior_discontinued",
                True,
                prior.discontinuation_flag,
                entity_id=child.treatment_episode_id,
            )
    for patient_id, first in first_episode.iterrows():
        children = children_by_previous.get(str(first.treatment_episode_id), [])
        switch_children = [child for child in children if child.transition_type == "switch"]
        restart_children = [child for child in children if child.transition_type == "restart"]
        compare(
            "switch_restart",
            patient_id,
            "switch.link_count",
            1 if first.switch_flag else 0,
            len(switch_children),
            entity_id=first.treatment_episode_id,
        )
        compare(
            "switch_restart",
            patient_id,
            "restart.link_count",
            1 if first.restart_flag else 0,
            len(restart_children),
            entity_id=first.treatment_episode_id,
        )
        mart = journey_index.loc[patient_id]
        for field in ("switch_flag", "switch_date", "restart_flag"):
            compare(
                "switch_restart",
                patient_id,
                f"patient_journey.{field}",
                first[field],
                mart[field],
            )
    evidence["switch_restart"] = {
        "switch_links": int(episode.transition_type.eq("switch").sum()),
        "restart_links": int(episode.transition_type.eq("restart").sum()),
    }

    # 8. Active-surveillance state, monitoring and treatment transition.
    monitor_count = (
        encounter.loc[encounter.encounter_type.astype(str).str.startswith("as_")]
        .groupby("patient_id")
        .size()
    )
    as_treatment = (
        episode.loc[episode.episode_reason.eq("active_surveillance_exit")]
        .sort_values(["patient_id", "treatment_start_date"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
    )
    reclassification_reasons = {"progression", "grade_reclassification", "psa_rise"}
    for patient_id, mart in journey_index.iterrows():
        has_assessment = patient_id in active_index.index
        compare(
            "active_surveillance",
            patient_id,
            "active_surveillance.assessment_presence",
            bool(diagnosis_index.loc[patient_id, "localized_flag"]),
            has_assessment,
        )
        if not has_assessment:
            expectations = {
                "active_surveillance_eligible_flag": False,
                "active_surveillance_status": "not_applicable",
                "active_surveillance_start_date": pd.NaT,
                "active_surveillance_exit_date": pd.NaT,
                "active_surveillance_exit_reason": pd.NA,
                "active_surveillance_reclassification_flag": False,
                "active_surveillance_reclassification_date": pd.NaT,
            }
        else:
            record = active_index.loc[patient_id]
            dx = diagnosis_index.loc[patient_id]
            person = patient_index.loc[patient_id]
            expected_eligible = bool(
                dx.localized_flag
                and dx.risk_group in config["active_surveillance"]["eligibility_risk_groups"]
                and pd.notna(dx.isup_grade_group)
                and int(dx.isup_grade_group) <= 3
                and person.age_at_index <= 85
            )
            expected_status = (
                "not_started"
                if pd.isna(record.as_start_date)
                else "exited"
                if pd.notna(record.as_exit_date)
                else "censored"
                if pd.Timestamp(observation_index.loc[patient_id, "censor_date"])
                < pd.Timestamp(config["observation_end_date"])
                else "continued"
            )
            expected_reclassification = bool(record.as_exit_reason in reclassification_reasons)
            compare(
                "active_surveillance",
                patient_id,
                "active_surveillance.as_eligibility_flag",
                expected_eligible,
                record.as_eligibility_flag,
                entity_id=record.active_surveillance_id,
            )
            compare(
                "active_surveillance",
                patient_id,
                "active_surveillance.as_status",
                expected_status,
                record.as_status,
                entity_id=record.active_surveillance_id,
            )
            compare(
                "active_surveillance",
                patient_id,
                "active_surveillance.monitoring_event_count",
                int(monitor_count.get(patient_id, 0)),
                record.monitoring_event_count,
                entity_id=record.active_surveillance_id,
            )
            compare(
                "active_surveillance",
                patient_id,
                "active_surveillance.as_reclassification_event_flag",
                expected_reclassification,
                record.as_reclassification_event_flag,
                entity_id=record.active_surveillance_id,
            )
            compare(
                "active_surveillance",
                patient_id,
                "active_surveillance.as_reclassification_date",
                record.as_exit_date if expected_reclassification else pd.NaT,
                record.as_reclassification_date,
                entity_id=record.active_surveillance_id,
            )
            has_transition = patient_id in as_treatment.index
            compare(
                "active_surveillance",
                patient_id,
                "active_surveillance.transition_to_treatment_flag",
                has_transition,
                record.transition_to_treatment_flag,
                entity_id=record.active_surveillance_id,
            )
            compare(
                "active_surveillance",
                patient_id,
                "active_surveillance.planned_treatment_start_date",
                as_treatment.loc[patient_id, "treatment_start_date"] if has_transition else pd.NaT,
                record.planned_treatment_start_date,
                entity_id=record.active_surveillance_id,
            )
            expectations = {
                "active_surveillance_eligible_flag": expected_eligible,
                "active_surveillance_status": record.as_status,
                "active_surveillance_start_date": record.as_start_date,
                "active_surveillance_exit_date": record.as_exit_date,
                "active_surveillance_exit_reason": record.as_exit_reason,
                "active_surveillance_reclassification_flag": expected_reclassification,
                "active_surveillance_reclassification_date": (
                    record.as_exit_date if expected_reclassification else pd.NaT
                ),
            }
        for field, expected in expectations.items():
            compare(
                "active_surveillance",
                patient_id,
                f"patient_journey.{field}",
                expected,
                mart[field],
            )
    evidence["active_surveillance"] = {
        "assessments": int(len(active)),
        "monitoring_events": int(monitor_count.sum()),
        "treatment_transitions": int(len(as_treatment)),
    }

    # 9. First referral transition, completion delay and decision ownership.
    for row in referral.itertuples():
        completed = row.referral_status == "completed"
        compare(
            "referral_transition",
            row.patient_id,
            "referral.completion_date_semantics",
            completed,
            pd.notna(row.completion_date),
            entity_id=row.referral_id,
        )
        expected_owner = row.destination_specialty if completed else row.source_specialty
        compare(
            "referral_transition",
            row.patient_id,
            "referral.decision_owner_specialty",
            expected_owner,
            row.decision_owner_specialty,
            entity_id=row.referral_id,
        )
        if completed:
            compare(
                "referral_transition",
                row.patient_id,
                "referral.completion_not_before_referral",
                True,
                pd.Timestamp(row.completion_date) >= pd.Timestamp(row.referral_date),
                entity_id=row.referral_id,
            )
    for patient_id, mart in journey_index.iterrows():
        if patient_id in first_referral.index:
            first = first_referral.loc[patient_id]
            completed = first.referral_status == "completed"
            delay = (
                (pd.Timestamp(first.completion_date) - pd.Timestamp(first.referral_date)).days
                if completed
                else pd.NA
            )
            expectations = {
                "referral_status": first.referral_status,
                "referral_completed_flag": completed,
                "referral_delay_days": delay,
                "decision_owner_specialty": (
                    first.destination_specialty if completed else first.source_specialty
                ),
            }
        else:
            expectations = {
                "referral_status": "not_applicable",
                "referral_completed_flag": False,
                "referral_delay_days": pd.NA,
                "decision_owner_specialty": "urology",
            }
        for field, expected in expectations.items():
            compare(
                "referral_transition",
                patient_id,
                f"patient_journey.{field}",
                expected,
                mart[field],
            )
    evidence["referral_transition"] = {
        "referrals": int(len(referral)),
        "completed": int(referral.referral_status.eq("completed").sum()),
    }

    # 10. Recompute censor from competing terminal dates and rebuild outcome status/flags.
    administrative_end = pd.Timestamp(config["observation_end_date"])
    adverse_counts = adverse.groupby("patient_id").size()
    censor_reasons: Counter[str] = Counter()
    for patient_id, obs in observation_index.iterrows():
        terminal: list[tuple[pd.Timestamp, int, str]] = [
            (administrative_end, 2, "administrative_end")
        ]
        if pd.notna(obs.death_date):
            terminal.append((pd.Timestamp(obs.death_date), 0, "death"))
        if pd.notna(obs.loss_to_follow_up_date):
            terminal.append((pd.Timestamp(obs.loss_to_follow_up_date), 1, "loss_to_follow_up"))
        expected_censor, _, expected_reason = min(terminal, key=lambda value: (value[0], value[1]))
        censor_reasons[expected_reason] += 1
        dx = diagnosis_index.loc[patient_id]
        mart = journey_index.loc[patient_id]
        out = outcome_index.loc[patient_id]
        for field, expected in (
            ("observation_end_date", administrative_end),
            ("censor_date", expected_censor),
            ("last_observed_date", expected_censor),
            ("censor_reason", expected_reason),
            (
                "follow_up_days_from_diagnosis",
                (expected_censor - pd.Timestamp(dx.diagnosis_date)).days,
            ),
        ):
            compare(
                "censoring_and_outcomes",
                patient_id,
                f"observation.{field}",
                expected,
                obs[field],
            )
        compare(
            "censoring_and_outcomes",
            patient_id,
            "observation.competing_terminal_events",
            False,
            bool(pd.notna(obs.death_date) and pd.notna(obs.loss_to_follow_up_date)),
        )
        for field, expected in (
            ("observation_start_date", obs.observation_start_date),
            ("observation_end_date", administrative_end),
            ("last_observed_date", expected_censor),
            ("death_date", obs.death_date),
            ("loss_to_follow_up_date", obs.loss_to_follow_up_date),
            ("censor_date", expected_censor),
            ("censor_reason", expected_reason),
            ("follow_up_days", (expected_censor - pd.Timestamp(dx.diagnosis_date)).days),
        ):
            compare(
                "censoring_and_outcomes",
                patient_id,
                f"patient_journey.{field}",
                expected,
                mart[field],
            )
        outcome_expectations = {
            "progression_event": pd.notna(out.progression_date),
            "hospitalisation_flag": pd.notna(out.first_hospitalisation_date),
            "adverse_event_flag": int(adverse_counts.get(patient_id, 0)) > 0,
            "death_flag": pd.notna(obs.death_date),
            "death_date": obs.death_date,
            "lost_to_follow_up_flag": pd.notna(obs.loss_to_follow_up_date),
            "loss_to_follow_up_date": obs.loss_to_follow_up_date,
            "censor_date": expected_censor,
            "censor_reason": expected_reason,
        }
        for field, expected in outcome_expectations.items():
            compare(
                "censoring_and_outcomes",
                patient_id,
                f"outcome.{field}",
                expected,
                out[field],
            )
        for date_field in (
            "progression_date",
            "castration_resistant_date",
            "first_hospitalisation_date",
        ):
            event_date = out[date_field]
            compare(
                "censoring_and_outcomes",
                patient_id,
                f"outcome.{date_field}_not_after_censor",
                True,
                pd.isna(event_date) or pd.Timestamp(event_date) <= expected_censor,
            )
        active_at_censor = bool(
            not episode.empty
            and (
                episode.patient_id.eq(patient_id)
                & episode.treatment_status.eq("ongoing")
                & pd.to_datetime(episode.treatment_start_date).le(expected_censor)
                & pd.to_datetime(episode.treatment_end_date).ge(expected_censor)
            ).any()
        )
        expected_outcome_status = (
            "death"
            if pd.notna(obs.death_date)
            else "progressed"
            if pd.notna(out.progression_date)
            else "hospitalised"
            if pd.notna(out.first_hospitalisation_date)
            else "lost_to_follow_up"
            if pd.notna(obs.loss_to_follow_up_date)
            else "active_treatment"
            if active_at_censor
            else "post_treatment_follow_up"
            if patient_id in first_episode.index
            else "observed_no_treatment"
        )
        compare(
            "censoring_and_outcomes",
            patient_id,
            "outcome.outcome_status",
            expected_outcome_status,
            out.outcome_status,
        )
        for field, expected in (
            ("progression_event", pd.notna(out.progression_date)),
            ("progression_date", out.progression_date),
            ("hospitalisation_flag", pd.notna(out.first_hospitalisation_date)),
            ("first_hospitalisation_date", out.first_hospitalisation_date),
            ("adverse_event_flag", int(adverse_counts.get(patient_id, 0)) > 0),
            ("death_flag", pd.notna(obs.death_date)),
            ("death_date", obs.death_date),
            ("lost_to_follow_up_flag", pd.notna(obs.loss_to_follow_up_date)),
            ("loss_to_follow_up_date", obs.loss_to_follow_up_date),
            ("final_outcome_status", expected_outcome_status),
        ):
            compare(
                "censoring_and_outcomes",
                patient_id,
                f"patient_journey.{field}",
                expected,
                mart[field],
            )
    evidence["censoring_and_outcomes"] = {"censor_reasons": dict(censor_reasons)}

    detail_columns = [
        "concept",
        "patient_id",
        "entity_id",
        "field",
        "expected",
        "actual",
        "message",
    ]
    detail_frame = pd.DataFrame(details, columns=detail_columns)
    mismatch_counts = Counter(detail_frame.concept) if not detail_frame.empty else Counter()
    summary_rows = []
    for concept in CONCEPTS:
        mismatches = int(mismatch_counts[concept])
        summary_rows.append(
            {
                "concept": concept,
                "comparisons": int(comparisons[concept]),
                "mismatches": mismatches,
                "status": "PASS" if mismatches == 0 else "FAIL",
                "evidence": json.dumps(evidence.get(concept, {}), sort_keys=True, default=str),
            }
        )
    summary_frame = pd.DataFrame(summary_rows)
    hard_failures = [
        f"{row.concept}: {row.mismatches} row-level mismatch(es)"
        for row in summary_frame.loc[summary_frame.mismatches.gt(0)].itertuples()
    ]
    return detail_frame, summary_frame, hard_failures


def write_release_reconciliation(
    tables: dict[str, pd.DataFrame], config: dict[str, Any], report_dir: str | Path
) -> dict[str, Any]:
    """Write row detail, concept summary, JSON and Markdown release evidence."""
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    detail, summary, hard_failures = reconcile_release_tables(tables, config)
    detail.to_csv(root / "release_reconciliation_detail.csv", index=False)
    summary.to_csv(root / "release_reconciliation_summary.csv", index=False)
    payload = {
        "status": "PASS" if not hard_failures else "FAIL",
        "concepts": len(summary),
        "comparisons": int(summary.comparisons.sum()),
        "total_mismatches": int(summary.mismatches.sum()),
        "hard_failures": hard_failures,
        "summary": summary.to_dict(orient="records"),
        "detail": detail.to_dict(orient="records"),
    }
    (root / "release_reconciliation.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Final Release Reconciliation",
        "",
        f"Status: **{payload['status']}**",
        "",
        f"Row-level mismatches: **{payload['total_mismatches']}**",
        "",
        "| Concept | Comparisons | Mismatches | Status |",
        "|---|---:|---:|---|",
    ]
    lines.extend(
        f"| {row.concept} | {row.comparisons} | {row.mismatches} | {row.status} |"
        for row in summary.itertuples()
    )
    if hard_failures:
        lines.extend(["", "## Hard failures", ""])
        lines.extend(f"- {failure}" for failure in hard_failures)
    (root / "release_reconciliation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def raise_on_release_reconciliation_failure(hard_failures: list[str]) -> None:
    """Stop a release when any independently rebuilt concept differs."""
    if hard_failures:
        raise ValueError("Release reconciliation failed: " + "; ".join(hard_failures))
