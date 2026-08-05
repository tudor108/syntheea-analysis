from pathlib import Path
import pytest
from prostate_journey.config import load_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def small_config():
    return load_config(ROOT / "configs/prostate_scenario.yaml", target_cohort_size=180, random_seed=123)

