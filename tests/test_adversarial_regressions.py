import math

import pandas as pd

from prostate_journey.adversarial_audit import audit_tables_independently
from prostate_journey.data_quality import validate_tables
from prostate_journey.feature_engineering import discontinuation_features
from prostate_journey.journey_builder import derive_persistence_status
from prostate_journey.synthea_loader import (
    calendar_year_age,
    make_base_patients,
    make_multimarket_base,
)


def _events(*rows):
    return pd.DataFrame(
        rows,
        columns=["prescription_event_id", "service_date", "covered_until_date"],
    )


def _calendar_ages(birth: pd.Series, reference: pd.Series) -> pd.Series:
    birth_dates = pd.to_datetime(birth)
    reference_dates = pd.to_datetime(reference)
    before_birthday = (reference_dates.dt.month < birth_dates.dt.month) | (
        reference_dates.dt.month.eq(birth_dates.dt.month)
        & reference_dates.dt.day.lt(birth_dates.dt.day)
    )
    return (reference_dates.dt.year - birth_dates.dt.year - before_birthday.astype("int64")).astype(
        "int64"
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
    age = _calendar_ages(base.BIRTHDATE, base.synthetic_index_date)
    assert age.between(small_config["minimum_age"], small_config["maximum_age"]).all()
    used = base.loc[base.source_record_type.eq("synthea_unique"), "source_patient_id"]
    assert used.is_unique


def test_generated_birth_dates_keep_exact_minimum_and_maximum_age_contract():
    base = make_base_patients(25_000, seed=191, minimum_age=50, maximum_age=90)
    age = _calendar_ages(base.BIRTHDATE, base.synthetic_index_date)
    assert age.between(50, 90).all()
    assert {50, 90}.issubset(set(age))


def test_calendar_age_waits_for_birthday_and_handles_february_29():
    assert calendar_year_age("1970-01-07", "2020-01-01") == 49
    assert calendar_year_age("1970-01-07", "2020-01-07") == 50
    assert calendar_year_age("1972-02-29", "2022-02-28") == 49
    assert calendar_year_age("1972-02-29", "2022-03-01") == 50


def test_dq_and_independent_audit_reject_day_count_age_false_positive(
    generated_tables, small_config
):
    altered = {name: frame for name, frame in generated_tables.items()}
    altered["patient"] = generated_tables["patient"].copy()
    row = altered["patient"].index[0]
    altered["patient"].loc[row, "birth_date"] = pd.Timestamp("1970-01-07")
    altered["patient"].loc[row, "index_date"] = pd.Timestamp("2020-01-01")
    altered["patient"].loc[row, "age_at_index"] = 50

    dq = {result["rule"]: result for result in validate_tables(altered)}
    assert dq["age_derived"]["failure_count"] == 1

    scorecard, _, _ = audit_tables_independently(altered, small_config)
    clinical_state = scorecard.loc[scorecard.check_id.eq(14)].iloc[0]
    assert clinical_state.status == "FAIL"


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
    timing_by_feature = timing.set_index("feature_name")
    full_episode_fields = [
        "initial_regimen",
        "initial_regimen_type",
        "combination_strategy",
        "intensification_flag",
        "regimen_component_count",
    ]
    start_snapshot_fields = [
        "regimen_at_treatment_start",
        "regimen_type_at_treatment_start",
        "combination_strategy_at_treatment_start",
        "intensification_at_treatment_start_flag",
        "regimen_component_count_at_treatment_start",
    ]
    assert timing_by_feature.loc[full_episode_fields].future_information_flag.all()
    assert not timing_by_feature.loc[full_episode_fields].predictor_allowed_flag.any()
    assert not timing_by_feature.loc[start_snapshot_fields].future_information_flag.any()
    assert timing_by_feature.loc[start_snapshot_fields].predictor_allowed_flag.all()
    assert not timing_by_feature.loc["treatment_episode_id", "predictor_allowed_flag"]
    discontinuation_frame = discontinuation_features(journey.reset_index())
    assert set(start_snapshot_fields).issubset(discontinuation_frame.columns)
    assert not set(full_episode_fields).intersection(discontinuation_frame.columns)


def test_independent_hostile_audit_passes_actual_records(generated_tables, small_config):
    scorecard, metrics, _ = audit_tables_independently(generated_tables, small_config)
    assert scorecard.status.eq("PASS").all(), scorecard.loc[scorecard.status.ne("PASS")].to_dict(
        orient="records"
    )
    assert scorecard.score.sum() == 100
    assert metrics["critical_events_after_censor"] == 0
    assert sum(metrics["persistence_mismatches"].values()) == 0
