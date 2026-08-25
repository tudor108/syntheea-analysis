"""Build reconstructable eligibility and the traceable patient-level analytical mart."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .diagnosis_generator import derive_mhspc


def build_eligibility(
    patient: pd.DataFrame,
    diagnosis: pd.DataFrame,
    observation: pd.DataFrame,
    config: dict,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Derive transparent eligibility with explicit reasons and no opaque suppression."""
    observation_index = observation.set_index("patient_id")
    rules = config["clinical_rule_configuration"]["clinical_rules"]
    rule_version = rules["arpi_eligibility"]["version"]
    rows: list[dict] = []
    mhspc = derive_mhspc(diagnosis)
    contraindication_config = config["contraindication"]

    for i, person in patient.iterrows():
        dx = diagnosis.iloc[i]
        obs = observation_index.loc[person.patient_id]
        evidence_complete = bool(
            dx.prostate_stage != "unknown"
            and not (
                dx.metastatic_flag
                and not dx.hormone_sensitive_flag
                and not dx.castration_resistant_flag
            )
        )
        probability = contraindication_config["base_probability"]
        probability += contraindication_config["high_comorbidity_increment"] * float(
            person.comorbidity_score >= 5
        )
        probability += contraindication_config["high_frailty_increment"] * float(
            person.frailty_proxy >= 0.60
        )
        contraindication = bool(rng.random() < np.clip(probability, 0.0, 0.50))
        reasons = contraindication_config["reasons"]
        contraindication_reason = (
            str(rng.choice(list(reasons), p=list(reasons.values()))) if contraindication else pd.NA
        )
        possible_followup = (
            pd.Timestamp(config["observation_end_date"]) - pd.Timestamp(dx.diagnosis_date)
        ).days
        sufficient_followup_potential = possible_followup >= config["minimum_follow_up_days"]
        eligible = bool(
            mhspc.iloc[i]
            and person.age_at_index >= 18
            and not contraindication
            and evidence_complete
            and sufficient_followup_potential
        )
        if eligible:
            status = "ELIGIBLE"
            eligibility_reason = "meets_configured_mhspc_denominator"
            ineligibility_reason = pd.NA
            clinical_exclusion_reason = pd.NA
            eligibility_date = max(
                pd.Timestamp(dx.diagnosis_date),
                pd.Timestamp(dx.metastatic_date),
                pd.Timestamp(dx.hormone_sensitive_confirmation_date),
            )
        elif not evidence_complete or not sufficient_followup_potential:
            status = "INSUFFICIENT_DATA"
            eligibility_reason = pd.NA
            ineligibility_reason = (
                "insufficient_clinical_state_evidence"
                if not evidence_complete
                else "insufficient_followup_potential"
            )
            clinical_exclusion_reason = pd.NA
            eligibility_date = pd.NaT
        else:
            status = "CLINICALLY_INELIGIBLE"
            eligibility_reason = pd.NA
            if contraindication:
                ineligibility_reason = "configured_contraindication"
                clinical_exclusion_reason = contraindication_reason
            elif not mhspc.iloc[i]:
                ineligibility_reason = "does_not_meet_mhspc_state"
                clinical_exclusion_reason = "disease_state_outside_configured_denominator"
            else:
                ineligibility_reason = "age_outside_rule"
                clinical_exclusion_reason = "age"
            eligibility_date = pd.NaT
        rows.append(
            {
                "eligibility_id": f"ELIG-{person.market_code}-{i:07d}",
                "patient_id": person.patient_id,
                "market_code": person.market_code,
                "mhspc_flag": bool(mhspc.iloc[i]),
                "eligibility_flag": eligible,
                "eligible_for_arpi": eligible,
                "eligibility_status": status,
                "eligibility_date": eligibility_date,
                "eligibility_reason": eligibility_reason,
                "ineligibility_reason": ineligibility_reason,
                "clinical_exclusion_reason": clinical_exclusion_reason,
                "contraindication_flag": contraindication,
                "contraindication_reason": contraindication_reason,
                "data_sufficiency_flag": evidence_complete,
                "possible_followup_days": possible_followup,
                "minimum_followup_required_days": config["minimum_follow_up_days"],
                "eligibility_rule_version": rule_version,
                "source_assumption": rules["arpi_eligibility"]["source_assumption"],
                "censor_date_at_generation": obs.censor_date,
                "synthetic_event_flag": True,
            }
        )
    return pd.DataFrame(rows)


