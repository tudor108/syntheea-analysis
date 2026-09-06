import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

import prostate_journey.predictive_evidence as predictive_evidence
from prostate_journey.dataset_resolver import AnalyticalDataset
from prostate_journey.industry_readiness import (
    FAIL,
    load_contract,
    validate_predictive_package,
)
from prostate_journey.model_governance import (
    assert_alias_promotion_allowed,
    load_model_governance,
    load_model_target_contracts,
    validate_model_alias_configuration,
)
from prostate_journey.predictive_dashboard import write_predictive_dashboard
from prostate_journey.predictive_evidence import (
    DECISION_CURVE_BLOCK,
    build_predictive_evidence_package,
    load_model_evaluation_config,
    verify_analysis_source_identity,
    verify_predictive_evidence_manifest,
)
from prostate_journey.predictive_modeling import (
    LeakageViolation,
    _resample_prevalence_shift,
    audit_feature_frame,
    audit_partition,
    build_model_datasets,
    build_subgroup_metrics,
    make_validation_partitions,
    pr_auc,
    raise_on_leakage,
    run_validation_framework,
)

ROOT = Path(__file__).resolve().parents[1]


def _model_frame(size: int = 420) -> pd.DataFrame:
    rng = np.random.default_rng(912)
    dates = pd.date_range("2019-01-01", periods=size, freq="3D")
    signal = rng.normal(size=size)
    target = (signal + rng.normal(scale=1.1, size=size) > 0.45).astype(int)
    markets = np.resize(np.array(["US", "DE", "JP", "FR", "CN", "AU", "CA"]), size)
    frame = pd.DataFrame(
        {
            "patient_id": [f"P-{index:05d}" for index in range(size)],
            "prediction_index_date": dates,
            "outcome_date": dates + pd.Timedelta(days=90),
            "target": target,
            "age_at_index": 69 + 5 * signal,
            "comorbidity_score": rng.integers(0, 7, size),
            "frailty_proxy": rng.normal(size=size),
            "access_index": np.clip(0.55 + 0.12 * signal, 0.05, 0.98),
            "prior_healthcare_utilization_180d": rng.integers(0, 8, size),
            "prior_treatment_count": rng.integers(0, 3, size),
            "time_since_diagnosis_days": rng.integers(0, 800, size),
            "time_since_metastasis_days": rng.integers(0, 500, size),
            "prior_treatment_status": np.where(signal > 0, "PRIOR", "NONE"),
            "disease_state": "mHSPC",
            "metastatic_site": np.where(signal > 0, "bone", "other"),
            "market_code": markets,
            "care_setting": np.where(signal > 0, "academic", "community"),
            "provider_specialty": "oncology",
            "provider_volume_band": np.where(signal > 0, "HIGH", "LOW"),
            "referral_proxy": np.where(signal > 0, "COMPLETED", "NONE"),
            "prior_hospitalization": np.where(signal > 1, "YES", "NO"),
            "insurance_type": np.where(signal > 0, "public", "commercial"),
            "calendar_period": np.where(dates.year <= 2021, "EARLY", "LATE"),
            "age_band": np.where(signal > 0, "GE_65", "LT_65"),
            "missingness_pattern": "NO_MISSING",
        }
    )
    for column in (
        "_max_encounter_feature_date",
        "_max_referral_feature_date",
        "_max_referral_completion_feature_date",
        "_max_prior_treatment_feature_date",
    ):
        frame[column] = dates - pd.Timedelta(days=1)
    frame["target_name"] = "non_initiated_within_90_days"
    frame["target_horizon_days"] = 90
    return frame


def _fast_evaluation_config() -> dict:
    config = load_model_evaluation_config(ROOT / "configs/model_evaluation.yaml")
    config = deepcopy(config)
    config["validation"].update(
        {
            "bootstrap_repeats": 12,
            "rolling_repeats": 2,
            "rolling_origins_per_repeat": 2,
            "minimum_training_n": 50,
            "minimum_validation_n": 20,
            "minimum_events_per_validation": 3,
            "calibration_curve_points": 7,
        }
    )
    config["subgroups"].update({"minimum_n": 20, "minimum_events": 3, "minimum_non_events": 3})
    return config


