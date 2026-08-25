# Adversarial Remediation Summary

## Issues discovered after the first implementation

- Persistence did not reconstruct from medication chronology: 157/131/122
  mismatches at 3/6/12 months and 163/122/130 under 30/60/90-day sensitivity.
- Provider capacity ignored market configuration and generated 40 providers in
  every market with nearly identical network structure.
- Chemotherapy behaved like indefinite dispensing: 327 components, median 13
  events, maximum 89, and 236 components with more than eight events.
- 334 components used an incompatible prescriber (208 radiotherapy and 126
  docetaxel); 115 chemotherapy patients lacked a completed oncology referral.
- Referral completion could occur after treatment initiation; this affected 776
  treated patients in the first full output.
- Two patients were age 91 although the configured contract was 50–90.
- One active-surveillance transition had no matching treatment episode.
- `initial_care_setting` used future encounters and differed from the actual first
  encounter for 4,212 patients.
- Feature timing governed only 23 of roughly 96 mart fields, leaving future or
  conditionally available fields insufficiently controlled.
- 576 of 819 rows labelled `active_treatment` had already ended treatment before
  censoring; terminal episode status also failed to distinguish administrative
  censoring from death/LTFU.
- Persistence configuration still declared v2.0 after the algorithm moved to
  v2.1, and the first cycle-cap remediation produced five rather than six complete
  docetaxel administrations.

## Generator fixes

- Rebuilt persistence as an event-clock landmark calculation with observed gap
  exhaustion, censor-aware evaluation and independent 30/60/90-day definitions.
- Implemented early-refill stockpiling without backward-moving effective coverage.
- Made provider counts follow each market's `providers_per_1000`; enforced stable
  specialties, organizations and region-aware care-team assignment.
- Routed chemotherapy, radiotherapy and surgery to compatible specialists; delayed
  treatment until referral completion and added explicit radiation-oncology
  transfers after active-surveillance exit.
- Bounded docetaxel to six 21-day cycles and exported planned cycle metadata.
- Prevented age overflow for generated and raw Synthea-derived archetypes.
- Reconciled active-surveillance exits, reclassification dates and treatment starts.
- Split first-encounter care setting from full-pathway care setting.
- Classified every mart field in feature-timing metadata and made future/target
  fields unavailable as predictors; referral variables require a cutoff condition.
- Reconstructed outcome status from terminal events and episodes active at censor;
  removed future-treatment dependence from outcome probability generation.
- Exported the aligned `PERSISTENCE-SYN-v2.1` rule version with every mart row.
- Added a separate adversarial audit that recomputes facts directly from normalized
  records and blocks release on any P0/P1 failure.

## New regression coverage

- landmark persistence, observed gap failure, censor-before-gap, and 30/60/90-day sensitivity;
- exact age bounds for generated and raw Synthea-overlaid archetypes;
- configured provider capacity and treatment-specialty compatibility;
- six-cycle chemotherapy cap and referral-before-treatment chronology;
- active-surveillance transition/reclassification reconciliation;
- first-encounter versus full-pathway care setting;
- outcome active-treatment reconstruction;
- complete leakage-safe feature timing and persistence rule version;
- hostile audit pass against actual generated records.

## Final execution summary

- Automated tests: 28 passed.
- Ruff: passed.
- Full same-seed generation: exact equality across all 19 tables.
- Data-quality rules: 90 passed, 0 failed.
- Readiness requirements: 25 passed, 0 partial, 0 failed.
- Adversarial attacks: 25 passed, 0 failed.

## Independently recalculated final metrics

| Metric | Result |
|---|---:|
| Patients / unique archetypes | 10,000 / 10,000 |
| Duplicate demographic signatures | 0 |
| Age range | 50–90 |
| Eligible | 2,281 |
| Treated eligible / untreated eligible | 1,752 / 529 |
| Initiated within 90 days / eligible 90-day gap | 1,691 / 590 |
| 12-month persistence evaluable | 1,659 |
| Discontinued or switched by 12 months | 722 |
| Persistence mismatches across all six definitions | 0 |
| Critical events after censor/death/LTFU | 0 |
| Chemotherapy components / maximum events | 451 / 6 |
| Deep-to-Scan encounter ratio | 1.861 |
| Deep / Scan missing product detail | 0.000 / 0.189 |
| Localized / metastatic progression rate | 0.185 / 0.455 |

Market, care-setting and patient-segment gap counts are in
`adversarial_audit.json`; the complete 25-row scorecard is in
`adversarial_audit_scorecard.csv`.

## Remaining warnings

- All records and relationships are synthetic and not population-representative.
- Clinical assumptions and guideline classifications require Bayer clinical review.
- Scan-market missing product detail is intentional and is not evidence of no treatment.
- Referral fields are usable only when their dated availability precedes the prediction index.
- Only four compatible unique raw Synthea archetypes were used; the remaining
  archetypes were generated independently.

Independent audit score: 100/100

P0 blockers remaining: 0

P1 issues remaining: 0

READY FOR BAYER DIAGNOSTIC: YES
