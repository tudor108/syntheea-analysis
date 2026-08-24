# Data Dictionary

> **SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA**  
> `generated` means sampled from YAML; `derived` means calculated by the stated rule. Examples are illustrative only. Dates use ISO-8601.

## patient

| Column | Definition | Type | Example | Source/method | Nullable | Validation |
|---|---|---|---|---|---|---|
| patient_id | Demo patient key | string | PJ-00000001 | generated | no | unique PK |
| synthea_patient_id | Source patient key | string | abc-123 | Synthea/fallback | no | traceable |
| birth_date | Date of birth | date | 1954-03-01 | Synthea | no | before diagnosis |
| birth_year | Birth year | integer | 1954 | derived | no | matches birth date |
| age_at_index | Age at index | integer | 68 | derived | no | configured range |
| sex | Recorded sex | category | male | Synthea/filter | no | male only |
| country | Synthetic country | string | US | generated | no | expected value |
| region | Synthetic state/region | string | MA | Synthea | no | provider region |
| postal_code_prefix | First 3 ZIP digits | string | 021 | Synthea | no | de-identified prefix |
| race | Synthetic race | category | white | Synthea | yes | configured missingness |
| ethnicity | Synthetic ethnicity | category | nonhispanic | Synthea | yes | configured missingness |
| insurance_type | Synthetic payer class | category | medicare | generated/Synthea-ready | yes | configured values |
| comorbidity_score | Demo burden count | integer | 2 | generated | no | 0–8 |
| frailty_proxy | Non-clinical demo proxy | decimal | 0.31 | generated | no | 0–1 |
| socioeconomic_proxy | Demo SES band | category | medium | generated | no | expected values |
| date_of_death | Generated death date | date | 2024-02-01 | outcome | yes | after birth |
| synthetic_oversampling_flag | Cohort enriched | boolean | true | constant | no | true |
| population_representative_flag | Population representative | boolean | false | constant | no | false |
| sampling_weight | Internal scenario weight | decimal | 1.0 | generated | no | positive |
| synthetic_scenario_version | Scenario version | string | demo-v1.0 | config | no | metadata match |

## diagnosis

| Column | Definition | Type | Example | Source/method | Nullable | Validation |
|---|---|---|---|---|---|---|
| diagnosis_id | Diagnosis key | string | DX-00000001 | generated | no | unique |
| patient_id | Patient FK | string | PJ-00000001 | patient | no | valid FK |
| diagnosis_date | Index diagnosis | date | 2022-01-10 | generated | no | after birth |
| prostate_cancer_flag | Prostate cohort marker | boolean | true | constant | no | true |
| prostate_stage | Demo stage | category | metastatic | generated | no | allowed enum |
| localized_flag | Localized indicator | boolean | false | derived | no | stage-consistent |
| locally_advanced_flag | Locally advanced | boolean | false | derived | no | stage-consistent |
| metastatic_flag | Metastatic indicator | boolean | true | derived | no | stage-consistent |
| metastatic_date | First metastatic date | date | 2022-01-22 | generated | yes | on/after diagnosis |
| metastatic_site | Demo metastatic site | category | bone | generated | no | allowed enum |
| hormone_sensitive_flag | Sensitive at index | boolean | true | generated | no | mHSPC rule |
| castration_resistant_flag | Resistant at index | boolean | false | generated | no | excludes mHSPC |
| castration_resistant_date | Transition date | date | 2024-01-01 | generated | yes | transition evidence |
| risk_group | Demo risk band | category | high | generated | no | expected enum |
| psa_value | Synthetic PSA | decimal | 42.1 | generated | yes | nonnegative |
| gleason_score | Synthetic score | integer | 8 | generated | yes | 6–10 |
| isup_grade_group | Synthetic ISUP group | integer | 3 | derived | no | 1–5 |
| diagnosis_source | Record provenance | string | synthetic_enrichment | constant | no | labeled synthetic |
| data_quality_flag | Row-level status | string | pass | derived | no | expected value |

## provider