def test_model_contracts_and_alias_policy_block_operational_promotion(tmp_path) -> None:
    contracts = load_model_target_contracts(ROOT / "contracts/model_target_contracts.yaml")
    governance = load_model_governance(ROOT / "contracts/model_governance.yaml")
    assert len(contracts["models"]) == 4
    assert {model["current_disposition"] for model in contracts["models"]} == {"RESEARCH ONLY"}
    with pytest.raises(PermissionError, match="cannot be promoted"):
        assert_alias_promotion_allowed(
            model_id="non_initiation_90d",
            disposition="RESEARCH ONLY",
            alias="operational",
            governance=governance,
        )

    alias_config = tmp_path / "aliases.yaml"
    alias_config.write_text(
        yaml.safe_dump(
            {
                "version": "TEST",
                "assignments": [{"model_id": "non_initiation_90d", "alias": "operational"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PermissionError, match="cannot be promoted"):
        validate_model_alias_configuration(
            alias_config,
            {"non_initiation_90d": "RESEARCH ONLY"},
            governance,
        )


def test_leakage_sentinel_blocks_future_and_prohibited_features() -> None:
    frame = _model_frame(80)
    frame.loc[0, "_max_encounter_feature_date"] = frame.loc[
        0, "prediction_index_date"
    ] + pd.Timedelta(days=1)
    frame.loc[1, "outcome_date"] = frame.loc[1, "outcome_date"] + pd.Timedelta(days=1)
    frame.loc[1, "patient_id"] = frame.loc[0, "patient_id"]
    frame["days_to_initiation"] = 30
    audit = audit_feature_frame(
        frame,
        ["age_at_index", "days_to_initiation"],
        ["days_to_initiation"],
        target_name="adversarial_target",
    )
    assert set(audit.loc[audit.status.eq("FAIL"), "check"]) == {
        "prohibited_feature_sentinel",
        "encounter_feature_date_not_after_prediction_time",
        "outcome_not_after_declared_horizon",
        "one_row_per_patient",
    }
    with pytest.raises(LeakageViolation, match="Predictive leakage gate failed"):
        raise_on_leakage(audit)


def test_split_sentinels_block_patient_time_and_market_contamination() -> None:
    train = pd.DataFrame(
        {
            "patient_id": ["P-1", "P-2"],
            "prediction_index_date": pd.to_datetime(["2024-01-01", "2024-01-04"]),
            "market_code": ["US", "DE"],
        }
    )
    temporal_test = pd.DataFrame(
        {
            "patient_id": ["P-2", "P-3"],
            "prediction_index_date": pd.to_datetime(["2024-01-03", "2024-01-05"]),
            "market_code": ["US", "US"],
        }
    )
    temporal = audit_partition(
        train,
        temporal_test,
        target_name="adversarial_target",
        fold_id="bad-temporal-fold",
        design="ROLLING_TEMPORAL",
    )
    assert set(temporal.loc[temporal.status.eq("FAIL"), "check"]) == {
        "patient_isolation",
        "strict_temporal_isolation",
    }
    with pytest.raises(LeakageViolation, match="Predictive leakage gate failed"):
        raise_on_leakage(temporal)

    market = audit_partition(
        train,
        temporal_test.loc[temporal_test.patient_id.eq("P-3")],
        target_name="adversarial_target",
        fold_id="bad-market-fold",
        design="LEAVE_ONE_MARKET_OUT",
        holdout_market="DE",
    )
    assert set(market.loc[market.status.eq("FAIL"), "check"]) == {"market_isolation"}
    with pytest.raises(LeakageViolation, match="Predictive leakage gate failed"):
        raise_on_leakage(market)


def test_prevalence_comparator_pr_auc_handles_ties() -> None:
    target = np.array([0, 1, 0, 0, 1, 0, 1, 0])
    probability = np.repeat(target.mean(), len(target))
    assert pr_auc(target, probability) == pytest.approx(target.mean())


def test_prevalence_shift_changes_observed_event_odds_not_prediction_odds() -> None:
    target = np.r_[np.ones(20, dtype=int), np.zeros(80, dtype=int)]
    probability = np.linspace(0.95, 0.05, len(target))
    shifted_target, shifted_probability, requested = _resample_prevalence_shift(
        target,
        probability,
        odds_multiplier=2.0,
        seed=17,
    )
    assert requested == pytest.approx(1 / 3)
    assert shifted_target.mean() == pytest.approx(requested, abs=1 / len(target))
    assert len(shifted_probability) == len(probability)
    assert not np.array_equal(shifted_probability, probability)


def test_repeated_temporal_final_holdout_and_lomo_are_nested() -> None:
    frame = _model_frame()
    config = _fast_evaluation_config()
    contracts = load_model_target_contracts(ROOT / "contracts/model_target_contracts.yaml")
    partitions, _ = make_validation_partitions(frame, config["validation"])
    assert sum(partition.design == "ROLLING_TEMPORAL" for partition in partitions) >= 4
    assert sum(partition.design == "FINAL_TEMPORAL_HOLDOUT" for partition in partitions) == 1
    assert sum(partition.design == "LEAVE_ONE_MARKET_OUT" for partition in partitions) == 7

    metrics, curves, leakage, folds, final_scores = run_validation_framework(
        {"non_initiated_within_90_days": frame}, contracts, config
    )
    evaluated = metrics.loc[metrics.status.eq("EVALUATED")]
    assert {
        "ROLLING_TEMPORAL",
        "FINAL_TEMPORAL_HOLDOUT",
        "LEAVE_ONE_MARKET_OUT",
    }.issubset(set(evaluated.evaluation_design))
    assert set(evaluated.model) == {
        "regularized_logistic_nested_calibration",
        "training_prevalence_comparator",
    }
    assert evaluated.preprocessing_fit_scope.eq("model_fit rows only").all()
    assert evaluated.threshold_metrics_status.str.startswith("NOT REPORTED").all()
    assert leakage.status.eq("PASS").all()
    assert not curves.empty and not folds.empty
    assert "non_initiated_within_90_days" in final_scores

    subgroup = build_subgroup_metrics(final_scores, contracts, config)
    assert not subgroup.empty
    assert subgroup.ranking_allowed.eq(False).all()  # noqa: E712
    assert {"roc_auc_ci_lower", "calibration_intercept", "predictor_missingness_rate"}.issubset(
        subgroup.columns
    )


def _persistence_from_journey(journey: pd.DataFrame) -> pd.DataFrame:
    rows = []
    initiated = journey.loc[journey.treatment_initiated & journey.treatment_start_date.notna()]
    for patient in initiated.itertuples(index=False):
        start = pd.Timestamp(patient.treatment_start_date)
        censor = pd.Timestamp(patient.censor_date)
        for gap in (30, 60, 90):
            status = getattr(patient, f"persistence_12m_status_gap_{gap}d")
            if status == "PERSISTENT":
                classification, failure, days = "ADMINISTRATIVE_CENSORING", False, 366
            elif status == "SWITCHED":
                classification, failure = "SWITCHED", False
                days = max(1, int((pd.Timestamp(patient.switch_date) - start).days))
            elif bool(patient.restart_flag):
                classification, failure = "TEMPORARY_GAP_RESTARTED", True
                days = min(
                    365, max(1, int((pd.Timestamp(patient.discontinuation_date) - start).days))
                )
            else:
                classification, failure = "DISCONTINUED", status == "DISCONTINUED"
                endpoint = patient.discontinuation_date
                days = (
                    min(365, max(1, int((pd.Timestamp(endpoint) - start).days)))
                    if pd.notna(endpoint)
                    else 180
                )
            restart_date = pd.NaT
            if bool(patient.restart_flag) and pd.notna(patient.discontinuation_date):
                candidate_restart = pd.Timestamp(patient.discontinuation_date) + pd.Timedelta(
                    days=45
                )
                if candidate_restart <= censor:
                    restart_date = candidate_restart
            rows.append(
                {
                    "patient_id": patient.patient_id,
                    "pathway": "mhspc_mcspc",
                    "gap_threshold_days": gap,
                    "treatment_episode_id": patient.treatment_episode_id,
                    "treatment_start_date": start,
                    "censor_date": censor,
                    "restart_date": restart_date,
                    "persistence_endpoint_date": start + pd.Timedelta(days=days),
                    "days_to_persistence_endpoint": days,
                    "event_classification": classification,
                    "persistence_failure_flag": failure,
                    "disease_state": "mHSPC",
                }
            )
    return pd.DataFrame(rows)


def test_model_population_derivation_reconciles(generated_tables) -> None:
    journey = generated_tables["patient_journey"].copy()
    eligible = journey.eligibility_flag.fillna(False).astype(bool)
    flags = pd.DataFrame(
        {
            "patient_id": journey.patient_id,
            "pathway": "mhspc_mcspc",
            "pathway_membership": journey.mhspc_flag.fillna(False),
            "eligible_candidate": eligible,
            "cohort_index_date": journey.eligibility_date,
            "pathway_disease_state": "mHSPC",
            "initiation_date": journey.treatment_start_date,
            "observable_for_30d": eligible,
            "observable_for_60d": eligible,
            "observable_for_90d": eligible,
            "initiated_within_30d": journey.initiated_within_30d,
            "initiated_within_60d": journey.initiated_within_60d,
            "initiated_within_90d": journey.initiated_within_90d,
        }
    )
    persistence = _persistence_from_journey(journey)
    config = load_model_evaluation_config(ROOT / "configs/model_evaluation.yaml")
    datasets, derivation = build_model_datasets(flags, persistence, generated_tables, config)
    assert set(datasets) == {
        "non_initiated_within_90_days",
        "discontinued_within_12_months",
        "switched_treatment",
        "restarted_after_gap",
    }
    assert derivation.reconciliation_difference.eq(0).all()
    initiation_steps = derivation.loc[derivation.model_id.eq("non_initiation_90d")]
    assert int(initiation_steps.iloc[0].retained_n) == int(journey.mhspc_flag.fillna(False).sum())
    final = derivation.groupby("model_id").tail(1).set_index("model_id")
    for model_id, target in {
        model["model_id"]: model["target_name"]
        for model in load_model_target_contracts(ROOT / "contracts/model_target_contracts.yaml")[
            "models"
        ]
    }.items():
        assert int(final.loc[model_id, "retained_n"]) == len(datasets[target])
        horizon_end = datasets[target].prediction_index_date + pd.to_timedelta(
            datasets[target].target_horizon_days, unit="D"
        )
        assert datasets[target].outcome_date.le(horizon_end).all()

    eligible_member = flags.loc[
        flags.pathway_membership.fillna(False) & flags.eligible_candidate.fillna(False)
    ].iloc[[0]]
    duplicated_flags = pd.concat([flags, eligible_member], ignore_index=True)
    with pytest.raises(LeakageViolation, match="Duplicate patient rows in the initiation"):
        build_model_datasets(
            duplicated_flags,
            persistence,
            generated_tables,
            config,
        )


def test_predictive_manifest_detects_post_seal_mutation(tmp_path) -> None:
    artifact = tmp_path / "aggregate.csv"
    artifact.write_text("metric,value\nauc,0.61\n", encoding="utf-8")
    manifest = {
        "artifacts": {
            artifact.name: {
                "bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        }
    }
    manifest_path = tmp_path / "predictive_evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    marker = tmp_path / "IMMUTABLE_PREDICTIVE_EVIDENCE"
    marker.write_text(hashlib.sha256(manifest_path.read_bytes()).hexdigest(), encoding="utf-8")
    verify_predictive_evidence_manifest(tmp_path)

    artifact.write_text("metric,value\nauc,0.99\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after sealing"):
        verify_predictive_evidence_manifest(tmp_path)


def test_predictive_evidence_blocks_dirty_or_mismatched_source(monkeypatch, tmp_path) -> None:
    def dirty_git_value(_project: Path, *args: str) -> str | None:
        if args == ("rev-parse", "HEAD"):
            return "expected-commit"
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return " M src/example.py"
        return None

    monkeypatch.setattr(predictive_evidence, "_git_value", dirty_git_value)
    with pytest.raises(ValueError, match="clean worktree"):
        verify_analysis_source_identity(tmp_path, "expected-commit")
    with pytest.raises(ValueError, match="does not match"):
        verify_analysis_source_identity(tmp_path, "different-commit")


def test_predictive_dashboard_is_interactive_and_aggregate_only(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    model_id = "non_initiation_90d"
    target = "non_initiated_within_90_days"
    summary = {
        "release": "TEST-RELEASE",
        "source_commit": "abc123",
        "models": [
            {
                "model_id": model_id,
                "analysis_population_n": 240,
                "analysis_event_n": 60,
                "disposition": "RESEARCH ONLY",
                "reason": "synthetic methods evidence only",
                "deployable": False,
            }
        ],
    }
    (evidence / "predictive_frontend_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    contract = {
        "models": [
            {
                "model_id": model_id,
                "target_name": target,
                "intended_research_use": "Evaluate a synthetic research target.",
                "prediction_time": "eligibility_date",
                "prediction_horizon_days": 90,
                "outcome_definition": "Synthetic non-initiation by day 90.",
                "predictor_availability_cutoff": "No later than time zero.",
                "false_positive_harm": "Unnecessary review.",
                "false_negative_harm": "A review opportunity may be missed.",
            }
        ]
    }
    (evidence / "model_target_contracts_snapshot.yaml").write_text(
        yaml.safe_dump(contract), encoding="utf-8"
    )
    (evidence / "decision_curve_status.json").write_text(
        json.dumps(
            {
                "decision_curve_generated": False,
                "statement": DECISION_CURVE_BLOCK,
            }
        ),
        encoding="utf-8",
    )
    metric = {
        "model_id": model_id,
        "target": target,
        "model": "regularized_logistic_nested_calibration",
        "evaluation_design": "FINAL_TEMPORAL_HOLDOUT",
        "fold_id": "final",
        "status": "EVALUATED",
        "validation_n": 48,
        "validation_event_n": 12,
        "event_prevalence": 0.25,
        "roc_auc": 0.64,
        "roc_auc_ci_lower": 0.52,
        "roc_auc_ci_upper": 0.74,
        "pr_auc": 0.37,
        "pr_auc_ci_lower": 0.25,
        "pr_auc_ci_upper": 0.49,
        "brier_score": 0.18,
        "calibration_intercept": 0.1,
        "calibration_slope": 0.9,
        "train_period_start": "2020-01-01",
        "train_period_end": "2022-12-31",
        "validation_period_start": "2023-01-01",
        "validation_period_end": "2023-12-31",
    }
    pd.DataFrame([metric]).to_csv(evidence / "validation_metrics.csv", index=False)
    pd.DataFrame(
        [
            {
                **{
                    key: metric[key] for key in ("model_id", "target", "model", "evaluation_design")
                },
                "mean_predicted_probability": 0.25,
                "smoothed_observed_event_rate": 0.27,
                "confidence_lower": 0.20,
                "confidence_upper": 0.34,
            }
        ]
    ).to_csv(evidence / "flexible_calibration_curves.csv", index=False)
    pd.DataFrame(
        [
            {
                "model_id": model_id,
                "target": target,
                "step_order": 1,
                "derivation_step": "eligible_records",
                "reason": "contract selection",
                "entered_n": 300,
                "excluded_n": 60,
                "retained_n": 240,
            }
        ]
    ).to_csv(evidence / "model_population_derivation.csv", index=False)
    pd.DataFrame(
        [{"target": target, "status": "PASS", "check": "future_information", "failure_count": 0}]
    ).to_csv(evidence / "leakage_audit.csv", index=False)
    pd.DataFrame(columns=["model_id", "target", "evaluation_design"]).to_csv(
        evidence / "validation_fold_registry.csv", index=False
    )
    pd.DataFrame(columns=["model_id", "subgroup_dimension", "subgroup_value"]).to_csv(
        evidence / "subgroup_metrics.csv", index=False
    )
    pd.DataFrame(columns=["model_id", "robustness_type", "scenario"]).to_csv(
        evidence / "robustness_metrics.csv", index=False
    )
    pd.DataFrame([{"target": target, "prior_roc_auc": 0.63}]).to_csv(
        evidence / "prior_claim_reproduction.csv", index=False
    )

    dashboard = write_predictive_dashboard(
        evidence,
        tmp_path / "presentation",
        {"configuration_hash": "f" * 64, "scientific_evidence_available": False},
    )
    document = dashboard.read_text(encoding="utf-8")
    payload = json.loads(
        (dashboard.parent / "predictive_dashboard_payload.json").read_text(encoding="utf-8")
    )
    assert "Model Evidence Lab" in document
    assert "Open each predictive tactic" in document
    assert "modelEvidenceData" in document
    assert 'role="dialog"' in document
    assert DECISION_CURVE_BLOCK in document
    assert payload["patient_level_data_included"] is False
    assert payload["deployable_models"] == 0


def test_predictive_package_builds_seals_and_passes_industry_gates(
    transition_tables, tmp_path, monkeypatch
) -> None:
    generated_tables = transition_tables
    journey = generated_tables["patient_journey"].copy()
    eligible = journey.eligibility_flag.fillna(False).astype(bool)
    flags = pd.DataFrame(
        {
            "patient_id": journey.patient_id,
            "pathway": "mhspc_mcspc",
            "pathway_membership": journey.mhspc_flag.fillna(False),
            "eligible_candidate": eligible,
            "cohort_index_date": journey.eligibility_date,
            "pathway_disease_state": "mHSPC",
            "initiation_date": journey.treatment_start_date,
            "observable_for_30d": eligible,
            "observable_for_60d": eligible,
            "observable_for_90d": eligible,
            "initiated_within_30d": journey.initiated_within_30d,
            "initiated_within_60d": journey.initiated_within_60d,
            "initiated_within_90d": journey.initiated_within_90d,
        }
    )
    evaluation = _fast_evaluation_config()
    evaluation["validation"].update(
        {
            "bootstrap_repeats": 12,
            "minimum_training_n": 5,
            "minimum_validation_n": 2,
            "minimum_events_per_validation": 1,
            "calibration_curve_points": 5,
        }
    )
    evaluation["subgroups"].update({"minimum_n": 5, "minimum_events": 1, "minimum_non_events": 1})
    evaluation["robustness"].update(
        {
            "initiation_windows_days": [90],
            "persistence_gap_days": [60],
            "added_feature_missingness_rates": [0.10],
            "prevalence_odds_multipliers": [0.5],
        }
    )
    evaluation_path = tmp_path / "evaluation.yaml"
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

    def clean_git_value(_project: Path, *args: str) -> str | None:
        if args == ("rev-parse", "HEAD"):
            return commit
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return ""
        return None

    monkeypatch.setattr(predictive_evidence, "_git_value", clean_git_value)
    output = tmp_path / "predictive"
    build_predictive_evidence_package(
        project_root=ROOT,
        tables=generated_tables,
        flags=flags,
        persistence=_persistence_from_journey(journey),
        output_dir=output,
        release="TEST_ONLY",
        release_source_commit=commit,
        model_contract_path=ROOT / "contracts/model_target_contracts.yaml",
        evaluation_config_path=evaluation_path,
        governance_path=ROOT / "contracts/model_governance.yaml",
        alias_config_path=ROOT / "configs/model_aliases.yaml",
    )
    verify_predictive_evidence_manifest(output)
    manifest = json.loads(
        (output / "predictive_evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["analysis_worktree_clean"] is True
    card = (output / "model_cards/non_initiation_90d.md").read_text(encoding="utf-8")
    assert "| Dimension | Group | n | Events | Missing |" in card
    assert "certified generated synthetic analytical release" in card
    restart_card = (output / "model_cards/restart_after_gap.md").read_text(encoding="utf-8")
    assert "Gap-failure membership is unknown at treatment start" in restart_card
    source = AnalyticalDataset(
        analytical_dir=tmp_path,
        dataset_version="TEST_ONLY",
        selection_method="test",
        release_dir=None,
        release_manifest={"git": {"git_commit": commit}},
    )
    checks = validate_predictive_package(
        output,
        source,
        load_contract(ROOT / "contracts/analytical_data_contract.yaml"),
    )
    assert all(check.status != FAIL for check in checks), checks
    assert not (output / ".predictive-in-progress").exists()
    assert not list(output.rglob("*.parquet"))
