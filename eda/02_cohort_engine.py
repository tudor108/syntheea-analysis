"""Build auditable patient-by-pathway cohort flags and attrition contracts."""

# ruff: noqa: E501

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from cohort_config import (
    COHORT_BASELINE_DAYS,
    COHORT_INITIATION_WINDOWS,
    COHORT_PATHWAYS,
    COHORT_PRIMARY_WINDOW_DAYS,
)
from config import (
    ANALYSIS_DISCLAIMER,
    OUTPUT_DIR,
    ensure_output_directories,
    resolve_analytical_data_dir,
    write_eda_artifact_manifest,
)

PATHWAY_LABELS = {
    "mhspc_mcspc": "mHSPC/mCSPC advanced disease",
    "nmcrpc": "nmCRPC",
    "mcrpc": "mCRPC",
    "active_surveillance": "Active surveillance",
}
GOVERNED_STATES = {
    "localized",
    "locally_advanced",
    "mHSPC",
    "mCRPC",
    "metastatic_other",
    "unknown",
}


def load_tables(analytical_dir: Path) -> dict[str, pd.DataFrame]:
    """Load only certified tables used by the cohort engine."""
    names = (
        "patient",
        "diagnosis",
        "disease_state_event",
        "eligibility",
        "observation",
        "encounter",
        "active_surveillance",
        "treatment_episode",
        "treatment_regimen",
        "outcome",
        "patient_journey",
    )
    return {name: pd.read_parquet(analytical_dir / f"{name}.parquet") for name in names}


def cohort_definitions() -> pd.DataFrame:
    """Return explicit definitions before any cohort counts are calculated."""
    common_exclusions = (
        "No prostate-cancer flag; missing/invalid state or index; index after censor; "
        "insufficient governed evidence; explicit contraindication where applicable."
    )
    return pd.DataFrame(
        [
            {
                "pathway": "mhspc_mcspc",
                "pathway_label": PATHWAY_LABELS["mhspc_mcspc"],
                "computability": "PROXY-BASED",
                "conceptual_definition": "Synthetic mHSPC/mCSPC patients meeting the governed ARPI diagnostic denominator; not clinical eligibility.",
                "operational_definition": "Exact mHSPC state evidence plus eligibility.eligibility_flag=true under ARPI-ELIG-SYN-v2.0.",
                "required_fields": "prostate cancer; mHSPC/mCSPC state; age; contraindication/comorbidity evidence; prior treatment; observability",
                "actual_fields_used": "diagnosis.prostate_cancer_flag; disease_state_event.state=mHSPC; eligibility.{mhspc_flag,eligibility_flag,contraindication_flag,data_sufficiency_flag,possible_followup_days}; patient.age_at_index; treatment_episode dates; observation.censor_date",
                "inclusion_rules": "mHSPC state event and explicit governed synthetic eligibility flag; 30/60/90 evaluability is handled separately.",
                "exclusion_rules": common_exclusions,
                "index_date_rule": "eligibility_date when populated; otherwise mHSPC state date/diagnosis date only for pre-eligibility funnel audit.",
                "baseline_period": f"{COHORT_BASELINE_DAYS} days. Pre-index clinical lookback is unavailable and NOT COMPUTABLE.",
                "initiation_window": "First normalized treatment episode on/after index; sensitivity at 30, 60 and 90 days.",
                "follow_up_requirement": "Censor date reaches the selected initiation landmark; governed eligibility also requires at least 90 possible days.",
                "censoring_rule": "Earliest of death, loss to follow-up, or administrative end; dataset end is not discontinuation.",
                "known_limitations": "Only mHSPC is present; mCSPC is not a recorded synonym. Eligibility is a synthetic ARPI proxy, not a clinical treatment rule.",
                "confidence_level": "HIGH within the synthetic contract; PROXY ONLY clinically",
            },
            {
                "pathway": "nmcrpc",
                "pathway_label": PATHWAY_LABELS["nmcrpc"],
                "computability": "NOT COMPUTABLE",
                "conceptual_definition": "Non-metastatic castration-resistant prostate cancer pathway.",
                "operational_definition": "Would require an explicit nmCRPC state plus non-metastatic and castration-resistant evidence at a dated index.",
                "required_fields": "nmCRPC state; non-metastatic evidence; castration resistance; dated index; eligibility criteria; treatment history; observability",
                "actual_fields_used": "Schema inspection only; disease_state_event contains no nmCRPC value.",
                "inclusion_rules": "None: the governed release has zero explicit nmCRPC records.",
                "exclusion_rules": "No patient is relabelled or inferred as nmCRPC.",
                "index_date_rule": "NOT COMPUTABLE",
                "baseline_period": "NOT COMPUTABLE",
                "initiation_window": "NOT COMPUTABLE",
                "follow_up_requirement": "NOT COMPUTABLE",
                "censoring_rule": "Would use the governed censor date if a cohort existed.",
                "known_limitations": "The required clinical state and eligibility definition are absent. mCRPC or metastatic_other are not substituted.",
                "confidence_level": "NOT COMPUTABLE",
            },
            {
                "pathway": "mcrpc",
                "pathway_label": PATHWAY_LABELS["mcrpc"],
                "computability": "PROXY-BASED",
                "conceptual_definition": "Patients entering an explicit dated mCRPC state, including observed mHSPC-to-mCRPC transitions.",
                "operational_definition": "disease_state_event.state=mCRPC; proxy eligibility requires valid state/index, age 50-90, no recorded contraindication, sufficient evidence and configured minimum possible follow-up.",
                "required_fields": "mCRPC state/date; prior treatment; age; contraindication/comorbidity evidence; indication-specific eligibility; observability",
                "actual_fields_used": "disease_state_event.{state,state_date,previous_state}; patient.age_at_index/comorbidity_score; eligibility contraindication/data-sufficiency/follow-up proxies; normalized treatment episodes; observation.censor_date",
                "inclusion_rules": "Exact mCRPC event. Proxy eligibility is never labelled eligible_observed.",
                "exclusion_rules": common_exclusions,
                "index_date_rule": "First exact mCRPC state date.",
                "baseline_period": f"{COHORT_BASELINE_DAYS} days required; prior treatment is described from normalized episodes.",
                "initiation_window": "First treatment episode beginning on/after the mCRPC state date; 30/60/90-day sensitivity.",
                "follow_up_requirement": "Censor date reaches each selected landmark.",
                "censoring_rule": "Governed earliest terminal boundary; prior ongoing treatment is not a new initiation.",
                "known_limitations": "No mCRPC-specific clinical eligibility or line-appropriateness definition exists; results are PROXY ONLY.",
                "confidence_level": "LOW; PROXY ONLY",
            },
            {
                "pathway": "active_surveillance",
                "pathway_label": PATHWAY_LABELS["active_surveillance"],
                "computability": "PROXY-BASED",
                "conceptual_definition": "Localized patients evaluated for the separate synthetic active-surveillance pathway.",
                "operational_definition": "Presence in active_surveillance; eligible_observed uses as_eligibility_flag. Initiation means AS uptake (as_start_date), never treatment initiation.",
                "required_fields": "localized disease; risk/grade; age/complexity; AS eligibility/status/start; observation window",
                "actual_fields_used": "disease_state_event.state=localized; active_surveillance.{as_eligibility_flag,as_start_date,as_status}; diagnosis risk/grade; patient age/complexity; observation.censor_date",
                "inclusion_rules": "Explicit active_surveillance record; eligibility uses the governed synthetic AS flag.",
                "exclusion_rules": "Metastatic disease is never placed in the AS denominator; AS ineligibility remains explicit.",
                "index_date_rule": "Diagnosis date proxy because no separate AS eligibility-assessment date is collected.",
                "baseline_period": f"{COHORT_BASELINE_DAYS} days; pre-diagnosis baseline is unavailable.",
                "initiation_window": "AS start/uptake within 30/60/90 days of diagnosis proxy index; not a therapy-gap metric.",
                "follow_up_requirement": "Censor date reaches each selected AS-uptake landmark.",
                "censoring_rule": "Governed censor date; no event is inferred after censor.",
                "known_limitations": "Index is proxied by diagnosis and AS uptake is not treatment. Do not compare its gap directly with metastatic-treatment gaps.",
                "confidence_level": "MEDIUM within synthetic AS rules; PROXY ONLY clinically",
            },
        ]
    )


