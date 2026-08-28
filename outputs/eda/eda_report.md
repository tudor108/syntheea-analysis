# Bayer Prostate Patient Journey — EDA foundation report

> **Synthetic demonstrational data only; not clinical guidance, diagnosis, causal evidence, real Bayer data, or a real-world market-size estimate.**
> All content is aggregate. No row-level patient data or identifiers are exposed.

## Executive result

- Selected dataset: `C:\Endava\EndevLocal\zzzzzzzzzzdate\prostate-patient-journey-synthetic\data\releases\BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z\analytical_dataset`
- Patients: **10,000** across **7** required markets
- Normalized/mart tables: **19**; inventoried repository data/reference files: **1,735**
- Data file types: CSV=373, DUCKDB=2, JSON=1,322, PARQUET=38; Excel=0 and SQLite=0 were found.
- Profiled source/analytical columns: **639**
- P0 issues: **0**; P1 issues: **0**; reconciliation mismatches: **0**
- Eligibility chain: 2,281 eligible; 1,700 initiated by day 90; 581 explicit gaps.
- Exact states present are `localized`, `locally_advanced`, `mHSPC`, `mCRPC`, `metastatic_other` and `unknown`; `nmCRPC` and `mCSPC` do not occur and were neither invented nor merged.

## Repository context inspected

- Source and generation logic: `src/prostate_journey/`, including pipeline, CLI, cohort, pathway, treatment, outcome, quality, reconciliation and release modules.
- Existing notebook: `notebooks/01_dataset_validation.ipynb`.
- Existing contracts/documentation: release `DATA_DICTIONARY.csv`, `docs/DATA_DICTIONARY.md`, `docs/ER_SCHEMA.md`, `docs/BUSINESS_RULES.md`, `docs/DATA_QUALITY.md`, `docs/ARCHITECTURE.md` and `docs/RUNBOOK.md`.
- Raw Synthea, working generated/gold copies, certified release files, normalized tables and `patient_journey` mart were inventoried; profiling uses the newest certified immutable release only.

## Reproduce

```powershell
python eda/00_inventory_and_data_contract.py
python eda/01_data_quality_profile.py
```

Set `EDA_DATASET_DIR` only when an explicit complete 19-table analytical override is required; otherwise the scripts select the newest certified release and record the choice and hashes in the run manifest.

## Detected grains

| Table | Rows | Grain | Primary key |
|---|---:|---|---|
| patient | 10,000 | one row per synthetic patient/archetype | patient_id |
| diagnosis | 10,000 | one index prostate diagnosis per patient | diagnosis_id |
| disease_state_event | 10,177 | one dated disease-state event | disease_state_event_id |
| eligibility | 10,000 | one versioned eligibility assessment per patient | eligibility_id |
| organization | 48 | one synthetic organization | organization_id |
| provider | 64 | one stable provider-master row | provider_id |
| encounter | 76,819 | one dated patient-provider encounter | encounter_id |
| referral | 5,419 | one provider-to-provider referral | referral_id |
| active_surveillance | 5,055 | one active-surveillance assessment/pathway record | active_surveillance_id |
| observation | 10,000 | one observation/censoring record per patient | observation_id |
| treatment_episode | 2,369 | one longitudinal treatment line/episode | treatment_episode_id |
| treatment_regimen | 2,369 | one regimen attached to a treatment episode | regimen_id |
| treatment_regimen_component | 4,230 | one drug/procedure component within a regimen | component_id |
| prescription_event | 26,306 | one dispensing/refill event | prescription_event_id |
| adverse_event | 439 | one dated adverse event | adverse_event_id |
| outcome | 10,000 | one derived outcome/censoring record per patient | outcome_id |
| patient_split | 10,000 | one reproducible analytical split per patient | patient_split_id |
| feature_timing | 105 | one timing/governance record per mart field | feature_metadata_id |
| patient_journey | 10,000 | one analysis-ready row per patient | patient_id |

## Temporal and follow-up coverage

| Market | Patients | Min | Median | P95 | Max follow-up days |
|---|---:|---:|---:|---:|---:|
| ALL | 10,000 | 90 | 1,364 | 2,426 | 2,556 |
| AU | 800 | 112 | 1,410 | 2,430 | 2,551 |
| CA | 900 | 103 | 1,308 | 2,414 | 2,554 |
| CN | 1,200 | 96 | 1,304 | 2,424 | 2,551 |
| DE | 1,800 | 95 | 1,306 | 2,421 | 2,555 |
| FR | 1,100 | 110 | 1,394 | 2,420 | 2,554 |
| JP | 1,600 | 98 | 1,397 | 2,442 | 2,556 |
| US | 2,600 | 90 | 1,412 | 2,427 | 2,555 |

## Most important data-quality issues and limitations