| Column | Definition | Type | Example | Source/method | Nullable | Validation |
|---|---|---|---|---|---|---|
| provider_id | Provider key | string | PR-MA-001 | generated | no | unique PK |
| organization_id | Organization key | string | ORG-MA-00 | generated | no | nonempty |
| provider_specialty | Demo specialty | category | urology | generated | no | allowed enum |
| care_setting | Demo pathway setting | category | community_urology | generated | no | allowed enum |
| academic_flag | Academic marker | boolean | false | derived | no | setting-consistent |
| region | Provider region | string | MA | generated | no | patient coverage |
| annual_prostate_volume | Synthetic annual volume | integer | 120 | generated | no | positive |
| multidisciplinary_team_flag | MDT availability | boolean | true | generated | no | boolean |
| synthetic_provider_flag | Synthetic marker | boolean | true | constant | no | true |

## encounter

| Column | Definition | Type | Example | Source/method | Nullable | Validation |
|---|---|---|---|---|---|---|
| encounter_id | Encounter key | string | ENC-00000001-1 | generated | no | unique |
| patient_id | Patient FK | string | PJ-00000001 | patient | no | valid FK |
| provider_id | Provider FK | string | PR-MA-001 | provider | no | valid FK |
| organization_id | Organization FK | string | ORG-MA-00 | provider | no | matches provider |
| encounter_date | Event date | date | 2022-02-01 | generated | no | chronological |
| encounter_type | Event type | category | oncology_consultation | generated | no | allowed enum |
| specialty | Encounter specialty | category | medical_oncology | derived | no | expected enum |
| care_setting | Event setting | category | academic_oncology | provider | no | allowed enum |
| referral_flag | Referral issued | boolean | true | generated | no | evidence-consistent |
| referral_source_specialty | Referral source | category | urology | generated | yes | needed when referral |
| referral_target_specialty | Referral target | category | medical_oncology | generated | yes | needed when referral |
| referral_date | Referral date | date | 2022-02-01 | generated | yes | on/before completion |
| referral_completed_flag | Consultation completed | boolean | true | derived | no | completion evidence |
| referral_completion_date | Completion date | date | 2022-03-01 | generated | yes | nonnegative delay |
| synthetic_event_flag | Synthetic marker | boolean | true | constant | no | true |

## treatment

| Column | Definition | Type | Example | Source/method | Nullable | Validation |
|---|---|---|---|---|---|---|
| treatment_id | Treatment episode key | string | TR-00000001-0 | generated | no | unique |
| patient_id | Patient FK | string | PJ-00000001 | patient | no | valid FK |
| drug_name | Demo drug | category | darolutamide | generated | no | configured list |
| drug_class | Drug class | category | ARPI | mapped | no | allowed enum |
| regimen_name | Demo regimen label | string | synthetic_darolutamide_regimen | generated | no | synthetic prefix |
| treatment_line | Sequence number | integer | 1 | derived | no | positive |
| treatment_start_date | Episode start | date | 2022-04-01 | generated | no | after eligibility |
| treatment_end_date | Episode end | date | 2023-04-01 | generated | no | after start |
| days_supply | Supply days | integer | 30 | generated | no | positive |
| refill_date | First/episode refill | date | 2022-04-01 | generated | no | on/after start |
| covered_until_date | Coverage end | date | 2023-04-01 | derived | no | on/after refill |
| treatment_setting | Care setting | category | community_oncology | provider | no | allowed enum |
| prescribing_specialty | Prescriber specialty | category | medical_oncology | provider | no | expected enum |
| prescribing_provider_id | Provider FK | string | PR-MA-001 | provider | no | valid FK |
| discontinuation_flag | Definitive stop | boolean | true | generated | no | date consistency |
| discontinuation_date | Stop date | date | 2022-10-01 | generated | yes | after start |
| discontinuation_reason | Synthetic reason | category | adverse_event | generated | yes | excludes death/LTFU |
| switch_flag | Switch from episode | boolean | true | generated | no | implies date/new drug |
| switch_date | Switch date | date | 2022-08-01 | generated | yes | after start |
| previous_drug | Drug before switch | category | ADT | derived | yes | different from new |
| switched_to_drug | New drug | category | apalutamide | generated | yes | different drug |
| restart_flag | Restart after gap | boolean | true | generated | no | implies date |
| restart_date | Restart date | date | 2023-01-01 | generated | yes | gap > threshold |
| temporary_gap_flag | Gap ended in restart | boolean | true | derived | no | restart-consistent |
| max_refill_gap_days | Largest generated gap | integer | 41 | derived | no | nonnegative |
| synthetic_event_flag | Synthetic marker | boolean | true | constant | no | true |

## prescription_event

