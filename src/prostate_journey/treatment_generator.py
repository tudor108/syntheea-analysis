"""Generate normalized treatment episodes, regimens, components and dispensing events."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .market import market_profiles

DRUG_CLASS = {
    "leuprolide": "ADT",
    "degarelix": "ADT",
    "darolutamide": "ARPI",
    "enzalutamide": "ARPI",
    "apalutamide": "ARPI",
    "abiraterone": "ARPI",
    "docetaxel": "chemotherapy",
    "radiotherapy": "procedure",
    "prostatectomy": "procedure",
}


def _mhspc_components(
    regimen_type: str,
    arpi: str,
    start: pd.Timestamp,
    add_on: bool,
    rng: np.random.Generator,
) -> tuple[str, str, list[dict[str, Any]]]:
    adt = str(rng.choice(["leuprolide", "degarelix"], p=[0.78, 0.22]))
    components = [
        {
            "drug_name": adt,
            "drug_class": "ADT",
            "component_role": "backbone",
            "route": "injection",
            "component_start_date": start,
            "dispensing_required_flag": True,
        }
    ]
    strategy = "monotherapy"
    if regimen_type == "adt_arpi_doublet":
        strategy = "planned_combination"
        components.append(
            {
                "drug_name": arpi,
                "drug_class": "ARPI",
                "component_role": "arpi",
                "route": "oral",
                "component_start_date": start,
                "dispensing_required_flag": True,
            }
        )
    elif regimen_type == "adt_chemotherapy_doublet":
        strategy = "planned_combination"
        components.append(
            {
                "drug_name": "docetaxel",
                "drug_class": "chemotherapy",
                "component_role": "chemotherapy",
                "route": "infusion",
                "component_start_date": start,
                "dispensing_required_flag": True,
            }
        )
    elif regimen_type == "adt_arpi_chemotherapy_triplet":
        strategy = "planned_combination"
        components.extend(
            [
                {
                    "drug_name": arpi,
                    "drug_class": "ARPI",
                    "component_role": "arpi",
                    "route": "oral",
                    "component_start_date": start,
                    "dispensing_required_flag": True,
                },
                {
                    "drug_name": "docetaxel",
                    "drug_class": "chemotherapy",
                    "component_role": "chemotherapy",
                    "route": "infusion",
                    "component_start_date": start,
                    "dispensing_required_flag": True,
                },
            ]
        )
    elif add_on:
        regimen_type = "adt_arpi_doublet"
        strategy = "add_on"
        components.append(
            {
                "drug_name": arpi,
                "drug_class": "ARPI",
                "component_role": "arpi",
                "route": "oral",
                "component_start_date": start + pd.Timedelta(days=int(rng.integers(30, 91))),
                "dispensing_required_flag": True,
            }
        )
    return regimen_type, strategy, components


def _prescription_events_for_component(
    component: dict[str, Any],
    episode: dict[str, Any],
    person: pd.Series,
    profile: dict[str, Any],
    adherence_profile: str,
    config: dict,
    rng: np.random.Generator,
) -> list[dict[str, Any]]:
    if not component["dispensing_required_flag"]:
        return []
    if profile["depth"] == "scan" and component["component_role"] not in {
        "arpi",
        "backbone",
    }:
        return []
    prescription = config["prescription"]
    supply_config = prescription["days_supply_by_class"][component["drug_class"]]
    gap_config = prescription["refill_gap_by_profile"][adherence_profile]
    service_date = pd.Timestamp(component["component_start_date"])
    component_end = pd.Timestamp(component["component_end_date"])
    events: list[dict[str, Any]] = []
    patient_id = person.get("patient_id", person.name)
    previous_coverage = pd.NaT
    event_number = 0
    while service_date <= component_end:
        days_supply = int(rng.choice(supply_config["values"], p=supply_config["probabilities"]))
        nominal_coverage = service_date + pd.Timedelta(days=days_supply)
        coverage_base = (
            service_date if pd.isna(previous_coverage) else max(service_date, previous_coverage)
        )
        effective_coverage = min(coverage_base + pd.Timedelta(days=days_supply), component_end)
        refill_gap = (
            0 if pd.isna(previous_coverage) else int((service_date - previous_coverage).days)
        )
        early_late = (
            "initial"
            if event_number == 0
            else "early"
            if refill_gap < 0
            else "on_time"
            if refill_gap <= 5
            else "late"
        )
        detail_missing = bool(
            profile["depth"] == "scan" and rng.random() < profile["prescription_missingness"]
        )
        quantity = (
            1
            if component["route"] in {"injection", "infusion"}
            else int(days_supply * rng.choice([1, 2], p=[0.86, 0.14]))
        )
        events.append(
            {
                "prescription_event_id": f"{component['component_id']}-RX-{event_number:04d}",
                "patient_id": patient_id,
                "market_code": person.market_code,
                "treatment_episode_id": episode["treatment_episode_id"],
                "regimen_id": component["regimen_id"],
                "component_id": component["component_id"],
                "service_date": service_date,
                "product_id": (
                    pd.NA if detail_missing else f"SYN-{component['drug_name'].upper()}"
                ),
                "drug_name": component["drug_name"],
                "drug_class": component["drug_class"],
                "quantity_dispensed": pd.NA if detail_missing else quantity,
                "days_supply": days_supply,
                "nominal_covered_until_date": nominal_coverage,
                "covered_until_date": effective_coverage,
                "event_type": "initial_fill" if event_number == 0 else "refill",
                "refill_gap_days": refill_gap,
                "refill_timing": early_late,
                "adherence_profile": adherence_profile,
                "detail_level": profile["depth"],
                "synthetic_event_flag": True,
            }
        )
        previous_coverage = effective_coverage
        if effective_coverage >= component_end:
            break
        sampled_gap = (
            0
            if component["drug_class"] == "chemotherapy"
            else int(
                np.clip(
                    rng.normal(gap_config["mean"], gap_config["sd"]),
                    gap_config["minimum"],
                    gap_config["maximum"],
                )
            )
        )
        service_date = max(
            service_date + pd.Timedelta(days=7),
            effective_coverage + pd.Timedelta(days=sampled_gap),
        )
        event_number += 1
    return events


def generate_treatment_model(
    patient: pd.DataFrame,
    eligibility: pd.DataFrame,
    referral: pd.DataFrame,
    active_surveillance: pd.DataFrame,
    care_team: pd.DataFrame,
    observation: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build treatment episode, regimen, component and prescription-event tables."""
    eligibility_index = eligibility.set_index("patient_id")
    team_index = care_team.set_index("patient_id")
    observation_index = observation.set_index("patient_id")
    referral_completed = (
        referral.groupby("patient_id").referral_status.apply(
            lambda values: values.eq("completed").any()
        )
        if not referral.empty
        else pd.Series(dtype="bool")
    )
    referral_completion_date = (
        referral.loc[referral.referral_status.eq("completed")]
        .groupby("patient_id")
        .completion_date.min()
        if not referral.empty
        else pd.Series(dtype="datetime64[ns]")
    )
    as_index = (
        active_surveillance.set_index("patient_id")
        if not active_surveillance.empty
        else pd.DataFrame()
    )
    profiles = market_profiles(config)
    treatment_config = config["treatment"]
    episodes: list[dict[str, Any]] = []
    regimens: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    treatment_referrals: list[dict[str, Any]] = []

    def create_episode(
        person: pd.Series,
        start: pd.Timestamp,
        end: pd.Timestamp,
        line: int,
        transition_type: str,
        previous_episode_id: Any,
        episode_reason: str,
        regimen_type: str,
        component_specs: list[dict[str, Any]],
        combination_strategy: str,
        provider_id: str,
        status: str,
        discontinuation_date: Any = pd.NaT,
        discontinuation_reason: Any = pd.NA,
        switch_date: Any = pd.NaT,
        restart_date: Any = pd.NaT,
    ) -> tuple[str, str]:
        component_specs = [
            spec for spec in component_specs if pd.Timestamp(spec["component_start_date"]) <= end
        ]
        if episode_reason == "mhspc_eligible":
            classes = {spec["drug_class"] for spec in component_specs}
            has_arpi = "ARPI" in classes
            has_chemotherapy = "chemotherapy" in classes
            regimen_type = (
                "adt_arpi_chemotherapy_triplet"
                if has_arpi and has_chemotherapy
                else "adt_arpi_doublet"
                if has_arpi
                else "adt_chemotherapy_doublet"
                if has_chemotherapy
                else "adt_monotherapy"
            )
            if len(component_specs) == 1:
                combination_strategy = "monotherapy"
            elif any(
                pd.Timestamp(spec["component_start_date"]) > start for spec in component_specs
            ):
                combination_strategy = "add_on"
            else:
                combination_strategy = "planned_combination"
        episode_id = f"TXE-{person.market_code}-{len(episodes):08d}"
        regimen_id = f"REG-{person.market_code}-{len(regimens):08d}"
        is_mhspc = episode_reason == "mhspc_eligible"
        intensified = bool(
            is_mhspc
            and any(spec["drug_class"] in {"ARPI", "chemotherapy"} for spec in component_specs)
        )
        episodes.append(
            {
                "treatment_episode_id": episode_id,
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "treatment_line": line,
                "treatment_start_date": start,
                "treatment_end_date": end,
                "treatment_status": status,
                "treatment_intent": "disease_control" if is_mhspc else "localized_definitive",
                "episode_reason": episode_reason,
                "transition_type": transition_type,
                "previous_episode_id": previous_episode_id,
                "prescribing_provider_id": provider_id,
                "discontinuation_flag": pd.notna(discontinuation_date),
                "discontinuation_date": discontinuation_date,
                "discontinuation_reason": discontinuation_reason,
                "switch_flag": pd.notna(switch_date),
                "switch_date": switch_date,
                "restart_flag": pd.notna(restart_date),
                "restart_date": restart_date,
                "temporary_gap_flag": transition_type == "restart",
                "tracking_component_id": pd.NA,
                "prescription_event_count": 0,
                "max_refill_gap_days": 0,
                "synthetic_event_flag": True,
            }
        )
        regimens.append(
            {
                "regimen_id": regimen_id,
                "treatment_episode_id": episode_id,
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "regimen_name": regimen_type,
                "regimen_type": (
                    "triplet"
                    if "triplet" in regimen_type
                    else "doublet"
                    if "doublet" in regimen_type
                    else "monotherapy"
                ),
                "combination_strategy": combination_strategy,
                "regimen_start_date": start,
                "regimen_end_date": end,
                "regimen_status": status,
                "intensification_flag": intensified,
                "guideline_concordance_classification": (
                    "SCENARIO_SUPPORTED" if intensified else "NOT_ASSESSED"
                ),
                "guideline_rule_version": treatment_config["guideline_rule_version"],
                "synthetic_event_flag": True,
            }
        )
        tracking_component_id = pd.NA
        for component_spec in component_specs:
            component_id = f"CMP-{person.market_code}-{len(components):09d}"
            component_start = max(start, pd.Timestamp(component_spec["component_start_date"]))
            component_end = end
            planned_cycle_count: int | Any = pd.NA
            cycle_length_days: int | Any = pd.NA
            if component_spec["drug_class"] == "chemotherapy":
                chemotherapy = treatment_config["chemotherapy"]
                planned_cycle_count = int(chemotherapy["planned_cycles"])
                cycle_length_days = int(chemotherapy["cycle_length_days"])
                component_end = min(
                    end,
                    component_start + pd.Timedelta(days=planned_cycle_count * cycle_length_days),
                )
            elif component_spec["drug_class"] == "procedure":
                component_end = component_start
            component = {
                "component_id": component_id,
                "regimen_id": regimen_id,
                "treatment_episode_id": episode_id,
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                **component_spec,
                "component_start_date": component_start,
                "component_end_date": component_end,
                "component_status": "completed" if component_end < end else status,
                "planned_cycle_count": planned_cycle_count,
                "cycle_length_days": cycle_length_days,
                "dispensing_detail_available_flag": bool(
                    component_spec["dispensing_required_flag"]
                    and (
                        profiles[person.market_code]["depth"] == "deep"
                        or component_spec["component_role"] in {"arpi", "backbone"}
                    )
                ),
                "synthetic_event_flag": True,
            }
            components.append(component)
            if component_spec["component_role"] == "arpi" and combination_strategy != "add_on":
                tracking_component_id = component_id
            elif pd.isna(tracking_component_id) and component_spec["component_role"] == "backbone":
                tracking_component_id = component_id
        episodes[-1]["tracking_component_id"] = tracking_component_id
        return episode_id, regimen_id

    for _, person in patient.iterrows():
        eligible = eligibility_index.loc[person.patient_id]
        team = team_index.loc[person.patient_id]
        patient_observation = observation_index.loc[person.patient_id]
        censor = pd.Timestamp(patient_observation.censor_date)
        profile = profiles[person.market_code]
        as_record = as_index.loc[person.patient_id] if person.patient_id in as_index.index else None
        as_transition = bool(
            as_record is not None
            and as_record.transition_to_treatment_flag
            and pd.notna(as_record.planned_treatment_start_date)
        )
        if eligible.eligibility_flag:
            probability = profile["initiation_probability_90d"]
            probability -= treatment_config["high_comorbidity_initiation_penalty"] * float(
                person.comorbidity_score >= 4
            )
            probability -= treatment_config["low_access_initiation_penalty"] * float(
                person.access_index < 0.4
            )
            probability += treatment_config["completed_referral_initiation_increment"] * float(
                referral_completed.get(person.patient_id, False)
            )
            if rng.random() >= np.clip(probability, 0.08, 0.96):
                continue
            delay = max(
                1,
                int(
                    rng.normal(
                        profile["initiation_delay_mean_days"],
                        profile["initiation_delay_sd_days"],
                    )
                ),
            )
            start = pd.Timestamp(eligible.eligibility_date) + pd.Timedelta(days=delay)
            episode_reason = "mhspc_eligible"
        elif as_transition:
            start = pd.Timestamp(as_record.planned_treatment_start_date)
            episode_reason = "active_surveillance_exit"
        else:
            continue
        completed_referral = bool(referral_completed.get(person.patient_id, False))
        if completed_referral:
            start = max(
                start,
                pd.Timestamp(referral_completion_date.loc[person.patient_id]),
            )
        if start >= censor:
            continue

        provider_id = (
            team.oncology_provider_id if completed_referral else team.initial_urology_provider_id
        )
        duration_cfg = treatment_config["duration_days"]
        duration = int(
            np.clip(
                rng.normal(duration_cfg["mean"], duration_cfg["sd"]),
                duration_cfg["minimum"],
                duration_cfg["maximum"],
            )
        )
        planned_end = min(start + pd.Timedelta(days=duration), censor)
        if episode_reason == "active_surveillance_exit":
            procedure = str(rng.choice(["radiotherapy", "prostatectomy"], p=[0.62, 0.38]))
            provider_id = (
                team.radiation_provider_id
                if procedure == "radiotherapy"
                else team.initial_urology_provider_id
            )
            if procedure == "radiotherapy":
                treatment_referrals.append(
                    {
                        "referral_id": (
                            f"TREF-{person.market_code}-{len(treatment_referrals):08d}"
                        ),
                        "patient_id": person.patient_id,
                        "market_code": person.market_code,
                        "source_provider_id": team.initial_urology_provider_id,
                        "source_organization_id": team.initial_urology_organization_id,
                        "source_specialty": "urology",
                        "destination_provider_id": team.radiation_provider_id,
                        "destination_organization_id": team.radiation_organization_id,
                        "destination_specialty": "radiation_oncology",
                        "referral_date": pd.Timestamp(as_record.as_exit_date),
                        "completion_date": start - pd.Timedelta(days=1),
                        "referral_status": "completed",
                        "referral_reason": "active_surveillance_exit_radiotherapy",
                        "decision_owner_specialty": "radiation_oncology",
                        "detail_level": profile["depth"],
                        "synthetic_event_flag": True,
                    }
                )
            regimen_type = f"localized_{procedure}"
            strategy = "monotherapy"
            component_specs = [
                {
                    "drug_name": procedure,
                    "drug_class": "procedure",
                    "component_role": "definitive_local_therapy",
                    "route": "procedure",
                    "component_start_date": start,
                    "dispensing_required_flag": False,
                }
            ]
        else:
            regimen_distribution = treatment_config["regimen_distribution"]
            if not completed_referral:
                regimen_distribution = {
                    name: probability
                    for name, probability in regimen_distribution.items()
                    if "chemotherapy" not in name
                }
                total_probability = sum(regimen_distribution.values())
                regimen_distribution = {
                    name: probability / total_probability
                    for name, probability in regimen_distribution.items()
                }
            regimen_type = str(
                rng.choice(list(regimen_distribution), p=list(regimen_distribution.values()))
            )
            arpi_distribution = treatment_config["arpi_distribution"]
            arpi = str(rng.choice(list(arpi_distribution), p=list(arpi_distribution.values())))
            add_on = bool(
                regimen_type == "adt_monotherapy"
                and rng.random() < treatment_config["add_on_probability"]
            )
            regimen_type, strategy, component_specs = _mhspc_components(
                regimen_type, arpi, start, add_on, rng
            )
            if any(component["drug_class"] == "chemotherapy" for component in component_specs):
                provider_id = team.oncology_provider_id

        transition_type = "initial"
        censor_terminal_status = (
            "ongoing" if patient_observation.censor_reason == "administrative_end" else "censored"
        )
        status = censor_terminal_status if planned_end == censor else "completed"
        transition_date = pd.NaT
        transition_choice = "none"
        available_duration = (planned_end - start).days
        if episode_reason == "mhspc_eligible" and available_duration > 210:
            switch_p = treatment_config["switch_probability"]
            restart_p = treatment_config["restart_probability"]
            discontinue_p = treatment_config["discontinuation_probability"]
            transition_choice = str(
                rng.choice(
                    ["none", "switch", "restart", "discontinue"],
                    p=[
                        1 - switch_p - restart_p - discontinue_p,
                        switch_p,
                        restart_p,
                        discontinue_p,
                    ],
                )
            )
            if transition_choice != "none":
                transition_date = start + pd.Timedelta(
                    days=int(
                        rng.integers(
                            treatment_config["transition_min_days"], available_duration - 30
                        )
                    )
                )

        initial_end = transition_date if pd.notna(transition_date) else planned_end
        initial_status = {
            "switch": "switched",
            "restart": "discontinued",
            "discontinue": "discontinued",
        }.get(transition_choice, status)
        discontinuation_date = (
            transition_date if transition_choice in {"restart", "discontinue"} else pd.NaT
        )
        restart_date = pd.NaT
        if transition_choice == "restart":
            restart_candidate = transition_date + pd.Timedelta(days=int(rng.integers(45, 121)))
            # A restart is a clinical event, so it is recorded only when observed.
            # A gap that extends beyond censoring remains an observed discontinuation.
            if restart_candidate < censor:
                restart_date = restart_candidate
        initial_episode_id, _ = create_episode(
            person,
            start,
            initial_end,
            1,
            transition_type,
            pd.NA,
            episode_reason,
            regimen_type,
            component_specs,
            strategy,
            provider_id,
            initial_status,
            discontinuation_date=discontinuation_date,
            discontinuation_reason=(
                "temporary_gap"
                if transition_choice == "restart"
                else "synthetic_tolerability_or_choice"
                if transition_choice == "discontinue"
                else pd.NA
            ),
            switch_date=transition_date if transition_choice == "switch" else pd.NaT,
            restart_date=restart_date,
        )

        if transition_choice == "switch":
            second_start = transition_date + pd.Timedelta(days=1)
            if second_start < censor:
                old_arpis = {
                    spec["drug_name"] for spec in component_specs if spec["drug_class"] == "ARPI"
                }
                alternatives = [
                    drug for drug in treatment_config["arpi_distribution"] if drug not in old_arpis
                ]
                new_arpi = str(rng.choice(alternatives))
                second_type, second_strategy, second_components = _mhspc_components(
                    "adt_arpi_doublet", new_arpi, second_start, False, rng
                )
                create_episode(
                    person,
                    second_start,
                    censor,
                    2,
                    "switch",
                    initial_episode_id,
                    episode_reason,
                    second_type,
                    second_components,
                    second_strategy,
                    provider_id,
                    censor_terminal_status,
                )
        elif transition_choice == "restart":
            if pd.notna(restart_date) and restart_date < censor:
                restarted_components = [
                    {**spec, "component_start_date": restart_date} for spec in component_specs
                ]
                create_episode(
                    person,
                    restart_date,
                    censor,
                    2,
                    "restart",
                    initial_episode_id,
                    episode_reason,
                    regimen_type,
                    restarted_components,
                    strategy,
                    provider_id,
                    censor_terminal_status,
                )

    episode_frame = pd.DataFrame(episodes)
    regimen_frame = pd.DataFrame(regimens)
    component_frame = pd.DataFrame(components)
    prescription_events: list[dict[str, Any]] = []
    if not component_frame.empty:
        episode_lookup = {row["treatment_episode_id"]: row for row in episodes}
        patient_lookup = patient.set_index("patient_id")
        for component in components:
            episode = episode_lookup[component["treatment_episode_id"]]
            person = patient_lookup.loc[component["patient_id"]]
            adherence_distribution = config["prescription"]["adherence_profiles"]
            adherence = str(
                rng.choice(list(adherence_distribution), p=list(adherence_distribution.values()))
            )
            if person.access_index < 0.35 and adherence == "high" and rng.random() < 0.55:
                adherence = "variable"
            prescription_events.extend(
                _prescription_events_for_component(
                    component,
                    episode,
                    person,
                    profiles[person.market_code],
                    adherence,
                    config,
                    rng,
                )
            )
    event_columns = [
        "prescription_event_id",
        "patient_id",
        "market_code",
        "treatment_episode_id",
        "regimen_id",
        "component_id",
        "service_date",
        "product_id",
        "drug_name",
        "drug_class",
        "quantity_dispensed",
        "days_supply",
        "nominal_covered_until_date",
        "covered_until_date",
        "event_type",
        "refill_gap_days",
        "refill_timing",
        "adherence_profile",
        "detail_level",
        "synthetic_event_flag",
    ]
    event_frame = pd.DataFrame(prescription_events, columns=event_columns)
    if not episode_frame.empty:
        event_summary = (
            event_frame.groupby("treatment_episode_id").agg(
                prescription_event_count=("prescription_event_id", "size"),
                max_refill_gap_days=("refill_gap_days", "max"),
            )
            if not event_frame.empty
            else pd.DataFrame()
        )
        episode_frame["prescription_event_count"] = (
            episode_frame.treatment_episode_id.map(
                event_summary.prescription_event_count
                if not event_summary.empty
                else pd.Series(dtype="int64")
            )
            .fillna(0)
            .astype("int64")
        )
        episode_frame["max_refill_gap_days"] = (
            episode_frame.treatment_episode_id.map(
                event_summary.max_refill_gap_days
                if not event_summary.empty
                else pd.Series(dtype="int64")
            )
            .fillna(0)
            .astype("int64")
        )
    treatment_referral_frame = pd.DataFrame(treatment_referrals, columns=referral.columns)
    return (
        episode_frame,
        regimen_frame,
        component_frame,
        event_frame,
        treatment_referral_frame,
    )


def generate_treatments_with_events(*args: Any, **kwargs: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compatibility wrapper returning treatment episodes and prescription events."""
    episodes, _, _, events, _ = generate_treatment_model(*args, **kwargs)
    return episodes, events
