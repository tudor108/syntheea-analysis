# Cohort Analysis Proposal

> **Synthetic demo only.** The cohorts below describe the configured synthetic prostate patient-journey scenario and must not be interpreted as clinical or population evidence.

## Objective

Define a small set of analysis-ready cohorts that directly support the demo questions around treatment initiation, referral pathway and treatment persistence.

## Implemented enrichment: prescription events

The synthetic pipeline now includes a normalized `prescription_event` table generated from the existing seeded treatment/refill logic. It is not copied from CMS beneficiaries or joined to CMS data. CMS DE-SynPUF PDE remains a schema/reference source for the event-level representation.

The table contains the complete normalized lineage
`treatment_episode_id -> regimen_id -> component_id`, plus service/product fields,
days supply, nominal and effective coverage dates, refill timing, adherence profile,
market detail level, and the synthetic-event flag. Each dispensing component starts
with `initial_fill` and may have later `refill` events. Nominal coverage is
`service_date + days_supply`; effective `covered_until_date` stockpiles early refills
and is capped by the component, episode, and observation boundary. Episode
`max_refill_gap_days` remains consistent with the emitted component events.

`patient_journey` includes event-derived `prescription_event_count` and
`max_refill_gap_days`. Persistence at 3, 6, and 12 months is reconstructed on an
event clock from the initial episode's tracking component, effective coverage,
observed gap exhaustion, explicit discontinuation/switch dates, and the patient's
censor date. The 30/60/90-day sensitivity statuses independently rerun that same
landmark logic.

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
- `pathway_care_setting` (descriptive only; it summarizes the full pathway)
- `prostate_stage`

Referral completion and delay are not eligibility-time predictors in the supplied
treatment-initiation feature set. They may be used only for retrospective pathway
description, or after joining the normalized `referral` table and proving that the
relevant referral/completion date is on or before the selected prediction index.

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
- multidisciplinary-team availability from the normalized provider/organization
  relationship
- `initiated_within_90d`
- `eligible_not_initiated_90d`

**Purpose**
Describe whether synthetic referral completion and delay are associated with treatment initiation differences in the configured scenario.

## Cohort 3: 12-month persistence gap

**Base population**
- `treatment_initiated = true`

**Comparison groups**
- Persistent: `persistent_12m = true`
- Discontinued or switched: `persistence_12m_status` is `DISCONTINUED` or `SWITCHED`

`CENSORED_NOT_EVALUABLE` and `NOT_APPLICABLE` are excluded from the evaluable
12-month comparison; they are never treated as non-persistent.

**Candidate segmentation variables**
- `age_at_index`
- `comorbidity_score`
- `frailty_proxy`
- `insurance_type`
- `initial_care_setting`
- `initial_provider_specialty`
- `regimen_at_treatment_start`
- `regimen_type_at_treatment_start`
- `combination_strategy_at_treatment_start`
- `intensification_at_treatment_start_flag`
- `regimen_component_count_at_treatment_start`
- `referral_delay_days`
- `discontinuation_flag`
- `switch_flag`
- `restart_flag`

For predictive persistence work, use the explicit `*_at_treatment_start` snapshot.
The full-episode `initial_regimen`, `initial_regimen_type`,
`combination_strategy`, `intensification_flag`, and `regimen_component_count`
fields are retrospective descriptors because they can incorporate later add-ons.
Referral fields are admitted only when their referral/completion date is no later
than treatment start (the prediction index). Final discontinuation, switch, and
restart fields are outcomes/descriptors, not treatment-start predictors.

**Sensitivity definitions**
- `persistent_12m_gap_30d`
- `persistent_12m_gap_60d`
- `persistent_12m_gap_90d`

These sensitivity flags are calculated independently from the same 12-month event
history, with separate permissible gaps. A patient may therefore fail the 30-day
definition while passing the 60- or 90-day definition.

**Purpose**
Compare initiated patients who remain persistent at 12 months with those who do not, and test sensitivity to different allowable refill-gap thresholds.

## Cohort 4: active-surveillance pathway

**Base population**

- `active_surveillance_eligible_flag = true`

**Observable states and transitions**

- AS uptake and dated start;
- PSA, imaging, and biopsy monitoring encounters;
- continued, exited, or censored AS status;
- dated reclassification/exit reason;
- transition to a matching normalized local-treatment episode.

**Purpose**

Reconstruct synthetic active-surveillance monitoring and the pathway from observed
exit to treatment without inferring unobserved events after censoring.

## Current data limitations

1. The gold `patient_journey` table is patient-level and contains the derived cohort
   flags needed for the four analyses.
2. Treatment is normalized into `treatment_episode`, `treatment_regimen`,
   `treatment_regimen_component`, and `prescription_event`; the former monolithic
   `treatment` export is not part of the current contract.
3. The normalized `prescription_event` table provides event-level traceability for
   persistence coverage and refill-gap calculations.
4. Active surveillance is explicitly represented by `active_surveillance` plus
   dated `as_*` encounters and matching treatment transitions where observed.
5. Raw Synthea medication data exists in the repository, but the prostate-specific
   pipeline does not use it as the primary source for treatment/persistence logic.

## Scope and future extensions

Keep the four cohorts above as the initial analysis scope. Future extensions should
preserve the distinction between synthetic demo events and external reference data:
CMS DE-SynPUF PDE and the existing Synthea `medications.csv` may inform schema
design, but should not be joined to the current synthetic patient IDs unless a
separate, explicitly documented integration is designed.
