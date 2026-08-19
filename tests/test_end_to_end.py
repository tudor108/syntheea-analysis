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
    assert set(tables) == {"patient", "diagnosis", "provider", "encounter", "treatment", "prescription_event", "outcome", "patient_journey"}
    for name in tables:
        assert (gold / f"{name}.csv").exists()
        assert (gold / f"{name}.parquet").exists()
    assert (gold / "prostate_journey.duckdb").exists()


def test_journey_persistence_uses_initial_treatment_events(small_config, tmp_path: Path):
    tables = generate_tables(small_config, tmp_path)
    journey = tables["patient_journey"].set_index("patient_id")
    treatment = tables["treatment"].sort_values("treatment_start_date").drop_duplicates("patient_id").set_index("patient_id")
    events = tables["prescription_event"]
    initial_events = events[events.treatment_id.isin(treatment.treatment_id)]
    expected_count = initial_events.groupby("patient_id").size()
    expected_max_gap = initial_events.groupby("patient_id").refill_gap_days.max()

    assert journey.prescription_event_count.equals(journey.index.to_series().map(expected_count).fillna(0).astype("int64"))
    assert journey.max_refill_gap_days.equals(journey.index.to_series().map(expected_max_gap).fillna(0).astype("int64"))
    assert (journey.persistent_12m_gap_30d <= journey.persistent_12m_gap_60d).all()
    assert (journey.persistent_12m_gap_60d <= journey.persistent_12m_gap_90d).all()