def _write_definition_markdown(definitions: pd.DataFrame) -> None:
    lines = [
        "# Cohort definitions",
        "",
        f"> **{ANALYSIS_DISCLAIMER}**",
        "",
        "The engine uses a patient-by-pathway audit grain. A patient may enter mHSPC and later mCRPC; those dated memberships remain separate. Active surveillance never shares a denominator with metastatic pathways.",
        "",
    ]
    for row in definitions.itertuples(index=False):
        lines.extend(
            [
                f"## {row.pathway_label} — {row.computability}",
                "",
                f"- **Conceptual definition:** {row.conceptual_definition}",
                f"- **Operational definition:** {row.operational_definition}",
                f"- **Required fields:** {row.required_fields}",
                f"- **Actual fields used:** {row.actual_fields_used}",
                f"- **Inclusion:** {row.inclusion_rules}",
                f"- **Exclusion:** {row.exclusion_rules}",
                f"- **Index date:** {row.index_date_rule}",
                f"- **Baseline:** {row.baseline_period}",
                f"- **Initiation:** {row.initiation_window}",
                f"- **Follow-up:** {row.follow_up_requirement}",
                f"- **Censoring:** {row.censoring_rule}",
                f"- **Limitations:** {row.known_limitations}",
                f"- **Confidence:** {row.confidence_level}",
                "",
            ]
        )
    lines.extend(
        [
            "## Outcome interpretation",
            "",
            "- `initiated_within_*d` is treatment initiation for mHSPC/mCSPC and mCRPC, AS uptake for active surveillance, and null for nmCRPC.",
            "- `eligible_observed` means an explicit governed flag exists in the synthetic dataset; it does not mean real clinical eligibility.",
            "- `eligible_proxy` is used only for mCRPC and is labelled PROXY-BASED in every aggregate.",
            "- `eligibility_uncertain` remains separate from explicit ineligibility.",
            "- Pre-index baseline history, nmCRPC, financial value and causal effects are NOT COMPUTABLE.",
        ]
    )
    (OUTPUT_DIR / "cohort_definitions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _base_patient_frame(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    patient = tables["patient"][
        [
            "patient_id",
            "market_code",
            "market_depth",
            "age_at_index",
            "comorbidity_score",
            "complexity_segment",
        ]
    ]
    diagnosis = tables["diagnosis"][
        [
            "patient_id",
            "diagnosis_date",
            "prostate_cancer_flag",
            "prostate_stage",
            "metastatic_flag",
            "metastatic_site",
            "data_quality_flag",
        ]
    ]
    eligibility = tables["eligibility"][
        [
            "patient_id",
            "mhspc_flag",
            "eligibility_flag",
            "eligibility_status",
            "eligibility_date",
            "eligibility_reason",
            "ineligibility_reason",
            "clinical_exclusion_reason",
            "contraindication_flag",
            "data_sufficiency_flag",
            "possible_followup_days",
            "minimum_followup_required_days",
            "eligibility_rule_version",
        ]
    ]
    observation = tables["observation"][
        [
            "patient_id",
            "observation_start_date",
            "observation_end_date",
            "censor_date",
            "censor_reason",
            "follow_up_days_from_diagnosis",
        ]
    ]
    first_encounter = (
        tables["encounter"]
        .sort_values(["patient_id", "encounter_date", "sequence_number", "encounter_id"])
        .drop_duplicates("patient_id")[["patient_id", "provider_specialty", "care_setting"]]
        .rename(
            columns={
                "provider_specialty": "initial_provider_specialty",
                "care_setting": "initial_care_setting",
            }
        )
    )
    frame = patient
    for other in (diagnosis, eligibility, observation, first_encounter):
        frame = frame.merge(other, on="patient_id", how="left", validate="one_to_one")
    return frame


