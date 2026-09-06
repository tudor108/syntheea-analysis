"""Healthcare-oriented descriptive analyses for the synthetic journey mart.

The functions in this module are deliberately descriptive. They preserve the
denominator, right-censoring, missingness, and uncertainty conventions needed
for a healthcare analytics prototype, but they do not estimate treatment
effects or make clinical recommendations.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import sqrt
from pathlib import Path

import pandas as pd

from . import DISCLAIMER

DEFAULT_MISSINGNESS_FIELDS = (
    "race",
    "ethnicity",
    "insurance_type",
    "psa_value",
    "referral_delay_days",
    "event_coverage_until_date",
)
_PERSISTENCE_STATUSES = {
    "PERSISTENT",
    "DISCONTINUED",
    "SWITCHED",
    "CENSORED_NOT_EVALUABLE",
}


def _require_columns(frame: pd.DataFrame, columns: Sequence[str], frame_name: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{frame_name} is missing required columns: {', '.join(missing)}")


def _normalise_group_by(group_by: str | Sequence[str] | None) -> list[str]:
    if group_by is None:
        return []
    if isinstance(group_by, str):
        return [group_by]
    return list(group_by)


def _strata(frame: pd.DataFrame, group_by: str | Sequence[str] | None) -> pd.Series:
    columns = _normalise_group_by(group_by)
    _require_columns(frame, columns, "analysis input")
    if not columns:
        return pd.Series("all", index=frame.index, dtype="string")
    values = frame[columns].astype("string").fillna("missing")
    if len(columns) == 1:
        return values.iloc[:, 0].rename("stratum")
    return values.agg(" | ".join, axis=1).rename("stratum")


def _wilson_interval(successes: int, denominator: int, z: float = 1.96) -> tuple[float, float]:
    """Return a 95% Wilson interval without adding a scipy dependency."""
    if denominator == 0:
        return float("nan"), float("nan")
    proportion = successes / denominator
    z_squared = z**2
    scale = 1 + z_squared / denominator
    centre = (proportion + z_squared / (2 * denominator)) / scale
    half_width = (
        z
        * sqrt(proportion * (1 - proportion) / denominator + z_squared / (4 * denominator**2))
        / scale
    )
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def initiation_funnel(
    journey: pd.DataFrame,
    windows: Sequence[int] = (30, 60, 90),
    group_by: str | Sequence[str] | None = None,
) -> pd.DataFrame:
    """Summarise censor-aware initiation among eligible patients.

    ``not_initiated_n`` excludes patients whose observation ended before the
    selected initiation window. Those patients are reported separately as
    ``censored_n`` and are never silently counted as treatment gaps.
    """
    windows = tuple(int(window) for window in windows)
    if not windows or any(window <= 0 for window in windows):
        raise ValueError("windows must contain positive day counts")
    _require_columns(
        journey,
        ("eligibility_flag", "eligibility_date", "censor_date"),
        "patient_journey",
    )
    for window in windows:
        _require_columns(journey, (f"initiated_within_{window}d",), "patient_journey")

    eligible = journey["eligibility_flag"].fillna(False).astype(bool)
    eligibility_date = pd.to_datetime(journey["eligibility_date"], errors="coerce")
    censor_date = pd.to_datetime(journey["censor_date"], errors="coerce")
    incomplete_dates = eligible & (eligibility_date.isna() | censor_date.isna())
    if incomplete_dates.any():
        raise ValueError("Eligible rows require non-null eligibility_date and censor_date")

    strata = _strata(journey, group_by)
    rows: list[dict[str, object]] = []
    for window in windows:
        initiated = journey[f"initiated_within_{window}d"].fillna(False).astype(bool)
        censored = (
            eligible & ~initiated & (censor_date < eligibility_date + pd.Timedelta(days=window))
        )
        evaluable = eligible & ~censored
        not_initiated = evaluable & ~initiated
        for stratum in pd.unique(strata):
            in_group = strata.eq(stratum)
            eligible_n = int((eligible & in_group).sum())
            initiated_n = int((initiated & evaluable & in_group).sum())
            evaluable_n = int((evaluable & in_group).sum())
            censored_n = int((censored & in_group).sum())
            not_initiated_n = int((not_initiated & in_group).sum())
            rate_low, rate_high = _wilson_interval(initiated_n, evaluable_n)
            rows.append(
                {
                    "stratum": str(stratum),
                    "window_days": window,
                    "eligible_n": eligible_n,
                    "initiated_n": initiated_n,
                    "evaluable_n": evaluable_n,
                    "not_initiated_n": not_initiated_n,
                    "censored_n": censored_n,
                    "initiation_rate_evaluable": (
                        initiated_n / evaluable_n if evaluable_n else float("nan")
                    ),
                    "censoring_rate_eligible": (
                        censored_n / eligible_n if eligible_n else float("nan")
                    ),
                    "rate_ci_low": rate_low,
                    "rate_ci_high": rate_high,
                    "data_label": DISCLAIMER,
                }
            )
    return pd.DataFrame(rows)


def persistence_summary(
    journey: pd.DataFrame,
    gap_days: Sequence[int] = (30, 60, 90),
    group_by: str | Sequence[str] | None = None,
) -> pd.DataFrame:
    """Summarise 12-month persistence while retaining right-censored rows."""
    gap_days = tuple(int(gap) for gap in gap_days)
    if not gap_days or any(gap not in (30, 60, 90) for gap in gap_days):
        raise ValueError("gap_days must contain only 30, 60, or 90")
    _require_columns(journey, ("treatment_initiated",), "patient_journey")
    treatment_initiated = journey["treatment_initiated"].fillna(False).astype(bool)
    strata = _strata(journey, group_by)
    rows: list[dict[str, object]] = []
    for gap in gap_days:
        status_column = (
            "persistence_12m_status" if gap == 60 else f"persistence_12m_status_gap_{gap}d"
        )
        _require_columns(journey, (status_column,), "patient_journey")
        status = journey[status_column].astype("string")
        invalid = treatment_initiated & ~status.isin(_PERSISTENCE_STATUSES | {"NOT_APPLICABLE"})
        if invalid.any():
            raise ValueError(f"Treated rows contain unsupported values in {status_column}")
        # Local treatment episodes can be present for active-surveillance patients. Their
        # persistence target is intentionally NOT_APPLICABLE, so they are reported but do
        # not enter the ARPI persistence denominator.
        treated = treatment_initiated & status.ne("NOT_APPLICABLE")
        for stratum in pd.unique(strata):
            in_group = strata.eq(stratum)
            treated_group = treated & in_group
            treatment_initiated_n = int((treatment_initiated & in_group).sum())
            not_applicable_n = int(
                (treatment_initiated & status.eq("NOT_APPLICABLE") & in_group).sum()
            )
            persistent_n = int((treated_group & status.eq("PERSISTENT")).sum())
            discontinued_n = int((treated_group & status.eq("DISCONTINUED")).sum())
            switched_n = int((treated_group & status.eq("SWITCHED")).sum())
            censored_n = int((treated_group & status.eq("CENSORED_NOT_EVALUABLE")).sum())
            event_n = discontinued_n + switched_n
            evaluable_n = persistent_n + event_n
            rate_low, rate_high = _wilson_interval(persistent_n, evaluable_n)
            treated_n = int(treated_group.sum())
            rows.append(
                {
                    "stratum": str(stratum),
                    "gap_days": gap,
                    "treatment_initiated_n": treatment_initiated_n,
                    "treated_n": treated_n,
                    "not_applicable_n": not_applicable_n,
                    "persistent_n": persistent_n,
                    "discontinued_n": discontinued_n,
                    "switched_n": switched_n,
                    "non_persistent_evaluable_n": event_n,
                    "evaluable_n": evaluable_n,
                    "censored_n": censored_n,
                    "persistence_rate_evaluable": (
                        persistent_n / evaluable_n if evaluable_n else float("nan")
                    ),
                    "censoring_rate_treated": (
                        censored_n / treated_n if treated_n else float("nan")
                    ),
                    "rate_ci_low": rate_low,
                    "rate_ci_high": rate_high,
                    "data_label": DISCLAIMER,
                }
            )
    return pd.DataFrame(rows)


def referral_summary(
    referral: pd.DataFrame,
    group_by: str | Sequence[str] | None = "market_code",
) -> pd.DataFrame:
    """Summarise referral completion and delay by market or pathway stratum."""
    _require_columns(
        referral,
        ("referral_date", "completion_date", "referral_status"),
        "referral",
    )
    referral_date = pd.to_datetime(referral["referral_date"], errors="coerce")
    completion_date = pd.to_datetime(referral["completion_date"], errors="coerce")
    completed = referral["referral_status"].eq("completed")
    invalid = completed & (
        referral_date.isna() | completion_date.isna() | (completion_date < referral_date)
    )
    if invalid.any():
        raise ValueError("Completed referrals require a non-negative dated referral delay")
    delay_days = (completion_date - referral_date).dt.days
    strata = _strata(referral, group_by)
    rows: list[dict[str, object]] = []
    for stratum in pd.unique(strata):
        in_group = strata.eq(stratum)
        referrals_n = int(in_group.sum())
        completed_n = int((in_group & completed).sum())
        delays = delay_days[in_group & completed].dropna()
        rate_low, rate_high = _wilson_interval(completed_n, referrals_n)
        rows.append(
            {
                "stratum": str(stratum),
                "referrals_n": referrals_n,
                "completed_n": completed_n,
                "not_completed_n": referrals_n - completed_n,
                "completion_rate": completed_n / referrals_n if referrals_n else float("nan"),
                "median_delay_days": delays.median() if not delays.empty else float("nan"),
                "p90_delay_days": delays.quantile(0.90) if not delays.empty else float("nan"),
                "rate_ci_low": rate_low,
                "rate_ci_high": rate_high,
                "data_label": DISCLAIMER,
            }
        )
    return pd.DataFrame(rows)


def stratified_missingness(
    journey: pd.DataFrame,
    by: str | Sequence[str] = "market_code",
    columns: Sequence[str] = DEFAULT_MISSINGNESS_FIELDS,
) -> pd.DataFrame:
    """Report missingness by stratum, preserving explicit missing categories."""
    columns = tuple(columns)
    _require_columns(journey, columns, "patient_journey")
    strata = _strata(journey, by)
    rows: list[dict[str, object]] = []
    for column in columns:
        overall_rate = float(journey[column].isna().mean()) if len(journey) else float("nan")
        for stratum in pd.unique(strata):
            in_group = strata.eq(stratum)
            group_n = int(in_group.sum())
            missing_n = int(journey.loc[in_group, column].isna().sum())
            rate = missing_n / group_n if group_n else float("nan")
            rows.append(
                {
                    "stratum": str(stratum),
                    "field": column,
                    "group_n": group_n,
                    "missing_n": missing_n,
                    "observed_n": group_n - missing_n,
                    "missing_rate": rate,
                    "overall_missing_rate": overall_rate,
                    "delta_vs_overall": rate - overall_rate if group_n else float("nan"),
                    "data_label": DISCLAIMER,
                }
            )
    return pd.DataFrame(rows)


def build_healthcare_analysis_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Build the standard descriptive healthcare analysis extracts."""
    journey = tables["patient_journey"]
    patient = tables["patient"]
    demographic_columns = [
        column for column in ("patient_id", "race", "ethnicity") if column in patient
    ]
    missingness_input = journey
    if demographic_columns and "patient_id" in demographic_columns:
        missingness_input = journey.merge(
            patient[demographic_columns],
            on="patient_id",
            how="left",
            validate="one_to_one",
            suffixes=("", "_patient"),
        )
    return {
        "healthcare_initiation_funnel": initiation_funnel(journey),
        "healthcare_persistence_summary": persistence_summary(journey),
        "healthcare_referral_summary": referral_summary(tables["referral"]),
        "healthcare_missingness_by_market": stratified_missingness(missingness_input),
    }


