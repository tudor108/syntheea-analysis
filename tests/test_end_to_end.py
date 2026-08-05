from pathlib import Path
import pandas as pd
from prostate_journey.pipeline import generate_tables, run_all


def test_reproducibility(small_config, tmp_path: Path):
    first = generate_tables(small_config, tmp_path / "missing-a")
    second = generate_tables(small_config, tmp_path / "missing-b")
    pd.testing.assert_frame_equal(first["patient_journey"], second["patient_journey"])


def test_end_to_end_outputs(small_config, tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    gold = tmp_path / "gold"
    tables = run_all(project, small_config, tmp_path / "raw", gold)
    assert set(tables) == {"patient", "diagnosis", "provider", "encounter", "treatment", "outcome", "patient_journey"}
    for name in tables:
        assert (gold / f"{name}.csv").exists()
        assert (gold / f"{name}.parquet").exists()
    assert (gold / "prostate_journey.duckdb").exists()
