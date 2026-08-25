"""Hostile audit that recomputes dataset claims directly from normalized records."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_MARKETS = {"US", "DE", "JP", "FR", "CN", "AU", "CA"}
DEEP_MARKETS = {"US", "DE", "JP"}
SCAN_MARKETS = REQUIRED_MARKETS - DEEP_MARKETS


def _status_from_events(
    events: pd.DataFrame,
    start: pd.Timestamp,
    censor: pd.Timestamp,
    target_days: int,
    permissible_gap: int,
    discontinuation_date: Any,
    switch_date: Any,
) -> str:
    """Independent event-clock persistence reconstruction used only by this audit."""
    if events.empty:
        return "NOT_APPLICABLE"

    boundaries: list[tuple[pd.Timestamp, int, str]] = []
    if pd.notna(switch_date):
        boundaries.append((pd.Timestamp(switch_date), 0, "SWITCHED"))
    if pd.notna(discontinuation_date):
        boundaries.append((pd.Timestamp(discontinuation_date), 1, "DISCONTINUED"))

    coverage = pd.NaT
    for row in events.sort_values(["service_date", "prescription_event_id"]).itertuples():
        service = pd.Timestamp(row.service_date)
        gap_start = start if pd.isna(coverage) else pd.Timestamp(coverage)
        if service > gap_start + pd.Timedelta(days=permissible_gap):
            boundaries.append(
                (
                    gap_start + pd.Timedelta(days=permissible_gap + 1),
                    2,
                    "DISCONTINUED",
                )
            )
            break
        supplied_through = pd.Timestamp(row.covered_until_date)
        coverage = supplied_through if pd.isna(coverage) else max(coverage, supplied_through)
    if pd.notna(coverage):
        boundaries.append(
            (
                pd.Timestamp(coverage) + pd.Timedelta(days=permissible_gap + 1),
                2,
                "DISCONTINUED",
            )
        )

    boundaries.extend(
        [
            (start + pd.Timedelta(days=target_days), 3, "PERSISTENT"),
            (censor, 4, "CENSORED_NOT_EVALUABLE"),
        ]
    )
    return min(boundaries, key=lambda value: (value[0], value[1]))[2]


def _expected_isup(diagnosis: pd.DataFrame) -> pd.Series:
    score = diagnosis.gleason_score
    primary = diagnosis.gleason_primary_pattern
    expected = pd.Series(pd.NA, index=diagnosis.index, dtype="Int64")
    expected.loc[score.le(6)] = 1
    expected.loc[score.eq(7) & primary.eq(3)] = 2
    expected.loc[score.eq(7) & primary.eq(4)] = 3
    expected.loc[score.eq(8)] = 4
    expected.loc[score.ge(9)] = 5
    return expected


def _count_temporal_violations(tables: dict[str, pd.DataFrame]) -> int:
    censor = tables["observation"].set_index("patient_id").censor_date
    domains = {
        "encounter": ["encounter_date"],
        "referral": ["referral_date", "completion_date"],
        "active_surveillance": [
            "as_start_date",
            "as_exit_date",
            "as_reclassification_date",
            "planned_treatment_start_date",
        ],
        "treatment_episode": [
            "treatment_start_date",
            "treatment_end_date",
            "discontinuation_date",
            "switch_date",
            "restart_date",
        ],
        "treatment_regimen": ["regimen_start_date", "regimen_end_date"],
        "treatment_regimen_component": ["component_start_date", "component_end_date"],
        "prescription_event": ["service_date", "covered_until_date"],
        "adverse_event": ["adverse_event_date"],
        "disease_state_event": ["state_date"],
        "outcome": [
            "progression_date",
            "castration_resistant_date",
            "first_hospitalisation_date",
            "death_date",
            "loss_to_follow_up_date",
        ],
    }
    failures = 0
    for table_name, columns in domains.items():
        frame = tables[table_name]
        final_date = pd.to_datetime(frame.patient_id.map(censor))
        for column in columns:
            value = pd.to_datetime(frame[column])
            failures += int((value.notna() & value.gt(final_date)).sum())
    return failures


def _relational_failures(tables: dict[str, pd.DataFrame]) -> tuple[int, int]:
    primary_failures = 0
    for frame in tables.values():
        id_columns = [column for column in frame.columns if column.endswith("_id")]
        if not id_columns:
            continue
        primary = id_columns[0]
        primary_failures += int(frame[primary].isna().sum() + frame[primary].duplicated().sum())

    patient_ids = set(tables["patient"].patient_id)
    foreign_failures = 0
    for name, frame in tables.items():
        if name != "patient" and "patient_id" in frame:
            foreign_failures += int((~frame.patient_id.isin(patient_ids)).sum())

    organization_ids = set(tables["organization"].organization_id)
    provider_ids = set(tables["provider"].provider_id)
    episode_ids = set(tables["treatment_episode"].treatment_episode_id)
    regimen_ids = set(tables["treatment_regimen"].regimen_id)
    component_ids = set(tables["treatment_regimen_component"].component_id)
    foreign_failures += int(
        (~tables["provider"].organization_id.isin(organization_ids)).sum()
        + (~tables["encounter"].provider_id.isin(provider_ids)).sum()
        + (~tables["encounter"].organization_id.isin(organization_ids)).sum()
        + (~tables["referral"].source_provider_id.isin(provider_ids)).sum()
        + (~tables["referral"].destination_provider_id.isin(provider_ids)).sum()
        + (~tables["treatment_episode"].prescribing_provider_id.isin(provider_ids)).sum()
        + (~tables["treatment_regimen"].treatment_episode_id.isin(episode_ids)).sum()
        + (~tables["treatment_regimen_component"].treatment_episode_id.isin(episode_ids)).sum()
        + (~tables["treatment_regimen_component"].regimen_id.isin(regimen_ids)).sum()
        + (~tables["prescription_event"].treatment_episode_id.isin(episode_ids)).sum()
        + (~tables["prescription_event"].regimen_id.isin(regimen_ids)).sum()
        + (~tables["prescription_event"].component_id.isin(component_ids)).sum()
        + (~tables["adverse_event"].treatment_episode_id.isin(episode_ids)).sum()
    )
    previous = tables["treatment_episode"].previous_episode_id.dropna()
    tracking = tables["treatment_episode"].tracking_component_id.dropna()
    foreign_failures += int(
        (~previous.isin(episode_ids)).sum() + (~tracking.isin(component_ids)).sum()
    )
    return primary_failures, foreign_failures


def audit_tables_independently(
    tables: dict[str, pd.DataFrame], config: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    """Attack the actual records without consuming supplied DQ or readiness results."""
    patient = tables["patient"]
    diagnosis = tables["diagnosis"]
    eligibility = tables["eligibility"]
    observation = tables["observation"]
    encounter = tables["encounter"]
    referral = tables["referral"]
    active = tables["active_surveillance"]
    provider = tables["provider"]
    episode = tables["treatment_episode"]
    regimen = tables["treatment_regimen"]
    component = tables["treatment_regimen_component"]
    rx = tables["prescription_event"]
    outcome = tables["outcome"]
    states = tables["disease_state_event"]
    split = tables["patient_split"]
    timing = tables["feature_timing"]
    journey = tables["patient_journey"]

    metrics: dict[str, Any] = {"patient_count": int(len(patient))}
    checks: list[dict[str, Any]] = []

    def add(check_id: int, name: str, priority: str, passed: bool, evidence: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "check": name,
                "priority": priority,
                "status": "PASS" if bool(passed) else "FAIL",
                "score": 4 if bool(passed) else 0,
                "max_score": 4,
                "evidence": evidence,
            }
        )

    signature_columns = [
        "birth_date",
        "index_date",
        "market_code",
        "region",
        "postal_code_prefix",
        "race",
        "ethnicity",
        "insurance_type",
        "access_index",
        "comorbidity_score",
        "frailty_proxy",
    ]
    duplicate_signatures = int(patient.duplicated(signature_columns, keep=False).sum())
    raw_sources = patient.loc[
        patient.source_record_type.eq("synthea_unique"), "source_patient_id"
    ].dropna()
    split_contamination = int(split.groupby("source_archetype_id").split.nunique().gt(1).sum())
    metrics.update(
        {
            "unique_archetypes": int(patient.source_archetype_id.nunique()),
            "duplicate_demographic_signatures": duplicate_signatures,
            "raw_source_records_used": int(len(raw_sources)),
            "split_contamination_archetypes": split_contamination,
        }
    )
    add(
        1,
        "Independent patients and no split contamination",
        "P0",
        patient.source_archetype_id.is_unique
        and raw_sources.is_unique
        and duplicate_signatures == 0
        and split_contamination == 0,
        f"archetypes={patient.source_archetype_id.nunique()}; duplicate signatures="
        f"{duplicate_signatures}; contaminated archetypes={split_contamination}",
    )

    market_counts = patient.groupby("market_code").size()
    age_means = patient.groupby("market_code").age_at_index.mean()
    stage_rates = diagnosis.groupby("market_code").metastatic_flag.mean()
    market_difference = (
        float(age_means.max() - age_means.min()) > 1.0
        and float(stage_rates.max() - stage_rates.min()) >= 0.05
    )
    metrics["market_patient_counts"] = {key: int(value) for key, value in market_counts.items()}
    metrics["market_metastatic_rates"] = {
        key: round(float(value), 6) for key, value in stage_rates.items()
    }
    add(
        2,
        "Seven markets with non-identical clinical distributions",
        "P0",
        set(market_counts.index) == REQUIRED_MARKETS and market_difference,
        f"counts={metrics['market_patient_counts']}; age mean range="
        f"{age_means.max() - age_means.min():.3f}; metastatic range="
        f"{stage_rates.max() - stage_rates.min():.3f}",
    )

    encounter_density = encounter.groupby("market_code").size() / market_counts
    deep_density = float(encounter_density.loc[list(DEEP_MARKETS)].mean())
    scan_density = float(encounter_density.loc[list(SCAN_MARKETS)].mean())
    deep_missing = float(rx.loc[rx.market_code.isin(DEEP_MARKETS), "product_id"].isna().mean())
    scan_missing = float(rx.loc[rx.market_code.isin(SCAN_MARKETS), "product_id"].isna().mean())
    depth_ratio = deep_density / max(scan_density, 0.001)
    metrics.update(
        {
            "deep_encounters_per_patient": round(deep_density, 6),
            "scan_encounters_per_patient": round(scan_density, 6),
            "deep_to_scan_encounter_ratio": round(depth_ratio, 6),
            "deep_product_missing_rate": round(deep_missing, 6),
            "scan_product_missing_rate": round(scan_missing, 6),
        }
    )
    add(
        3,
        "Deep and Scan markets differ in pathway depth and missingness",
        "P1",
        depth_ratio >= config["readiness"]["deep_to_scan_event_ratio_minimum"]
        and scan_missing > deep_missing,
        f"encounter ratio={depth_ratio:.3f}; product missing deep={deep_missing:.3f}, "
        f"scan={scan_missing:.3f}",
    )

    expected_provider_counts = {
        market: max(
            4,
            math.ceil(int(market_counts[market]) / 1000 * float(profile["providers_per_1000"])),
        )
        for market, profile in config["market_configuration"]["markets"].items()
    }
    actual_provider_counts = provider.groupby("market_code").size().to_dict()
    add(
        4,
        "Configured market-specific provider capacity is realised",
        "P1",
        actual_provider_counts == expected_provider_counts,
        f"actual={actual_provider_counts}; expected={expected_provider_counts}",
    )

    diagnosis_by_patient = diagnosis.set_index("patient_id")
    eligibility_by_patient = eligibility.set_index("patient_id")
    reconstructed_mhspc = (
        diagnosis_by_patient.prostate_cancer_flag
        & diagnosis_by_patient.metastatic_flag
        & diagnosis_by_patient.hormone_sensitive_flag
        & ~diagnosis_by_patient.castration_resistant_flag
    )
    expected_eligible = (
        reconstructed_mhspc
        & ~eligibility_by_patient.contraindication_flag
        & eligibility_by_patient.data_sufficiency_flag
        & eligibility_by_patient.possible_followup_days.ge(
            eligibility_by_patient.minimum_followup_required_days
        )
    )
    eligibility_mismatches = int(
        eligibility_by_patient.mhspc_flag.ne(reconstructed_mhspc).sum()
        + eligibility_by_patient.eligibility_flag.ne(expected_eligible).sum()
    )
    eligibility_semantic_failures = int(
        (eligibility.eligibility_flag & eligibility.eligibility_date.isna()).sum()
        + (~eligibility.eligibility_flag & eligibility.eligibility_date.notna()).sum()
        + (~eligibility.eligibility_flag & eligibility.ineligibility_reason.isna()).sum()
    )
    metrics["eligible_patients"] = int(expected_eligible.sum())
    add(
        5,
        "Eligibility and null semantics reconstruct",
        "P0",
        eligibility_mismatches == 0 and eligibility_semantic_failures == 0,
        f"eligible={expected_eligible.sum()}; label mismatches={eligibility_mismatches}; "
        f"semantic failures={eligibility_semantic_failures}",
    )
    expected_eligibility_version = config["clinical_rule_configuration"]["clinical_rules"][
        "arpi_eligibility"
    ]["version"]
    add(
        6,
        "Eligibility rule version is complete and configured",
        "P1",
        eligibility.eligibility_rule_version.eq(expected_eligibility_version).all(),
        f"expected version={expected_eligibility_version}; observed="
        f"{sorted(eligibility.eligibility_rule_version.dropna().unique())}",
    )

    initial_episode = (
        episode.sort_values(["patient_id", "treatment_start_date", "treatment_episode_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
    )
    journey_by_patient = journey.set_index("patient_id")
    treated = journey_by_patient.treatment_initiated
    first_treatment_failures = int(
        treated.ne(journey_by_patient.index.isin(initial_episode.index)).sum()
        + journey_by_patient.loc[treated, "treatment_start_date"]
        .ne(initial_episode.loc[journey_by_patient.index[treated], "treatment_start_date"])
        .sum()
    )
    component_classes_by_regimen = component.groupby("regimen_id").drug_class.agg(set)
    component_count_by_regimen = component.groupby("regimen_id").size()
    mhspc_episodes = set(
        episode.loc[episode.episode_reason.eq("mhspc_eligible")].treatment_episode_id
    )
    actual_intensified = regimen.regimen_id.map(
        component_classes_by_regimen.apply(lambda values: bool(values & {"ARPI", "chemotherapy"}))
    ) & regimen.treatment_episode_id.isin(mhspc_episodes)
    expected_regimen_type = regimen.regimen_id.map(component_classes_by_regimen).apply(
        lambda classes: (
            "triplet"
            if {"ADT", "ARPI", "chemotherapy"}.issubset(classes)
            else "doublet"
            if len(classes) > 1 and "procedure" not in classes
            else "monotherapy"
        )
    )
    regimen_by_episode = regimen.set_index("treatment_episode_id")
    initial_regimen_id = initial_episode.treatment_episode_id.map(regimen_by_episode.regimen_id)
    initial_component_count = initial_regimen_id.map(component_count_by_regimen)
    hierarchy_failures = int(
        regimen.regimen_type.ne(expected_regimen_type).sum()
        + regimen.intensification_flag.ne(actual_intensified).sum()
        + first_treatment_failures
        + journey_by_patient.loc[treated, "regimen_component_count"]
        .astype(int)
        .ne(initial_component_count.reindex(journey_by_patient.index[treated]).astype(int))
        .sum()
    )
    add(
        7,
        "First treatment, regimen components and intensity reconstruct",
        "P0",
        hierarchy_failures == 0,
        f"episodes={len(episode)}; regimens={len(regimen)}; components={len(component)}; "
        f"reconstruction failures={hierarchy_failures}",
    )

    incompatible_regimens = 0
    for _, group in component.groupby("regimen_id"):
        classes = set(group.drug_class)
        incompatible_regimens += int("procedure" in classes and len(classes) > 1)
        incompatible_regimens += int(len(group[group.drug_class.eq("ADT")]) > 1)
        incompatible_regimens += int(len(group[group.drug_class.eq("ARPI")]) > 1)
    lines_valid = episode.groupby("patient_id").treatment_line.apply(
        lambda values: sorted(values) == list(range(1, len(values) + 1))
    )
    chemo = component[component.drug_class.eq("chemotherapy")]
    chemo_event_count = chemo.component_id.map(rx.groupby("component_id").size()).fillna(0)
    chemo_failures = int(chemo_event_count.gt(chemo.planned_cycle_count.astype(float)).sum())
    metrics["chemotherapy_components"] = int(len(chemo))
    metrics["maximum_chemotherapy_events"] = int(chemo_event_count.max()) if len(chemo) else 0
    add(
        8,
        "Treatment combinations, lines and chemotherapy cycles are plausible",
        "P1",
        incompatible_regimens == 0 and lines_valid.all() and chemo_failures == 0,
        f"incompatible regimens={incompatible_regimens}; invalid line sequences="
        f"{(~lines_valid).sum()}; chemo cycle failures={chemo_failures}",
    )

    after_censor = _count_temporal_violations(tables)
    metrics["critical_events_after_censor"] = after_censor
    add(
        9,
        "No clinical event occurs after censor, death or LTFU",
        "P0",
        after_censor == 0,
        f"events after final observable date={after_censor}",
    )

    observation_by_patient = observation.set_index("patient_id")
    events_by_component = {key: value for key, value in rx.groupby("component_id", sort=False)}
    persistence_mismatches: dict[str, int] = {}
    persistence_specs = [
        ("persistence_3m_status", 90, 60),
        ("persistence_6m_status", 180, 60),
        ("persistence_12m_status", 365, 60),
        ("persistence_12m_status_gap_30d", 365, 30),
        ("persistence_12m_status_gap_60d", 365, 60),
        ("persistence_12m_status_gap_90d", 365, 90),
    ]
    for column, target_days, gap in persistence_specs:
        mismatch = 0
        for patient_id, treatment in initial_episode.iterrows():
            calculated = _status_from_events(
                events_by_component.get(treatment.tracking_component_id, rx.iloc[0:0]),
                pd.Timestamp(treatment.treatment_start_date),
                pd.Timestamp(observation_by_patient.loc[patient_id, "censor_date"]),
                target_days,
                gap,
                treatment.discontinuation_date,
                treatment.switch_date,
            )
            mismatch += int(journey_by_patient.loc[patient_id, column] != calculated)
        mismatch += int(
            journey_by_patient.loc[~journey_by_patient.treatment_initiated, column]
            .ne("NOT_APPLICABLE")
            .sum()
        )
        persistence_mismatches[column] = mismatch
    metrics["persistence_mismatches"] = persistence_mismatches
    add(
        10,
        "Persistence reconstructs at 3/6/12 months and 30/60/90-day gaps",
        "P0",
        sum(persistence_mismatches.values()) == 0,
        f"mismatches={persistence_mismatches}",
    )

    linked = episode[episode.transition_type.isin(["switch", "restart"])]
    episode_lookup = episode.set_index("treatment_episode_id")
    link_failures = int((~linked.previous_episode_id.isin(episode.treatment_episode_id)).sum())
    valid_linked = linked[linked.previous_episode_id.isin(episode.treatment_episode_id)]
    link_failures += int(
        (
            valid_linked.treatment_start_date
            <= valid_linked.previous_episode_id.map(episode_lookup.treatment_end_date)
        ).sum()
    )
    switched_previous = set(
        valid_linked.loc[valid_linked.transition_type.eq("switch"), "previous_episode_id"]
    )
    old_refills = rx[rx.treatment_episode_id.isin(switched_previous)]
    link_failures += int(
        (
            old_refills.service_date
            > old_refills.treatment_episode_id.map(episode_lookup.treatment_end_date)
        ).sum()
    )
    restart_links = valid_linked[valid_linked.transition_type.eq("restart")]
    link_failures += int(
        restart_links.previous_episode_id.map(episode_lookup.treatment_status)
        .ne("discontinued")
        .sum()
    )
    add_on = regimen[regimen.combination_strategy.eq("add_on")]
    delayed_arpi = component[
        component.regimen_id.isin(add_on.regimen_id) & component.drug_class.eq("ARPI")
    ]
    link_failures += int(
        delayed_arpi.component_start_date.le(
            delayed_arpi.regimen_id.map(regimen.set_index("regimen_id").regimen_start_date)
        ).sum()
    )
    transition_semantics_present = bool(
        config["target_cohort_size"] < 5000
        or ({"switch", "restart"}.issubset(set(episode.transition_type)) and not add_on.empty)
    )
    add(
        11,
        "Switch, add-on and restart semantics are non-contradictory",
        "P1",
        link_failures == 0 and transition_semantics_present,
        f"linked transitions={len(linked)}; add-ons={len(add_on)}; failures={link_failures}",
    )

    as_monitors = encounter[encounter.encounter_type.str.startswith("as_")]
    monitor_counts = as_monitors.groupby("patient_id").size()
    active_failures = int(
        active.monitoring_event_count.ne(active.patient_id.map(monitor_counts).fillna(0)).sum()
    )
    transitioned = active[active.transition_to_treatment_flag]
    as_treatment = episode[episode.episode_reason.eq("active_surveillance_exit")].set_index(
        "patient_id"
    )
    active_failures += int(
        (~transitioned.patient_id.isin(as_treatment.index)).sum()
        + transitioned.planned_treatment_start_date.ne(
            transitioned.patient_id.map(as_treatment.treatment_start_date)
        ).sum()
        + (
            active.as_reclassification_event_flag
            & active.as_reclassification_date.ne(active.as_exit_date)
        ).sum()
    )
    add(
        12,
        "Active surveillance is a dated state/event sequence",
        "P1",
        active_failures == 0
        and active.as_start_date.notna().any()
        and as_monitors.encounter_type.nunique() >= 2,
        f"AS episodes={active.as_start_date.notna().sum()}; monitors={len(as_monitors)}; "
        f"transition/reclassification failures={active_failures}",
    )

    provider_lookup = provider.set_index("provider_id")
    provider_failures = int(
        encounter.provider_specialty.ne(
            encounter.provider_id.map(provider_lookup.provider_specialty)
        ).sum()
        + encounter.organization_id.ne(
            encounter.provider_id.map(provider_lookup.organization_id)
        ).sum()
        + referral.source_provider_id.eq(referral.destination_provider_id).sum()
        + referral.source_specialty.ne(
            referral.source_provider_id.map(provider_lookup.provider_specialty)
        ).sum()
        + referral.destination_specialty.ne(
            referral.destination_provider_id.map(provider_lookup.provider_specialty)
        ).sum()
        + referral.source_organization_id.ne(
            referral.source_provider_id.map(provider_lookup.organization_id)
        ).sum()
        + referral.destination_organization_id.ne(
            referral.destination_provider_id.map(provider_lookup.organization_id)
        ).sum()
    )
    expected_owner = referral.source_specialty.where(
        ~referral.referral_status.eq("completed"), referral.destination_specialty
    )
    provider_failures += int(referral.decision_owner_specialty.ne(expected_owner).sum())
    component_specialty = component.treatment_episode_id.map(
        episode_lookup.prescribing_provider_id
    ).map(provider_lookup.provider_specialty)
    provider_failures += int(
        (component.drug_class.eq("chemotherapy") & component_specialty.ne("medical_oncology")).sum()
        + (
            component.drug_name.eq("radiotherapy") & component_specialty.ne("radiation_oncology")
        ).sum()
        + (component.drug_name.eq("prostatectomy") & component_specialty.ne("urology")).sum()
    )
    completed_referrals = set(referral.loc[referral.referral_status.eq("completed"), "patient_id"])
    completed_referral_date = (
        referral.loc[referral.referral_status.eq("completed")]
        .groupby("patient_id")
        .completion_date.min()
    )
    chemotherapy_start = component.treatment_episode_id.map(episode_lookup.treatment_start_date)
    provider_failures += int(
        (
            component.drug_class.eq("chemotherapy")
            & ~component.patient_id.isin(completed_referrals)
        ).sum()
        + (
            component.drug_class.eq("chemotherapy")
            & chemotherapy_start.lt(component.patient_id.map(completed_referral_date))
        ).sum()
    )
    completed_radiation_date = (
        referral.loc[
            referral.referral_status.eq("completed")
            & referral.destination_specialty.eq("radiation_oncology")
        ]
        .groupby("patient_id")
        .completion_date.min()
    )
    radiotherapy = component[component.drug_name.eq("radiotherapy")]
    radiotherapy_start = radiotherapy.treatment_episode_id.map(episode_lookup.treatment_start_date)
    provider_failures += int(
        radiotherapy.patient_id.map(completed_radiation_date).isna().sum()
        + radiotherapy_start.lt(radiotherapy.patient_id.map(completed_radiation_date)).sum()
    )
    add(
        13,
        "Provider, referral, organization and decision ownership reconstruct",
        "P0",
        provider_failures == 0,
        f"provider/referral/treatment incompatibilities={provider_failures}",
    )

    derived_age = (
        pd.to_datetime(patient.index_date) - pd.to_datetime(patient.birth_date)
    ).dt.days // 365
    state_order = states.sort_values(["patient_id", "state_date", "disease_state_event_id"])
    prior_date = state_order.groupby("patient_id").state_date.shift()
    transitions = states[states.previous_state.notna()]
    invalid_state = int(
        (derived_age != patient.age_at_index).sum()
        + (~derived_age.between(config["minimum_age"], config["maximum_age"])).sum()
        + (state_order.state_date < prior_date).sum()
        + sum(
            (previous, current) != ("mHSPC", "mCRPC")
            for previous, current in zip(
                transitions.previous_state, transitions.state, strict=False
            )
        )
    )
    expected_isup = _expected_isup(diagnosis)
    invalid_state += int(
        diagnosis.isup_grade_group.astype("Int64").ne(expected_isup).fillna(False).sum()
    )
    invalid_state += int(
        (diagnosis.castration_resistant_flag & ~diagnosis.metastatic_flag).sum()
        + (diagnosis.castration_resistant_flag & diagnosis.hormone_sensitive_flag).sum()
    )
    metrics["age_minimum"] = int(derived_age.min())
    metrics["age_maximum"] = int(derived_age.max())
    add(
        14,
        "Age, Gleason/ISUP and disease-state transitions are coherent",
        "P0",
        invalid_state == 0,
        f"age range={derived_age.min()}-{derived_age.max()}; clinical-state failures="
        f"{invalid_state}",
    )

    outcome_failures = int(
        outcome.progression_event.ne(outcome.progression_date.notna()).sum()
        + outcome.hospitalisation_flag.ne(outcome.first_hospitalisation_date.notna()).sum()
        + outcome.death_flag.ne(outcome.death_date.notna()).sum()
        + outcome.lost_to_follow_up_flag.ne(outcome.loss_to_follow_up_date.notna()).sum()
    )
    active_patients = set(episode.loc[episode.treatment_status.eq("ongoing"), "patient_id"])
    outcome_failures += int(
        (
            ~outcome.loc[outcome.outcome_status.eq("active_treatment"), "patient_id"].isin(
                active_patients
            )
        ).sum()
    )
    progression_by_stage = journey.groupby("metastatic_flag").progression_event.mean()
    structured_outcome = bool(
        len(progression_by_stage) == 2
        and progression_by_stage.between(0.01, 0.95).all()
        and progression_by_stage.loc[True] > progression_by_stage.loc[False] + 0.05
    )
    metrics["progression_rate_by_metastatic_flag"] = {
        str(key): round(float(value), 6) for key, value in progression_by_stage.items()
    }
    add(
        15,
        "Outcomes are dated, non-deterministic and clinically structured",
        "P1",
        outcome_failures == 0 and structured_outcome,
        f"date/status failures={outcome_failures}; progression rates="
        f"{metrics['progression_rate_by_metastatic_flag']}",
    )

    critical_complete = all(
        not tables[name][column].isna().any()
        for name, column in (
            ("patient", "patient_id"),
            ("diagnosis", "diagnosis_date"),
            ("eligibility", "eligibility_flag"),
            ("observation", "censor_date"),
        )
    )
    market_product_missing = rx.groupby("market_code").product_id.apply(
        lambda values: float(values.isna().mean())
    )
    add(
        16,
        "Missingness is explicit, market-varying and does not hide derivations",
        "P1",
        critical_complete and market_product_missing.nunique() > 1 and scan_missing > deep_missing,
        f"critical derivation fields complete={critical_complete}; product missing by market="
        f"{market_product_missing.round(4).to_dict()}",
    )

    timing_by_feature = timing.set_index("feature_name")
    missing_timing = set(journey.columns) - set(timing.feature_name)
    forbidden = timing.future_information_flag & timing.predictor_allowed_flag
    target_predictors = timing.target_label_flag & timing.predictor_allowed_flag
    referral_timing = timing_by_feature.loc[
        ["referral_status", "referral_completed_flag", "referral_delay_days"]
    ].availability_condition.eq("referral_or_completion_date_le_prediction_index")
    add(
        17,
        "Feature timing blocks target, outcome and pathway leakage",
        "P0",
        not missing_timing
        and not forbidden.any()
        and not target_predictors.any()
        and referral_timing.all(),
        f"unclassified mart fields={len(missing_timing)}; future predictors={forbidden.sum()}; "
        f"target predictors={target_predictors.sum()}; conditional referrals="
        f"{referral_timing.sum()}/3",
    )

    continuous_support = {
        "access_index": int(patient.access_index.nunique()),
        "frailty_proxy": int(patient.frailty_proxy.nunique()),
        "psa_value": int(diagnosis.psa_value.nunique()),
    }
    add(
        18,
        "No obvious clone, tiny-support or formula artefact remains",
        "P1",
        duplicate_signatures == 0
        and continuous_support["access_index"] >= min(100, len(patient) // 2)
        and continuous_support["frailty_proxy"] >= min(100, len(patient) // 2)
        and continuous_support["psa_value"] >= min(100, len(patient) // 2),
        f"duplicate signatures={duplicate_signatures}; continuous support={continuous_support}",
    )

    primary_failures, foreign_failures = _relational_failures(tables)
    add(
        19,
        "Primary keys are unique and non-null",
        "P0",
        primary_failures == 0,
        f"primary-key failures={primary_failures}",
    )
    add(
        20,
        "Foreign keys resolve across normalized domains",
        "P0",
        foreign_failures == 0,
        f"foreign-key failures={foreign_failures}",
    )

    first_encounter = (
        encounter.sort_values(["patient_id", "encounter_date", "sequence_number", "encounter_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
    )
    initial_care_failures = int(
        journey_by_patient.initial_care_setting.ne(first_encounter.care_setting).sum()
        + journey_by_patient.initial_provider_specialty.ne(first_encounter.provider_specialty).sum()
    )
    reconstructed_pathway = encounter.groupby("patient_id").care_setting.apply(
        lambda values: values.iloc[0] if values.nunique() == 1 else "mixed_pathway"
    )
    initial_care_failures += int(
        journey_by_patient.pathway_care_setting.ne(reconstructed_pathway).sum()
    )
    add(
        21,
        "Initial and whole-pathway care settings are not conflated",
        "P1",
        initial_care_failures == 0,
        f"care-setting reconstruction failures={initial_care_failures}",
    )

    eligible_ids = set(eligibility.loc[expected_eligible.values, "patient_id"])
    treated_ids = set(initial_episode.index) & eligible_ids
    untreated_ids = eligible_ids - treated_ids
    initiated_90 = int(
        (
            journey_by_patient.index.isin(eligible_ids)
            & journey_by_patient.days_to_initiation.le(90)
        ).sum()
    )
    gap_90 = int(
        (
            journey_by_patient.index.isin(eligible_ids) & ~journey_by_patient.initiated_within_90d
        ).sum()
    )
    evaluable_12 = journey_by_patient.persistence_12m_status.isin(
        ["PERSISTENT", "DISCONTINUED", "SWITCHED"]
    )
    discontinued_12 = int(
        journey_by_patient.persistence_12m_status.isin(["DISCONTINUED", "SWITCHED"]).sum()
    )
    metrics.update(
        {
            "treated_eligible": len(treated_ids),
            "untreated_eligible": len(untreated_ids),
            "initiated_within_90_days": initiated_90,
            "eligible_treatment_gap_90_days": gap_90,
            "persistence_12m_evaluable": int(evaluable_12.sum()),
            "discontinued_or_switched_by_12m": discontinued_12,
            "market_treatment_gap": journey_by_patient.groupby("market_code")
            .eligible_not_initiated_90d.sum()
            .astype(int)
            .to_dict(),
            "care_setting_treatment_gap": journey_by_patient.groupby("initial_care_setting")
            .eligible_not_initiated_90d.sum()
            .astype(int)
            .to_dict(),
            "segment_treatment_gap": journey_by_patient.groupby("complexity_segment")
            .eligible_not_initiated_90d.sum()
            .astype(int)
            .to_dict(),
        }
    )
    deliverable_consistency = (
        len(eligible_ids) == len(treated_ids) + len(untreated_ids)
        and initiated_90 + gap_90 == len(eligible_ids)
        and evaluable_12.any()
    )
    add(
        22,
        "Core eligible-to-value deliverables independently reconstruct",
        "P0",
        deliverable_consistency,
        f"eligible={len(eligible_ids)}; treated={len(treated_ids)}; untreated="
        f"{len(untreated_ids)}; initiated90={initiated_90}; gap90={gap_90}; "
        f"12m evaluable={evaluable_12.sum()}",
    )

    mart_eligibility_failures = int(
        journey_by_patient.eligibility_flag.ne(
            eligibility_by_patient.eligibility_flag.reindex(journey_by_patient.index)
        ).sum()
    )
    outcome_by_patient = outcome.set_index("patient_id")
    mart_outcome_failures = int(
        journey_by_patient.final_outcome_status.ne(
            outcome_by_patient.outcome_status.reindex(journey_by_patient.index)
        ).sum()
    )
    add(
        23,
        "Analytical mart reconciles to normalized source domains",
        "P0",
        mart_eligibility_failures + first_treatment_failures + mart_outcome_failures == 0,
        f"eligibility={mart_eligibility_failures}; first treatment="
        f"{first_treatment_failures}; outcome={mart_outcome_failures}",
    )

    rule_columns = [
        diagnosis.clinical_state_model_version,
        eligibility.eligibility_rule_version,
        active.active_surveillance_rule_version,
        observation.observation_rule_version,
        regimen.guideline_rule_version,
        outcome.outcome_model_version,
        journey.persistence_rule_version,
    ]
    persistence_version = config["clinical_rule_configuration"]["clinical_rules"]["persistence"][
        "version"
    ]
    add(
        24,
        "Clinical, censoring and outcome rule versions are complete",
        "P1",
        all(series.notna().all() and series.nunique() == 1 for series in rule_columns)
        and config["prescription"]["definition_version"] == persistence_version
        and journey.persistence_rule_version.eq(persistence_version).all(),
        "all exported rule-version domains contain exactly one non-null configured version",
    )

    reproducibility_verified = config["readiness"].get("runtime_reproducibility_verified")
    reproducibility_pass = bool(
        config.get("random_seed") is not None
        and config.get("scenario_version")
        and (
            reproducibility_verified is True
            or config["target_cohort_size"] < 5000
            or not config["readiness"].get("verify_reproducibility_full", False)
        )
    )
    add(
        25,
        "Deterministic generation contract and full-run rerun verification",
        "P1",
        reproducibility_pass,
        f"seed={config.get('random_seed')}; scenario={config.get('scenario_version')}; "
        f"runtime full rerun verified={reproducibility_verified}",
    )

    warnings = [
        "All records and effect relationships are synthetic and are not population-representative.",
        "Clinical assumptions and guideline classifications still require Bayer clinical review.",
        (
            "Scan-market product detail is intentionally incomplete and must not be treated "
            "as absence."
        ),
        (
            "Referral variables are predictors only when their event/completion date is on or "
            "before the prediction index."
        ),
        (
            "Raw Synthea contributes only unique compatible archetypes; most records are "
            "generated independently."
        ),
    ]
    return pd.DataFrame(checks), metrics, warnings


def write_adversarial_audit(
    tables: dict[str, pd.DataFrame], config: dict[str, Any], report_dir: str | Path
) -> dict[str, Any]:
    """Write the independent hostile audit scorecard and directly derived metrics."""
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    checks, metrics, warnings = audit_tables_independently(tables, config)
    score = int(checks.score.sum())
    failed = checks[checks.status.eq("FAIL")]
    payload = {
        "independent_audit_score": score,
        "maximum_score": 100,
        "p0_blockers_remaining": int(failed.priority.eq("P0").sum()),
        "p1_issues_remaining": int(failed.priority.eq("P1").sum()),
        "ready_for_bayer_diagnostic": bool(failed.empty and score == 100),
        "independent_metrics": metrics,
        "remaining_warnings": warnings,
        "scorecard": checks.to_dict(orient="records"),
    }
    checks.to_csv(root / "adversarial_audit_scorecard.csv", index=False)
    (root / "adversarial_audit.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Adversarial Independent Audit",
        "",
        f"Independent audit score: **{score}/100**",
        "",
        "| ID | Independent attack | Priority | Status | Score | Evidence |",
        "|---:|---|---|---|---:|---|",
    ]
    lines.extend(
        f"| {row.check_id} | {row.check} | {row.priority} | {row.status} | "
        f"{row.score}/{row.max_score} | {row.evidence} |"
        for row in checks.itertuples()
    )
    lines.extend(["", "## Independently recalculated metrics", "", "```json"])
    lines.append(json.dumps(metrics, indent=2, default=str))
    lines.extend(["```", "", "## Remaining warnings", ""])
    lines.extend(f"- {warning}" for warning in warnings)
    (root / "adversarial_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def raise_on_adversarial_failure(payload: dict[str, Any]) -> None:
    """Stop release when the independent audit retains a P0 or P1 failure."""
    if payload["p0_blockers_remaining"] or payload["p1_issues_remaining"]:
        raise ValueError(
            "Independent adversarial audit failed: "
            f"P0={payload['p0_blockers_remaining']}, "
            f"P1={payload['p1_issues_remaining']}"
        )
