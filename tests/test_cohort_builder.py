import pandas as pd

REQUIRED_MARKETS = {"US", "DE", "JP", "FR", "CN", "AU", "CA"}


def test_population_has_independent_archetypes_and_all_markets(generated_tables):
    patient = generated_tables["patient"]
    assert set(patient.market_code) == REQUIRED_MARKETS
    assert patient.patient_id.is_unique
    assert patient.source_archetype_id.is_unique
    raw_sources = patient.loc[
        patient.source_record_type.eq("synthea_unique"), "source_patient_id"
    ].dropna()
    assert raw_sources.is_unique
    assert set(patient.sex) == {"male"}
    assert not patient.population_representative_flag.any()


def test_age_is_derived_from_dates_and_has_variation(generated_tables):
    patient = generated_tables["patient"]
    expected = (
        pd.to_datetime(patient.index_date) - pd.to_datetime(patient.birth_date)
    ).dt.days // 365
    pd.testing.assert_series_equal(patient.age_at_index, expected, check_names=False)
    assert patient.age_at_index.nunique() >= 30
    assert patient.age_at_index.between(50, 90).all()


def test_market_profiles_are_not_country_label_clones(generated_tables):
    patient = generated_tables["patient"]
    market_means = patient.groupby("market_code").agg(
        access=("access_index", "mean"),
        comorbidity=("comorbidity_score", "mean"),
        age=("age_at_index", "mean"),
    )
    assert market_means.access.max() - market_means.access.min() > 0.08
    assert market_means.age.max() - market_means.age.min() > 1.0
    assert patient.groupby("market_code").insurance_type.nunique().min() >= 2
