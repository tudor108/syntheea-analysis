from copy import deepcopy

import pandas as pd

from prostate_journey.data_quality import validate_tables
from prostate_journey.pipeline import TABLES, generate_tables, run_all
from prostate_journey.readiness_audit import audit_tables


def test_reproducibility_same_seed_same_normalized_and_mart_outputs(small_config, tmp_path):
    config = deepcopy(small_config)
    config["target_cohort_size"] = 120
    first = generate_tables(config, tmp_path / "missing-a")
    second = generate_tables(config, tmp_path / "missing-b")
    for table_name in TABLES:
        pd.testing.assert_frame_equal(first[table_name], second[table_name])


def test_market_depth_and_leakage_controls(generated_tables, small_config):
    patient = generated_tables["patient"]
    encounter = generated_tables["encounter"]
    event_rate = encounter.groupby("market_code").size() / patient.groupby("market_code").size()
    deep_rate = event_rate.loc[["US", "DE", "JP"]].mean()
    scan_rate = event_rate.loc[["FR", "CN", "AU", "CA"]].mean()
    assert deep_rate > scan_rate * 1.35

    split = generated_tables["patient_split"]
    assert split.groupby("source_archetype_id").split.nunique().max() == 1
    timing = generated_tables["feature_timing"]
    assert not timing.loc[timing.future_information_flag, "predictor_allowed_flag"].any()

    matrix, *_ = audit_tables(generated_tables, validate_tables(generated_tables), small_config)
    assert matrix.loc[matrix.requirement_id.ne(11), "status"].eq("PASS").all()


def test_end_to_end_exports_contract_database_and_reports(small_config, tmp_path):
    config = deepcopy(small_config)
    config["target_cohort_size"] = 180
    config["readiness"]["fail_on_p0_p1"] = False
    project = tmp_path / "project"
    project.mkdir()
    gold = tmp_path / "gold"
    tables = run_all(project, config, tmp_path / "raw", gold)
    assert set(tables) == set(TABLES)
    for name in TABLES:
        assert (gold / f"{name}.csv").exists()
        assert (gold / f"{name}.parquet").exists()
    assert (gold / "prostate_journey.duckdb").exists()
    for report in [
        "data_quality_summary.json",
        "readiness_audit.json",
        "readiness_requirement_matrix.csv",
        "readiness_scorecard.csv",
        "adversarial_audit.json",
        "adversarial_audit.md",
        "adversarial_audit_scorecard.csv",
        "market_summary.csv",
        "schema_summary.csv",
        "missingness_summary.csv",
        "healthcare_analysis_report.md",
        "healthcare_initiation_funnel.csv",
        "healthcare_persistence_summary.csv",
        "healthcare_referral_summary.csv",
        "healthcare_missingness_by_market.csv",
        "cohort_dashboard.html",
        "config_snapshot.yaml",
    ]:
        assert (project / "data" / "reports" / report).exists()
