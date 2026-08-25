# Data Quality Report

> **SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA**

| Rule | Severity | Status | Failures | Detail |
|---|---|---:|---:|---|
| pk_patient | critical | pass | 0 | patient_id is non-null and unique at documented grain |
| pk_diagnosis | critical | pass | 0 | diagnosis_id is non-null and unique at documented grain |
| pk_disease_state_event | critical | pass | 0 | disease_state_event_id is non-null and unique at documented grain |
| pk_eligibility | critical | pass | 0 | eligibility_id is non-null and unique at documented grain |
| pk_organization | critical | pass | 0 | organization_id is non-null and unique at documented grain |
| pk_provider | critical | pass | 0 | provider_id is non-null and unique at documented grain |
| pk_encounter | critical | pass | 0 | encounter_id is non-null and unique at documented grain |
| pk_referral | critical | pass | 0 | referral_id is non-null and unique at documented grain |
| pk_active_surveillance | critical | pass | 0 | active_surveillance_id is non-null and unique at documented grain |
| pk_observation | critical | pass | 0 | observation_id is non-null and unique at documented grain |
| pk_treatment_episode | critical | pass | 0 | treatment_episode_id is non-null and unique at documented grain |
| pk_treatment_regimen | critical | pass | 0 | regimen_id is non-null and unique at documented grain |
| pk_treatment_regimen_component | critical | pass | 0 | component_id is non-null and unique at documented grain |
| pk_prescription_event | critical | pass | 0 | prescription_event_id is non-null and unique at documented grain |
| pk_adverse_event | critical | pass | 0 | adverse_event_id is non-null and unique at documented grain |
| pk_outcome | critical | pass | 0 | outcome_id is non-null and unique at documented grain |
| pk_patient_split | critical | pass | 0 | patient_split_id is non-null and unique at documented grain |
| pk_feature_timing | critical | pass | 0 | feature_metadata_id is non-null and unique at documented grain |
| pk_patient_journey | critical | pass | 0 | patient_id is non-null and unique at documented grain |
| fk_patient | critical | pass | 0 | all patient foreign keys resolve |
| fk_provider_organization | critical | pass | 0 | provider organization foreign keys resolve |
| fk_encounter_provider | critical | pass | 0 | encounter provider foreign keys resolve |
| fk_referral_providers | critical | pass | 0 | referral source and destination providers resolve |
| fk_treatment | critical | pass | 0 | all normalized treatment foreign keys resolve |
| age_derived | critical | pass | 0 | age is derived from DOB and index date |
| age_configured_range | critical | pass | 0 | age stays within the configured 50-90 year cohort contract |
| male_only | critical | pass | 0 | prostate cohort contains males only |
| independent_archetypes | critical | pass | 0 | each generated patient has an independent archetype identifier |
| no_source_cloning | critical | pass | 0 | raw Synthea IDs are never cloned |
| all_markets | critical | pass | 0 | all seven required markets are present |
| birth_before_diagnosis | critical | pass | 0 | birth precedes diagnosis |
| gleason_isup_mapping | critical | pass | 0 | Gleason patterns, score and ISUP mapping are coherent |
| metastatic_state_consistency | critical | pass | 0 | hormone-sensitive and resistant metastatic states are coherent |
| disease_state_transitions | critical | pass | 0 | disease states are chronological and only configured forward transitions occur |
| eligibility_reconstructable | critical | pass | 0 | eligibility reconstructs exactly from exported source variables |
| eligibility_date_semantics | critical | pass | 0 | eligibility date exists only for eligible patients |
| ineligibility_explained | critical | pass | 0 | every ineligible/insufficient patient has a reason |
| no_event_after_censor | critical | pass | 0 | no clinical event occurs after censor/death/LTFU |
| downstream_events_after_diagnosis | critical | pass | 0 | clinical pathway events do not precede diagnosis |
| observation_competing_risks | critical | pass | 0 | death and LTFU are competing and censor equals last observation |
| encounter_specialty_matches_provider | critical | pass | 0 | encounter specialty matches provider master specialty |
| encounter_setting_matches_provider | critical | pass | 0 | encounter care setting derives from provider organization |
| encounter_organization_matches_provider | critical | pass | 0 | encounter organization matches the provider master |
| referral_distinct_providers | critical | pass | 0 | real transfers use distinct source and destination providers |
| referral_specialty_consistency | critical | pass | 0 | referral specialties match provider masters |
| referral_organization_consistency | critical | pass | 0 | referral source and destination organizations match provider masters |
| referral_completion_semantics | critical | pass | 0 | only completed referrals have completion dates |
| referral_decision_owner_semantics | critical | pass | 0 | decision ownership transfers only when the referral completes |
| treatment_episode_dates | critical | pass | 0 | episode intervals and terminal events are coherent |
| treatment_censor_status | critical | pass | 0 | ongoing versus censored episode status reflects the terminal boundary |
| regimen_episode_dates | critical | pass | 0 | regimens stay within episodes |
| component_episode_dates | critical | pass | 0 | regimen components stay within their episode |
| intensification_reconstructable | critical | pass | 0 | intensification derives from mHSPC state and regimen components |
| treatment_provider_compatibility | critical | pass | 0 | chemotherapy, radiotherapy and surgery use compatible specialists |
| chemotherapy_referral_coherence | critical | pass | 0 | chemotherapy occurs only after an observed, already-completed oncology referral |
| radiotherapy_referral_coherence | critical | pass | 0 | radiotherapy occurs only after a completed radiation-oncology transfer |
| chemotherapy_cycle_limit | critical | pass | 0 | chemotherapy dispensing does not exceed the explicit planned cycle count |
| prescription_component_match | critical | pass | 0 | prescription events match component drug and patient |
| prescription_dates | critical | pass | 0 | dispensing dates and nominal/effective coverage are coherent |
| prescription_sequence | critical | pass | 0 | initial/refill sequence and early/on-time/late gaps reconstruct |
| prescription_coverage_monotonic | critical | pass | 0 | effective coverage never moves backward after an early refill |
| prescription_component_coverage | critical | pass | 0 | every component with dispensing detail has exactly one initial event |
| prescription_episode_summary | critical | pass | 0 | episode maximum refill gap reconciles to events |
| switch_restart_nonoverlap | critical | pass | 0 | switch/restart episodes link to and follow the closed prior episode |
| no_old_drug_after_switch | critical | pass | 0 | true switch closes previous dispensing |
| active_surveillance_logic | critical | pass | 0 | AS start, exit and treatment transition are coherent |
| active_surveillance_treatment_reconciliation | critical | pass | 0 | every observed AS treatment transition has a matching normalized episode |
| active_surveillance_reclassification_semantics | critical | pass | 0 | AS reclassification is a dated event reconciled to AS exit |
| persistence_rule_version | critical | pass | 0 | every mart persistence label carries the configured v2.1 definition |
| persistence_3m_status_reconstructable | critical | pass | 0 | persistence_3m_status reconstructs from landmark-bounded dispensing events |
| persistence_6m_status_reconstructable | critical | pass | 0 | persistence_6m_status reconstructs from landmark-bounded dispensing events |
| persistence_12m_status_reconstructable | critical | pass | 0 | persistence_12m_status reconstructs from landmark-bounded dispensing events |
| persistence_right_censoring | critical | pass | 0 | 12-month status distinguishes observed gap failure from right censoring |
| persistence_sensitivity_reconstructable_30 | critical | pass | 0 | 30-day persistence reconstructs independently from events |
| persistence_status_flag_30 | critical | pass | 0 | 30-day status and nullable flag agree |
| persistence_sensitivity_reconstructable_60 | critical | pass | 0 | 60-day persistence reconstructs independently from events |
| persistence_status_flag_60 | critical | pass | 0 | 60-day status and nullable flag agree |
| persistence_sensitivity_reconstructable_90 | critical | pass | 0 | 90-day persistence reconstructs independently from events |
| persistence_status_flag_90 | critical | pass | 0 | 90-day status and nullable flag agree |
| persistence_sensitivity_monotonic | critical | pass | 0 | persistence cannot decrease when the permissible gap increases |
| split_one_per_patient | critical | pass | 0 | each independent patient/archetype belongs to one split |
| split_archetype_no_overlap | critical | pass | 0 | no archetype crosses train/validation/test |
| feature_timing_leakage | critical | pass | 0 | future/outcome features are prohibited from predictive feature sets |
| feature_timing_mart_coverage | critical | pass | 0 | every analytical mart field has one explicit timing/governance record |
| mart_eligibility_reconciliation | critical | pass | 0 | mart eligibility reconciles to eligibility table |
| mart_treatment_reconciliation | critical | pass | 0 | mart initiation reconciles to episodes |
| mart_outcome_reconciliation | critical | pass | 0 | mart outcomes reconcile to normalized outcome table |
| outcome_status_reconstructable | critical | pass | 0 | terminal outcome status and model version reconstruct from dated source states |
| mart_care_setting_reconciliation | critical | pass | 0 | initial care setting and specialty derive only from the first encounter |
| mart_pathway_setting_reconciliation | critical | pass | 0 | descriptive pathway setting reconciles to the complete encounter sequence |
