from datetime import timedelta

from prostate_journey.release_reconciliation import reconcile_release_tables


def test_clean_generated_tables_reconcile_without_mismatches(generated_tables, small_config):
    detail, summary, hard_failures = reconcile_release_tables(generated_tables, small_config)

    assert detail.empty, detail.head(20).to_dict(orient="records")
    assert len(summary) == 10
    assert summary.status.eq("PASS").all()
    assert summary.mismatches.eq(0).all()
    assert summary.comparisons.gt(0).all()
    assert hard_failures == []


def test_mutated_mart_field_is_reported_at_row_level(generated_tables, small_config):
    altered = {name: frame for name, frame in generated_tables.items()}
    altered["patient_journey"] = generated_tables["patient_journey"].copy()
    row = altered["patient_journey"].index[0]
    patient_id = altered["patient_journey"].loc[row, "patient_id"]
    original = bool(altered["patient_journey"].loc[row, "eligibility_flag"])
    altered["patient_journey"].loc[row, "eligibility_flag"] = not original

    detail, summary, hard_failures = reconcile_release_tables(altered, small_config)

    detected = detail.loc[
        detail.concept.eq("eligibility")
        & detail.patient_id.eq(patient_id)
        & detail.field.eq("patient_journey.eligibility_flag")
    ]
    assert len(detected) == 1
    assert summary.set_index("concept").loc["eligibility", "status"] == "FAIL"
    assert any(failure.startswith("eligibility:") for failure in hard_failures)


def test_switch_coverage_after_replacement_is_a_hard_mismatch(transition_tables, small_config):
    altered = {name: frame for name, frame in transition_tables.items()}
    altered["prescription_event"] = transition_tables["prescription_event"].copy()
    switched = (
        transition_tables["treatment_episode"]
        .loc[transition_tables["treatment_episode"].transition_type.eq("switch")]
        .iloc[0]
    )
    prior = (
        transition_tables["treatment_episode"]
        .set_index("treatment_episode_id")
        .loc[switched.previous_episode_id]
    )
    old_event_index = altered["prescription_event"].index[
        altered["prescription_event"].treatment_episode_id.eq(switched.previous_episode_id)
    ][0]
    altered["prescription_event"].loc[old_event_index, "covered_until_date"] = (
        prior.switch_date + timedelta(days=1)
    )

    detail, summary, hard_failures = reconcile_release_tables(altered, small_config)

    assert detail.field.eq("switch.old_coverage_not_after_switch").any()
    assert summary.set_index("concept").loc["switch_restart", "status"] == "FAIL"
    assert any(failure.startswith("switch_restart:") for failure in hard_failures)
