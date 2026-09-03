"""Run the governed, component-based synthetic mHSPC intensification analysis."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

WINDOWS = (30, 60, 90)
PATHWAY = "mhspc_mcspc"
QUALIFYING_CLASSES = {"ARPI", "chemotherapy"}
OUTPUT_NAMES = (
    "intensification_funnel.csv",
    "intensification_by_segment.csv",
    "intensification_timing.csv",
    "intensification_reconciliation.csv",
    "intensification_summary.md",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_certified_data_dir() -> Path:
    """Use the existing EDA resolver without hardcoding a machine path."""
    eda_dir = project_root() / "eda"
    if str(eda_dir) not in sys.path:
        sys.path.insert(0, str(eda_dir))
    from config import resolve_analytical_data_dir

    data_dir, _ = resolve_analytical_data_dir()
    return data_dir


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flags_path = project_root() / "outputs" / "eda" / "cohort_patient_flags.parquet"
    if not flags_path.is_file():
        raise FileNotFoundError(
            "Missing governed cohort output: "
            f"{flags_path}. Run the existing cohort EDA first "
            "(eda/02_cohort_engine.py) before running this analysis."
        )

    data_dir = resolve_certified_data_dir()
    flags = pd.read_parquet(flags_path)
    episodes = pd.read_parquet(data_dir / "treatment_episode.parquet")
    regimens = pd.read_parquet(data_dir / "treatment_regimen.parquet")
    components = pd.read_parquet(data_dir / "treatment_regimen_component.parquet")
    return flags, episodes, regimens, components


def require_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    missing = sorted(columns.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def prepare_inputs(
    flags: pd.DataFrame,
    episodes: pd.DataFrame,
    regimens: pd.DataFrame,
    components: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
            "initial_care_setting",
            "market_code",
            *(f"observable_for_{window}d" for window in WINDOWS),
            *(f"initiated_within_{window}d" for window in WINDOWS),
        },
    )
    require_columns(
        episodes,
        "treatment_episode.parquet",
        {"patient_id", "treatment_episode_id", "treatment_start_date"},
    )
    require_columns(
        regimens,
        "treatment_regimen.parquet",
        {"patient_id", "treatment_episode_id", "regimen_id", "intensification_flag"},
    )
    require_columns(
        components,
        "treatment_regimen_component.parquet",
        {
            "patient_id",
            "treatment_episode_id",
            "regimen_id",
            "component_start_date",
            "drug_class",
        },
    )

    flags = flags.loc[
        flags.pathway.eq(PATHWAY) & flags.pathway_membership.fillna(False)
    ].copy()
    if flags.patient_id.duplicated().any():
        raise ValueError("Governed mHSPC cohort flags contain duplicate patient_id rows")
    for frame, date_columns in (
        (flags, ["cohort_index_date", "censor_date", "initiation_date"]),
        (episodes, ["treatment_start_date"]),
        (components, ["component_start_date"]),
    ):
        for column in date_columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return flags, episodes, regimens, components


def build_patient_detail(
    flags: pd.DataFrame,
    episodes: pd.DataFrame,
    regimens: pd.DataFrame,
    components: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    detail_columns = [
        "patient_id",
        "market_code",
        "initial_care_setting",
        "cohort_index_date",
        "censor_date",
        "eligible_candidate",
        "initiation_date",
        "pathway_membership",
        *(f"observable_for_{window}d" for window in WINDOWS),
        *(f"initiated_within_{window}d" for window in WINDOWS),
    ]
    detail = flags[detail_columns].copy()
    detail["eligible"] = detail.eligible_candidate.fillna(False)

    post_index = episodes.merge(
        detail[["patient_id", "cohort_index_date", "censor_date"]],
        on="patient_id",
        how="inner",
        validate="many_to_one",
    )
    post_index = post_index.loc[
        post_index.treatment_start_date.ge(post_index.cohort_index_date)
        & post_index.treatment_start_date.le(post_index.censor_date)
    ].copy()
    first_episode = (
        post_index.sort_values(["patient_id", "treatment_start_date", "treatment_episode_id"])
        .drop_duplicates("patient_id")
        [["patient_id", "treatment_episode_id", "treatment_start_date"]]
        .rename(columns={"treatment_start_date": "first_treatment_start_date"})
    )
    detail = detail.merge(first_episode, on="patient_id", how="left", validate="one_to_one")

    observed_episodes = post_index[
        ["patient_id", "treatment_episode_id", "treatment_start_date"]
    ].rename(columns={"treatment_start_date": "episode_start_date"})
    component_detail = components.merge(
        observed_episodes,
        on=["patient_id", "treatment_episode_id"],
        how="inner",
        validate="many_to_one",
    ).merge(
        detail[["patient_id", "cohort_index_date", "censor_date"]],
        on="patient_id",
        how="inner",
        validate="many_to_one",
    )
    component_detail["component_start_date"] = pd.to_datetime(
        component_detail["component_start_date"], errors="coerce"
    )
    qualifying = component_detail.loc[
        component_detail.drug_class.isin(QUALIFYING_CLASSES)
        & component_detail.component_start_date.ge(component_detail.cohort_index_date)
        & component_detail.component_start_date.le(component_detail.censor_date)
    ].copy()
    first_intensification = (
        qualifying.sort_values(["patient_id", "component_start_date", "component_id"])
        .drop_duplicates("patient_id")
        [["patient_id", "component_start_date", "episode_start_date"]]
        .rename(
            columns={
                "component_start_date": "first_intensification_date",
                "episode_start_date": "intensification_episode_start_date",
            }
        )
    )
    detail = detail.merge(first_intensification, on="patient_id", how="left", validate="one_to_one")

    regimen_observed = regimens.merge(
        observed_episodes[["patient_id", "treatment_episode_id"]],
        on=["patient_id", "treatment_episode_id"],
        how="inner",
        validate="many_to_one",
    )
    regimen_any = (
        regimen_observed.groupby("patient_id", as_index=False)["intensification_flag"]
        .any()
        .rename(columns={"intensification_flag": "regimen_intensification_any"})
    )
    detail = detail.merge(regimen_any, on="patient_id", how="left", validate="one_to_one")
    detail["regimen_intensification_any"] = detail.regimen_intensification_any.fillna(False)
    detail["component_intensification_any"] = detail.first_intensification_date.notna()
    return detail, component_detail


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def classify(detail: pd.DataFrame, window: int) -> pd.Series:
    evaluable = detail.eligible & detail[f"observable_for_{window}d"]
    initiated = detail[f"initiated_within_{window}d"].fillna(False)
    landmark = detail.cohort_index_date + pd.to_timedelta(window, unit="D")
    intensified = (
        detail.first_intensification_date.notna()
        & detail.first_intensification_date.le(landmark)
    )
    states = pd.Series(pd.NA, index=detail.index, dtype="string")
    states.loc[evaluable & ~initiated] = "UNTREATED"
    states.loc[evaluable & initiated & ~intensified] = "TREATED_NOT_INTENSIFIED"
    states.loc[evaluable & initiated & intensified] = "INTENSIFIED"
    return states


def metrics(detail: pd.DataFrame, window: int) -> dict[str, Any]:
    states = classify(detail, window)
    evaluable = states.notna()
    denominator = int(evaluable.sum())
    counts = {state: int(states.eq(state).sum()) for state in (
        "UNTREATED", "TREATED_NOT_INTENSIFIED", "INTENSIFIED"
    )}
    initiated = int((evaluable & detail[f"initiated_within_{window}d"].fillna(False)).sum())
    return {
        "window_days": window,
        "evaluable_eligible_n": denominator,
        "any_treatment_initiation_n": initiated,
        "any_treatment_initiation_rate": rate(initiated, denominator),
        "intensified_n": counts["INTENSIFIED"],
        "intensified_rate": rate(counts["INTENSIFIED"], denominator),
        "treated_not_intensified_n": counts["TREATED_NOT_INTENSIFIED"],
        "treated_not_intensified_rate": rate(counts["TREATED_NOT_INTENSIFIED"], denominator),
        "untreated_n": counts["UNTREATED"],
        "untreated_rate": rate(counts["UNTREATED"], denominator),
        "category_total_n": sum(counts.values()),
    }


def build_segment_outputs(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    segment_definitions = {
        "overall": [("ALL", detail)],
        "market": [
            (str(value), group)
            for value, group in detail.groupby("market_code", dropna=False)
        ],
        "initial_care_setting": [
            ("<missing>" if pd.isna(value) else str(value), group)
            for value, group in detail.groupby("initial_care_setting", dropna=False)
        ],
    }
    for dimension, groups in segment_definitions.items():
        for segment, group in groups:
            for window in WINDOWS:
                rows.append(
                    {
                        "segment_dimension": dimension,
                        "segment": segment,
                        **metrics(group, window),
                    }
                )
    segment_output = pd.DataFrame(rows)
    funnel = segment_output.loc[
        segment_output.segment_dimension.eq("overall")
    ].drop(columns=["segment_dimension", "segment"])
    return funnel, segment_output


def summary_statistics(values: pd.Series) -> tuple[int, float | None, float | None, float | None]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return 0, None, None, None
    return int(values.size), float(values.median()), float(values.quantile(0.25)), float(values.quantile(0.75))


def build_timing_output(detail: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for window in WINDOWS:
        evaluable = detail.eligible & detail[f"observable_for_{window}d"]
        landmark = detail.cohort_index_date + pd.to_timedelta(window, unit="D")
        observed = evaluable & detail.first_intensification_date.notna()
        observed &= detail.first_intensification_date.le(landmark)
        index_days = (
            detail.loc[observed, "first_intensification_date"]
            - detail.loc[observed, "cohort_index_date"]
        ).dt.days
        delayed = observed & detail.first_intensification_date.gt(detail.first_treatment_start_date)
        treatment_days = (
            detail.loc[delayed, "first_intensification_date"]
            - detail.loc[delayed, "first_treatment_start_date"]
        ).dt.days
        index_n, index_median, index_q1, index_q3 = summary_statistics(index_days)
        treatment_n, treatment_median, treatment_q1, treatment_q3 = summary_statistics(treatment_days)
        rows.append(
            {
                "window_days": window,
                "intensification_observed_n": index_n,
                "index_to_intensification_median_days": index_median,
                "index_to_intensification_iqr_low_days": index_q1,
                "index_to_intensification_iqr_high_days": index_q3,
                "delayed_add_on_observed_n": treatment_n,
                "treatment_to_intensification_median_days": treatment_median,
                "treatment_to_intensification_iqr_low_days": treatment_q1,
                "treatment_to_intensification_iqr_high_days": treatment_q3,
            }
        )
    return pd.DataFrame(rows)


def build_reconciliation(detail: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(name: str, count: int, details: str, hard_failure: bool = True) -> None:
        rows.append(
            {
                "check_name": name,
                "status": "FAIL" if count else "PASS",
                "violation_count": count,
                "details": details,
                "hard_failure": hard_failure,
            }
        )

    index_violations = int(
        (detail.first_intensification_date < detail.cohort_index_date).fillna(False).sum()
    )
    episode_violations = int(
        (detail.first_intensification_date < detail.intensification_episode_start_date).fillna(False).sum()
    )
    censor_violations = int(
        (detail.first_intensification_date > detail.censor_date).fillna(False).sum()
    )
    add("intensification_not_before_index", index_violations, "first_intensification_date >= cohort_index_date")
    add("intensification_not_before_episode_start", episode_violations, "component start >= corresponding episode start")
    add("intensification_not_after_censor", censor_violations, "component start <= censor_date")

    for window in WINDOWS:
        states = classify(detail, window)
        evaluable = detail.eligible & detail[f"observable_for_{window}d"]
        initiated = detail[f"initiated_within_{window}d"].fillna(False)
        intensified_without_treatment = int((evaluable & states.eq("INTENSIFIED") & ~initiated).sum())
        total_mismatch = int(states.notna().sum() - sum(int(states.eq(state).sum()) for state in (
            "UNTREATED", "TREATED_NOT_INTENSIFIED", "INTENSIFIED"
        )))
        add(
            f"intensified_without_treatment_{window}d",
            intensified_without_treatment,
            "INTENSIFIED patients must also be initiated",
        )
        add(
            f"category_total_mismatch_{window}d",
            total_mismatch,
            "landmark category totals must equal evaluable denominator",
        )

        existing = flags[f"initiated_within_{window}d"].fillna(False)
        recomputed = (
            detail.eligible
            & detail.first_treatment_start_date.notna()
            & detail.first_treatment_start_date.le(
                detail.cohort_index_date + pd.to_timedelta(window, unit="D")
            )
            & detail.first_treatment_start_date.ge(detail.cohort_index_date)
            & detail.first_treatment_start_date.le(detail.censor_date)
        )
        existing_by_patient = flags.set_index("patient_id")[f"initiated_within_{window}d"].fillna(False)
        comparable = detail.patient_id.isin(existing_by_patient.index)
        existing_aligned = detail.patient_id.map(existing_by_patient).fillna(False)
        mismatch = int((comparable & (existing_aligned.ne(recomputed))).sum())
        add(
            f"any_treatment_reconciliation_{window}d",
            mismatch,
            "governed initiation flag must match independently checked episode timing",
            hard_failure=False,
        )

    regimen_mismatch = int(
        detail.component_intensification_any.ne(detail.regimen_intensification_any).sum()
    )
    add(
        "component_vs_regimen_intensification_mismatch",
        regimen_mismatch,
        "report component-derived status versus regimen-level intensification_flag",
        hard_failure=False,
    )
    return pd.DataFrame(rows)


def write_summary(
    output_dir: Path,
    funnel: pd.DataFrame,
    timing: pd.DataFrame,
    reconciliation: pd.DataFrame,
) -> None:
    failures = int(reconciliation.status.eq("FAIL").sum())
    mismatch = reconciliation.loc[
        reconciliation.check_name.eq("component_vs_regimen_intensification_mismatch"),
        "violation_count",
    ].iloc[0]
    lines = [
        "# Synthetic mHSPC Treatment Intensification",
        "",
        "> Exploratory, scenario-supported intensification analysis. Synthetic data only; not clinical guidance or causal evidence.",
        "",
        "## Scope",
        "",
        "The primary population is the governed `mhspc_mcspc` pathway from `outputs/eda/cohort_patient_flags.parquet`. Existing eligibility, index, censoring, observability, and treatment-initiation fields are reused.",
        "",
        "Synthetic intensification is defined from the earliest post-index, pre-censor ARPI or chemotherapy component linked to an observed treatment episode. ADT monotherapy is not intensified. The regimen-level flag is reconciliation-only.",
        "",
        "## Results",
        "",
        "The aggregate KPI results are in `intensification_funnel.csv`; segment results are limited to overall, market, and initial care setting in `intensification_by_segment.csv`.",
        "",
        "Timing summaries are in `intensification_timing.csv` and are restricted to evaluable patients with an observable component-derived date.",
        "",
        f"Validation recorded {failures} failing check row(s). Component-versus-regimen mismatches: {int(mismatch)} patient(s). Review `intensification_reconciliation.csv` before interpreting results.",
        "",
        "## Limitations and Guardrails",
        "",
        "- All data are synthetic and all findings are exploratory/descriptive.",
        "- No causal claims, clinical recommendations, real-world market-size claims, or invented financial value are supported.",
        "- The ARPI/chemotherapy rule is scenario-supported synthetic intensification, not authoritative clinical guidance.",
        "- Results depend on governed cohort definitions, normalized treatment lineage, and censor-aware 30/60/90-day evaluability.",
        "- This work does not modify upstream cohort or treatment logic and does not infer events after censoring.",
    ]
    (output_dir / "intensification_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    flags, episodes, regimens, components = prepare_inputs(*load_inputs())
    detail, _ = build_patient_detail(flags, episodes, regimens, components)
    funnel, by_segment = build_segment_outputs(detail)
    timing = build_timing_output(detail)
    reconciliation = build_reconciliation(detail, flags)

    output_dir = Path(__file__).resolve().parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    funnel.to_csv(output_dir / "intensification_funnel.csv", index=False)
    by_segment.to_csv(output_dir / "intensification_by_segment.csv", index=False)
    timing.to_csv(output_dir / "intensification_timing.csv", index=False)
    reconciliation.to_csv(output_dir / "intensification_reconciliation.csv", index=False)
    write_summary(output_dir, funnel, timing, reconciliation)

    hard_failures = reconciliation.loc[
        reconciliation.hard_failure & reconciliation.status.eq("FAIL")
    ]
    if not hard_failures.empty:
        checks = ", ".join(hard_failures.check_name)
        raise AssertionError(
            "Treatment intensification validation failed; inspect "
            f"{output_dir / 'intensification_reconciliation.csv'}: {checks}"
        )

    print(f"Wrote treatment intensification outputs to {output_dir}")


if __name__ == "__main__":
    run()