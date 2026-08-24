# Cohort Analysis Proposal

> **Synthetic demo only.** The cohorts below describe the configured synthetic prostate patient-journey scenario and must not be interpreted as clinical or population evidence.

## Objective

Define a small set of analysis-ready cohorts that directly support the demo questions around treatment initiation, referral pathway and treatment persistence.

## Implemented enrichment: prescription events

The synthetic pipeline now includes a normalized `prescription_event` table generated from the existing seeded treatment/refill logic. It is not copied from CMS beneficiaries or joined to CMS data. CMS DE-SynPUF PDE remains a schema/reference source for the event-level representation.

The table contains `prescription_event_id`, `patient_id`, `treatment_id`, `service_date`, `product_id`, `drug_name`, `quantity_dispensed`, `days_supply`, `covered_until_date`, `event_type`, `refill_gap_days` and `synthetic_event_flag`. One treatment may have multiple events: the first is `initial_fill`, followed by `refill` events. Event chronology is internally consistent: `covered_until_date = service_date + days_supply`, subsequent service dates incorporate the sampled refill gap after previous coverage, and `refill_gap_days` is the actual gap after that coverage. Treatment `max_refill_gap_days` remains consistent with the emitted events.

`patient_journey` includes event-derived `prescription_event_count` and `max_refill_gap_days`. Persistence at 3, 6 and 12 months uses prescription-event coverage and refill gaps together with treatment initiation, discontinuation and sufficient follow-up. The existing `persistent_12m_gap_30d`, `persistent_12m_gap_60d` and `persistent_12m_gap_90d` sensitivity flags use the event-derived refill-gap information.

`prescription_event` is exported to CSV and Parquet and loaded into DuckDB as a normal table. This is synthetic demo logic for application and analysis development, not clinical evidence.

## Cohort 1: 90-day treatment initiation gap

**Base population**
- `eligible_for_arpi = true`

**Comparison groups**
- Initiated: `initiated_within_90d = true`
- Gap: `eligible_not_initiated_90d = true`

**Candidate segmentation variables**
- `age_at_index`
- `comorbidity_score`
- `frailty_proxy`
- `insurance_type`
- `initial_care_setting`
- `initial_provider_specialty`
- `multidisciplinary_team_flag`
- `referral_completed_flag`
- `referral_delay_days`
- `prostate_stage`

**Purpose**
Describe synthetic pathway differences between eligible patients who initiate treatment within 90 days and those who do not.

## Cohort 2: referral gap

**Base population**
- `eligible_for_arpi = true`

**Referral groups**
- `referral_delay_days <= 30`
- `referral_delay_days` between 31 and 60
- `referral_delay_days > 60`
- `referral_completed_flag = false`

**Compare**
- patient characteristics
- care setting and provider specialty
- multidisciplinary-team availability
- `initiated_within_90d`
- `eligible_not_initiated_90d`

**Purpose**
Describe whether synthetic referral completion and delay are associated with treatment initiation differences in the configured scenario.

## Cohort 3: 12-month persistence gap

**Base population**
- `treatment_initiated = true`

**Comparison groups**
- Persistent: `persistent_12m = true`
- Non-persistent: `persistent_12m = false`

**Candidate segmentation variables**
- `age_at_index`
- `comorbidity_score`
- `frailty_proxy`
- `insurance_type`
- `initial_care_setting`
- `initial_provider_specialty`
- `initial_treatment`
- `initial_treatment_class`
- `referral_delay_days`
- `discontinuation_flag`
- `switch_flag`
- `restart_flag`

**Sensitivity definitions**
- `persistent_12m_gap_30d`
- `persistent_12m_gap_60d`
- `persistent_12m_gap_90d`

These sensitivity flags are calculated independently from the same 12-month coverage, discontinuation and follow-up base, using the event-derived maximum refill gap for the patient's initial treatment episode. A patient may therefore fail the 30-day definition while passing the 60- or 90-day definition.

**Purpose**
Compare initiated patients who remain persistent at 12 months with those who do not, and test sensitivity to different allowable refill-gap thresholds.

## Current data limitations

1. The gold `patient_journey` table is patient-level and contains the derived cohort flags needed for the three analyses.
2. The `treatment` model retains episode-level refill summaries such as `days_supply`, `refill_date`, `covered_until_date` and `max_refill_gap_days` for backward compatibility.
3. The normalized `prescription_event` table provides event-level traceability for the initial treatment episode and is the source for event-derived persistence coverage and refill-gap calculations.
4. Raw Synthea medication data already exists in the repository, but the current prostate-specific pipeline does not use it as the primary source for treatment/persistence logic.
5. The current demo does not explicitly model an active-surveillance cohort, so that business leak would require additional scenario design before it can be analysed consistently.

## Scope and future extensions

Keep the three cohorts above as the initial analysis scope. Future extensions should preserve the distinction between synthetic demo events and external reference data: CMS DE-SynPUF PDE and the existing Synthea `medications.csv` may inform schema design, but should not be joined to the current synthetic patient IDs unless a separate, explicitly documented integration is designed.
