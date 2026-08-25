import pandas as pd


def test_normalized_treatment_hierarchy_and_chronology(generated_tables):
    episode = generated_tables["treatment_episode"]
    regimen = generated_tables["treatment_regimen"]
    component = generated_tables["treatment_regimen_component"]
    assert (episode.treatment_start_date < episode.treatment_end_date).all()
    assert regimen.treatment_episode_id.isin(episode.treatment_episode_id).all()
    assert component.regimen_id.isin(regimen.regimen_id).all()
    assert component.treatment_episode_id.isin(episode.treatment_episode_id).all()
    assert {"ADT", "ARPI", "chemotherapy", "procedure"}.issubset(set(component.drug_class))
    assert {"monotherapy", "doublet", "triplet"}.issubset(set(regimen.regimen_type))


def test_dispensing_has_realistic_supply_refill_and_effective_coverage(generated_tables):
    event = generated_tables["prescription_event"].sort_values(
        ["component_id", "service_date", "prescription_event_id"]
    )
    component = generated_tables["treatment_regimen_component"].set_index("component_id")
    nominal = event.service_date + pd.to_timedelta(event.days_supply, unit="D")
    assert event.nominal_covered_until_date.equals(nominal)
    assert (event.covered_until_date >= event.service_date).all()
    assert (event.covered_until_date <= event.component_id.map(component.component_end_date)).all()
    ordered_previous_coverage = event.groupby("component_id").covered_until_date.shift()
    early_refills = ordered_previous_coverage.notna() & event.service_date.lt(
        ordered_previous_coverage
    )
    assert (
        event.loc[early_refills, "covered_until_date"]
        >= ordered_previous_coverage.loc[early_refills]
    ).all()
    assert (event.covered_until_date <= event.component_id.map(component.component_end_date)).all()
    assert event.days_supply.nunique() >= 5
    assert {"early", "on_time", "late"}.issubset(set(event.refill_timing))
    first = event.groupby("component_id").cumcount().eq(0)
    assert event.loc[first, "event_type"].eq("initial_fill").all()
    assert event.loc[~first, "event_type"].eq("refill").all()


def test_switch_restart_add_on_and_discontinuation_are_distinct(transition_tables):
    episode = transition_tables["treatment_episode"]
    regimen = transition_tables["treatment_regimen"]
    event = transition_tables["prescription_event"]
    assert {"switch", "restart"}.issubset(set(episode.transition_type))
    assert {"planned_combination", "add_on"}.issubset(set(regimen.combination_strategy))
    assert episode.discontinuation_flag.any()

    lookup = episode.set_index("treatment_episode_id")
    linked = episode[episode.transition_type.isin(["switch", "restart"])]
    previous_end = linked.previous_episode_id.map(lookup.treatment_end_date)
    assert (linked.treatment_start_date > previous_end).all()
    switched_previous = set(linked.loc[linked.transition_type.eq("switch"), "previous_episode_id"])
    old_events = event[event.treatment_episode_id.isin(switched_previous)]
    assert (
        old_events.service_date <= old_events.treatment_episode_id.map(lookup.treatment_end_date)
    ).all()


def test_persistence_sensitivity_is_nullable_and_monotonic(generated_tables):
    journey = generated_tables["patient_journey"]
    p30 = journey.persistent_12m_gap_30d.fillna(False)
    p60 = journey.persistent_12m_gap_60d.fillna(False)
    p90 = journey.persistent_12m_gap_90d.fillna(False)
    assert not (p30 & ~p60).any()
    assert not (p60 & ~p90).any()
    censored = journey.persistence_12m_status.eq("CENSORED_NOT_EVALUABLE")
    assert journey.loc[censored, "persistent_12m"].isna().all()
    assert p30.sum() < p90.sum()
