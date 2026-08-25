def test_outcomes_have_imperfect_clinical_signal(generated_tables):
    journey = generated_tables["patient_journey"]
    progression = journey.groupby("metastatic_flag").progression_event.mean()
    assert progression.between(0.01, 0.95).all()
    assert progression.loc[True] > progression.loc[False] + 0.05
    assert journey.progression_event.nunique() == 2
    assert journey.hospitalisation_flag.nunique() == 2


def test_competing_censoring_and_dated_adverse_events(generated_tables):
    observation = generated_tables["observation"]
    adverse = generated_tables["adverse_event"]
    episode = generated_tables["treatment_episode"].set_index("treatment_episode_id")
    censor = observation.set_index("patient_id").censor_date
    assert not (observation.death_date.notna() & observation.loss_to_follow_up_date.notna()).any()
    assert observation.censor_date.equals(observation.last_observed_date)
    assert (
        adverse.adverse_event_date >= adverse.treatment_episode_id.map(episode.treatment_start_date)
    ).all()
    assert (adverse.adverse_event_date <= adverse.patient_id.map(censor)).all()


def test_active_surveillance_has_monitoring_exit_and_treatment_transition(generated_tables):
    active = generated_tables["active_surveillance"]
    encounter = generated_tables["encounter"]
    assert active.as_start_date.notna().any()
    assert active.as_exit_date.notna().any()
    assert active.transition_to_treatment_flag.any()
    assert encounter.encounter_type.str.startswith("as_").any()
    transitioned = active[active.transition_to_treatment_flag]
    assert transitioned.planned_treatment_start_date.notna().all()
    assert (transitioned.planned_treatment_start_date >= transitioned.as_exit_date).all()
