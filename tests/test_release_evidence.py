import json

import pandas as pd

from prostate_journey.release_evidence import (
    REALIZED_VALUE_PROXY_VERSION,
    REQUIRED_MARKETS,
    write_release_evidence,
)


def _clean_reconciliation():
    return {
        "status": "PASS",
        "eligibility_mismatches": 0,
        "first_treatment_mismatches": 0,
        "initiation_window_mismatches": 0,
        "regimen_mismatches": 0,
        "persistence_mismatches": 0,
        "discontinuation_mismatches": 0,
        "switch_mismatches": 0,
        "active_surveillance_mismatches": 0,
        "referral_mismatches": 0,
        "censoring_mismatches": 0,
    }


def test_release_evidence_writes_complete_actual_artifacts(
    generated_tables, small_config, tmp_path
):
    analytical = tmp_path / "analytical"
    qa = tmp_path / "qa"
    paths = write_release_evidence(
        generated_tables, small_config, analytical, qa, _clean_reconciliation()
    )

    assert len(paths) == 19
    assert all(path.exists() and path.stat().st_size > 0 for path in paths.values())

    dictionary = pd.read_csv(paths["data_dictionary_csv"])
    assert len(dictionary) == sum(len(frame.columns) for frame in generated_tables.values())
    assert not dictionary.duplicated(["table", "column"]).any()
    assert dictionary.description.notna().all()

    coverage = pd.read_csv(paths["market_coverage_csv"])
    assert set(coverage.market_code) == REQUIRED_MARKETS
    for column in (
        "follow_up_median_days",
        "diagnosis_date_min",
        "censor_date_max",
        "providers",
        "organizations",
        "encounters",
        "treatment_episodes",
        "prescription_events",
        "as_monitoring_events",
        "referrals",
        "clinical_missing_rate",
        "evaluable_12m",
        "encounter_event_date_min",
        "encounter_event_date_max",
        "referral_event_date_min",
        "referral_event_date_max",
        "treatment_event_date_min",
        "treatment_event_date_max",
        "prescription_event_date_min",
        "prescription_event_date_max",
        "active_surveillance_event_date_min",
        "active_surveillance_event_date_max",
        "patient_aggregate_missing_rate",
        "diagnosis_aggregate_missing_rate",
        "encounter_aggregate_missing_rate",
        "referral_aggregate_missing_rate",
        "active_surveillance_aggregate_missing_rate",
        "treatment_episode_aggregate_missing_rate",
        "prescription_aggregate_missing_rate",
        "outcome_aggregate_missing_rate",
    ):
        assert column in coverage
    assert "Deep vs Scan Quantitative Comparison" in paths["market_coverage_md"].read_text(
        encoding="utf-8"
    )

    uncertainty = pd.read_csv(paths["uncertainty_confidence_csv"])
    assert uncertainty.caveat.str.contains("synthetic scenario", case=False).all()
    observed_intervals = uncertainty.dropna(subset=["wilson_ci95_low", "wilson_ci95_high"])
    assert observed_intervals.wilson_ci95_low.between(0, 1).all()
    assert observed_intervals.wilson_ci95_high.between(0, 1).all()

    opportunity = pd.read_csv(paths["market_opportunity_csv"])
    assert opportunity.eligible.equals(
        opportunity.initiated_90d
        + opportunity.treatment_gap_90d
        + opportunity.initiation_90d_censored_not_evaluable
    )
    assert opportunity.initiation_90d_evaluable.equals(
        opportunity.initiated_90d + opportunity.treatment_gap_90d
    )
    assert opportunity.persistent_12m.le(opportunity.evaluable_12m).all()
    assert opportunity.realized_value_proxy_version.eq(REALIZED_VALUE_PROXY_VERSION).all()

    heatmap = pd.read_csv(paths["treatment_gap_heatmap_csv"])
    assert heatmap.eligible.gt(0).all()
    assert heatmap.treatment_gap_rate_90d.between(0, 1).all()
    assert heatmap.initiation_90d_partition_unexplained.eq(0).all()
    assert "background:" in paths["treatment_gap_heatmap_html"].read_text(encoding="utf-8")

    sensitivity = pd.read_csv(paths["sensitivity_analysis_csv"])
    assert set(sensitivity.sensitivity_domain) == {
        "initiation_window",
        "persistence_permissible_gap",
    }
    assert set(sensitivity.parameter_days) == {30, 60, 90}
    assert sensitivity.unexplained_partition.eq(0).all()
    assert sensitivity.precomputed_flag_mismatch_count.eq(0).all()
    assert sensitivity.evaluable_denominator.le(sensitivity.eligible_denominator).all()

    tree = pd.read_csv(paths["driver_tree_csv"], keep_default_na=False)
    terminal = tree.loc[tree.node_id.eq("realized_value_proxy_12m")]
    assert terminal.definition_version.eq(REALIZED_VALUE_PROXY_VERSION).all()
    assert terminal.caveat.str.contains("not causal", case=False).all()

    intervention = pd.read_csv(paths["intervention_inputs_csv"])
    assert intervention.caveat.str.contains("does not estimate causal", case=False).all()

    leakage = pd.read_csv(paths["leakage_report_csv"])
    assert set(leakage.task) == {
        "treatment_initiation_90d",
        "discontinuation_12m",
        "referral_completion_pathway",
    }
    assert leakage.status.eq("PASS").all()
    assert leakage.leakage_violation_count.eq(0).all()
    payload = json.loads(paths["leakage_report_json"].read_text(encoding="utf-8"))
    assert payload["all_tasks_pass"]
    assert all(payload["tasks"][task]["predictor_columns"] for task in leakage.task)

    realism = pd.read_csv(paths["synthetic_realism_csv"])
    assert set(realism.diagnostic) >= {
        "patient_independence",
        "age_and_comorbidity",
        "disease_state_variation",
        "treatment_variation",
        "provider_patterns",
        "refill_gap_variation",
        "outcome_structure_without_determinism",
        "deep_scan_depth",
        "market_missingness",
        "correlation_and_leakage",
    }

    assumptions = pd.read_csv(paths["assumptions_register_csv"])
    assert assumptions.assumption_id.is_unique
    assert assumptions.validation_status.isin(["TECHNICAL_CONTRACT", "REQUIRES_BAYER_REVIEW"]).all()

    scorecard = pd.read_csv(paths["final_scorecard_csv"])
    assert len(scorecard) == 11
    assert scorecard.score_0_100.between(0, 100).all()
    assert scorecard.loc[scorecard.status.eq("PASS"), "score_0_100"].eq(100).all()
    assert scorecard.loc[scorecard.score_0_100.eq(100), "remaining_deficiency"].eq("NONE").all()


def test_reconciliation_failure_prevents_overall_100(generated_tables, small_config, tmp_path):
    paths = write_release_evidence(
        generated_tables,
        small_config,
        tmp_path / "analytical",
        tmp_path / "qa",
        {"status": "FAIL", "persistence_mismatches": 1},
    )
    scorecard = pd.read_csv(paths["final_scorecard_csv"])
    overall = scorecard.loc[scorecard.dimension.eq("Overall diagnostic readiness")].iloc[0]
    assert overall.score_0_100 < 100
    assert overall.remaining_deficiency != "NONE"
