import pandas as pd


def _copy_tables(tables):
    return {name: frame.copy(deep=True) for name, frame in tables.items()}


def _rule(results, name):
    return next(result for result in results if result["rule"] == name)


def test_generated_data_passes_every_quality_rule(generated_tables):
    from prostate_journey.data_quality import validate_tables

    results = validate_tables(generated_tables)
    assert len(results) >= 65
    assert not [result for result in results if result["failure_count"]]


def test_quality_catches_duplicate_primary_key(generated_tables):
    from prostate_journey.data_quality import validate_tables

    tables = _copy_tables(generated_tables)
    tables["patient"].loc[1, "patient_id"] = tables["patient"].loc[0, "patient_id"]
    assert _rule(validate_tables(tables), "pk_patient")["failure_count"] == 1


def test_quality_catches_event_after_censor(generated_tables):
    from prostate_journey.data_quality import validate_tables

    tables = _copy_tables(generated_tables)
    patient_id = tables["encounter"].loc[0, "patient_id"]
    censor = tables["observation"].set_index("patient_id").loc[patient_id, "censor_date"]
    tables["encounter"].loc[0, "encounter_date"] = censor + type(censor - censor)(days=1)
    assert _rule(validate_tables(tables), "no_event_after_censor")["failure_count"] >= 1


def test_quality_catches_opaque_eligibility_and_provider_mismatch(generated_tables):
    from prostate_journey.data_quality import validate_tables

    tables = _copy_tables(generated_tables)
    tables["eligibility"].loc[0, "eligibility_flag"] = ~tables["eligibility"].loc[
        0, "eligibility_flag"
    ]
    tables["encounter"].loc[0, "provider_specialty"] = "invalid_specialty"
    results = validate_tables(tables)
    assert _rule(results, "eligibility_reconstructable")["failure_count"] >= 1
    assert _rule(results, "encounter_specialty_matches_provider")["failure_count"] == 1


def test_quality_reconstructs_initiation_censor_and_real_referral_evidence(generated_tables):
    from prostate_journey.data_quality import validate_tables

    tables = _copy_tables(generated_tables)
    eligible_index = tables["patient_journey"].index[tables["patient_journey"].eligibility_flag][0]
    tables["patient_journey"].loc[eligible_index, "initiated_within_90d"] = not bool(
        tables["patient_journey"].loc[eligible_index, "initiated_within_90d"]
    )

    terminal = (
        tables["observation"].death_date.notna()
        | tables["observation"].loss_to_follow_up_date.notna()
    )
    observation_index = terminal.idxmax()
    if not terminal.any():
        tables["observation"].loc[observation_index, "death_date"] = tables["observation"].loc[
            observation_index, "observation_end_date"
        ] - pd.Timedelta(days=1)
    tables["observation"].loc[observation_index, "censor_date"] = tables["observation"].loc[
        observation_index, "observation_end_date"
    ]

    completed_index = tables["referral"].index[tables["referral"].referral_status.eq("completed")][
        0
    ]
    completed_patient = tables["referral"].loc[completed_index, "patient_id"]
    completed_censor = (
        tables["observation"].set_index("patient_id").loc[completed_patient, "censor_date"]
    )
    tables["referral"].loc[completed_index, "completion_date"] = completed_censor

    results = validate_tables(tables)
    assert _rule(results, "mart_initiation_window_reconciliation")["failure_count"] >= 1
    assert _rule(results, "observation_competing_risks")["failure_count"] >= 1
    assert _rule(results, "referral_destination_event_evidence")["failure_count"] >= 1
