from pathlib import Path
from prostate_journey.pipeline import generate_tables


def test_terminal_outcomes_are_separate(small_config, tmp_path: Path):
    tables = generate_tables(small_config, tmp_path)
    outcome, treatment = tables["outcome"], tables["treatment"]
    assert outcome.loc[outcome.death_flag, "death_date"].notna().all()
    assert outcome.loc[outcome.lost_to_follow_up_flag, "last_observed_date"].notna().all()
    assert not treatment.discontinuation_reason.astype("string").isin(["death", "lost_to_follow_up"]).any()