def derive_persistence_status(
    events: pd.DataFrame,
    start: pd.Timestamp,
    censor: pd.Timestamp,
    target_days: int,
    permissible_gap: int,
    discontinuation_date: pd.Timestamp | pd.NaT,
    switch_date: pd.Timestamp | pd.NaT,
) -> str:
    """Reconstruct landmark persistence using only events observable by the landmark."""
    if events.empty:
        return "NOT_APPLICABLE"
    target = start + pd.Timedelta(days=target_days)
    candidates: list[tuple[pd.Timestamp, int, str]] = []
    if pd.notna(switch_date):
        candidates.append((pd.Timestamp(switch_date), 0, "SWITCHED"))
    if pd.notna(discontinuation_date):
        candidates.append((pd.Timestamp(discontinuation_date), 1, "DISCONTINUED"))

    ordered = events.sort_values(["service_date", "prescription_event_id"])
    previous_coverage = pd.NaT
    for event in ordered.itertuples():
        service_date = pd.Timestamp(event.service_date)
        if pd.isna(previous_coverage):
            gap_origin = start
        else:
            gap_origin = pd.Timestamp(previous_coverage)
        if service_date > gap_origin + pd.Timedelta(days=permissible_gap):
            candidates.append(
                (
                    gap_origin + pd.Timedelta(days=permissible_gap + 1),
                    2,
                    "DISCONTINUED",
                )
            )
            break
        event_coverage = pd.Timestamp(event.covered_until_date)
        previous_coverage = (
            event_coverage
            if pd.isna(previous_coverage)
            else max(pd.Timestamp(previous_coverage), event_coverage)
        )
    if pd.notna(previous_coverage):
        candidates.append(
            (
                pd.Timestamp(previous_coverage) + pd.Timedelta(days=permissible_gap + 1),
                2,
                "DISCONTINUED",
            )
        )

    # Reaching the landmark exactly is evaluable; censoring must occur before it.
    candidates.extend(
        [
            (target, 3, "PERSISTENT"),
            (censor, 4, "CENSORED_NOT_EVALUABLE"),
        ]
    )
    return min(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]


