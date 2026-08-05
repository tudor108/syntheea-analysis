from pathlib import Path
from prostate_journey.pipeline import generate_tables


def test_treatment_chronology_and_switch(small_config, tmp_path: Path):
    treatment = generate_tables(small_config, tmp_path)["treatment"]
    assert (treatment.treatment_end_date > treatment.treatment_start_date).all()
    assert (treatment.refill_date >= treatment.treatment_start_date).all()
    switched = treatment[treatment.switch_flag]
    assert switched.switch_date.notna().all()
    assert (switched.drug_name != switched.switched_to_drug).all()

