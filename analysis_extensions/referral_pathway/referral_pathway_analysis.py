"""Run the minimum descriptive referral/handoff pathway analysis."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

WINDOW_DAYS = 90
PATHWAY = "mhspc_mcspc"
RELEVANT_REASON = "advanced_prostate_pathway_review"
RELEVANT_DESTINATION = "medical_oncology"
QUALIFYING_CLASSES = {"ARPI", "chemotherapy"}
MIN_SEGMENT_N = 30


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_certified_data_dir() -> Path:
    eda_dir = project_root() / "eda"
    if str(eda_dir) not in sys.path:
        sys.path.insert(0, str(eda_dir))
    from config import resolve_analytical_data_dir

    data_dir, _ = resolve_analytical_data_dir()
    return data_dir


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flags_path = project_root() / "outputs" / "eda" / "cohort_patient_flags.parquet"
    if not flags_path.is_file():
        raise FileNotFoundError(
            f"Missing governed cohort output: {flags_path}. "
            "Run eda/02_cohort_engine.py first."
        )
    data_dir = resolve_certified_data_dir()
    stage2_path = (
        project_root()
        / "analysis_extensions"
        / "treatment_intensification"
        / "outputs"
        / "intensification_funnel.csv"
    )
    if not stage2_path.is_file():
        raise FileNotFoundError(
            f"Missing validated Stage 2 output: {stage2_path}. "
            "Run the treatment-intensification analysis first."
        )
    return (
        pd.read_parquet(flags_path),
        pd.read_parquet(data_dir / "referral.parquet"),
        pd.read_parquet(data_dir / "treatment_episode.parquet"),
        pd.read_parquet(data_dir / "treatment_regimen_component.parquet"),
        pd.read_csv(stage2_path),
    )


def require_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    missing = sorted(columns.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def prepare_cohort(
    flags: pd.DataFrame,
    referrals: pd.DataFrame,
    episodes: pd.DataFrame,
    components: pd.DataFrame,
    stage2: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    require_columns(
        flags,
        "cohort_patient_flags.parquet",
        {
            "patient_id",
            "pathway",
            "pathway_membership",
            "eligible_candidate",
            "cohort_index_date",
            "censor_date",
            "initiation_date",
            "initiated_within_90d",
            "observable_for_90d",
            "market_code",
            "initial_care_setting",
        },
    )
    require_columns(
        referrals,
        "referral.parquet",
        {
            "patient_id",
            "referral_id",
            "referral_reason",
            "destination_specialty",
            "referral_date",
            "completion_date",
            "referral_status",
        },
    )
    require_columns(episodes, "treatment_episode.parquet", {"patient_id", "treatment_episode_id", "treatment_start_date"})
    require_columns(
        components,
        "treatment_regimen_component.parquet",
        {"patient_id", "treatment_episode_id", "component_start_date", "drug_class"},
    )
    require_columns(stage2, "intensification_funnel.csv", {"window_days", "intensified_n"})

    for frame, columns in (
        (flags, ["cohort_index_date", "censor_date", "initiation_date"]),
        (referrals, ["referral_date", "completion_date"]),
        (episodes, ["treatment_start_date"]),
        (components, ["component_start_date"]),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")

    cohort = flags.loc[
        flags.pathway.eq(PATHWAY)
        & flags.pathway_membership.fillna(False)
        & flags.eligible_candidate.fillna(False)
    ].copy()
    if cohort.patient_id.duplicated().any():
        raise ValueError("Governed eligible mHSPC cohort contains duplicate patient_id rows")
    cohort["evaluable_90d"] = cohort.observable_for_90d.fillna(False)
    cohort["initiated_90d"] = cohort.initiated_within_90d.fillna(False)

    relevant = referrals.loc[
        referrals.referral_reason.eq(RELEVANT_REASON)
        & referrals.destination_specialty.eq(RELEVANT_DESTINATION)
    ].copy()
    return cohort, relevant, stage2


def build_detail(
    cohort: pd.DataFrame,
    relevant: pd.DataFrame,
    episodes: pd.DataFrame,
    components: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    detail = cohort[
        [
            "patient_id",
            "market_code",
            "initial_care_setting",
            "cohort_index_date",
            "censor_date",
            "initiation_date",
            "initiated_90d",
            "evaluable_90d",
        ]
    ].copy()
    first_referral = (
        relevant.sort_values(["patient_id", "referral_date", "referral_id"])
        .drop_duplicates("patient_id")
        [["patient_id", "referral_id", "referral_date"]]
        .rename(columns={"referral_date": "first_referral_date"})
    )
    completed = relevant.loc[
        relevant.referral_status.eq("completed") & relevant.completion_date.notna()
    ]
    first_completion = (
        completed.sort_values(["patient_id", "completion_date", "referral_id"])
        .drop_duplicates("patient_id")
        [["patient_id", "completion_date"]]
    )
    detail = detail.merge(first_referral, on="patient_id", how="left", validate="one_to_one")
    detail = detail.merge(first_completion, on="patient_id", how="left", validate="one_to_one")

    post_index_episodes = episodes.merge(
        detail[["patient_id", "cohort_index_date", "censor_date"]],
        on="patient_id",
        how="inner",
        validate="many_to_one",
    )
    post_index_episodes = post_index_episodes.loc[
        post_index_episodes.treatment_start_date.ge(post_index_episodes.cohort_index_date)
        & post_index_episodes.treatment_start_date.le(post_index_episodes.censor_date)
    ]
    first_treatment = (
        post_index_episodes.sort_values(["patient_id", "treatment_start_date", "treatment_episode_id"])
        .drop_duplicates("patient_id")
        [["patient_id", "treatment_episode_id", "treatment_start_date"]]
        .rename(columns={"treatment_start_date": "first_treatment_start_date"})
    )
    detail = detail.merge(first_treatment, on="patient_id", how="left", validate="one_to_one")

    observed_components = components.merge(
        post_index_episodes[["patient_id", "treatment_episode_id", "treatment_start_date"]],
        on=["patient_id", "treatment_episode_id"],
        how="inner",
        validate="many_to_one",
    ).merge(
        detail[["patient_id", "cohort_index_date", "censor_date"]],
        on="patient_id",
        how="inner",
        validate="many_to_one",
    )
    observed_components = observed_components.merge(
        first_treatment[["patient_id", "treatment_episode_id"]],
        on=["patient_id", "treatment_episode_id"],
        how="inner",
        validate="many_to_one",
    )
    qualifying = observed_components.loc[
        observed_components.drug_class.isin(QUALIFYING_CLASSES)
        & observed_components.component_start_date.ge(observed_components.cohort_index_date)
        & observed_components.component_start_date.le(observed_components.censor_date)
    ]
    first_intensification = (
        qualifying.sort_values(["patient_id", "component_start_date", "component_id"])
        .drop_duplicates("patient_id")
        [["patient_id", "component_start_date"]]
        .rename(columns={"component_start_date": "first_intensification_date"})
    )
    detail = detail.merge(first_intensification, on="patient_id", how="left", validate="one_to_one")

    detail["referral_created"] = detail.first_referral_date.notna()
    detail["referral_completed"] = detail.completion_date.notna()
    detail["intensified"] = detail.first_intensification_date.notna()
    detail["treated_without_completed_referral"] = detail.initiation_date.notna() & ~detail.referral_completed
    detail["intensified_without_completed_referral"] = (
        detail.intensified & detail.initiated_90d & ~detail.referral_completed
    )
    detail["relevant_referral_within_90d"] = detail.referral_created & detail.first_referral_date.le(
        detail.cohort_index_date + pd.Timedelta(days=WINDOW_DAYS)
    )
    detail["completed_referral_within_90d"] = detail.referral_completed & detail.completion_date.le(
        detail.cohort_index_date + pd.Timedelta(days=WINDOW_DAYS)
    )
    detail["treatment_before_completion"] = (
        detail.initiation_date.notna()
        & detail.completion_date.notna()
        & detail.initiation_date.lt(detail.completion_date)
    )
    detail["intensification_before_completion"] = (
        detail.first_intensification_date.notna()
        & detail.completion_date.notna()
        & detail.first_intensification_date.lt(detail.completion_date)
    )
    discrepancy_counts = {
        "eligible_with_any_referral_but_not_relevant": int(
            cohort.patient_id.isin(relevant.patient_id).eq(False).sum()
        ),
        "relevant_referral_duplicate_patient_count": int(
            relevant.groupby("patient_id").size().gt(1).sum()
        ),
    }
    return detail, discrepancy_counts


def timing_row(name: str, values: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    return {
        "metric": name,
        "observed_n": int(values.size),
        "median_days": float(values.median()) if not values.empty else None,
        "iqr_low_days": float(values.quantile(0.25)) if not values.empty else None,
        "iqr_high_days": float(values.quantile(0.75)) if not values.empty else None,
    }


def build_outputs(detail: pd.DataFrame, stage2: pd.DataFrame, discrepancy_counts: dict[str, int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    evaluable = detail.evaluable_90d
    pathway = pd.DataFrame(
        [
            {"stage": "governed_eligible_evaluable_mhspc", "n": int(evaluable.sum()), "rate": 1.0},
            {"stage": "relevant_referral_created", "n": int((evaluable & detail.referral_created).sum()), "rate": float((evaluable & detail.referral_created).sum() / evaluable.sum())},
            {"stage": "relevant_referral_completed_by_90d", "n": int((evaluable & detail.completed_referral_within_90d).sum()), "rate": float((evaluable & detail.completed_referral_within_90d).sum() / evaluable.sum())},
            {"stage": "any_treatment_initiated_by_90d", "n": int((evaluable & detail.initiated_90d).sum()), "rate": float((evaluable & detail.initiated_90d).sum() / evaluable.sum())},
            {"stage": "scenario_supported_intensified_by_90d", "n": int((evaluable & detail.initiated_90d & detail.intensified & detail.first_intensification_date.le(detail.cohort_index_date + pd.Timedelta(days=WINDOW_DAYS))).sum()), "rate": float((evaluable & detail.initiated_90d & detail.intensified & detail.first_intensification_date.le(detail.cohort_index_date + pd.Timedelta(days=WINDOW_DAYS))).sum() / evaluable.sum())},
            {"stage": "treated_without_completed_relevant_referral", "n": int((evaluable & detail.treated_without_completed_referral).sum()), "rate": float((evaluable & detail.treated_without_completed_referral).sum() / evaluable.sum())},
            {"stage": "intensified_without_completed_relevant_referral", "n": int((evaluable & detail.intensified_without_completed_referral).sum()), "rate": float((evaluable & detail.intensified_without_completed_referral).sum() / evaluable.sum())},
        ]
    )
    segment_rows: list[dict[str, Any]] = []
    segments = {"overall": [("ALL", detail)], "market": list(detail.groupby("market_code", dropna=False)), "initial_care_setting": list(detail.groupby("initial_care_setting", dropna=False))}
    for dimension, groups in segments.items():
        for value, group in groups:
            group = group.loc[group.evaluable_90d]
            if len(group) < MIN_SEGMENT_N:
                continue
            group_intensified = group.initiated_90d & group.intensified & group.first_intensification_date.le(group.cohort_index_date + pd.Timedelta(days=WINDOW_DAYS))
            segment_rows.append({"segment_dimension": dimension, "segment": "<missing>" if pd.isna(value) else str(value), "evaluable_n": len(group), "referral_completed_by_90d_n": int(group.completed_referral_within_90d.sum()), "referral_completed_by_90d_rate": float(group.completed_referral_within_90d.mean()), "treatment_initiated_by_90d_n": int(group.initiated_90d.sum()), "treatment_initiated_by_90d_rate": float(group.initiated_90d.mean()), "intensified_by_90d_n": int(group_intensified.sum()), "intensified_by_90d_rate": float(group_intensified.mean())})
    segment_output = pd.DataFrame(segment_rows)
    summary = pathway.assign(record_type="overall", segment_dimension="overall", segment="ALL")
    segment_summary = segment_output.rename(
        columns={
            "evaluable_n": "n",
            "referral_completed_by_90d_n": "completed_referral_n",
            "referral_completed_by_90d_rate": "completed_referral_rate",
            "treatment_initiated_by_90d_n": "treatment_n",
            "treatment_initiated_by_90d_rate": "treatment_rate",
            "intensified_by_90d_n": "intensified_n",
            "intensified_by_90d_rate": "intensified_rate",
        }
    )
    segment_summary["record_type"] = "segment"
    segment_summary["stage"] = "90d_segment"
    summary = pd.concat([summary, segment_summary], ignore_index=True, sort=False)

    timing = []
    completed = detail.referral_completed & detail.evaluable_90d
    timing.append(timing_row("referral_to_completion", (detail.loc[completed, "completion_date"] - detail.loc[completed, "first_referral_date"]).dt.days))
    treatment_linked = completed & detail.initiation_date.notna()
    timing.append(timing_row("completion_to_treatment", (detail.loc[treatment_linked, "initiation_date"] - detail.loc[treatment_linked, "completion_date"]).dt.days))
    intensification_linked = completed & detail.first_intensification_date.notna()
    timing.append(timing_row("completion_to_intensification", (detail.loc[intensification_linked, "first_intensification_date"] - detail.loc[intensification_linked, "completion_date"]).dt.days))
    timing.append(timing_row("eligibility_to_referral_note", (detail.loc[evaluable & detail.referral_created, "first_referral_date"] - detail.loc[evaluable & detail.referral_created, "cohort_index_date"]).dt.days))
    return summary, pd.DataFrame(timing)


def build_reconciliation(detail: pd.DataFrame, stage2: pd.DataFrame, discrepancy_counts: dict[str, int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    def add(name: str, count: int, details: str, hard_failure: bool = True) -> None:
        rows.append({"check_name": name, "status": "FAIL" if count else "PASS", "violation_count": count, "details": details, "hard_failure": hard_failure})
    add("referral_not_before_index", int((detail.first_referral_date < detail.cohort_index_date).fillna(False).sum()), "referral_date >= cohort_index_date")
    add("completed_referral_not_before_creation", int((detail.completion_date < detail.first_referral_date).fillna(False).sum()), "completion_date >= referral_date")
    referral_events = pd.read_parquet(resolve_certified_data_dir() / "referral.parquet")
    referral_events = referral_events.loc[
        referral_events.referral_reason.eq(RELEVANT_REASON)
        & referral_events.destination_specialty.eq(RELEVANT_DESTINATION)
    ].merge(detail[["patient_id", "cohort_index_date", "censor_date"]], on="patient_id", how="inner")
    referral_events["referral_date"] = pd.to_datetime(referral_events["referral_date"], errors="coerce")
    add("referral_not_after_censor", int((referral_events.referral_date > referral_events.censor_date).fillna(False).sum()), "all relevant referral_date values <= censor_date")
    add("treatment_before_completed_referral", int(detail.treatment_before_completion.sum()), "treatment does not precede completed referral")
    add("intensification_before_completed_referral", int(detail.intensification_before_completion.sum()), "intensification does not precede completed referral")
    governed_count = int(detail.initiated_90d.sum())
    eda_count = int(stage2.loc[stage2.window_days.eq(WINDOW_DAYS), "intensified_n"].iloc[0]) if False else None
    existing_eda = pd.read_csv(project_root() / "outputs" / "eda" / "treatment_gap_by_segment.csv")
    existing_eda = existing_eda.loc[existing_eda.pathway.eq(PATHWAY) & existing_eda.segment_dimension.eq("overall") & existing_eda.segment_value.eq("ALL") & existing_eda.window_days.eq(WINDOW_DAYS)]
    eda_initiated = int(existing_eda.initiated_n.iloc[0])
    add("governed_eda_treatment_initiation_reconciliation", abs(governed_count - eda_initiated), f"governed={governed_count}; existing_eda={eda_initiated}")
    stage2_intensified = int(stage2.loc[stage2.window_days.eq(WINDOW_DAYS), "intensified_n"].iloc[0])
    component_intensified = int((detail.evaluable_90d & detail.initiated_90d & detail.intensified & detail.first_intensification_date.le(detail.cohort_index_date + pd.Timedelta(days=WINDOW_DAYS))).sum())
    add("stage2_intensification_reconciliation", abs(component_intensified - stage2_intensified), f"component_derived={component_intensified}; stage2={stage2_intensified}")
    add("relevant_referral_definition_discrepancy", discrepancy_counts["eligible_with_any_referral_but_not_relevant"], "eligible referrals not matching the specified reason and destination", hard_failure=False)
    add("valid_treated_without_completed_referral", int(detail.treated_without_completed_referral.sum()), "valid synthetic exception; report only", hard_failure=False)
    add("valid_intensified_without_completed_referral", int(detail.intensified_without_completed_referral.sum()), "valid synthetic exception; report only", hard_failure=False)
    return pd.DataFrame(rows)


def write_summary(output_dir: Path, pathway: pd.DataFrame, timing: pd.DataFrame, reconciliation: pd.DataFrame) -> None:
    completed = int(pathway.loc[pathway.stage.eq("relevant_referral_completed_by_90d"), "n"].iloc[0])
    total = int(pathway.loc[pathway.stage.eq("governed_eligible_evaluable_mhspc"), "n"].iloc[0])
    lines = [
        "# Referral / Handoff Pathway Analysis",
        "",
        "> Descriptive synthetic pathway analysis only; no causal or clinical interpretation.",
        "",
        "The 90-day pathway reuses the governed eligible `mhspc_mcspc` denominator and initiation fields, then follows relevant referral creation, completion, treatment initiation, and scenario-supported component-derived intensification.",
        "",
        f"Within the evaluable denominator of {total:,}, {completed:,} patients had a relevant referral completed by 90 days. See `referral_pathway_summary.csv` for the aggregate and limited segment results, and `referral_timing.csv` for timing statistics.",
        "",
        "Referral creation timing is included only as a small descriptive note because it has little variation in this synthetic cohort. Referral completion is structurally coupled by the generator to initiation probability, treatment timing, provider selection, and chemotherapy availability; observed patterns must not be treated as causal or real-world evidence.",
        "",
        "The reconciliation file records valid synthetic cases treated or intensified without a completed referral as report-only observations, not data errors. It also records any mismatch between the specified relevant-referral definition and source rows.",
        "",
        "All data are synthetic. This analysis does not rank providers, model causality, estimate financial value, or modify upstream cohort/treatment logic.",
    ]
    (output_dir / "referral_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    flags, referrals, episodes, components, stage2 = load_inputs()
    cohort, relevant, stage2 = prepare_cohort(flags, referrals, episodes, components, stage2)
    detail, discrepancy_counts = build_detail(cohort, relevant, episodes, components)
    pathway, timing = build_outputs(detail, stage2, discrepancy_counts)
    reconciliation = build_reconciliation(detail, stage2, discrepancy_counts)
    output_dir = Path(__file__).resolve().parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    pathway.to_csv(output_dir / "referral_pathway_summary.csv", index=False)
    timing.to_csv(output_dir / "referral_timing.csv", index=False)
    reconciliation.to_csv(output_dir / "referral_reconciliation.csv", index=False)
    write_summary(output_dir, pathway, timing, reconciliation)
    hard_failures = reconciliation.loc[reconciliation.hard_failure & reconciliation.status.eq("FAIL")]
    if not hard_failures.empty:
        raise AssertionError("Referral pathway validation failed: " + ", ".join(hard_failures.check_name))
    print(f"Wrote referral pathway outputs to {output_dir}")


if __name__ == "__main__":
    run()
