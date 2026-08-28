# EDA assumptions and limitations

> **Synthetic demonstrational data only; not clinical guidance, diagnosis, causal evidence, real Bayer data, or a real-world market-size estimate.**

## Observed facts

- The selected certified dataset is `C:\Endava\EndevLocal\zzzzzzzzzzdate\prostate-patient-journey-synthetic\data\releases\BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z\analytical_dataset`.
- It contains 19 normalized/mart tables and 10,000 patient-level mart rows.
- Markets are AU, CA, CN, DE, FR, JP, US; Deep=['US', 'DE', 'JP'], Scan=['FR', 'CN', 'AU', 'CA'].
- Active surveillance is retained as its own pathway and is not combined with advanced disease states.
- Exact observed states are localized, locally_advanced, mHSPC, mCRPC, metastatic_other and unknown; nmCRPC and mCSPC are absent and are not inferred or merged.
- Missing values remain missing. No imputation is performed by these scripts.
- Administrative data end remains censoring and is never converted to discontinuation.

## Assumptions

- The release manifest and explicit table contracts define the usable analytical baseline.
- `market_depth` governs expected detail differences; Scan missingness can represent non-collection by design.
- A populated date is treated as available only on/after that date; post-index fields are not baseline predictors.
- The EDA uses aggregate outputs only. Identifier examples are masked in the data dictionary.

## Missingness interpretation

- Demographic/clinical nulls are labelled collected-but-unavailable or unresolved unless metadata proves otherwise.
- Treatment/referral/outcome dates can be structurally missing because the corresponding event did not occur.
- A missing treatment/referral field is not interpreted as a negative event or zero delay.
- `event_coverage_until_date` varies by `persistence_outcome` by up to 100.0 percentage points; this is descriptive and may be structural, not causal.
- `event_coverage_until_date` varies by `initiation_outcome` by up to 100.0 percentage points; this is descriptive and may be structural, not causal.
- `initial_regimen` varies by `persistence_outcome` by up to 95.9 percentage points; this is descriptive and may be structural, not causal.
- `initial_regimen` varies by `initiation_outcome` by up to 95.6 percentage points; this is descriptive and may be structural, not causal.
- `referral_delay_days` varies by `persistence_outcome` by up to 54.9 percentage points; this is descriptive and may be structural, not causal.
- `referral_delay_days` varies by `initiation_outcome` by up to 49.3 percentage points; this is descriptive and may be structural, not causal.
- `progression_date` varies by `initiation_outcome` by up to 31.3 percentage points; this is descriptive and may be structural, not causal.
- `progression_date` varies by `persistence_outcome` by up to 21.8 percentage points; this is descriptive and may be structural, not causal.

## Proxies

- Eligibility, persistence, progression, hospitalisation and the realised-value node are synthetic governed constructs.
- The realised-value definition is an operational synthetic proxy, not clinical effectiveness or commercial value.
- Generated archetypes are independent synthetic records, not real patients or population estimates.

## Unresolved clinical/business definitions

- Bayer approval is required for any production definition of realised value and intervention priority.
- Permissible refill gaps, clinically meaningful discontinuation and episode-of-care conventions require clinical validation before real-data use.
- No causal estimand or clinical recommendation is defined or supported by this EDA.

## Raw-source boundary

- Raw Synthea files were inspected under `C:\Endava\EndevLocal\zzzzzzzzzzdate\prostate-patient-journey-synthetic\data\raw\synthea` but were not modified.
- External Synthea JSON/CSV fixtures are inventoried as references, not treated as project analytical inputs.
