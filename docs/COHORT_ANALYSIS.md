# Cohort Analysis Proposal

> **Synthetic demo only.** The cohorts below describe the configured synthetic prostate patient-journey scenario and must not be interpreted as clinical or population evidence.

## Objective

Define a small set of analysis-ready cohorts that directly support the demo questions around treatment initiation, referral pathway and treatment persistence.

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

**Purpose**
Compare initiated patients who remain persistent at 12 months with those who do not, and test sensitivity to different allowable refill-gap thresholds.

## Current data limitations

1. The gold `patient_journey` table is patient-level and contains the derived cohort flags needed for the three analyses.
2. The current `treatment` model stores episode-level refill summaries such as `days_supply`, `refill_date`, `covered_until_date` and `max_refill_gap_days`, but not every prescription fill/refill as a separate event row.
3. This limits traceability of persistence calculations and makes it harder to reconstruct medication coverage over time from individual dispensing events.
4. Raw Synthea medication data already exists in the repository, but the current prostate-specific pipeline does not use it as the primary source for treatment/persistence logic.
5. The current demo does not explicitly model an active-surveillance cohort, so that business leak would require additional scenario design before it can be analysed consistently.

## Recommended next implementation step

Keep the three cohorts above as the initial analysis scope. Before adding new clinical logic, evaluate a normalized prescription-event representation that can support event-level persistence calculations. CMS DE-SynPUF PDE and the existing Synthea `medications.csv` should be used as schema references, not joined to the current synthetic patient IDs.
