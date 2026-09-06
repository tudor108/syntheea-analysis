import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from prostate_journey.missingness_sensitivity import run_truth_recovery_experiment
from prostate_journey.scientific_dashboard import write_scientific_dashboard
from prostate_journey.scientific_evidence import (
    build_scientific_evidence_package,
    verify_scientific_evidence_manifest,
)
from prostate_journey.synthetic_utility import (
    evaluate_synthetic_utility,
    load_real_data_hook_spec,
)

ROOT = Path(__file__).resolve().parents[1]


def _truth_frame(size: int = 240) -> pd.DataFrame:
    rng = np.random.default_rng(445)
    return pd.DataFrame(
        {
            "patient_id": [f"P-{index:04d}" for index in range(size)],
            "market_code": np.resize(np.array(["US", "DE", "FR", "CN"]), size),
            "access_index": rng.uniform(0.1, 1.0, size),
            "comorbidity_score": rng.integers(0, 7, size),
            "psa_value": rng.lognormal(mean=2.5, sigma=0.7, size=size),
        }
    )


def test_missingness_truth_recovery_reports_bias_rmse_coverage_and_ess(small_config) -> None:
    spec = yaml.safe_load((ROOT / "configs/simulation_scenarios.yaml").read_text(encoding="utf-8"))
    experiment = deepcopy(spec["missingness_truth_recovery"])
    experiment["replications"] = 8
    replicates, summary, tipping = run_truth_recovery_experiment(
        _truth_frame(),
        small_config,
        experiment,
        release="TEST_ONLY",
        scenario="test-scenario",
    )
    assert set(summary.mechanism) == {"EXISTING_CONFIGURED", "MCAR", "MAR", "MNAR"}
    assert {
        "bias",
        "rmse",
        "interval_coverage",
        "mean_effective_sample_size",
        "failure_count",
    }.issubset(summary.columns)
    assert not (
        replicates.mechanism.eq("MNAR") & replicates.method.eq("ORACLE_IPW_KNOWN_SYNTHETIC_MASK")
    ).any()
    assert set(tipping.delta_standard_deviations) == set(experiment["delta_standard_deviations"])


def test_utility_dimensions_remain_separate_and_real_data_hooks_are_blocked(
    generated_tables, small_config
) -> None:
    hooks = load_real_data_hook_spec(ROOT / "contracts/real_data_evaluation_hooks.yaml")
    evidence = evaluate_synthetic_utility(
        generated_tables,
        small_config,
        release="TEST_ONLY",
        scenario="test-scenario",
        seed_summary="single source seed 123",
        real_hook_spec=hooks,
    )
    assert evidence.dimension.nunique() >= 10
    assert "universal_realism_score" not in set(evidence.metric)
    blocked = evidence.loc[evidence.dimension.eq("governed_real_data_evaluation")]
    assert len(blocked) == len(hooks["hooks"])
    assert blocked.status.eq("BLOCKED").all()
    impossible = evidence.loc[
        evidence.metric.eq("mutually_exclusive_or_post_censor_conflicts"), "value"
    ]
    assert float(impossible.iloc[0]) == 0.0


def test_scientific_package_is_sealed_and_frontend_json_is_valid(
    generated_tables, small_config, tmp_path
) -> None:
    simulation_spec = yaml.safe_load(
        (ROOT / "configs/simulation_scenarios.yaml").read_text(encoding="utf-8")
    )
    simulation_spec["missingness_truth_recovery"].update(
        {"truth_cohort_size": 90, "replications": 5}
    )
    simulation_path = tmp_path / "simulation.yaml"
    simulation_path.write_text(yaml.safe_dump(simulation_spec, sort_keys=False), encoding="utf-8")
    output = tmp_path / "scientific"
    build_scientific_evidence_package(
        project_root=ROOT,
        tables=generated_tables,
        config=small_config,
        output_dir=output,
        release="TEST_ONLY",
        analysis_registry_path=ROOT / "contracts/analysis_registry.yaml",
        event_hierarchy_path=ROOT / "configs/event_hierarchy.yaml",
        simulation_spec_path=simulation_path,
        real_hook_spec_path=ROOT / "contracts/real_data_evaluation_hooks.yaml",
        input_dir=tmp_path / "raw",
    )
    verify_scientific_evidence_manifest(output)
    manifest = json.loads(
        (output / "scientific_evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["synthetic_data_only"] is True
    assert manifest["formal_clinical_or_regulatory_claim"] is False
    assert manifest["causal_interpretation_allowed"] is False
    frontend_text = (output / "scientific_frontend_summary.json").read_text(encoding="utf-8")
    frontend = json.loads(frontend_text)
    assert "NaN" not in frontend_text
    assert len(frontend["survival"]) == 4
    assert all("censoring_mark_count" in row for row in frontend["survival"])
    assert frontend["causal_interpretation_allowed"] is False
    assert not (output / ".scientific-in-progress").exists()
    generated_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace").lower()
        for path in output.iterdir()
        if path.suffix in {".csv", ".json", ".md", ".yaml"}
    )
    for prohibited_affirmative_claim in (
        "these results are clinically validated",
        "these records represent real patients",
        "this is a bayer insight",
        "this is a comparative-effectiveness result",
        "this estimate is a causal effect",
    ):
        assert prohibited_affirmative_claim not in generated_text

    dashboard = write_scientific_dashboard(
        output,
        None,
        tmp_path / "presentation",
        {"dataset_version": "TEST_ONLY", "source_git_commit": "abc123"},
    )
    document = dashboard.read_text(encoding="utf-8")
    assert "Scientific Evidence Lab" in document
    assert "Three different uncertainty questions" in document
    assert "Open each scientific tactic" in document
    assert 'role="dialog"' in document
    assert generated_tables["patient"].patient_id.iloc[0] not in document
    dashboard_payload = json.loads(
        (dashboard.parent / "scientific_dashboard_payload.json").read_text(encoding="utf-8")
    )
    assert len(dashboard_payload["tactics"]) == 8