def _state_evidence(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    events = tables["disease_state_event"].copy()
    events["state_date"] = pd.to_datetime(events.state_date)
    ordered = events.sort_values(["patient_id", "state_date", "disease_state_event_id"])
    first = ordered.drop_duplicates("patient_id").set_index("patient_id")
    latest = ordered.drop_duplicates("patient_id", keep="last").set_index("patient_id")
    mhspc = ordered[ordered.state.eq("mHSPC")].drop_duplicates("patient_id").set_index("patient_id")
    mcrpc = ordered[ordered.state.eq("mCRPC")].drop_duplicates("patient_id").set_index("patient_id")
    patient_ids = tables["patient"].patient_id
    return pd.DataFrame(
        {
            "patient_id": patient_ids,
            "initial_disease_state": patient_ids.map(first.state),
            "initial_state_date": patient_ids.map(first.state_date),
            "latest_disease_state": patient_ids.map(latest.state),
            "latest_state_date": patient_ids.map(latest.state_date),
            "mhspc_state_date": patient_ids.map(mhspc.state_date),
            "mcrpc_state_date": patient_ids.map(mcrpc.state_date),
            "mcrpc_previous_state": patient_ids.map(mcrpc.previous_state),
        }
    )


def _prepare_cross_product(base: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Create one row per patient per required pathway without inferring absent states."""
    state = _state_evidence(tables)
    active_surveillance = tables["active_surveillance"][
        [
            "patient_id",
            "as_eligibility_flag",
            "as_start_date",
            "as_status",
            "as_exit_date",
            "transition_to_treatment_flag",
        ]
    ]
    enriched = base.merge(state, on="patient_id", how="left", validate="one_to_one").merge(
        active_surveillance,
        on="patient_id",
        how="left",
        validate="one_to_one",
    )
    paths = pd.DataFrame({"pathway": list(COHORT_PATHWAYS), "_cross_key": 1})
    enriched["_cross_key"] = 1
    flags = enriched.merge(paths, on="_cross_key", how="inner").drop(columns="_cross_key")
    flags["pathway_label"] = flags.pathway.map(PATHWAY_LABELS)

    membership = pd.Series(False, index=flags.index)
    membership |= flags.pathway.eq("mhspc_mcspc") & flags.mhspc_state_date.notna()
    membership |= flags.pathway.eq("mcrpc") & flags.mcrpc_state_date.notna()
    membership |= flags.pathway.eq("active_surveillance") & flags.as_status.notna()
    flags["pathway_membership"] = membership
    flags["active_surveillance_flag"] = flags.as_status.notna()

    flags["disease_state"] = flags.latest_disease_state.astype("string")
    flags["pathway_disease_state"] = pd.Series(pd.NA, index=flags.index, dtype="string")
    flags.loc[flags.pathway.eq("mhspc_mcspc") & membership, "pathway_disease_state"] = "mHSPC"
    flags.loc[flags.pathway.eq("mcrpc") & membership, "pathway_disease_state"] = "mCRPC"
    as_mask = flags.pathway.eq("active_surveillance") & membership
    flags.loc[as_mask, "pathway_disease_state"] = flags.loc[
        as_mask, "initial_disease_state"
    ].astype("string")

    explicit_eligibility_date = pd.to_datetime(flags.pop("eligibility_date"))
    flags["eligibility_date"] = pd.NaT
    flags["eligibility_date_source"] = "not_applicable"
    mhspc_mask = flags.pathway.eq("mhspc_mcspc") & membership
    flags.loc[mhspc_mask, "eligibility_date"] = explicit_eligibility_date[mhspc_mask].fillna(
        pd.to_datetime(flags.loc[mhspc_mask, "mhspc_state_date"])
    )
    flags.loc[mhspc_mask & explicit_eligibility_date.notna(), "eligibility_date_source"] = (
        "explicit_eligibility_date"
    )
    flags.loc[mhspc_mask & explicit_eligibility_date.isna(), "eligibility_date_source"] = (
        "mHSPC_state_date_proxy"
    )
    mcrpc_mask = flags.pathway.eq("mcrpc") & membership
    flags.loc[mcrpc_mask, "eligibility_date"] = pd.to_datetime(
        flags.loc[mcrpc_mask, "mcrpc_state_date"]
    )
    flags.loc[mcrpc_mask, "eligibility_date_source"] = "mCRPC_state_date_proxy"
    flags.loc[as_mask, "eligibility_date"] = pd.to_datetime(flags.loc[as_mask, "diagnosis_date"])
    flags.loc[as_mask, "eligibility_date_source"] = "diagnosis_date_proxy_for_AS_assessment"
    flags["cohort_index_date"] = pd.to_datetime(flags.eligibility_date)

    flags["valid_disease_state_evidence"] = (
        flags.prostate_cancer_flag.fillna(False)
        & flags.initial_disease_state.isin(GOVERNED_STATES)
        & pd.to_datetime(flags.initial_state_date).notna()
    )
    flags["valid_index_date"] = (
        flags.pathway_membership
        & flags.cohort_index_date.notna()
        & flags.cohort_index_date.le(pd.to_datetime(flags.censor_date))
    )
    baseline_days = (flags.cohort_index_date - pd.to_datetime(flags.observation_start_date)).dt.days
    flags["baseline_observation_days"] = baseline_days
    flags["required_baseline_observed"] = flags.valid_index_date & baseline_days.ge(
        COHORT_BASELINE_DAYS
    )
    flags["follow_up_days"] = (pd.to_datetime(flags.censor_date) - flags.cohort_index_date).dt.days
    for window in COHORT_INITIATION_WINDOWS:
        flags[f"observable_for_{window}d"] = flags.valid_index_date & flags.follow_up_days.ge(
            window
        )

    explicit_mhspc = mhspc_mask & flags.eligibility_flag.fillna(False)
    explicit_as = as_mask & flags.as_eligibility_flag.fillna(False)
    mcrpc_proxy = (
        mcrpc_mask
        & flags.valid_index_date
        & flags.required_baseline_observed
        & flags.age_at_index.between(50, 90)
        & ~flags.contraindication_flag.fillna(True)
        & flags.data_sufficiency_flag.fillna(False)
        & flags.possible_followup_days.ge(flags.minimum_followup_required_days)
    )
    flags["eligible_observed"] = explicit_mhspc | explicit_as
    flags["eligible_proxy"] = mcrpc_proxy
    flags["eligibility_uncertain"] = False
    flags.loc[
        mhspc_mask & flags.eligibility_status.eq("INSUFFICIENT_DATA"),
        "eligibility_uncertain",
    ] = True
    flags.loc[
        mcrpc_mask
        & (
            flags.data_sufficiency_flag.isna()
            | flags.contraindication_flag.isna()
            | flags.age_at_index.isna()
        ),
        "eligibility_uncertain",
    ] = True
    flags["eligible_candidate"] = flags.eligible_observed | flags.eligible_proxy
    flags["eligibility_classification"] = "not_relevant_pathway"
    flags.loc[membership, "eligibility_classification"] = "explicitly_ineligible"
    flags.loc[flags.eligibility_uncertain, "eligibility_classification"] = "eligibility_uncertain"
    flags.loc[flags.eligible_proxy, "eligibility_classification"] = "eligible_proxy"
    flags.loc[flags.eligible_observed, "eligibility_classification"] = "eligible_observed"
    flags["eligibility_confidence"] = flags.pathway.map(
        {
            "mhspc_mcspc": "HIGH_SYNTHETIC_PROXY",
            "nmcrpc": "NOT_COMPUTABLE",
            "mcrpc": "LOW_PROXY_ONLY",
            "active_surveillance": "MEDIUM_SYNTHETIC_PROXY",
        }
    )
    return flags


def _attach_treatment_and_outcomes(
    flags: pd.DataFrame, tables: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    episodes = tables["treatment_episode"].copy()
    for column in (
        "treatment_start_date",
        "treatment_end_date",
        "discontinuation_date",
        "switch_date",
        "restart_date",
    ):
        episodes[column] = pd.to_datetime(episodes[column])
    regimens = tables["treatment_regimen"][
        [
            "treatment_episode_id",
            "regimen_name",
            "regimen_type",
            "combination_strategy",
            "intensification_flag",
        ]
    ]
    episode_detail = episodes.merge(
        regimens, on="treatment_episode_id", how="left", validate="one_to_one"
    )
    member_index = flags.loc[
        flags.pathway_membership & flags.pathway.isin(["mhspc_mcspc", "mcrpc"]),
        ["patient_id", "pathway", "cohort_index_date"],
    ]
    candidates = member_index.merge(episode_detail, on="patient_id", how="inner")
    candidates = candidates[
        candidates.treatment_start_date.ge(candidates.cohort_index_date)
    ].sort_values(
        ["patient_id", "pathway", "treatment_start_date", "treatment_line", "treatment_episode_id"]
    )
    first = candidates.drop_duplicates(["patient_id", "pathway"]).set_index(
        ["patient_id", "pathway"]
    )
    key = pd.MultiIndex.from_frame(flags[["patient_id", "pathway"]])
    attached_columns = (
        "treatment_episode_id",
        "treatment_start_date",
        "treatment_end_date",
        "treatment_status",
        "treatment_intent",
        "discontinuation_flag",
        "discontinuation_date",
        "switch_flag",
        "switch_date",
        "restart_flag",
        "restart_date",
        "regimen_name",
        "regimen_type",
        "combination_strategy",
        "intensification_flag",
    )
    for column in attached_columns:
        flags[f"first_post_index_{column}"] = key.map(first[column])

    flags["initiation_event_type"] = flags.pathway.map(
        {
            "mhspc_mcspc": "treatment_episode_start",
            "nmcrpc": "not_computable",
            "mcrpc": "post_mCRPC_treatment_episode_start",
            "active_surveillance": "active_surveillance_start_not_treatment",
        }
    )
    flags["initiation_date"] = pd.to_datetime(flags.first_post_index_treatment_start_date)
    as_rows = flags.pathway.eq("active_surveillance") & flags.pathway_membership
    flags.loc[as_rows, "initiation_date"] = pd.to_datetime(flags.loc[as_rows, "as_start_date"])
    flags["days_to_initiation"] = (
        pd.to_datetime(flags.initiation_date) - flags.cohort_index_date
    ).dt.days

    for window in COHORT_INITIATION_WINDOWS:
        evaluable = flags.eligible_candidate & flags[f"observable_for_{window}d"]
        result = pd.Series(pd.NA, index=flags.index, dtype="boolean")
        result.loc[evaluable] = flags.loc[evaluable, "days_to_initiation"].between(0, window)
        flags[f"initiated_within_{window}d"] = result

    non_intensified = pd.Series(pd.NA, index=flags.index, dtype="boolean")
    mhspc_treated = flags.pathway.eq("mhspc_mcspc") & flags.initiation_date.notna()
    non_intensified.loc[mhspc_treated] = ~flags.loc[
        mhspc_treated, "first_post_index_intensification_flag"
    ].fillna(False).astype(bool)
    flags["non_intensified_regimen"] = non_intensified

    treatment_start = pd.to_datetime(flags.first_post_index_treatment_start_date)
    discontinuation_date = pd.to_datetime(flags.first_post_index_discontinuation_date)
    switch_date = pd.to_datetime(flags.first_post_index_switch_date)
    landmark = treatment_start + pd.Timedelta(days=365)
    explicit_event = discontinuation_date.le(landmark) | switch_date.le(landmark)
    evaluable_12m = treatment_start.notna() & (
        pd.to_datetime(flags.censor_date).ge(landmark) | explicit_event
    )
    discontinued = pd.Series(pd.NA, index=flags.index, dtype="boolean")
    discontinued.loc[evaluable_12m] = discontinuation_date.loc[evaluable_12m].le(
        landmark.loc[evaluable_12m]
    )
    flags["discontinued_within_12_months"] = discontinued
    event_date = pd.concat([discontinuation_date, switch_date], axis=1).min(axis=1)
    flags["days_to_discontinuation_or_switch"] = (event_date - treatment_start).dt.days
    switched = pd.Series(pd.NA, index=flags.index, dtype="boolean")
    switched.loc[treatment_start.notna()] = switch_date.loc[treatment_start.notna()].notna()
    flags["switched_treatment"] = switched

    post_index_episodes = member_index.merge(episodes, on="patient_id", how="inner")
    post_index_episodes = post_index_episodes[
        post_index_episodes.treatment_start_date.ge(post_index_episodes.cohort_index_date)
    ]
    restart_lookup = (
        post_index_episodes.assign(
            restart_evidence=lambda frame: (
                frame.transition_type.eq("restart") | frame.restart_flag.fillna(False)
            )
        )
        .groupby(["patient_id", "pathway"])
        .restart_evidence.any()
    )
    restart = pd.Series(pd.NA, index=flags.index, dtype="boolean")
    treatment_path_member = flags.pathway_membership & flags.pathway.isin(["mhspc_mcspc", "mcrpc"])
    restart.loc[treatment_path_member] = (
        key[treatment_path_member].map(restart_lookup).fillna(False)
    )
    flags["restarted_after_gap"] = restart

    first_episode_by_patient = episodes.groupby("patient_id").treatment_start_date.min()
    flags["prior_treatment_status"] = np.where(
        flags.pathway_membership
        & flags.patient_id.map(first_episode_by_patient).lt(flags.cohort_index_date),
        "prior_treatment_observed",
        "no_prior_treatment_observed",
    )

    outcome = tables["outcome"].set_index("patient_id")
    progression_date = pd.to_datetime(flags.patient_id.map(outcome.progression_date))
    flags["progression_event"] = (
        flags.pathway_membership
        & progression_date.notna()
        & progression_date.ge(flags.cohort_index_date)
    )
    flags["progression_date"] = progression_date.where(flags.progression_event)
    flags["death_or_censoring"] = flags.censor_reason.map(
        {
            "death": "death",
            "loss_to_follow_up": "loss_to_follow_up_censoring",
            "administrative_end": "administrative_censoring",
        }
    ).fillna("other_censoring")
    flags["censoring_status"] = flags.death_or_censoring
    return flags


def _add_segments_and_warnings(flags: pd.DataFrame) -> pd.DataFrame:
    flags["market_group"] = flags.market_depth.map({"deep": "Deep", "scan": "Scan"})
    flags["academic_vs_community"] = np.select(
        [
            flags.initial_care_setting.eq("academic_oncology"),
            flags.initial_care_setting.astype("string").str.startswith("community", na=False),
        ],
        ["academic", "community"],
        default="mixed_or_other",
    )
    flags["age_band"] = pd.cut(
        flags.age_at_index,
        bins=[0, 64, 74, 84, np.inf],
        labels=["<65", "65-74", "75-84", "85+"],
    ).astype("string")
    flags["comorbidity_band"] = pd.cut(
        flags.comorbidity_score,
        bins=[-1, 1, 3, np.inf],
        labels=["0-1", "2-3", "4+"],
    ).astype("string")
    index_year = flags.cohort_index_date.dt.year
    flags["calendar_period"] = pd.cut(
        index_year,
        bins=[2018, 2020, 2022, 2024, np.inf],
        labels=["2019-2020", "2021-2022", "2023-2024", "2025+"],
    ).astype("string")

    essential = [
        flags.initial_disease_state.isna(),
        flags.cohort_index_date.isna(),
        flags.age_at_index.isna(),
        flags.comorbidity_score.isna(),
        flags.initial_care_setting.isna(),
        flags.initial_provider_specialty.isna(),
    ]
    flags["row_missingness_rate"] = pd.concat(essential, axis=1).mean(axis=1)

    warnings: list[str] = []
    excluded: list[str] = []
    for row in flags.itertuples(index=False):
        row_warnings: list[str] = []
        if row.pathway == "nmcrpc":
            row_warnings.append("nmCRPC_state_and_definition_unavailable")
        if row.pathway == "mcrpc" and row.pathway_membership:
            row_warnings.append("mCRPC_clinical_eligibility_is_proxy_only")
        if row.pathway == "active_surveillance" and row.pathway_membership:
            row_warnings.append("AS_initiation_means_uptake_not_treatment")
        if row.pathway_membership and pd.isna(row.initial_care_setting):
            row_warnings.append("missing_care_setting")
        if row.pathway_membership and pd.isna(row.initial_provider_specialty):
            row_warnings.append("missing_provider_specialty")
        warnings.append(";".join(row_warnings) if row_warnings else "none")

        if not row.prostate_cancer_flag:
            reason = "not_prostate_cancer"
        elif not row.valid_disease_state_evidence:
            reason = "invalid_or_missing_disease_state_evidence"
        elif not row.pathway_membership:
            reason = (
                "pathway_not_computable_in_dataset"
                if row.pathway == "nmcrpc"
                else "not_member_of_pathway"
            )
        elif not row.valid_index_date:
            reason = "missing_or_invalid_index_date"
        elif not row.required_baseline_observed:
            reason = "required_baseline_not_observed"
        elif row.eligibility_uncertain:
            reason = "eligibility_uncertain"
        elif not row.eligible_candidate:
            reason = "explicit_or_proxy_ineligibility"
        elif not getattr(row, f"observable_for_{COHORT_PRIMARY_WINDOW_DAYS}d"):
            reason = f"not_observable_for_{COHORT_PRIMARY_WINDOW_DAYS}d"
        else:
            reason = "included_in_primary_eligible_denominator"
        excluded.append(reason)
    flags["data_quality_warning"] = warnings
    flags["excluded_reason"] = excluded
    return flags


def build_attrition(flags: pd.DataFrame) -> pd.DataFrame:
    """Calculate the ten requested sequential/branch funnel steps per pathway."""
    rows: list[dict[str, Any]] = []
    for pathway in COHORT_PATHWAYS:
        group = flags[flags.pathway.eq(pathway)].copy()
        masks: dict[int, pd.Series] = {}
        masks[1] = pd.Series(True, index=group.index)
        masks[2] = masks[1] & group.prostate_cancer_flag.fillna(False)
        masks[3] = masks[2] & group.valid_disease_state_evidence
        masks[4] = masks[3] & group.pathway_membership
        masks[5] = masks[4] & group.valid_index_date
        masks[6] = masks[5] & group.required_baseline_observed
        masks[7] = masks[6] & group[f"observable_for_{COHORT_PRIMARY_WINDOW_DAYS}d"]
        masks[8] = masks[7] & group.eligible_candidate
        masks[9] = masks[8] & group[f"initiated_within_{COHORT_PRIMARY_WINDOW_DAYS}d"].fillna(False)
        gap_or_non_intensified = group[f"initiated_within_{COHORT_PRIMARY_WINDOW_DAYS}d"].eq(
            False
        ).fillna(False) | group.non_intensified_regimen.eq(True).fillna(False)
        masks[10] = masks[8] & gap_or_non_intensified
        labels = {
            1: "All unique patients",
            2: "Prostate cancer patients",
            3: "Valid disease-state evidence",
            4: "Relevant pathway",
            5: "Valid index date",
            6: "Required baseline observation",
            7: f"Observable through {COHORT_PRIMARY_WINDOW_DAYS} days",
            8: "Eligible patients",
            9: "Initiated pathway within 90 days",
            10: "Non-initiated or non-intensified branch",
        }
        exclusion_reasons = {
            1: "none",
            2: "prostate_cancer_flag is false/missing",
            3: "missing or ungoverned disease-state evidence",
            4: "not a member of this separate pathway",
            5: "missing index or index after censor",
            6: "observation does not cover configured baseline",
            7: "censoring before the 90-day landmark",
            8: "explicit/proxy ineligibility or uncertainty",
            9: "no qualifying initiation within 90 days",
            10: "outcome branch: no initiation or mHSPC non-intensification",
        }
        original = int(masks[1].sum())
        for step in range(1, 11):
            reference_step = 8 if step == 10 else max(1, step - 1)
            previous = int(masks[reference_step].sum())
            count = int(masks[step].sum())
            computability = (
                "NOT COMPUTABLE"
                if pathway == "nmcrpc" and step >= 4
                else "PROXY-BASED"
                if pathway in {"mcrpc", "active_surveillance"} and step >= 8
                else "DESCRIPTIVE"
            )
            rows.append(
                {
                    "pathway": pathway,
                    "pathway_label": PATHWAY_LABELS[pathway],
                    "step_number": step,
                    "funnel_step": labels[step],
                    "step_kind": "outcome_branch" if step == 10 else "sequential",
                    "comparison_step": reference_step,
                    "patient_count": count,
                    "percentage_of_previous": count / previous if previous else None,
                    "percentage_of_original": count / original if original else None,
                    "exclusion_count": max(previous - count, 0),
                    "exclusion_reason": exclusion_reasons[step],
                    "missingness_burden": float(
                        group.loc[masks[step], "row_missingness_rate"].mean()
                    )
                    if count
                    else None,
                    "confidence": (
                        "NOT COMPUTABLE"
                        if computability == "NOT COMPUTABLE"
                        else "LOW"
                        if computability == "PROXY-BASED" and pathway == "mcrpc"
                        else "MEDIUM"
                        if computability == "PROXY-BASED"
                        else "HIGH_SYNTHETIC"
                    ),
                    "conclusion_type": computability,
                }
            )
    return pd.DataFrame(rows)


def validate_flags(
    flags: pd.DataFrame, attrition: pd.DataFrame, tables: dict[str, pd.DataFrame]
) -> None:
    expected_rows = len(tables["patient"]) * len(COHORT_PATHWAYS)
    if len(flags) != expected_rows:
        raise ValueError(f"Expected {expected_rows:,} patient-pathway rows, found {len(flags):,}")
    if flags.duplicated(["patient_id", "pathway"]).any():
        raise ValueError("patient_id + pathway is not unique")
    if flags.loc[flags.pathway.eq("nmcrpc"), "pathway_membership"].any():
        raise ValueError("nmCRPC was inferred despite being absent")
    as_members = flags.pathway.eq("active_surveillance") & flags.pathway_membership
    if flags.loc[as_members, "metastatic_flag"].fillna(False).any():
        raise ValueError("Active surveillance contains metastatic patients")
    for left, right in ((30, 60), (60, 90)):
        contradiction = (
            flags[f"initiated_within_{left}d"].eq(True)
            & flags[f"initiated_within_{right}d"].ne(True)
        ).fillna(False)
        if contradiction.any():
            raise ValueError(f"Initiation flags are not monotonic for {left}/{right} days")
    after_censor = flags.initiation_date.notna() & pd.to_datetime(flags.initiation_date).gt(
        pd.to_datetime(flags.censor_date)
    )
    if after_censor.any():
        raise ValueError("Initiation events occur after censor")
    expected_mhspc_90 = int(tables["patient_journey"].initiated_within_90d.sum())
    observed_mhspc_90 = int(
        flags.loc[flags.pathway.eq("mhspc_mcspc"), "initiated_within_90d"].fillna(False).sum()
    )
    if expected_mhspc_90 != observed_mhspc_90:
        raise ValueError(
            f"mHSPC 90-day initiation mismatch: normalized={observed_mhspc_90}, mart={expected_mhspc_90}"
        )
    if len(attrition) != len(COHORT_PATHWAYS) * 10:
        raise ValueError("Attrition output does not contain ten steps per pathway")


def _output_columns() -> list[str]:
    return [
        "patient_id",
        "pathway",
        "pathway_label",
        "pathway_membership",
        "market_code",
        "market_group",
        "market_depth",
        "disease_state",
        "pathway_disease_state",
        "initial_disease_state",
        "latest_disease_state",
        "active_surveillance_flag",
        "active_surveillance_status",
        "as_status",
        "as_start_date",
        "eligible_candidate",
        "eligible_observed",
        "eligible_proxy",
        "eligibility_uncertain",
        "eligibility_classification",
        "eligibility_confidence",
        "eligibility_date",
        "eligibility_date_source",
        "cohort_index_date",
        "valid_disease_state_evidence",
        "valid_index_date",
        "required_baseline_observed",
        "baseline_observation_days",
        "observable_for_30d",
        "observable_for_60d",
        "observable_for_90d",
        "initiation_event_type",
        "initiation_date",
        "days_to_initiation",
        "initiated_within_30d",
        "initiated_within_60d",
        "initiated_within_90d",
        "non_intensified_regimen",
        "first_post_index_treatment_episode_id",
        "first_post_index_treatment_start_date",
        "first_post_index_regimen_name",
        "first_post_index_regimen_type",
        "first_post_index_combination_strategy",
        "first_post_index_intensification_flag",
        "discontinued_within_12_months",
        "days_to_discontinuation_or_switch",
        "switched_treatment",
        "restarted_after_gap",
        "progression_event",
        "progression_date",
        "death_or_censoring",
        "censoring_status",
        "censor_date",
        "censor_reason",
        "follow_up_days",
        "initial_care_setting",
        "initial_provider_specialty",
        "academic_vs_community",
        "age_at_index",
        "age_band",
        "comorbidity_score",
        "comorbidity_band",
        "complexity_segment",
        "metastatic_site",
        "calendar_period",
        "prior_treatment_status",
        "row_missingness_rate",
        "excluded_reason",
        "data_quality_warning",
    ]


def main() -> None:
    started = datetime.now(UTC)
    ensure_output_directories()
    required_prompt1 = (
        OUTPUT_DIR / "data_inventory.csv",
        OUTPUT_DIR / "data_dictionary.csv",
        OUTPUT_DIR / "data_quality_summary.csv",
        OUTPUT_DIR / "eda_run_manifest.json",
    )
    missing = [path.name for path in required_prompt1 if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Prompt 1 EDA outputs are required but missing: {missing}")
    dq = pd.read_csv(OUTPUT_DIR / "data_quality_summary.csv")
    blockers = dq[dq.severity.isin(["P0", "P1"]) & dq.status.eq("ISSUE")]
    if not blockers.empty:
        raise RuntimeError(
            f"Cohort engine stopped because Prompt 1 has {len(blockers)} unresolved P0/P1 issues"
        )

    analytical_dir, selection_metadata = resolve_analytical_data_dir()
    tables = load_tables(analytical_dir)
    definitions = cohort_definitions()
    definitions.to_csv(OUTPUT_DIR / "cohort_definitions.csv", index=False)
    _write_definition_markdown(definitions)

    base = _base_patient_frame(tables)
    flags = _prepare_cross_product(base, tables)
    flags = _attach_treatment_and_outcomes(flags, tables)
    flags = _add_segments_and_warnings(flags)
    flags["active_surveillance_status"] = flags.as_status.astype("string")
    attrition = build_attrition(flags)
    validate_flags(flags, attrition, tables)

    output = flags[_output_columns()].sort_values(["patient_id", "pathway"], ignore_index=True)
    output.to_parquet(OUTPUT_DIR / "cohort_patient_flags.parquet", index=False)
    attrition.to_csv(OUTPUT_DIR / "cohort_attrition.csv", index=False)
    summary = {
        "status": "PASS_WITH_DECLARED_LIMITATIONS",
        "started_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "analytical_data_dir": str(analytical_dir),
        "dataset_selection": selection_metadata,
        "patient_pathway_rows": len(output),
        "unique_patients": int(output.patient_id.nunique()),
        "pathway_members": {
            pathway: int(output.loc[output.pathway.eq(pathway), "pathway_membership"].sum())
            for pathway in COHORT_PATHWAYS
        },
        "eligible_candidates": {
            pathway: int(output.loc[output.pathway.eq(pathway), "eligible_candidate"].sum())
            for pathway in COHORT_PATHWAYS
        },
        "initiation_90d": {
            pathway: int(
                output.loc[output.pathway.eq(pathway), "initiated_within_90d"].fillna(False).sum()
            )
            for pathway in COHORT_PATHWAYS
        },
        "python": sys.version,
    }
    (OUTPUT_DIR / "cohort_engine_run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    write_eda_artifact_manifest(analytical_dir, selection_metadata)
    print(
        f"Cohort engine complete: {len(output):,} patient-pathway rows; "
        f"mHSPC 90d={summary['initiation_90d']['mhspc_mcspc']:,}; "
        "nmCRPC=NOT COMPUTABLE"
    )


if __name__ == "__main__":
    main()
