# Longitudinal treatment EDA: assumptions and release interpretation

> **Synthetic demonstrational data only; not clinical guidance, diagnosis, causal evidence, real Bayer data, or a real-world market-size estimate.**

## Scope and non-causal interpretation

This analysis uses the certified normalized patient, treatment-episode, regimen-component, prescription-event and observation tables plus the Prompt-2 cohort flags. Source data were read only. **Persistence results are descriptive/associational and not causal.** They must not be interpreted as treatment effectiveness, comparative effectiveness or a patient-level clinical recommendation.

Treatment initiation is the first qualifying normalized treatment episode on or after the governed pathway eligibility/index date. Continuation means remaining on the tracked initial component without a gap beyond the selected threshold. Temporary gaps with an observed later refill/restart, explicit switches, within-regimen add-ons, documented stops, death, loss to follow-up and administrative end remain separate. `UNKNOWN` is retained when governed evidence cannot support another terminal class.

## What is reliable within this synthetic contract

- Episode linkage is high-confidence within the synthetic data contract: 2,369 normalized episodes for 2,092 treated patients, with 0 detected episode overlaps.
- `days_supply` comes only from observed prescription events. No value is fabricated. There are 0 initiated treatment-pathway patients without tracking-component days supply; their persistence cannot use a supply-based inference unless a clearly labelled scenario is invoked.
- Explicit source events identify 145 switches, 132 temporary-gap restarts, 46 add-on regimens and 301 documented non-temporary stops.
- In the primary mHSPC pathway, 1,751/2,281 eligible patients initiated during observed follow-up. Among observed initiators, median time was 49.0 days, IQR 26.0, p75 62.0, and p90 75.0.

## Proxy-based or assumption-dependent outcomes

- mCRPC results use a low-confidence pathway eligibility proxy and are not a clinical mCRPC eligibility analysis. nmCRPC is `NOT COMPUTABLE` because no explicit nmCRPC state exists.
- A refill gap is observed between recorded coverage and a later refill. A terminal gap is scenario-based: coverage end plus the configurable permissible gap, provided the patient remains observed. Terminal coverage, missing events and dataset end are never themselves labelled a documented stop.
- Gap sensitivity materially changes the terminal discontinuation proxy: >30d: 86.1%, >60d: 80.9%, >90d: 78.6%. Temporary-gap restarts remain separate from non-restarted discontinuation in every threshold.
- At the 60-day gap definition, censor-aware landmark persistence is 3_months: 99.3% (1723/1736; 15 excluded), 6_months: 83.5% (1420/1701; 50 excluded), 12_months: 58.4% (970/1661; 90 excluded). Denominators include observable patients and known failures/switches; deaths, LTFU, early administrative censoring and unknown early endpoints are excluded and counted.
- The independently rebuilt 12-month 30/60/90-day statuses have 0 patient-level mismatches against the governed `patient_journey` sensitivity fields.
- Standard Kaplan-Meier curves right-censor death, LTFU and other competing events. No Fine-Gray/Aalen-Johansen library is available in the controlled environment, so the report includes a descriptive competing-event table. KM initiation probability can therefore be optimistic when competing events are frequent.

## Robustness checks

- Initiation is re-estimated at 30, 60, 90 days.
- Discontinuation/persistence is re-estimated for gaps greater than 30, 60, 90 days.
- Minimum baseline observation of 180, 365 days was tested. Available counts were 180_days: 2281, 365_days: 1517; a zero count is reported as not computable rather than silently relaxing the rule.
- Landmark risk sets at 90, 180, 365 days explicitly count insufficient follow-up exclusions.
- Episode overlap and same-day alternative ordering were audited. Same-day component/refill events are ordered deterministically by service date and stable event ID; episode starts had no same-day ties in this release.
- Missing-supply scenario values are configurable as 30, 60, 90 days, but none is written into `days_supply`; any future use must set `scenario_based=true`.

## Top data gaps preventing stronger persistence conclusions

1. No pre-index clinical history supports a valid 180/365-day baseline sensitivity for most/all governed eligibility rows.
2. Prescription events are synthetic dispensing/coverage records, not proof that medicine was ingested; administration is proxied only where a dated infusion/injection/procedure component exists.
3. Disenrollment is not a separately captured event; loss to follow-up is the only non-death early censor category.
4. Reasons for ordinary refill gaps and some completed episodes are not observed, so `UNKNOWN` is retained rather than forced into discontinuation.
5. mCRPC has no indication-specific clinical eligibility definition and nmCRPC is absent.
6. Standard KM is not a competing-risk estimator; death and LTFU are described separately but causal/cumulative-incidence claims are unsupported.

## Files and interpretation contract

`treatment_episodes.parquet` is one row per normalized episode and contains source evidence. `time_to_initiation_event_data.parquet` and `persistence_event_data.parquet` are audit datasets. Aggregate CSVs and figures must always be read with the cohort definitions and this assumptions file. All results describe synthetic data only.
