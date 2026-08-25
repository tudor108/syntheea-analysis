from copy import deepcopy
from pathlib import Path

import pytest

from prostate_journey.config import load_config
from prostate_journey.pipeline import generate_tables

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def small_config():
    return load_config(
        ROOT / "configs/prostate_scenario.yaml",
        target_cohort_size=350,
        random_seed=123,
    )


@pytest.fixture(scope="session")
def generated_tables(small_config, tmp_path_factory):
    return generate_tables(deepcopy(small_config), tmp_path_factory.mktemp("raw"))


@pytest.fixture(scope="session")
def transition_tables(small_config, tmp_path_factory):
    config = deepcopy(small_config)
    config["target_cohort_size"] = 900
    config["random_seed"] = 991
    config["treatment"]["switch_probability"] = 0.20
    config["treatment"]["restart_probability"] = 0.20
    config["treatment"]["discontinuation_probability"] = 0.15
    config["treatment"]["add_on_probability"] = 0.75
    return generate_tables(config, tmp_path_factory.mktemp("transition-raw"))
