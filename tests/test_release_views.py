import duckdb
import pandas as pd

from prostate_journey.dashboard import eligible_cohort_funnel_counts
from prostate_journey.duckdb_loader import load_duckdb
from prostate_journey.pipeline import export_tables


def test_market_opportunity_view_uses_one_nested_eligible_cohort(generated_tables, tmp_path):
    export_tables(generated_tables, tmp_path)
    database = load_duckdb(tmp_path)
    with duckdb.connect(str(database), read_only=True) as connection:
        opportunity = connection.sql(
            "SELECT * FROM vw_market_opportunity ORDER BY market_code"
        ).df()

    assert opportunity.eligible.equals(
        opportunity.initiated_90d
        + opportunity.treatment_gap_90d
        + opportunity.initiation_censored_not_evaluable_90d
    )
    assert opportunity.persistent_12m.le(opportunity.evaluable_12m).all()
    assert opportunity.evaluable_12m.le(opportunity.initiated_90d).all()
    assert opportunity.censored_12m.le(opportunity.initiated_90d).all()

    journey = generated_tables["patient_journey"]
    eligible = journey.eligibility_flag.fillna(False)
    initiated = eligible & journey.initiated_within_90d.fillna(False)
    assert int(opportunity.eligible.sum()) == int(eligible.sum())
    assert int(opportunity.initiated_90d.sum()) == int(initiated.sum())
    gap = journey.eligible_not_initiated_90d.fillna(False)
    censored = journey.initiation_90d_status.eq("CENSORED_NOT_EVALUABLE")
    assert int(opportunity.treatment_gap_90d.sum()) == int(gap.sum())
    assert int(opportunity.initiation_censored_not_evaluable_90d.sum()) == int(censored.sum())
    assert int(opportunity.persistent_12m.sum()) == int(
        (initiated & journey.persistence_12m_status.eq("PERSISTENT")).sum()
    )


def test_dashboard_funnel_excludes_ineligible_and_late_initiators():
    journey = pd.DataFrame(
        {
            "eligibility_flag": [True, True, False, True, True],
            "initiated_within_90d": [True, False, True, True, False],
            "eligible_not_initiated_90d": [False, True, False, False, False],
            "initiation_90d_status": [
                "INITIATED_WITHIN_90D",
                "NOT_INITIATED_WITHIN_90D",
                "NOT_ELIGIBLE",
                "INITIATED_WITHIN_90D",
                "CENSORED_NOT_EVALUABLE",
            ],
            "persistence_12m_status": [
                "PERSISTENT",
                "PERSISTENT",
                "PERSISTENT",
                "CENSORED_NOT_EVALUABLE",
                "NOT_APPLICABLE",
            ],
        }
    )

    assert eligible_cohort_funnel_counts(journey) == {
        "eligible": 4,
        "initiated_90d": 2,
        "treatment_gap_90d": 1,
        "initiation_censored_not_evaluable_90d": 1,
        "evaluable_12m": 1,
        "persistent_12m": 1,
        "censored_12m": 1,
    }
