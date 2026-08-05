# Data Quality Report

> **SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA**

| Rule | Severity | Status | Failures | Detail |
|---|---|---:|---:|---|
| patient_unique | critical | pass | 0 | patient_id must be unique |
| male_only | critical | pass | 0 | prostate cohort contains males only |
| birth_before_diagnosis | critical | pass | 0 | birth precedes diagnosis |
| diagnosis_before_metastatic | critical | pass | 0 | diagnosis <= metastatic |
| eligibility_before_treatment | critical | pass | 0 | eligibility <= start |
| treatment_dates | critical | pass | 0 | start < end |
| death_after_birth | critical | pass | 0 | death after birth |
| death_censor_alignment | critical | pass | 0 | death not after censor |
| mhspc_implies_metastatic | critical | pass | 0 | mHSPC => metastatic |
| mhspc_implies_hormone_sensitive | critical | pass | 0 | mHSPC => hormone sensitive |
| mhspc_excludes_cr | critical | pass | 0 | mHSPC excludes CR at index |
| eligibility_implies_mhspc | critical | pass | 0 | demo eligibility => mHSPC |
| nonnegative_referral_delay_days | critical | pass | 0 | referral_delay_days cannot be negative |
| nonnegative_days_to_initiation | critical | pass | 0 | days_to_initiation cannot be negative |
| nonnegative_days_to_discontinuation | critical | pass | 0 | days_to_discontinuation cannot be negative |
| nonnegative_days_to_switch | critical | pass | 0 | days_to_switch cannot be negative |
| nonnegative_days_to_progression | critical | pass | 0 | days_to_progression cannot be negative |
| persistence_requires_followup | warning | pass | 0 | 12m persistence requires follow-up |
| switch_has_date | critical | pass | 0 | switch implies date |
| restart_has_date | critical | pass | 0 | restart implies date |
| death_has_date | critical | pass | 0 | death implies date |
| ltfu_has_last_observed | critical | pass | 0 | LTFU implies last observed |
| no_switch_after_death | critical | pass | 0 | no switch after death |
| no_treatment_after_death | critical | pass | 0 | no treatment after death |
| death_not_nonadherence | critical | pass | 0 | death is a separate outcome |
| ltfu_not_discontinuation | critical | pass | 0 | LTFU is separate |
| persistence_requires_initiation | critical | pass | 0 | persistence requires initiation |
| refill_after_start | critical | pass | 0 | refill >= start |
| coverage_after_refill | critical | pass | 0 | coverage >= refill |
| encounter_provider_fk | critical | pass | 0 | encounter provider exists |
| treatment_provider_fk | critical | pass | 0 | prescriber exists |
| patient_foreign_keys | critical | pass | 0 | all patient foreign keys exist |
| diagnosis_patient_coverage | critical | pass | 0 | each patient has diagnosis |
| outcome_patient_coverage | critical | pass | 0 | each patient has outcome |