def build_patient_journey(
    patient: pd.DataFrame,
    diagnosis: pd.DataFrame,
    eligibility: pd.DataFrame,
    encounter: pd.DataFrame,
    referral: pd.DataFrame,
    active_surveillance: pd.DataFrame,
    treatment_episode: pd.DataFrame,
    treatment_regimen: pd.DataFrame,
    regimen_component: pd.DataFrame,
    prescription_event: pd.DataFrame,
    observation: pd.DataFrame,
    outcome: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """Derive one analytical row per patient exclusively from normalized tables."""
    diagnosis_index = diagnosis.set_index("patient_id")
    eligibility_index = eligibility.set_index("patient_id")
    observation_index = observation.set_index("patient_id")
    outcome_index = outcome.set_index("patient_id")
    initial_episodes = (
        treatment_episode.sort_values(["patient_id", "treatment_start_date"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
        if not treatment_episode.empty
        else pd.DataFrame()
    )
    regimen_index = (
        treatment_regimen.set_index("treatment_episode_id")
        if not treatment_regimen.empty
        else pd.DataFrame()
    )
    as_index = (
        active_surveillance.set_index("patient_id")
        if not active_surveillance.empty
        else pd.DataFrame()
    )
    referral_first = (
        referral.sort_values("referral_date").drop_duplicates("patient_id").set_index("patient_id")
        if not referral.empty
        else pd.DataFrame()
    )
    rows: list[dict] = []
    default_gap = int(config["prescription"]["permissible_gap_days"])
    sensitivity_gaps = config["prescription"]["sensitivity_gaps"]

    for _, person in patient.iterrows():
        pid = person.patient_id
        dx = diagnosis_index.loc[pid]
        elig = eligibility_index.loc[pid]
        obs = observation_index.loc[pid]
        out = outcome_index.loc[pid]
        patient_encounters = encounter[encounter.patient_id.eq(pid)].sort_values(
            ["encounter_date", "sequence_number", "encounter_id"]
        )
        settings = list(patient_encounters.care_setting.dropna().unique())
        first_encounter = patient_encounters.iloc[0]
        if len(settings) > 1:
            pathway_setting = "mixed_pathway"
        else:
            pathway_setting = settings[0]

        first_referral = referral_first.loc[pid] if pid in referral_first.index else None
        first_episode = initial_episodes.loc[pid] if pid in initial_episodes.index else None
        treatment_initiated = first_episode is not None
        first_regimen = (
            regimen_index.loc[first_episode.treatment_episode_id]
            if treatment_initiated and first_episode.treatment_episode_id in regimen_index.index
            else None
        )
        first_components = (
            regimen_component[
                regimen_component.treatment_episode_id.eq(first_episode.treatment_episode_id)
            ]
            if treatment_initiated
            else regimen_component.iloc[0:0]
        )
        tracking_events = prescription_event.iloc[0:0]
        if treatment_initiated and pd.notna(first_episode.tracking_component_id):
            tracking_events = prescription_event[
                prescription_event.component_id.eq(first_episode.tracking_component_id)
            ].sort_values("service_date")
        coverage_until = (
            tracking_events.covered_until_date.max() if not tracking_events.empty else pd.NaT
        )
        max_gap = int(tracking_events.refill_gap_days.max()) if not tracking_events.empty else 0
        start = pd.Timestamp(first_episode.treatment_start_date) if treatment_initiated else pd.NaT
        censor = pd.Timestamp(obs.censor_date)
        discontinuation_date = first_episode.discontinuation_date if treatment_initiated else pd.NaT
        switch_date = first_episode.switch_date if treatment_initiated else pd.NaT

        persistence: dict[str, object] = {}
        for months, days in ((3, 90), (6, 180), (12, 365)):
            status = (
                derive_persistence_status(
                    tracking_events,
                    start,
                    censor,
                    days,
                    default_gap,
                    discontinuation_date,
                    switch_date,
                )
                if treatment_initiated
                else "NOT_APPLICABLE"
            )
            persistence[f"persistence_{months}m_status"] = status
            persistence[f"persistent_{months}m"] = (
                True
                if status == "PERSISTENT"
                else pd.NA
                if status in {"CENSORED_NOT_EVALUABLE", "NOT_APPLICABLE"}
                else False
            )
        for gap in sensitivity_gaps:
            status = (
                derive_persistence_status(
                    tracking_events,
                    start,
                    censor,
                    365,
                    int(gap),
                    discontinuation_date,
                    switch_date,
                )
                if treatment_initiated
                else "NOT_APPLICABLE"
            )
            persistence[f"persistence_12m_status_gap_{gap}d"] = status
            persistence[f"persistent_12m_gap_{gap}d"] = (
                True
                if status == "PERSISTENT"
                else pd.NA
                if status in {"CENSORED_NOT_EVALUABLE", "NOT_APPLICABLE"}
                else False
            )

        days_to_initiation = (
            (start - pd.Timestamp(elig.eligibility_date)).days
            if treatment_initiated and elig.eligibility_flag
            else pd.NA
        )
        initiation_target = (
            pd.Timestamp(elig.eligibility_date) + pd.Timedelta(days=90)
            if elig.eligibility_flag
            else pd.NaT
        )
        if not elig.eligibility_flag:
            initiation_status = "NOT_ELIGIBLE"
        elif treatment_initiated and days_to_initiation <= 90:
            initiation_status = "INITIATED_WITHIN_90D"
        elif censor < initiation_target:
            initiation_status = "CENSORED_NOT_EVALUABLE"
        else:
            initiation_status = "NOT_INITIATED_WITHIN_90D"

        as_record = as_index.loc[pid] if pid in as_index.index else None
        row = {
            "patient_id": pid,
            "market_code": person.market_code,
            "country": person.country,
            "market_depth": person.market_depth,
            "source_archetype_id": person.source_archetype_id,
            "age_at_index": person.age_at_index,
            "comorbidity_score": person.comorbidity_score,
            "frailty_proxy": person.frailty_proxy,
            "complexity_segment": person.complexity_segment,
            "region": person.region,
            "insurance_type": person.insurance_type,
            "access_index": person.access_index,
            "socioeconomic_proxy": person.socioeconomic_proxy,
            "prostate_stage": dx.prostate_stage,
            "metastatic_flag": dx.metastatic_flag,
            "hormone_sensitive_flag": dx.hormone_sensitive_flag,
            "castration_resistant_flag": dx.castration_resistant_flag,
            "risk_group": dx.risk_group,
            "psa_value": dx.psa_value,
            "gleason_score": dx.gleason_score,
            "isup_grade_group": dx.isup_grade_group,
            "mhspc_flag": elig.mhspc_flag,
            "denominator_status": elig.eligibility_status,
            "eligibility_flag": elig.eligibility_flag,
            "eligible_for_arpi": elig.eligibility_flag,
            "eligibility_date": elig.eligibility_date,
            "eligibility_reason": elig.eligibility_reason,
            "ineligibility_reason": elig.ineligibility_reason,
            "clinical_exclusion_reason": elig.clinical_exclusion_reason,
            "contraindication_flag": elig.contraindication_flag,
            "data_sufficiency_flag": elig.data_sufficiency_flag,
            "eligibility_rule_version": elig.eligibility_rule_version,
            "initial_care_setting": first_encounter.care_setting,
            "initial_provider_specialty": first_encounter.provider_specialty,
            "pathway_care_setting": pathway_setting,
            "referral_status": first_referral.referral_status
            if first_referral is not None
            else "not_applicable",
            "referral_completed_flag": bool(
                first_referral is not None and first_referral.referral_status == "completed"
            ),
            "referral_delay_days": (
                (first_referral.completion_date - first_referral.referral_date).days
                if first_referral is not None and pd.notna(first_referral.completion_date)
                else pd.NA
            ),
            "decision_owner_specialty": first_referral.decision_owner_specialty
            if first_referral is not None
            else "urology",
            "active_surveillance_eligible_flag": bool(
                as_record is not None and as_record.as_eligibility_flag
            ),
            "active_surveillance_status": as_record.as_status
            if as_record is not None
            else "not_applicable",
            "active_surveillance_start_date": as_record.as_start_date
            if as_record is not None
            else pd.NaT,
            "active_surveillance_exit_date": as_record.as_exit_date
            if as_record is not None
            else pd.NaT,
            "active_surveillance_exit_reason": as_record.as_exit_reason
            if as_record is not None
            else pd.NA,
            "active_surveillance_reclassification_flag": bool(
                as_record is not None and as_record.as_reclassification_event_flag
            ),
            "active_surveillance_reclassification_date": (
                as_record.as_reclassification_date if as_record is not None else pd.NaT
            ),
            "treatment_initiated": treatment_initiated,
            "treatment_episode_id": first_episode.treatment_episode_id
            if treatment_initiated
            else pd.NA,
            "treatment_start_date": start,
            "days_to_initiation": days_to_initiation,
            "initiation_90d_status": initiation_status,
            "initiated_within_30d": bool(
                treatment_initiated and elig.eligibility_flag and days_to_initiation <= 30
            ),
            "initiated_within_60d": bool(
                treatment_initiated and elig.eligibility_flag and days_to_initiation <= 60
            ),
            "initiated_within_90d": initiation_status == "INITIATED_WITHIN_90D",
            "eligible_not_initiated_90d": initiation_status == "NOT_INITIATED_WITHIN_90D",
            "initial_regimen": first_regimen.regimen_name if first_regimen is not None else pd.NA,
            "initial_regimen_type": first_regimen.regimen_type
            if first_regimen is not None
            else pd.NA,
            "combination_strategy": first_regimen.combination_strategy
            if first_regimen is not None
            else pd.NA,
            "intensification_flag": bool(
                first_regimen is not None and first_regimen.intensification_flag
            ),
            "regimen_component_count": len(first_components),
            "prescription_event_count": len(tracking_events),
            "max_refill_gap_days": max_gap,
            "event_coverage_until_date": coverage_until,
            "discontinuation_flag": bool(
                treatment_initiated and first_episode.discontinuation_flag
            ),
            "discontinuation_date": discontinuation_date,
            "switch_flag": bool(treatment_initiated and first_episode.switch_flag),
            "switch_date": switch_date,
            "restart_flag": bool(treatment_initiated and first_episode.restart_flag),
            "follow_up_days": int(obs.follow_up_days_from_diagnosis),
            "treatment_follow_up_days": (censor - start).days if treatment_initiated else pd.NA,
            "observation_start_date": obs.observation_start_date,
            "observation_end_date": obs.observation_end_date,
            "last_observed_date": obs.last_observed_date,
            "loss_to_follow_up_date": obs.loss_to_follow_up_date,
            "death_date": obs.death_date,
            "censor_date": obs.censor_date,
            "censor_reason": obs.censor_reason,
            "progression_event": out.progression_event,
            "progression_date": out.progression_date,
            "hospitalisation_flag": out.hospitalisation_flag,
            "first_hospitalisation_date": out.first_hospitalisation_date,
            "adverse_event_flag": out.adverse_event_flag,
            "death_flag": out.death_flag,
            "lost_to_follow_up_flag": out.lost_to_follow_up_flag,
            "final_outcome_status": out.outcome_status,
            "synthetic_data_flag": True,
            "synthetic_scenario_version": person.synthetic_scenario_version,
            "persistence_rule_version": config["clinical_rule_configuration"]["clinical_rules"][
                "persistence"
            ]["version"],
            **persistence,
        }
        rows.append(row)
    journey = pd.DataFrame(rows)
    boolean_columns = [column for column in journey.columns if column.startswith("persistent_")]
    for column in boolean_columns:
        journey[column] = journey[column].astype("boolean")
    return journey
