"""Comprehensive cross-table P0/P1 data-integrity validation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import DISCLAIMER
from .diagnosis_generator import isup_from_patterns
from .journey_builder import derive_persistence_status


def _calendar_age(birth: pd.Series, reference: pd.Series) -> pd.Series:
    """Independently reconstruct completed calendar years for DQ."""
    birth_dates = pd.to_datetime(birth)
    reference_dates = pd.to_datetime(reference)
    birthday_not_reached = (reference_dates.dt.month < birth_dates.dt.month) | (
        reference_dates.dt.month.eq(birth_dates.dt.month)
        & reference_dates.dt.day.lt(birth_dates.dt.day)
    )
    return (
        reference_dates.dt.year - birth_dates.dt.year - birthday_not_reached.astype(int)
    ).astype("int64")


def _result(rule: str, severity: str, failures: int, detail: str) -> dict:
    return {
        "rule": rule,
        "severity": severity,
        "status": "pass" if failures == 0 else "fail",
        "failure_count": int(failures),
        "detail": detail,
    }


def validate_tables(tables: dict[str, pd.DataFrame]) -> list[dict]:
    """Execute key, chronology, clinical, market, leakage and mart rules."""
    results: list[dict] = []

    def add(rule: str, severity: str, count: int, detail: str) -> None:
        results.append(_result(rule, severity, count, detail))

    p = tables["patient"]
    d = tables["diagnosis"]
    ds = tables["disease_state_event"]
    elig = tables["eligibility"]
    org = tables["organization"]
    provider = tables["provider"]
    encounter = tables["encounter"]
    referral = tables["referral"]
    active = tables["active_surveillance"]
    observation = tables["observation"]
    episode = tables["treatment_episode"]
    regimen = tables["treatment_regimen"]
    component = tables["treatment_regimen_component"]
    rx = tables["prescription_event"]
    adverse = tables["adverse_event"]
    outcome = tables["outcome"]
    split = tables["patient_split"]
    feature_timing = tables["feature_timing"]
    journey = tables["patient_journey"]

    primary_keys = {
        "patient": (p, "patient_id"),
        "diagnosis": (d, "diagnosis_id"),
        "disease_state_event": (ds, "disease_state_event_id"),
        "eligibility": (elig, "eligibility_id"),
        "organization": (org, "organization_id"),
        "provider": (provider, "provider_id"),
        "encounter": (encounter, "encounter_id"),
        "referral": (referral, "referral_id"),
        "active_surveillance": (active, "active_surveillance_id"),
        "observation": (observation, "observation_id"),
        "treatment_episode": (episode, "treatment_episode_id"),
        "treatment_regimen": (regimen, "regimen_id"),
        "treatment_regimen_component": (component, "component_id"),
        "prescription_event": (rx, "prescription_event_id"),
        "adverse_event": (adverse, "adverse_event_id"),
        "outcome": (outcome, "outcome_id"),
        "patient_split": (split, "patient_split_id"),
        "feature_timing": (feature_timing, "feature_metadata_id"),
        "patient_journey": (journey, "patient_id"),
    }
    for table_name, (frame, key) in primary_keys.items():
        add(
            f"pk_{table_name}",
            "critical",
            frame[key].isna().sum() + frame[key].duplicated().sum(),
            f"{key} is non-null and unique at documented grain",
        )

    patient_ids = set(p.patient_id)
    patient_frames = [
        d,
        ds,
        elig,
        encounter,
        referral,
        active,
        observation,
        episode,
        regimen,
        component,
        rx,
        adverse,
        outcome,
        split,
        journey,
    ]
    patient_fk_failures = sum(
        (~frame.patient_id.isin(patient_ids)).sum() for frame in patient_frames
    )
    add("fk_patient", "critical", patient_fk_failures, "all patient foreign keys resolve")
    add(
        "fk_provider_organization",
        "critical",
        (~provider.organization_id.isin(org.organization_id)).sum(),
        "provider organization foreign keys resolve",
    )
    add(
        "fk_encounter_provider",
        "critical",
        (~encounter.provider_id.isin(provider.provider_id)).sum(),
        "encounter provider foreign keys resolve",
    )
    add(
        "fk_referral_providers",
        "critical",
        (~referral.source_provider_id.isin(provider.provider_id)).sum()
        + (~referral.destination_provider_id.isin(provider.provider_id)).sum(),
        "referral source and destination providers resolve",
    )
    add(
        "fk_treatment",
        "critical",
        (~episode.prescribing_provider_id.isin(provider.provider_id)).sum()
        + (
            episode.previous_episode_id.notna()
            & ~episode.previous_episode_id.isin(episode.treatment_episode_id)
        ).sum()
        + (
            episode.tracking_component_id.notna()
            & ~episode.tracking_component_id.isin(component.component_id)
        ).sum()
        + (~regimen.treatment_episode_id.isin(episode.treatment_episode_id)).sum()
        + (~component.regimen_id.isin(regimen.regimen_id)).sum()
        + (~component.treatment_episode_id.isin(episode.treatment_episode_id)).sum()
        + (~rx.treatment_episode_id.isin(episode.treatment_episode_id)).sum()
        + (~rx.regimen_id.isin(regimen.regimen_id)).sum()
        + (~rx.component_id.isin(component.component_id)).sum()
        + (~adverse.treatment_episode_id.isin(episode.treatment_episode_id)).sum(),
        "all normalized treatment foreign keys resolve",
    )

    expected_age = _calendar_age(p.birth_date, p.index_date)
    add(
        "age_derived",
        "critical",
        p.age_at_index.ne(expected_age).sum(),
        "age is completed calendar years derived from DOB and index date",
    )
    add(
        "age_configured_range",
        "critical",
        (~p.age_at_index.between(50, 90)).sum(),
        "age stays within the configured 50-90 year cohort contract",
    )
    add("male_only", "critical", (~p.sex.eq("male")).sum(), "prostate cohort contains males only")
    add(
        "independent_archetypes",
        "critical",
        p.source_archetype_id.duplicated().sum(),
        "each generated patient has an independent archetype identifier",
    )
    raw_sources = p[p.source_record_type.eq("synthea_unique")].source_patient_id.dropna()
    add(
        "no_source_cloning",
        "critical",
        raw_sources.duplicated().sum(),
        "raw Synthea IDs are never cloned",
    )
    add(
        "all_markets",
        "critical",
        len({"US", "DE", "JP", "FR", "CN", "AU", "CA"} - set(p.market_code)),
        "all seven required markets are present",
    )

    diagnosis_patient = p[["patient_id", "birth_date"]].merge(
        d[["patient_id", "diagnosis_date"]], on="patient_id"
    )
    add(
        "birth_before_diagnosis",
        "critical",
        (diagnosis_patient.birth_date >= diagnosis_patient.diagnosis_date).sum(),
        "birth precedes diagnosis",
    )
    grade_rows = d.dropna(
        subset=["gleason_primary_pattern", "gleason_secondary_pattern", "isup_grade_group"]
    )
    expected_isup = grade_rows.apply(
        lambda row: isup_from_patterns(
            int(row.gleason_primary_pattern), int(row.gleason_secondary_pattern)
        ),
        axis=1,
    )
    add(
        "gleason_isup_mapping",
        "critical",
        grade_rows.isup_grade_group.astype(int).ne(expected_isup).sum()
        + grade_rows.gleason_score.astype(int)
        .ne(
            grade_rows.gleason_primary_pattern.astype(int)
            + grade_rows.gleason_secondary_pattern.astype(int)
        )
        .sum(),
        "Gleason patterns, score and ISUP mapping are coherent",
    )
    add(
        "metastatic_state_consistency",
        "critical",
        (d.hormone_sensitive_flag & ~d.metastatic_flag).sum()
        + (d.castration_resistant_flag & ~d.metastatic_flag).sum()
        + (d.hormone_sensitive_flag & d.castration_resistant_flag).sum(),
        "hormone-sensitive and resistant metastatic states are coherent",
    )
    transition_rows = ds[ds.previous_state.notna()]
    allowed_transitions = {("mHSPC", "mCRPC")}
    invalid_transitions = sum(
        (previous, current) not in allowed_transitions
        for previous, current in zip(
            transition_rows.previous_state,
            transition_rows.state,
            strict=False,
        )
    )
    ordered_states = ds.sort_values(["patient_id", "state_date", "disease_state_event_id"])
    prior_state_date = ordered_states.groupby("patient_id").state_date.shift()
    diagnosis_dates = d.set_index("patient_id").diagnosis_date
    add(
        "disease_state_transitions",
        "critical",
        invalid_transitions
        + (ordered_states.state_date < prior_state_date).sum()
        + (ordered_states.state_date < ordered_states.patient_id.map(diagnosis_dates)).sum(),
        "disease states are chronological and only configured forward transitions occur",
    )

    expected_eligible = (
        elig.mhspc_flag
        & ~elig.contraindication_flag
        & elig.data_sufficiency_flag
        & (elig.possible_followup_days >= elig.minimum_followup_required_days)
    )
    add(
        "eligibility_reconstructable",
        "critical",
        elig.eligibility_flag.ne(expected_eligible).sum(),
        "eligibility reconstructs exactly from exported source variables",
    )
    add(
        "eligibility_date_semantics",
        "critical",
        (elig.eligibility_flag & elig.eligibility_date.isna()).sum()
        + (~elig.eligibility_flag & elig.eligibility_date.notna()).sum(),
        "eligibility date exists only for eligible patients",
    )
    add(
        "ineligibility_explained",
        "critical",
        (~elig.eligibility_flag & elig.ineligibility_reason.isna()).sum(),
        "every ineligible/insufficient patient has a reason",
    )

    censor_map = observation.set_index("patient_id").censor_date
    event_date_columns = [
        (encounter, ["encounter_date"]),
        (referral, ["referral_date", "completion_date"]),
        (active, ["as_start_date", "as_exit_date", "planned_treatment_start_date"]),
        (
            episode,
            [
                "treatment_start_date",
                "treatment_end_date",
                "discontinuation_date",
                "switch_date",
                "restart_date",
            ],
        ),
        (regimen, ["regimen_start_date", "regimen_end_date"]),
        (component, ["component_start_date", "component_end_date"]),
        (rx, ["service_date", "covered_until_date"]),
        (adverse, ["adverse_event_date"]),
        (outcome, ["progression_date", "castration_resistant_date", "first_hospitalisation_date"]),
        (ds, ["state_date"]),
    ]
    after_censor = 0
    for frame, columns in event_date_columns:
        mapped_censor = pd.to_datetime(frame.patient_id.map(censor_map))
        for column in columns:
            values = pd.to_datetime(frame[column])
            after_censor += (values.notna() & (values > mapped_censor)).sum()
    add(
        "no_event_after_censor",
        "critical",
        after_censor,
        "no clinical event occurs after censor/death/LTFU",
    )
    downstream_after_diagnosis = 0
    downstream_date_columns = [
        (encounter, ["encounter_date"]),
        (referral, ["referral_date", "completion_date"]),
        (active, ["as_start_date", "as_exit_date", "planned_treatment_start_date"]),
        (episode, ["treatment_start_date", "treatment_end_date"]),
        (rx, ["service_date"]),
        (adverse, ["adverse_event_date"]),
        (outcome, ["progression_date", "castration_resistant_date", "first_hospitalisation_date"]),
    ]
    for frame, columns in downstream_date_columns:
        mapped_diagnosis = pd.to_datetime(frame.patient_id.map(diagnosis_dates))
        for column in columns:
            values = pd.to_datetime(frame[column])
            downstream_after_diagnosis += (values.notna() & (values < mapped_diagnosis)).sum()
    add(
        "downstream_events_after_diagnosis",
        "critical",
        downstream_after_diagnosis,
        "clinical pathway events do not precede diagnosis",
    )
    reconstructed_censor = pd.concat(
        [
            observation.observation_end_date,
            observation.death_date,
            observation.loss_to_follow_up_date,
        ],
        axis=1,
    ).min(axis=1)
    reconstructed_reason = pd.Series("administrative_end", index=observation.index, dtype="string")
    reconstructed_reason.loc[
        observation.loss_to_follow_up_date.notna()
        & observation.loss_to_follow_up_date.eq(reconstructed_censor)
    ] = "loss_to_follow_up"
    reconstructed_reason.loc[
        observation.death_date.notna() & observation.death_date.eq(reconstructed_censor)
    ] = "death"
    add(
        "observation_competing_risks",
        "critical",
        (observation.death_date.notna() & observation.loss_to_follow_up_date.notna()).sum()
        + observation.censor_date.ne(reconstructed_censor).sum()
        + observation.censor_date.ne(observation.last_observed_date).sum()
        + observation.censor_reason.ne(reconstructed_reason).sum(),
        "censor and reason independently reconstruct as min(death, LTFU, administrative end)",
    )

    provider_lookup = provider.set_index("provider_id")
    add(
        "encounter_specialty_matches_provider",
        "critical",
        encounter.provider_specialty.ne(
            encounter.provider_id.map(provider_lookup.provider_specialty)
        ).sum(),
        "encounter specialty matches provider master specialty",
    )
    add(
        "encounter_setting_matches_provider",
        "critical",
        encounter.care_setting.ne(encounter.provider_id.map(provider_lookup.care_setting)).sum(),
        "encounter care setting derives from provider organization",
    )
    add(
        "encounter_organization_matches_provider",
        "critical",
        encounter.organization_id.ne(
            encounter.provider_id.map(provider_lookup.organization_id)
        ).sum(),
        "encounter organization matches the provider master",
    )
    add(
        "referral_distinct_providers",
        "critical",
        referral.source_provider_id.eq(referral.destination_provider_id).sum(),
        "real transfers use distinct source and destination providers",
    )
    add(
        "referral_specialty_consistency",
        "critical",
        referral.source_specialty.ne(
            referral.source_provider_id.map(provider_lookup.provider_specialty)
        ).sum()
        + referral.destination_specialty.ne(
            referral.destination_provider_id.map(provider_lookup.provider_specialty)
        ).sum(),
        "referral specialties match provider masters",
    )
    add(
        "referral_organization_consistency",
        "critical",
        referral.source_organization_id.ne(
            referral.source_provider_id.map(provider_lookup.organization_id)
        ).sum()
        + referral.destination_organization_id.ne(
            referral.destination_provider_id.map(provider_lookup.organization_id)
        ).sum(),
        "referral source and destination organizations match provider masters",
    )
    add(
        "referral_completion_semantics",
        "critical",
        (referral.referral_status.eq("completed") & referral.completion_date.isna()).sum()
        + (~referral.referral_status.eq("completed") & referral.completion_date.notna()).sum(),
        "only completed referrals have completion dates",
    )
    add(
        "referral_decision_owner_semantics",
        "critical",
        (
            referral.referral_status.eq("completed")
            & referral.decision_owner_specialty.ne(referral.destination_specialty)
        ).sum()
        + (
            ~referral.referral_status.eq("completed")
            & referral.decision_owner_specialty.ne(referral.source_specialty)
        ).sum(),
        "decision ownership transfers only when the referral completes",
    )
    completed_referrals = referral.loc[referral.referral_status.eq("completed")].copy()
    destination_encounter_latest = encounter.groupby(
        ["patient_id", "provider_id"]
    ).encounter_date.max()
    destination_treatment_latest = episode.groupby(
        ["patient_id", "prescribing_provider_id"]
    ).treatment_start_date.max()
    referral_evidence_failures = 0
    for completed_referral in completed_referrals.itertuples():
        key = (
            completed_referral.patient_id,
            completed_referral.destination_provider_id,
        )
        encounter_date = destination_encounter_latest.get(key, pd.NaT)
        treatment_date = destination_treatment_latest.get(key, pd.NaT)
        evidence_dates = [
            pd.Timestamp(value) for value in (encounter_date, treatment_date) if pd.notna(value)
        ]
        referral_evidence_failures += int(
            not evidence_dates
            or max(evidence_dates) < pd.Timestamp(completed_referral.completion_date)
        )
    add(
        "referral_destination_event_evidence",
        "critical",
        referral_evidence_failures,
        "every completed referral has a dated destination-provider encounter or treatment event",
    )

    add(
        "treatment_episode_dates",
        "critical",
        (episode.treatment_start_date >= episode.treatment_end_date).sum()
        + (
            episode.discontinuation_date.notna()
            & (episode.discontinuation_date > episode.treatment_end_date)
        ).sum()
        + (episode.switch_date.notna() & (episode.switch_date > episode.treatment_end_date)).sum(),
        "episode intervals and terminal events are coherent",
    )
    episode_censor = episode.patient_id.map(observation.set_index("patient_id").censor_date)
    episode_censor_reason = episode.patient_id.map(
        observation.set_index("patient_id").censor_reason
    )
    add(
        "treatment_censor_status",
        "critical",
        (
            episode.treatment_status.eq("ongoing")
            & (
                episode.treatment_end_date.ne(episode_censor)
                | episode_censor_reason.ne("administrative_end")
            )
        ).sum()
        + (
            episode.treatment_status.eq("censored")
            & (
                episode.treatment_end_date.ne(episode_censor)
                | episode_censor_reason.eq("administrative_end")
            )
        ).sum(),
        "ongoing versus censored episode status reflects the terminal boundary",
    )
    add(
        "regimen_episode_dates",
        "critical",
        (
            regimen.regimen_start_date
            < regimen.treatment_episode_id.map(
                episode.set_index("treatment_episode_id").treatment_start_date
            )
        ).sum()
        + (
            regimen.regimen_end_date
            > regimen.treatment_episode_id.map(
                episode.set_index("treatment_episode_id").treatment_end_date
            )
        ).sum(),
        "regimens stay within episodes",
    )
    component_episode_start = component.treatment_episode_id.map(
        episode.set_index("treatment_episode_id").treatment_start_date
    )
    component_episode_end = component.treatment_episode_id.map(
        episode.set_index("treatment_episode_id").treatment_end_date
    )
    add(
        "component_episode_dates",
        "critical",
        (component.component_start_date < component_episode_start).sum()
        + (component.component_end_date > component_episode_end).sum()
        + (component.component_start_date > component.component_end_date).sum(),
        "regimen components stay within their episode",
    )
    component_classes = component.groupby("regimen_id").drug_class.agg(set)
    expected_intensified = regimen.regimen_id.map(component_classes).apply(
        lambda values: bool(values and ({"ARPI", "chemotherapy"} & values))
    ) & regimen.patient_id.isin(elig.loc[elig.mhspc_flag, "patient_id"])
    add(
        "intensification_reconstructable",
        "critical",
        regimen.intensification_flag.ne(expected_intensified).sum(),
        "intensification derives from mHSPC state and regimen components",
    )
    component_provider = component.treatment_episode_id.map(
        episode.set_index("treatment_episode_id").prescribing_provider_id
    )
    component_specialty = component_provider.map(provider_lookup.provider_specialty)
    incompatible_prescriber = (
        (component.drug_class.eq("chemotherapy") & component_specialty.ne("medical_oncology"))
        | (component.drug_name.eq("radiotherapy") & component_specialty.ne("radiation_oncology"))
        | (component.drug_name.eq("prostatectomy") & component_specialty.ne("urology"))
    )
    add(
        "treatment_provider_compatibility",
        "critical",
        incompatible_prescriber.sum(),
        "chemotherapy, radiotherapy and surgery use compatible specialists",
    )
    completed_referral_patients = set(
        referral.loc[referral.referral_status.eq("completed"), "patient_id"]
    )
    completed_referral_dates = (
        referral.loc[referral.referral_status.eq("completed")]
        .groupby("patient_id")
        .completion_date.min()
    )
    chemotherapy_episode_start = component.treatment_episode_id.map(
        episode.set_index("treatment_episode_id").treatment_start_date
    )
    add(
        "chemotherapy_referral_coherence",
        "critical",
        (
            component.drug_class.eq("chemotherapy")
            & ~component.patient_id.isin(completed_referral_patients)
        ).sum()
        + (
            component.drug_class.eq("chemotherapy")
            & chemotherapy_episode_start.lt(component.patient_id.map(completed_referral_dates))
        ).sum(),
        "chemotherapy occurs only after an observed, already-completed oncology referral",
    )
    completed_radiation_dates = (
        referral.loc[
            referral.referral_status.eq("completed")
            & referral.destination_specialty.eq("radiation_oncology")
        ]
        .groupby("patient_id")
        .completion_date.min()
    )
    radiotherapy = component[component.drug_name.eq("radiotherapy")]
    radiotherapy_start = radiotherapy.treatment_episode_id.map(
        episode.set_index("treatment_episode_id").treatment_start_date
    )
    add(
        "radiotherapy_referral_coherence",
        "critical",
        radiotherapy.patient_id.map(completed_radiation_dates).isna().sum()
        + radiotherapy_start.lt(radiotherapy.patient_id.map(completed_radiation_dates)).sum(),
        "radiotherapy occurs only after a completed radiation-oncology transfer",
    )
    chemotherapy_components = component[component.drug_class.eq("chemotherapy")]
    chemotherapy_event_counts = rx.groupby("component_id").size()
    add(
        "chemotherapy_cycle_limit",
        "critical",
        (
            pd.to_numeric(
                chemotherapy_components.component_id.map(chemotherapy_event_counts),
                errors="coerce",
            )
            .fillna(0)
            .gt(
                pd.to_numeric(
                    chemotherapy_components.planned_cycle_count,
                    errors="coerce",
                ).fillna(0)
            )
        ).sum(),
        "chemotherapy dispensing does not exceed the explicit planned cycle count",
    )

    component_lookup = component.set_index("component_id")
    episode_lookup = episode.set_index("treatment_episode_id")
    add(
        "prescription_component_match",
        "critical",
        rx.drug_name.ne(rx.component_id.map(component_lookup.drug_name)).sum()
        + rx.patient_id.ne(rx.component_id.map(component_lookup.patient_id)).sum(),
        "prescription events match component drug and patient",
    )
    rx_component_start = rx.component_id.map(component_lookup.component_start_date)
    rx_component_end = rx.component_id.map(component_lookup.component_end_date)
    add(
        "prescription_dates",
        "critical",
        (rx.service_date < rx_component_start).sum()
        + (rx.service_date > rx_component_end).sum()
        + (rx.covered_until_date > rx_component_end).sum()
        + rx.nominal_covered_until_date.ne(
            rx.service_date + pd.to_timedelta(rx.days_supply, unit="D")
        ).sum(),
        "dispensing dates and nominal/effective coverage are coherent",
    )
    ordered_rx = rx.sort_values(["component_id", "service_date", "prescription_event_id"]).copy()
    event_number = ordered_rx.groupby("component_id").cumcount()
    expected_type = pd.Series("refill", index=ordered_rx.index)
    expected_type.loc[event_number.eq(0)] = "initial_fill"
    previous_coverage = ordered_rx.groupby("component_id").covered_until_date.shift()
    expected_gap = (ordered_rx.service_date - previous_coverage).dt.days.fillna(0).astype(int)
    add(
        "prescription_sequence",
        "critical",
        ordered_rx.event_type.ne(expected_type).sum()
        + ordered_rx.refill_gap_days.ne(expected_gap).sum(),
        "initial/refill sequence and early/on-time/late gaps reconstruct",
    )
    add(
        "prescription_coverage_monotonic",
        "critical",
        (ordered_rx.covered_until_date < previous_coverage).sum(),
        "effective coverage never moves backward after an early refill",
    )
    detailed_components = component.loc[component.dispensing_detail_available_flag, "component_id"]
    fill_counts = (
        rx.event_type.eq("initial_fill")
        .groupby(rx.component_id)
        .sum()
        .reindex(detailed_components, fill_value=0)
    )
    add(
        "prescription_component_coverage",
        "critical",
        fill_counts.ne(1).sum(),
        "every component with dispensing detail has exactly one initial event",
    )
    event_max_gap = rx.groupby("treatment_episode_id").refill_gap_days.max()
    expected_episode_gap = episode.treatment_episode_id.map(event_max_gap).fillna(0).astype(int)
    add(
        "prescription_episode_summary",
        "critical",
        episode.max_refill_gap_days.ne(expected_episode_gap).sum(),
        "episode maximum refill gap reconciles to events",
    )

    linked = episode[episode.transition_type.isin(["switch", "restart"])]
    previous_end = linked.previous_episode_id.map(episode_lookup.treatment_end_date)
    add(
        "switch_restart_nonoverlap",
        "critical",
        linked.previous_episode_id.isna().sum()
        + (linked.treatment_start_date <= previous_end).sum(),
        "switch/restart episodes link to and follow the closed prior episode",
    )
    switched_previous_ids = set(
        linked.loc[linked.transition_type.eq("switch"), "previous_episode_id"].dropna()
    )
    old_switch_events = rx[rx.treatment_episode_id.isin(switched_previous_ids)]
    add(
        "no_old_drug_after_switch",
        "critical",
        (
            old_switch_events.service_date
            > old_switch_events.treatment_episode_id.map(episode_lookup.treatment_end_date)
        ).sum(),
        "true switch closes previous dispensing",
    )

    add(
        "active_surveillance_logic",
        "critical",
        (active.as_start_date.notna() & ~active.as_eligibility_flag).sum()
        + (active.as_exit_date.notna() & active.as_start_date.isna()).sum()
        + (active.transition_to_treatment_flag & active.planned_treatment_start_date.isna()).sum(),
        "AS start, exit and treatment transition are coherent",
    )
    as_treatment_start = (
        episode[episode.episode_reason.eq("active_surveillance_exit")]
        .groupby("patient_id")
        .treatment_start_date.min()
    )
    transitioned_as = active[active.transition_to_treatment_flag]
    add(
        "active_surveillance_treatment_reconciliation",
        "critical",
        (~transitioned_as.patient_id.isin(as_treatment_start.index)).sum()
        + transitioned_as.planned_treatment_start_date.ne(
            transitioned_as.patient_id.map(as_treatment_start)
        ).sum(),
        "every observed AS treatment transition has a matching normalized episode",
    )
    add(
        "active_surveillance_reclassification_semantics",
        "critical",
        (
            active.as_reclassification_event_flag
            & (
                active.as_reclassification_date.isna()
                | active.as_exit_date.ne(active.as_reclassification_date)
            )
        ).sum()
        + (~active.as_reclassification_event_flag & active.as_reclassification_date.notna()).sum(),
        "AS reclassification is a dated event reconciled to AS exit",
    )

    initial_episode = (
        episode.sort_values(["patient_id", "treatment_start_date", "treatment_episode_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
    )
    tracking_events = {
        component_id: events for component_id, events in rx.groupby("component_id", sort=False)
    }
    observation_censor = observation.set_index("patient_id").censor_date
    journey_by_patient = journey.set_index("patient_id")

    def reconstructed_persistence_failures(
        target_days: int, permissible_gap: int, status_column: str
    ) -> int:
        failures = 0
        for patient_id, treatment in initial_episode.iterrows():
            events = tracking_events.get(treatment.tracking_component_id, rx.iloc[0:0])
            expected_status = derive_persistence_status(
                events,
                pd.Timestamp(treatment.treatment_start_date),
                pd.Timestamp(observation_censor.loc[patient_id]),
                target_days,
                permissible_gap,
                treatment.discontinuation_date,
                treatment.switch_date,
            )
            failures += int(journey_by_patient.loc[patient_id, status_column] != expected_status)
        untreated = journey.loc[~journey.treatment_initiated, status_column]
        return failures + int(untreated.ne("NOT_APPLICABLE").sum())

    persistence_failures = {
        "persistence_3m_status": reconstructed_persistence_failures(
            90, 60, "persistence_3m_status"
        ),
        "persistence_6m_status": reconstructed_persistence_failures(
            180, 60, "persistence_6m_status"
        ),
        "persistence_12m_status": reconstructed_persistence_failures(
            365, 60, "persistence_12m_status"
        ),
    }
    add(
        "persistence_rule_version",
        "critical",
        journey.persistence_rule_version.ne("PERSISTENCE-SYN-v2.1").sum(),
        "every mart persistence label carries the configured v2.1 definition",
    )
    for status_column, failure_count in persistence_failures.items():
        add(
            f"{status_column}_reconstructable",
            "critical",
            failure_count,
            f"{status_column} reconstructs from landmark-bounded dispensing events",
        )
    add(
        "persistence_right_censoring",
        "critical",
        persistence_failures["persistence_12m_status"],
        "12-month status distinguishes observed gap failure from right censoring",
    )
    for gap in (30, 60, 90):
        status_column = f"persistence_12m_status_gap_{gap}d"
        flag_column = f"persistent_12m_gap_{gap}d"
        add(
            f"persistence_sensitivity_reconstructable_{gap}",
            "critical",
            reconstructed_persistence_failures(365, gap, status_column),
            f"{gap}-day persistence reconstructs independently from events",
        )
        add(
            f"persistence_status_flag_{gap}",
            "critical",
            (journey[status_column].eq("PERSISTENT") & ~journey[flag_column].fillna(False)).sum()
            + (
                journey[status_column].eq("CENSORED_NOT_EVALUABLE") & journey[flag_column].notna()
            ).sum(),
            f"{gap}-day status and nullable flag agree",
        )
    persistent_30 = journey.persistent_12m_gap_30d.fillna(False).astype(bool)
    persistent_60 = journey.persistent_12m_gap_60d.fillna(False).astype(bool)
    persistent_90 = journey.persistent_12m_gap_90d.fillna(False).astype(bool)
    add(
        "persistence_sensitivity_monotonic",
        "critical",
        (persistent_30 & ~persistent_60).sum() + (persistent_60 & ~persistent_90).sum(),
        "persistence cannot decrease when the permissible gap increases",
    )

    add(
        "split_one_per_patient",
        "critical",
        len(patient_ids - set(split.patient_id)) + split.patient_id.duplicated().sum(),
        "each independent patient/archetype belongs to one split",
    )
    add(
        "split_archetype_no_overlap",
        "critical",
        split.groupby("source_archetype_id").split.nunique().gt(1).sum(),
        "no archetype crosses train/validation/test",
    )
    forbidden_features = feature_timing[
        feature_timing.future_information_flag & feature_timing.predictor_allowed_flag
    ]
    add(
        "feature_timing_leakage",
        "critical",
        len(forbidden_features),
        "future/outcome features are prohibited from predictive feature sets",
    )
    add(
        "feature_timing_mart_coverage",
        "critical",
        len(set(journey.columns) - set(feature_timing.feature_name))
        + feature_timing.feature_name.duplicated().sum(),
        "every analytical mart field has one explicit timing/governance record",
    )

    journey_index = journey.set_index("patient_id")
    eligibility_match = elig.set_index("patient_id").eligibility_flag
    add(
        "mart_eligibility_reconciliation",
        "critical",
        journey_index.eligibility_flag.ne(eligibility_match).sum(),
        "mart eligibility reconciles to eligibility table",
    )
    add(
        "mart_treatment_reconciliation",
        "critical",
        journey.treatment_initiated.ne(journey.patient_id.isin(episode.patient_id)).sum(),
        "mart initiation reconciles to episodes",
    )
    first_start = (
        episode.sort_values(["patient_id", "treatment_start_date", "treatment_episode_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
        .treatment_start_date.reindex(journey_index.index)
    )
    eligibility_date = elig.set_index("patient_id").eligibility_date.reindex(journey_index.index)
    eligible_mask = eligibility_match.reindex(journey_index.index).astype(bool)
    initiation_days = (first_start - eligibility_date).dt.days.astype("Int64")
    expected_initiated_30 = eligible_mask & initiation_days.le(30).fillna(False)
    expected_initiated_60 = eligible_mask & initiation_days.le(60).fillna(False)
    expected_initiated_90 = eligible_mask & initiation_days.le(90).fillna(False)
    initiation_target = eligibility_date + pd.Timedelta(days=90)
    patient_censor = observation.set_index("patient_id").censor_date.reindex(journey_index.index)
    expected_censored_90 = (
        eligible_mask & ~expected_initiated_90 & patient_censor.lt(initiation_target)
    )
    expected_gap_90 = eligible_mask & ~expected_initiated_90 & ~expected_censored_90
    expected_status = pd.Series("NOT_ELIGIBLE", index=journey_index.index, dtype="string")
    expected_status.loc[expected_gap_90] = "NOT_INITIATED_WITHIN_90D"
    expected_status.loc[expected_censored_90] = "CENSORED_NOT_EVALUABLE"
    expected_status.loc[expected_initiated_90] = "INITIATED_WITHIN_90D"
    expected_days = initiation_days.where(eligible_mask & first_start.notna())
    day_presence_mismatch = journey_index.days_to_initiation.notna().ne(expected_days.notna())
    day_value_mismatch = (
        journey_index.days_to_initiation.astype("Int64").ne(expected_days).fillna(False)
    )
    add(
        "mart_initiation_window_reconciliation",
        "critical",
        journey_index.initiation_90d_status.ne(expected_status).sum()
        + journey_index.initiated_within_30d.ne(expected_initiated_30).sum()
        + journey_index.initiated_within_60d.ne(expected_initiated_60).sum()
        + journey_index.initiated_within_90d.ne(expected_initiated_90).sum()
        + journey_index.eligible_not_initiated_90d.ne(expected_gap_90).sum()
        + day_presence_mismatch.sum()
        + day_value_mismatch.sum(),
        "initiation dates/statuses independently reconstruct from eligibility, first episode, "
        "and censor dates",
    )
    add(
        "mart_outcome_reconciliation",
        "critical",
        journey_index.progression_event.ne(outcome.set_index("patient_id").progression_event).sum(),
        "mart outcomes reconcile to normalized outcome table",
    )
    active_treatment_patients = set(
        episode.loc[episode.treatment_status.eq("ongoing"), "patient_id"]
    )
    treated_patients = set(episode.patient_id)
    expected_outcome_status = pd.Series("observed_no_treatment", index=outcome.index)
    expected_outcome_status.loc[outcome.patient_id.isin(treated_patients)] = (
        "post_treatment_follow_up"
    )
    expected_outcome_status.loc[outcome.patient_id.isin(active_treatment_patients)] = (
        "active_treatment"
    )
    expected_outcome_status.loc[outcome.lost_to_follow_up_flag] = "lost_to_follow_up"
    expected_outcome_status.loc[outcome.hospitalisation_flag] = "hospitalised"
    expected_outcome_status.loc[outcome.progression_event] = "progressed"
    expected_outcome_status.loc[outcome.death_flag] = "death"
    add(
        "outcome_status_reconstructable",
        "critical",
        outcome.outcome_status.ne(expected_outcome_status).sum()
        + outcome.outcome_model_version.isna().sum(),
        "terminal outcome status and model version reconstruct from dated source states",
    )

    def pathway_setting(events: pd.DataFrame) -> str:
        settings = set(events.care_setting.dropna())
        if len(settings) > 1:
            return "mixed_pathway"
        return next(iter(settings))

    reconstructed_pathway_setting = encounter.groupby("patient_id").apply(
        pathway_setting, include_groups=False
    )
    first_encounter = (
        encounter.sort_values(["patient_id", "encounter_date", "sequence_number", "encounter_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
    )
    add(
        "mart_care_setting_reconciliation",
        "critical",
        journey_index.initial_care_setting.ne(first_encounter.care_setting).sum()
        + journey_index.initial_provider_specialty.ne(first_encounter.provider_specialty).sum(),
        "initial care setting and specialty derive only from the first encounter",
    )
    add(
        "mart_pathway_setting_reconciliation",
        "critical",
        journey_index.pathway_care_setting.ne(reconstructed_pathway_setting).sum(),
        "descriptive pathway setting reconciles to the complete encounter sequence",
    )
    return results


def write_quality_report(results: list[dict], report_dir: str | Path) -> None:
    """Write JSON, CSV and Markdown validation reports."""
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "disclaimer": DISCLAIMER,
        "rules": results,
        "critical_failures": sum(
            result["failure_count"] for result in results if result["severity"] == "critical"
        ),
    }
    (root / "data_quality_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    pd.DataFrame(results).to_csv(root / "data_quality_summary.csv", index=False)
    lines = [
        f"# Data Quality Report\n\n> **{DISCLAIMER}**\n",
        "| Rule | Severity | Status | Failures | Detail |",
        "|---|---|---:|---:|---|",
    ]
    lines.extend(
        f"| {result['rule']} | {result['severity']} | {result['status']} | "
        f"{result['failure_count']} | {result['detail']} |"
        for result in results
    )
    (root / "data_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def raise_on_critical(results: list[dict]) -> None:
    """Fail the pipeline when a critical rule fails."""
    failed = [
        result for result in results if result["severity"] == "critical" and result["failure_count"]
    ]
    if failed:
        raise ValueError(
            "Critical data-quality failures: " + ", ".join(result["rule"] for result in failed)
        )
