from pathlib import Path

import pandas as pd
import pytest

from prostate_journey.scientific_evidence import load_analysis_registry
from prostate_journey.scientific_methods import (
    build_survival_outputs,
    estimate_aalen_johansen,
    estimate_kaplan_meier,
    load_event_hierarchy,
    prepare_event_records,
)

ROOT = Path(__file__).resolve().parents[1]


def test_analysis_registry_covers_current_tactics_and_targets() -> None:
    registry = load_analysis_registry(ROOT / "contracts/analysis_registry.yaml")
    identifiers = {analysis["analysis_id"] for analysis in registry["analyses"]}
    assert len(identifiers) == 14
    assert {
        "cohort_definition",
        "initiation_funnel",
        "persistence_landmark",
        "time_to_initiation",
        "missingness_profile_and_truth_recovery",
        "predict_non_initiation_90d",
        "predict_discontinuation_12m",
        "predict_treatment_switch",
        "predict_restart_after_gap",
    }.issubset(identifiers)
    assert not {
        analysis["analysis_id"]
        for analysis in registry["analyses"]
        if analysis["reviewer_status"] in {"SME REVIEWED", "SOURCE VALIDATED"}
    }


def test_same_day_death_wins_configured_tie() -> None:
    hierarchy = load_event_hierarchy(ROOT / "configs/event_hierarchy.yaml")
    journey = pd.DataFrame(
        {
            "patient_id": ["P-1"],
            "eligibility_flag": [True],
            "eligibility_date": [pd.Timestamp("2024-01-01")],
            "treatment_start_date": [pd.Timestamp("2024-01-11")],
            "death_date": [pd.Timestamp("2024-01-11")],
            "loss_to_follow_up_date": [pd.NaT],
            "observation_end_date": [pd.Timestamp("2025-12-31")],
        }
    )
    records = prepare_event_records(journey, "initiation", hierarchy)
    assert records.loc[0, "event_type"] == "death"
    assert records.loc[0, "event_category"] == "competing"
    assert records.loc[0, "same_day_candidate_count"] == 2


def test_km_and_aalen_johansen_reconcile_exactly() -> None:
    records = pd.DataFrame(
        {
            "time_days": [5, 5, 10, 12],
            "event_type": ["initiation", "death", "administrative_data_end", "initiation"],
            "target_event": [True, False, False, True],
            "competing_event": [False, True, False, False],
            "censored": [False, False, True, False],
        }
    )
    curve, risk = estimate_kaplan_meier(records)
    assert risk.reconciliation_difference.eq(0).all()
    assert risk.iloc[-1].n_at_risk_after == 0
    assert curve.survival_probability.between(0, 1).all()
    assert curve.confidence_lower.between(0, 1).all()
    assert curve.confidence_upper.between(0, 1).all()
    assert curve.censoring_mark_count.sum() == records.censored.sum()
    assert curve.has_censoring_mark.any()

    cif = estimate_aalen_johansen(records, causes=("initiation", "death"))
    latest = cif.sort_values("time_days").groupby("cause").tail(1)
    probability_mass = float(latest.cumulative_incidence.sum()) + float(
        latest.all_event_survival.iloc[0]
    )
    assert probability_mass == pytest.approx(1.0)
    assert (
        cif.groupby("cause").cumulative_incidence.apply(lambda x: x.is_monotonic_increasing).all()
    )


def test_generated_survival_outputs_are_chart_ready(generated_tables) -> None:
    hierarchy = load_event_hierarchy(ROOT / "configs/event_hierarchy.yaml")
    records, curves, risk, cif = build_survival_outputs(
        generated_tables["patient_journey"],
        hierarchy,
        scenario="test-scenario",
        seed_summary="single source seed 123",
        release="TEST_ONLY",
    )
    assert set(records.endpoint) == set(hierarchy["endpoints"])
    required = {
        "numerator",
        "denominator",
        "population_definition",
        "time_zero",
        "horizon_days",
        "scenario",
        "seed_summary",
        "release",
        "assumptions",
        "limitation",
        "synthetic_data_only",
    }
    for frame in (curves, risk, cif):
        assert required.issubset(frame.columns)
    assert risk.reconciliation_difference.eq(0).all()
    assert cif.cumulative_incidence.between(0, 1).all()
