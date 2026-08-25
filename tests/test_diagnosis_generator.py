from prostate_journey.diagnosis_generator import isup_from_patterns


def test_mhspc_rule_is_reconstructable(generated_tables):
    journey = generated_tables["patient_journey"]
    expected = (
        journey.metastatic_flag
        & journey.hormone_sensitive_flag
        & ~journey.castration_resistant_flag
    )
    assert journey.mhspc_flag.equals(expected)


def test_gleason_score_and_isup_mapping(generated_tables):
    diagnosis = generated_tables["diagnosis"].dropna(
        subset=["gleason_primary_pattern", "gleason_secondary_pattern", "isup_grade_group"]
    )
    assert (
        diagnosis.gleason_score
        == diagnosis.gleason_primary_pattern + diagnosis.gleason_secondary_pattern
    ).all()
    expected = diagnosis.apply(
        lambda row: isup_from_patterns(
            int(row.gleason_primary_pattern), int(row.gleason_secondary_pattern)
        ),
        axis=1,
    )
    assert diagnosis.isup_grade_group.astype(int).equals(expected.astype(int))


def test_disease_state_transitions_only_move_forward(generated_tables):
    events = generated_tables["disease_state_event"].sort_values(
        ["patient_id", "state_date", "disease_state_event_id"]
    )
    transitions = events[events.previous_state.notna()]
    assert set(zip(transitions.previous_state, transitions.state, strict=False)) <= {
        ("mHSPC", "mCRPC")
    }
    prior_date = events.groupby("patient_id").state_date.shift()
    assert (events.loc[prior_date.notna(), "state_date"] >= prior_date.dropna()).all()
