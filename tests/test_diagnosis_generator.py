from pathlib import Path
from prostate_journey.pipeline import generate_tables


def test_mhspc_rule(small_config, tmp_path: Path):
    tables = generate_tables(small_config, tmp_path)
    journey = tables["patient_journey"]
    mhspc = journey[journey.mhspc_flag]
    assert mhspc.metastatic_flag.all()
    assert mhspc.hormone_sensitive_flag.all()
    assert not mhspc.castration_resistant_flag.any()

