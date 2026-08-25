import math

import pandas as pd

from prostate_journey.adversarial_audit import audit_tables_independently
from prostate_journey.journey_builder import derive_persistence_status
from prostate_journey.synthea_loader import make_base_patients, make_multimarket_base


def _events(*rows):
    return pd.DataFrame(
        rows,
        columns=["prescription_event_id", "service_date", "covered_until_date"],
    )


def test_persistence_uses_landmark_and_observed_gap_chronology():
    start = pd.Timestamp("2024-01-01")
    future_gap = _events(
        ("RX-1", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-05-01")),
        ("RX-2", pd.Timestamp("2024-09-01"), pd.Timestamp("2024-12-01")),
    )
    assert (
        derive_persistence_status(
            future_gap,
            start,
            pd.Timestamp("2024-12-31"),
            90,
            60,
            pd.NaT,
            pd.NaT,
        )
        == "PERSISTENT"
    )

    one_fill = _events(("RX-1", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-31")))
    assert (
        derive_persistence_status(
            one_fill,
            start,
            pd.Timestamp("2024-06-01"),
            180,
            60,
            pd.NaT,
            pd.NaT,
        )
        == "DISCONTINUED"
    )
    assert (
        derive_persistence_status(
            one_fill,
            start,
            pd.Timestamp("2024-03-15"),
            180,
            60,
            pd.NaT,
            pd.NaT,
        )
        == "CENSORED_NOT_EVALUABLE"
    )

    sensitivity = _events(
        ("RX-1", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-31")),
        ("RX-2", pd.Timestamp("2024-04-01"), pd.Timestamp("2024-12-31")),
    )
    statuses = {
        gap: derive_persistence_status(
            sensitivity,
            start,
            pd.Timestamp("2025-01-01"),
            90,
            gap,
            pd.NaT,
            pd.NaT,
        )
        for gap in (30, 60, 90)
    }
    assert statuses == {30: "DISCONTINUED", 60: "PERSISTENT", 90: "PERSISTENT"}


def test_raw_synthea_overlay_cannot_break_configured_age_bounds(small_config):
    raw = {
        "patients": pd.DataFrame(
            {
                "Id": ["old-edge", "young-edge", "middle"],
                "GENDER": ["M", "M", "M"],
                "BIRTHDATE": ["1932-01-01", "1972-01-01", "1955-06-15"],
                "RACE": ["white", "black", "asian"],
                "ETHNICITY": ["nonhispanic", "hispanic", "nonhispanic"],
            }
        )
    }
    base = make_multimarket_base(raw, small_config)
    age = (
        pd.to_datetime(base.synthetic_index_date) - pd.to_datetime(base.BIRTHDATE)
    ).dt.days // 365
    assert age.between(small_config["minimum_age"], small_config["maximum_age"]).all()
    used = base.loc[base.source_record_type.eq("synthea_unique"), "source_patient_id"]
    assert used.is_unique


def test_generated_birth_dates_keep_exact_minimum_and_maximum_age_contract():
    base = make_base_patients(25_000, seed=191, minimum_age=50, maximum_age=90)
    age = (
        pd.to_datetime(base.synthetic_index_date) - pd.to_datetime(base.BIRTHDATE)
    ).dt.days // 365
    assert age.between(50, 90).all()
    assert {50, 90}.issubset(set(age))


def test_provider_capacity_and_treatment_specialties_follow_market_rules(
    generated_tables, small_config
):
    patient = generated_tables["patient"]
    provider = generated_tables["provider"]
    actual = provider.groupby("market_code").size().to_dict()
    expected = {
        market: max(
            4,
            math.ceil(patient.market_code.eq(market).sum() / 1000 * profile["providers_per_1000"]),
        )
        for market, profile in small_config["market_configuration"]["markets"].items()
    }
    assert actual == expected

    episode = generated_tables["treatment_episode"].set_index("treatment_episode_id")
    component = generated_tables["treatment_regimen_component"]
    specialty = component.treatment_episode_id.map(episode.prescribing_provider_id).map(
        provider.set_index("provider_id").provider_specialty
    )
    assert specialty.loc[component.drug_class.eq("chemotherapy")].eq("medical_oncology").all()
    assert specialty.loc[component.drug_name.eq("radiotherapy")].eq("radiation_oncology").all()
    assert specialty.loc[component.drug_name.eq("prostatectomy")].eq("urology").all()


def test_chemotherapy_cycles_and_specialty_referrals_are_observed_before_treatment(
    generated_tables,
):
    component = generated_tables["treatment_regimen_component"]
    episode = generated_tables["treatment_episode"].set_index("treatment_episode_id")
    event_counts = generated_tables["prescription_event"].groupby("component_id").size()
    chemo = component[component.drug_class.eq("chemotherapy")]
    chemo_counts = chemo.component_id.map(event_counts).fillna(0)
    assert chemo_counts.le(chemo.planned_cycle_count).all()
    assert chemo_counts.eq(chemo.planned_cycle_count).any()

    referral = generated_tables["referral"]
    completed_oncology = (
        referral.loc[
            referral.referral_status.eq("completed")
            & referral.destination_specialty.eq("medical_oncology")
        ]
        .groupby("patient_id")
        .completion_date.min()
    )
    chemo_start = chemo.treatment_episode_id.map(episode.treatment_start_date)
    assert chemo.patient_id.map(completed_oncology).notna().all()
    assert chemo_start.ge(chemo.patient_id.map(completed_oncology)).all()

    radiation = component[component.drug_name.eq("radiotherapy")]
    completed_radiation = (
        referral.loc[
            referral.referral_status.eq("completed")
            & referral.destination_specialty.eq("radiation_oncology")
        ]
        .groupby("patient_id")
        .completion_date.min()
    )
    radiation_start = radiation.treatment_episode_id.map(episode.treatment_start_date)
    assert radiation.patient_id.map(completed_radiation).notna().all()
    assert radiation_start.ge(radiation.patient_id.map(completed_radiation)).all()


def test_active_surveillance_transition_and_reclassification_reconstruct(generated_tables):
    active = generated_tables["active_surveillance"]
    episode = generated_tables["treatment_episode"]
    transitioned = active[active.transition_to_treatment_flag]
    observed = episode[episode.episode_reason.eq("active_surveillance_exit")].set_index(
        "patient_id"
    )
    assert transitioned.patient_id.isin(observed.index).all()
    assert transitioned.planned_treatment_start_date.equals(
        transitioned.patient_id.map(observed.treatment_start_date)
    )
    reclassified = active[active.as_reclassification_event_flag]
    assert reclassified.as_reclassification_date.equals(reclassified.as_exit_date)


def test_mart_care_outcome_and_feature_timing_are_reconstructable(generated_tables):
    encounter = generated_tables["encounter"]
    journey = generated_tables["patient_journey"].set_index("patient_id")
    first = (
        encounter.sort_values(["patient_id", "encounter_date", "sequence_number", "encounter_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
    )
    assert journey.initial_care_setting.equals(first.care_setting.reindex(journey.index))
    pathway = encounter.groupby("patient_id").care_setting.apply(
        lambda values: values.iloc[0] if values.nunique() == 1 else "mixed_pathway"
    )
    assert journey.pathway_care_setting.equals(pathway.reindex(journey.index))

    episode = generated_tables["treatment_episode"]
    ongoing = set(episode.loc[episode.treatment_status.eq("ongoing"), "patient_id"])
    outcome = generated_tables["outcome"]
    active = outcome[outcome.outcome_status.eq("active_treatment")]
    assert active.patient_id.isin(ongoing).all()

    timing = generated_tables["feature_timing"]
    assert set(generated_tables["patient_journey"].columns) == set(timing.feature_name)
    assert not (timing.future_information_flag & timing.predictor_allowed_flag).any()
    assert not (timing.target_label_flag & timing.predictor_allowed_flag).any()
    assert journey.persistence_rule_version.eq("PERSISTENCE-SYN-v2.1").all()
    referral_features = timing[timing.feature_name.str.startswith("referral_")]
    assert referral_features.availability_condition.eq(
        "referral_or_completion_date_le_prediction_index"
    ).all()


def test_independent_hostile_audit_passes_actual_records(generated_tables, small_config):
    scorecard, metrics, _ = audit_tables_independently(generated_tables, small_config)
    assert scorecard.status.eq("PASS").all(), scorecard.loc[scorecard.status.ne("PASS")].to_dict(
        orient="records"
    )
    assert scorecard.score.sum() == 100
    assert metrics["critical_events_after_censor"] == 0
    assert sum(metrics["persistence_mismatches"].values()) == 0
