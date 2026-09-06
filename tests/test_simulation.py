from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import yaml

from prostate_journey.pipeline import generate_tables, verify_exact_reproducibility
from prostate_journey.simulation import (
    load_simulation_spec,
    run_multi_seed_study,
    run_simulation_child,
    summarize_simulation_replicates,
    verify_child_manifest,
    verify_simulation_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def test_same_seed_is_exact_and_different_seed_changes_generation(small_config, tmp_path) -> None:
    config = deepcopy(small_config)
    config["target_cohort_size"] = 35
    config["random_seed"] = 701
    first = generate_tables(deepcopy(config), tmp_path / "raw")
    second = generate_tables(deepcopy(config), tmp_path / "raw")
    verify_exact_reproducibility(first, second)

    config["random_seed"] = 702
    different = generate_tables(config, tmp_path / "raw")
    assert not first["patient"].equals(different["patient"])


def test_child_run_is_sealed_and_mutation_is_detected(small_config, tmp_path) -> None:
    spec = load_simulation_spec(ROOT / "configs/simulation_scenarios.yaml")
    output = tmp_path / "study"
    run_simulation_child(
        project_root=ROOT,
        output_root=output,
        base_config=small_config,
        scenario_name="base",
        scenario_spec=spec["scenarios"]["base"],
        seed=812,
        cohort_size=30,
        input_dir=tmp_path / "raw",
        simulation_version=spec["version"],
    )
    child = output / "children/base/seed-000812"
    verify_child_manifest(child)
    (child / "metrics.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after sealing"):
        verify_child_manifest(child)


def _replicate_frame() -> pd.DataFrame:
    rows = []
    for scenario, shift in (("low", -0.1), ("base", 0.0), ("high", 0.1)):
        for seed, noise in ((1, -0.01), (2, 0.01), (3, 0.0)):
            rows.append(
                {
                    "scenario": scenario,
                    "seed": seed,
                    "metric_id": "initiation_90d_rate",
                    "value": 0.5 + shift + noise,
                    "numerator": "initiated",
                    "numerator_count": 50,
                    "denominator": "evaluable eligible",
                    "denominator_count": 100,
                    "population_definition": "test generated cohort",
                    "time_zero": "eligibility_date",
                    "horizon_days": 90,
                    "release": "NOT_RELEASED_SIMULATION::test",
                    "assumptions": scenario,
                    "limitation": "synthetic test",
                }
            )
    return pd.DataFrame(rows)


def test_uncertainty_types_are_never_collapsed() -> None:
    spec = load_simulation_spec(ROOT / "configs/simulation_scenarios.yaml")
    within, mcse, envelope, drivers = summarize_simulation_replicates(_replicate_frame(), spec)
    assert set(within.uncertainty_type) == {"WITHIN_SCENARIO_SIMULATION_INTERVAL_95"}
    assert set(mcse.uncertainty_type) == {"MONTE_CARLO_STANDARD_ERROR"}
    assert set(envelope.uncertainty_type) == {
        "SCENARIO_ASSUMPTION_ENVELOPE_NOT_CONFIDENCE_INTERVAL"
    }
    assert set(drivers.uncertainty_type) == {"SCENARIO_SENSITIVITY_DRIVER"}
    assert envelope.iloc[0].scenario_envelope_lower < envelope.iloc[0].base_mean
    assert envelope.iloc[0].scenario_envelope_upper > envelope.iloc[0].base_mean


def test_tiny_end_to_end_study_has_valid_parent_and_child_manifests(tmp_path) -> None:
    spec = load_simulation_spec(ROOT / "configs/simulation_scenarios.yaml")
    spec["base_config_file"] = str((ROOT / "configs/prostate_scenario.yaml").resolve())
    spec["simulation"].update(
        {
            "seeds_per_scenario": 2,
            "seed_end_inclusive": 10001,
            "maximum_seeds_per_scenario": 2,
            "adaptive_batch_size": 1,
            "cohort_size_per_seed": 25,
        }
    )
    specification = tmp_path / "simulation.yaml"
    specification.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    output = tmp_path / "sealed-study"
    run_multi_seed_study(
        ROOT,
        specification,
        output,
        input_dir=tmp_path / "raw",
        release="TEST-RELEASE",
    )
    verify_simulation_manifest(output)
    manifest = yaml.safe_load((output / "simulation_manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed_seeds"] == {"base": 2, "high": 2, "low": 2}
    assert manifest["release"] == "TEST-RELEASE"
    assert len(manifest["child_manifests"]) == 6
    assert not (output / ".simulation-in-progress").exists()
    missing_child = output / next(iter(manifest["child_manifests"]))
    missing_child.unlink()
    with pytest.raises(ValueError, match="child-run inventory changed"):
        verify_simulation_manifest(output)