| # | Severity | Classification | Finding | Required handling |
|---:|---|---|---|---|
| 1 | P2 | assumption_proxy_or_limitation | population_representative_flag=false for 10,000 patients | Use only for demonstrational diagnostics; do not weight to real populations. |
| 2 | P2 | assumption_proxy_or_limitation | Most records are independent generated archetypes rather than direct raw Synthea patients. | Keep source_record_type visible in sensitivity descriptions. |
| 3 | P2 | assumption_proxy_or_limitation | product_id missing in 1,655 prescription rows, concentrated in Scan markets | Report product analyses by detail level and never impute a missing product as no therapy. |
| 4 | P2 | assumption_proxy_or_limitation | 90 treated patients are not evaluable at 12 months | Keep right-censored patients separate from discontinued/switched patients. |
| 5 | P2 | assumption_proxy_or_limitation | Referral delay is structurally unavailable when no completed referral exists. | Use referral status and completion date to define denominators first. |
| 6 | P2 | assumption_proxy_or_limitation | Progression, hospitalisation and death are synthetic probabilistic outcomes. | Label all outcome analyses as synthetic descriptive proxies. |
| 7 | P2 | assumption_proxy_or_limitation | Realised value is governed by a synthetic operational proxy, not an approved clinical/commercial endpoint. | Obtain a Bayer-approved definition before external or commercial interpretation. |
| 8 | P3 | observed_missingness | event_coverage_until_date missingness=82.5% | Report denominators and missing category; do not impute in EDA. |
| 9 | P3 | observed_missingness | initial_regimen missingness=79.1% | Report denominators and missing category; do not impute in EDA. |
| 10 | P3 | observed_missingness | progression_date missingness=74.7% | Report denominators and missing category; do not impute in EDA. |

## Important-field missingness

| Variable | Missing n | Missing rate |
|---|---:|---:|
| event_coverage_until_date | 8,249 | 82.5% |
| initial_regimen | 7,908 | 79.1% |
| progression_date | 7,467 | 74.7% |
| referral_delay_days | 6,016 | 60.2% |
| psa_value | 488 | 4.9% |
| ethnicity | 436 | 4.4% |
| gleason_score | 412 | 4.1% |
| isup_grade_group | 412 | 4.1% |
| race | 291 | 2.9% |
| insurance_type | 277 | 2.8% |
| decision_owner_specialty | 0 | 0.0% |

Missingness indicators were created in memory and aggregated by market, exact disease state, active-surveillance pathway, care setting, provider specialty, calendar period, initiation outcome and persistence outcome. No values were imputed.

## Downstream readiness

| Analysis | Status | Evidence/blocker |
|---|---|---|
| Eligibility denominator and untreated gap | **READY** | Eligibility and 30/60/90 initiation reconcile with normalized tables. |
| Treatment initiation over time | **READY** | Dated first episodes, eligibility dates and censor dates are available. |
| 12-month persistence/discontinuation | **READY** | Right-censoring and 30/60/90 refill-gap sensitivities are explicit. |
| Switch, restart and interruption | **READY** | Episode transitions and prescription coverage are normalized and dated. |
| Active-surveillance pathway | **READY** | AS remains a separate normalized pathway with monitoring and transition fields. |
| Deep-versus-Scan market EDA | **READY** | All seven markets and market-depth metadata are present; missingness must remain stratified. |
| Referral, specialty and care-setting EDA | **READY** | Provider-master and referral endpoints reconcile. |
| Missingness-driver exploration | **READY** | Aggregate missingness indicators are available; results are descriptive and no imputation is performed. |
| Descriptive driver associations | **PARTIALLY READY** | Feature timing is governed, but synthetic associations are not causal and require sensitivity analysis. |
| Realised-value analysis | **PARTIALLY READY** | A synthetic proxy exists; an approved Bayer clinical/business definition remains unresolved. |
| Causal treatment effectiveness | **NOT READY** | No randomized or causal identification design; synthetic outcomes cannot estimate effectiveness. |
| Clinical recommendations or real market sizing | **NOT READY** | The cohort is synthetic and non-representative by design. |

## Facts, assumptions, proxies and unresolved definitions

- **Observed facts:** counts, dates, keys, categories, missingness and normalized-to-mart comparisons are calculated directly from the selected files.
- **Assumptions:** table grain and timing follow the certified schema/feature-timing contracts.
- **Proxies:** eligibility, persistence and outcomes are synthetic governed constructs; realised value is an operational synthetic proxy.
- **Unresolved definitions:** production realised value, intervention priority, real-world persistence and causal estimands require Bayer/clinical agreement.

## Figures

The `figures/` directory contains aggregate SVG charts for missingness, temporal coverage, follow-up, disease state, market/setting, treatment, invalid records and severity.
