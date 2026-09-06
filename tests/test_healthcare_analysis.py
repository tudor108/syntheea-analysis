import pandas as pd

from prostate_journey.healthcare_analysis import (
    initiation_funnel,
    persistence_summary,
    referral_summary,
    stratified_missingness,
)


def test_initiation_funnel_keeps_censored_patients_out_of_treatment_gap():
    journey = pd.DataFrame(
        {
            "eligibility_flag": [True, True, True, False],
            "eligibility_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01", None]),
            "censor_date": pd.to_datetime(["2024-04-01", "2024-01-31", "2024-05-01", "2024-05-01"]),
            "initiated_within_90d": [True, False, False, False],
            "market_code": ["US", "US", "DE", "US"],
        }
    )

    result = initiation_funnel(journey, windows=(90,))
    row = result.iloc[0]
    assert row.eligible_n == 3
    assert row.initiated_n == 1
    assert row.not_initiated_n == 1
    assert row.censored_n == 1
    assert row.evaluable_n == 2
    assert row.initiation_rate_evaluable == 0.5


def test_generated_persistence_summary_is_censor_aware_and_monotonic(generated_tables):
    result = persistence_summary(generated_tables["patient_journey"])
    all_rows = result[result.stratum.eq("all")].set_index("gap_days")

    for gap in (30, 60, 90):
        row = all_rows.loc[gap]
        assert (
            row.persistent_n
            + row.non_persistent_evaluable_n
            + row.censored_n
            + row.not_applicable_n
            == row.treatment_initiated_n
        )
        assert row.treated_n + row.not_applicable_n == row.treatment_initiated_n
        assert row.evaluable_n == row.persistent_n + row.non_persistent_evaluable_n
        assert 0 <= row.persistence_rate_evaluable <= 1
        assert 0 <= row.censoring_rate_treated <= 1
    assert all_rows.loc[30, "persistent_n"] <= all_rows.loc[60, "persistent_n"]
    assert all_rows.loc[60, "persistent_n"] <= all_rows.loc[90, "persistent_n"]


def test_generated_referral_summary_reconciles_counts(generated_tables):
    result = referral_summary(generated_tables["referral"])
    assert (result.completed_n + result.not_completed_n == result.referrals_n).all()
    assert result.completion_rate.between(0, 1).all()
    assert (result.median_delay_days.dropna() >= 0).all()


def test_missingness_extract_has_one_row_per_market_and_field(generated_tables):
    journey = generated_tables["patient"]
    fields = ("race", "ethnicity", "insurance_type")
    result = stratified_missingness(journey, columns=fields)
    assert len(result) == journey.market_code.nunique() * len(fields)
    assert result.missing_rate.between(0, 1).all()
    assert (result.missing_n + result.observed_n == result.group_n).all()
