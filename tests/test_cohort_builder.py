import numpy as np
import pandas as pd
from prostate_journey.cohort_builder import build_patient_table
from prostate_journey.synthea_loader import make_base_patients, select_base_patients


def test_cohort_is_male_and_not_representative(small_config):
    base = make_base_patients(20, 1, 50, 90)
    result = build_patient_table(base, small_config, np.random.default_rng(1))
    assert result.patient_id.is_unique
    assert set(result.sex) == {"male"}
    assert not result.population_representative_flag.any()


def test_synthea_birthdates_are_filtered_and_oversampled():
    raw = pd.DataFrame({"Id": ["a", "b"], "BIRTHDATE": ["1955-06-01", "2010-01-01"], "GENDER": ["M", "M"]})
    selected = select_base_patients({"patients": raw}, 5, 42, 50, 90)
    assert len(selected) == 5
    assert set(selected.Id) == {"a"}