One row represents one synthetic initial fill or refill. Events are linked to a generated treatment episode and are not CMS observations.

| Column | Definition | Type | Example | Source/method | Nullable | Validation |
|---|---|---|---|---|---|---|
| prescription_event_id | Prescription-event key | string | TR-00000001-0-RX-0000 | generated | no | unique |
| patient_id | Patient FK | string | PJ-00000001 | patient | no | valid FK and treatment match |
| treatment_id | Treatment FK | string | TR-00000001-0 | treatment | no | valid FK |
| service_date | Fill/refill date | date | 2022-04-01 | generated | no | within treatment episode |
| product_id | Synthetic product identifier | string | SYN-DAROLUTAMIDE | mapped | no | synthetic prefix |
| drug_name | Dispensed demo drug | category | darolutamide | treatment | no | treatment-consistent |
| quantity_dispensed | Synthetic quantity | integer | 30 | generated | no | positive |
| days_supply | Supplied days | integer | 30 | generated | no | positive |
| covered_until_date | Event coverage end | date | 2022-05-01 | derived | no | service date + days supply |
| event_type | Dispensing event type | category | refill | derived | no | initial_fill then refill |
| refill_gap_days | Gap after prior coverage | integer | 12 | derived | no | chronology-consistent |
| synthetic_event_flag | Synthetic marker | boolean | true | constant | no | true |

## outcome

| Column | Definition | Type | Example | Source/method | Nullable | Validation |
|---|---|---|---|---|---|---|
| patient_id | Patient FK | string | PJ-00000001 | patient | no | unique valid FK |
| progression_event | Progression marker | boolean | true | generated | no | date consistency |
| progression_date | First progression | date | 2023-05-01 | generated | yes | after eligibility |
| castration_resistant_transition | Transition marker | boolean | true | generated | no | date consistency |
| castration_resistant_date | Transition date | date | 2023-06-01 | generated | yes | after progression |
| hospitalisation_flag | Hospital event marker | boolean | false | generated | no | date consistency |
| first_hospitalisation_date | First hospital date | date | 2023-01-01 | generated | yes | in observation |
| adverse_event_flag | Demo AE marker | boolean | true | generated | no | type consistency |
| adverse_event_type | Demo AE type | category | fatigue | generated | yes | present when flagged |
| death_flag | Death event | boolean | false | generated | no | date consistency |
| death_date | Death date | date | 2024-05-01 | generated | yes | censor-aligned |
| lost_to_follow_up_flag | LTFU event | boolean | false | generated | no | last-date consistency |
| last_observed_date | Last observable date | date | 2025-12-31 | derived | no | on/before censor logic |
| censor_date | Follow-up end | date | 2025-12-31 | derived minimum | no | earliest terminal date |
| outcome_status | Final precedence status | category | progressed | derived | no | allowed enum |

## patient_journey (gold)

Common demographic/diagnostic columns (`patient_id`, `age_at_index`, `comorbidity_score`, `frailty_proxy`, `region`, `insurance_type`, `prostate_stage`, `metastatic_flag`, `hormone_sensitive_flag`, `castration_resistant_flag`) retain the definitions/types above.

