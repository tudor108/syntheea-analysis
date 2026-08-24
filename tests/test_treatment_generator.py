from copy import deepcopy
from pathlib import Path

import pandas as pd

from prostate_journey.pipeline import generate_tables


def test_treatment_chronology_and_switch(small_config, tmp_path: Path):
    treatment = generate_tables(small_config, tmp_path)["treatment"]
    assert (treatment.treatment_end_date > treatment.treatment_start_date).all()
    assert (treatment.refill_date >= treatment.treatment_start_date).all()
    switched = treatment[treatment.switch_flag]
    assert switched.switch_date.notna().all()
    assert (switched.drug_name != switched.switched_to_drug).all()


def test_prescription_events_match_treatment_summaries(small_config, tmp_path: Path):
    config = deepcopy(small_config)
    config["switch_probability"] = 1.0
    tables = generate_tables(config, tmp_path)
    treatment = tables["treatment"]
    events = tables["prescription_event"].sort_values(
        ["treatment_id", "service_date", "prescription_event_id"]
    )

    expected_coverage = events.service_date + pd.to_timedelta(events.days_supply, unit="D")
    assert events.prescription_event_id.is_unique
    assert events.covered_until_date.equals(expected_coverage)

    event_number = events.groupby("treatment_id").cumcount()
    assert events.loc[event_number.eq(0), "event_type"].eq("initial_fill").all()
    assert events.loc[event_number.gt(0), "event_type"].eq("refill").all()

    previous_coverage = events.groupby("treatment_id").covered_until_date.shift()
    expected_gap = (events.service_date - previous_coverage).dt.days.fillna(0)
    assert events.refill_gap_days.equals(expected_gap.astype("int64"))

    event_max_gap = events.groupby("treatment_id").refill_gap_days.max()
    treatment_max_gap = treatment.set_index("treatment_id").max_refill_gap_days
    assert treatment_max_gap.equals(event_max_gap.reindex(treatment_max_gap.index))

    switched_ids = treatment.loc[treatment.treatment_line.eq(2), "treatment_id"]
    assert not switched_ids.empty
    assert events[events.treatment_id.isin(switched_ids)].groupby("treatment_id").size().ge(2).all()
