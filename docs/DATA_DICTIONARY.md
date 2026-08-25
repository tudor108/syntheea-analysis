# Data Dictionary and Relational Contract

> All records and identifiers are synthetic. Dates are ISO-8601 in CSV and typed timestamps in Parquet/DuckDB.

The generated `schema_summary.csv` and `missingness_summary.csv` provide observed row counts, column counts, dtypes, and null rates for every run. The tables below define grain, keys, and main analytical content.

| Table | Grain | Primary key | Foreign keys | Main content |
|---|---|---|---|---|
| `patient` | one row per independent patient archetype | `patient_id` | — | source/archetype IDs, DOB/index-derived age, market/depth, demographics, access, comorbidity, frailty, complexity, SES |
| `diagnosis` | one index prostate diagnosis per patient | `diagnosis_id` | `patient_id → patient` | stage, metastatic/hormonal state, PSA, Gleason patterns/score, ISUP, risk group |
| `disease_state_event` | one dated disease-state observation | `disease_state_event_id` | `patient_id → patient` | localized/locally advanced/mHSPC/mCRPC state, previous state, transition reason/version |
| `eligibility` | one ARPI eligibility assessment per patient | `eligibility_id` | `patient_id → patient` | status/date/reasons, contraindication, evidence sufficiency, follow-up, rule version |
| `organization` | one synthetic organization | `organization_id` | — | market, region, organization type, care setting, academic/MDT flags |
| `provider` | one stable provider master | `provider_id` | `organization_id → organization` | specialty, region, care setting, volume, MDT |
| `encounter` | one dated patient-provider encounter | `encounter_id` | `patient_id → patient`; `provider_id → provider`; `organization_id → organization` | encounter type, specialty, setting, sequence, depth |
| `referral` | one provider-to-provider referral | `referral_id` | patient, source/destination provider and organization | dates, source/destination specialties, status, reason, decision owner |
| `active_surveillance` | one AS assessment/episode per localized patient | `active_surveillance_id` | `patient_id → patient` | eligibility/start/status/exit/reason, treatment transition, monitoring count |
| `observation` | one observation/censor record per patient | `observation_id` | `patient_id → patient` | observation start/end, death, LTFU, censor date/reason, follow-up |
| `treatment_episode` | one continuous treatment episode/line | `treatment_episode_id` | patient, previous episode, prescribing provider | line, intent, start/end/status, switch/restart/gap/discontinuation semantics |
| `treatment_regimen` | one regimen per treatment episode | `regimen_id` | `treatment_episode_id → treatment_episode`; patient | regimen type/name, combination strategy, intensification, explicit guideline-rule classification |
| `treatment_regimen_component` | one drug/procedure component per regimen | `component_id` | regimen, episode, patient | ADT backbone, ARPI, chemotherapy or procedure role, route and interval |
| `prescription_event` | one initial fill/refill/administration record | `prescription_event_id` | component, regimen, episode, patient | service date, product, quantity, days supply, nominal/effective coverage, refill gap/timing |
| `adverse_event` | one dated adverse event | `adverse_event_id` | patient, treatment episode | type, date, severity, serious flag |
| `outcome` | one derived outcome summary per patient | `outcome_id` | `patient_id → patient` | progression, CR transition, hospitalization, adverse count, death/LTFU/censor status |
| `patient_split` | one ML split assignment per patient/archetype | `patient_split_id` | `patient_id → patient` | train/validation/test and split version |
| `feature_timing` | one feature-governance definition | `feature_metadata_id` | — | availability stage, allowed use cases, future-information flag |
| `patient_journey` | one analytical mart row per patient | `patient_id` | reconciles to all patient domains | denominator, initiation, regimen, persistence, censoring, AS, pathway, care, market, complexity and outcomes |

## Important controlled values

- Market depth: `deep`, `scan`.
- Referral status: `completed`, `pending`, `rejected`, `cancelled`, `not_completed`.
- Regimen type: `monotherapy`, `doublet`, `triplet`; strategies include `monotherapy`, `planned_combination`, `add_on`.
- Episode transition: `initial`, `switch`, `restart`; discontinuation and temporary gap are separate flags/reasons.
- Twelve-month persistence: `PERSISTENT`, `DISCONTINUED`, `SWITCHED`, `CENSORED_NOT_EVALUABLE`, `NOT_APPLICABLE`.
- Care setting mart: `community_urology`, `community_oncology`, `academic_oncology`, `mixed_pathway`, reconstructed from provider-backed encounters.

Nullable persistence booleans deliberately use null for censored/not-applicable patients. Use the corresponding status field for denominators.