| Column | Definition | Type | Example | Source/method | Nullable | Validation |
|---|---|---|---|---|---|---|
| mhspc_flag | Meets demo mHSPC rule | boolean | true | derived | no | rule implications |
| eligibility_date | Latest qualifying date | date | 2022-01-22 | derived maximum | no | before treatment |
| eligible_for_arpi | Meets demo cohort rule | boolean | true | derived | no | implies mHSPC |
| eligibility_rule_version | Rule version | string | DEMO-ARPI-v1 | config | no | metadata match |
| first_urology_date | First decision visit | date | 2022-02-01 | encounter | no | chronological |
| first_oncology_date | First oncology visit | date | 2022-03-01 | encounter | yes | after urology |
| referral_completed_flag | Referral completed | boolean | true | derived | no | oncology evidence |
| referral_delay_days | Urology-to-oncology days | integer | 28 | derived | yes | nonnegative |
| initial_care_setting | Initial pathway setting | category | community_urology | provider | no | allowed enum |
| initial_provider_specialty | Initial provider specialty | category | urology | provider | no | allowed enum |
| multidisciplinary_team_flag | Initial provider MDT | boolean | false | provider | no | boolean |
| initial_treatment | First drug | category | darolutamide | treatment | yes | configured list |
| initial_treatment_class | First drug class | category | ARPI | mapped | yes | allowed enum |
| treatment_start_date | First start | date | 2022-04-01 | treatment | yes | after eligibility |
| days_to_initiation | Eligibility-to-start days | integer | 69 | derived | yes | nonnegative |
| treatment_initiated | Any start | boolean | true | derived | no | start evidence |
| prescription_event_count | Events for initial treatment | integer | 8 | prescription_event | no | nonnegative |
| max_refill_gap_days | Largest gap for initial treatment | integer | 41 | prescription_event | no | event-summary match |
| initiated_within_30d | Start by day 30 | boolean | false | derived | no | eligible + elapsed |
| initiated_within_60d | Start by day 60 | boolean | false | derived | no | eligible + elapsed |
| initiated_within_90d | Start by day 90 | boolean | true | derived | no | eligible + elapsed |
| eligible_not_initiated_90d | 90-day treatment gap | boolean | false | derived subtraction | no | eligible minus initiated |
| persistent_3m | Persistent at 90 days | boolean | true | derived | no | initiation/coverage |
| persistent_6m | Persistent at 180 days | boolean | true | derived | no | initiation/coverage |
| persistent_12m | Persistent at 365 days | boolean | false | derived | no | follow-up required |
| persistent_12m_gap_30d | 12m, 30-day sensitivity | boolean | false | derived | no | max gap <=30 |
| persistent_12m_gap_60d | 12m, 60-day sensitivity | boolean | false | derived | no | max gap <=60 |
| persistent_12m_gap_90d | 12m, 90-day sensitivity | boolean | true | derived | no | max gap <=90 |
| discontinuation_flag | Definitive stop | boolean | true | treatment | yes | not death/LTFU |
| discontinued_within_12m | Stop by 365 days | boolean | true | derived | no | elapsed <=365 |
| discontinuation_date | Stop date | date | 2022-10-01 | treatment | yes | implies flag |
| discontinuation_reason | Synthetic stop reason | category | access | treatment | yes | excludes death/LTFU |
| days_to_discontinuation | Start-to-stop days | integer | 183 | derived | yes | nonnegative |
| switch_flag | Switched treatment | boolean | true | treatment | yes | date/new drug |
| switch_date | First switch | date | 2022-08-01 | treatment | yes | implies flag |
| switched_to_drug | New drug | category | apalutamide | treatment | yes | differs from previous |
| days_to_switch | Start-to-switch days | integer | 122 | derived | yes | nonnegative |
| restart_flag | Restarted after gap | boolean | false | treatment | yes | date evidence |
| restart_date | First restart | date | 2023-01-01 | treatment | yes | gap > threshold |
| progression_event | Progressed | boolean | true | outcome | no | date evidence |
| progression_date | Progression date | date | 2023-05-01 | outcome | yes | after eligibility |
| days_to_progression | Eligibility-to-progression | integer | 465 | derived | yes | nonnegative |
| castration_resistant_transition | Follow-up transition | boolean | true | outcome | no | date evidence |
| castration_resistant_date | Transition date | date | 2023-06-01 | outcome | yes | in observation |
| hospitalisation_flag | Hospital event | boolean | false | outcome | no | date consistency |
| first_hospitalisation_date | First hospital date | date | 2023-01-01 | outcome | yes | in observation |
| adverse_event_flag | Demo adverse event | boolean | true | outcome | no | type consistency |
| adverse_event_type | Demo event type | category | fatigue | outcome | yes | required if flagged |
| death_flag | Death event | boolean | false | outcome | no | date evidence |
| death_date | Death date | date | 2024-05-01 | outcome | yes | censor-aligned |
| lost_to_follow_up_flag | LTFU marker | boolean | false | outcome | no | last observed evidence |
| last_observed_date | Last observed | date | 2025-12-31 | outcome | no | censor input |
| censor_date | Follow-up end | date | 2025-12-31 | derived minimum | no | terminal minimum |
| follow_up_days | Eligibility-to-censor | integer | 1200 | derived | no | nonnegative |
| final_outcome_status | Final status | category | progressed | derived precedence | no | allowed enum |
| synthetic_data_flag | Synthetic marker | boolean | true | constant | no | true |
| synthetic_scenario_version | Scenario version | string | demo-v1.0 | config | no | metadata match |
