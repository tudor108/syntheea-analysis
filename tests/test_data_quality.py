from pathlib import Path

import pandas as pd

from prostate_journey.data_quality import validate_tables
from prostate_journey.pipeline import generate_tables


def test_generated_data_passes_critical_rules(small_config, tmp_path: Path):
    results = validate_tables(generate_tables(small_config, tmp_path))
    assert not [r for r in results if r["severity"] == "critical" and r["failure_count"]]


def test_quality_catches_duplicate_patient(small_config, tmp_path: Path):
    tables = generate_tables(small_config, tmp_path)
    tables["patient"].loc[1, "patient_id"] = tables["patient"].loc[0, "patient_id"]
    results = validate_tables(tables)
    assert next(r for r in results if r["rule"] == "patient_unique")["failure_count"] == 1


def test_quality_catches_invalid_prescription_event_coverage(small_config, tmp_path: Path):
    tables = generate_tables(small_config, tmp_path)
    tables["prescription_event"].loc[0, "covered_until_date"] += pd.Timedelta(days=1)

    results = validate_tables(tables)

    rule = next(r for r in results if r["rule"] == "prescription_event_coverage")
    assert rule["failure_count"] == 1