def write_healthcare_analysis_report(
    tables: dict[str, pd.DataFrame], report_dir: str | Path
) -> dict[str, pd.DataFrame]:
    """Write standard healthcare analysis extracts and a short report index."""
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    extracts = build_healthcare_analysis_tables(tables)
    for name, frame in extracts.items():
        frame.to_csv(root / f"{name}.csv", index=False)
    lines = [
        "# Healthcare analysis extracts",
        "",
        f"> **{DISCLAIMER}**",
        "> These are descriptive extracts for synthetic-data development, "
        "not clinical or causal evidence.",
        "",
        "| Extract | Grain | Main use |",
        "|---|---|---|",
        "| healthcare_initiation_funnel.csv | stratum x initiation window | "
        "eligible denominator, initiation and censoring |",
        "| healthcare_persistence_summary.csv | stratum x refill-gap sensitivity | "
        "persistence, discontinuation, switch and censoring |",
        "| healthcare_referral_summary.csv | referral stratum | "
        "completion and delay distribution |",
        "| healthcare_missingness_by_market.csv | market x field | "
        "structural/market-dependent missingness review |",
        "",
        "Rates include Wilson intervals where a binomial denominator is defined. "
        "Censored rows are retained and excluded from evaluable-rate denominators.",
    ]
    (root / "healthcare_analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return extracts
