# Adversarial Independent Audit

Independent audit score: **100/100**

| ID | Independent attack | Priority | Status | Score | Evidence |
|---:|---|---|---|---:|---|
| 1 | Independent patients and no split contamination | P0 | PASS | 4/4 | archetypes=10000; duplicate signatures=0; contaminated archetypes=0 |
| 2 | Seven markets with non-identical clinical distributions | P0 | PASS | 4/4 | counts={'AU': 800, 'CA': 900, 'CN': 1200, 'DE': 1800, 'FR': 1100, 'JP': 1600, 'US': 2600}; age mean range=4.291; metastatic range=0.197 |
| 3 | Deep and Scan markets differ in pathway depth and missingness | P1 | PASS | 4/4 | encounter ratio=1.861; product missing deep=0.000, scan=0.189 |
| 4 | Configured market-specific provider capacity is realised | P1 | PASS | 4/4 | actual={'AU': 4, 'CA': 4, 'CN': 5, 'DE': 13, 'FR': 5, 'JP': 12, 'US': 21}; expected={'US': 21, 'DE': 13, 'JP': 12, 'FR': 5, 'CN': 5, 'AU': 4, 'CA': 4} |
| 5 | Eligibility and null semantics reconstruct | P0 | PASS | 4/4 | eligible=2281; label mismatches=0; semantic failures=0 |
| 6 | Eligibility rule version is complete and configured | P1 | PASS | 4/4 | expected version=ARPI-ELIG-SYN-v2.0; observed=['ARPI-ELIG-SYN-v2.0'] |
| 7 | First treatment, regimen components and intensity reconstruct | P0 | PASS | 4/4 | episodes=2383; regimens=2383; components=4231; reconstruction failures=0 |
| 8 | Treatment combinations, lines and chemotherapy cycles are plausible | P1 | PASS | 4/4 | incompatible regimens=0; invalid line sequences=0; chemo cycle failures=0 |
| 9 | No clinical event occurs after censor, death or LTFU | P0 | PASS | 4/4 | events after final observable date=0 |
| 10 | Persistence reconstructs at 3/6/12 months and 30/60/90-day gaps | P0 | PASS | 4/4 | mismatches={'persistence_3m_status': 0, 'persistence_6m_status': 0, 'persistence_12m_status': 0, 'persistence_12m_status_gap_30d': 0, 'persistence_12m_status_gap_60d': 0, 'persistence_12m_status_gap_90d': 0} |
| 11 | Switch, add-on and restart semantics are non-contradictory | P1 | PASS | 4/4 | linked transitions=290; add-ons=55; failures=0 |
| 12 | Active surveillance is a dated state/event sequence | P1 | PASS | 4/4 | AS episodes=1738; monitors=13243; transition/reclassification failures=0 |
| 13 | Provider, referral, organization and decision ownership reconstruct | P0 | PASS | 4/4 | provider/referral/treatment incompatibilities=0 |
| 14 | Age, Gleason/ISUP and disease-state transitions are coherent | P0 | PASS | 4/4 | age range=50-90; clinical-state failures=0 |
| 15 | Outcomes are dated, non-deterministic and clinically structured | P1 | PASS | 4/4 | date/status failures=0; progression rates={'False': 0.185299, 'True': 0.454641} |
| 16 | Missingness is explicit, market-varying and does not hide derivations | P1 | PASS | 4/4 | critical derivation fields complete=True; product missing by market={'AU': 0.1472, 'CA': 0.1566, 'CN': 0.2306, 'DE': 0.0, 'FR': 0.1681, 'JP': 0.0, 'US': 0.0} |
| 17 | Feature timing blocks target, outcome and pathway leakage | P0 | PASS | 4/4 | unclassified mart fields=0; future predictors=0; target predictors=0; conditional referrals=3/3 |
| 18 | No obvious clone, tiny-support or formula artefact remains | P1 | PASS | 4/4 | duplicate signatures=0; continuous support={'access_index': 753, 'frailty_proxy': 788, 'psa_value': 926} |
| 19 | Primary keys are unique and non-null | P0 | PASS | 4/4 | primary-key failures=0 |
| 20 | Foreign keys resolve across normalized domains | P0 | PASS | 4/4 | foreign-key failures=0 |
| 21 | Initial and whole-pathway care settings are not conflated | P1 | PASS | 4/4 | care-setting reconstruction failures=0 |
| 22 | Core eligible-to-value deliverables independently reconstruct | P0 | PASS | 4/4 | eligible=2281; treated=1752; untreated=529; initiated90=1691; gap90=590; 12m evaluable=1659 |
| 23 | Analytical mart reconciles to normalized source domains | P0 | PASS | 4/4 | eligibility=0; first treatment=0; outcome=0 |
| 24 | Clinical, censoring and outcome rule versions are complete | P1 | PASS | 4/4 | all exported rule-version domains contain exactly one non-null configured version |
| 25 | Deterministic generation contract and full-run rerun verification | P1 | PASS | 4/4 | seed=42; scenario=diagnostic-v2.0; runtime full rerun verified=True |

## Independently recalculated metrics

```json
{
  "patient_count": 10000,
  "unique_archetypes": 10000,
  "duplicate_demographic_signatures": 0,
  "raw_source_records_used": 4,
  "split_contamination_archetypes": 0,
  "market_patient_counts": {
    "AU": 800,
    "CA": 900,
    "CN": 1200,
    "DE": 1800,
    "FR": 1100,
    "JP": 1600,
    "US": 2600
  },
  "market_metastatic_rates": {
    "AU": 0.1925,
    "CA": 0.232222,
    "CN": 0.389167,
    "DE": 0.263333,
    "FR": 0.251818,
    "JP": 0.260625,
    "US": 0.325385
  },
  "deep_encounters_per_patient": 9.525066,
  "scan_encounters_per_patient": 5.119362,
  "deep_to_scan_encounter_ratio": 1.860596,
  "deep_product_missing_rate": 0.0,
  "scan_product_missing_rate": 0.189018,
  "eligible_patients": 2281,
  "chemotherapy_components": 451,
  "maximum_chemotherapy_events": 6,
  "critical_events_after_censor": 0,
  "persistence_mismatches": {
    "persistence_3m_status": 0,
    "persistence_6m_status": 0,
    "persistence_12m_status": 0,
    "persistence_12m_status_gap_30d": 0,
    "persistence_12m_status_gap_60d": 0,
    "persistence_12m_status_gap_90d": 0
  },
  "age_minimum": 50,
  "age_maximum": 90,
  "progression_rate_by_metastatic_flag": {
    "False": 0.185299,
    "True": 0.454641
  },
  "treated_eligible": 1752,
  "untreated_eligible": 529,
  "initiated_within_90_days": 1691,
  "eligible_treatment_gap_90_days": 590,
  "persistence_12m_evaluable": 1659,
  "discontinued_or_switched_by_12m": 722,
  "market_treatment_gap": {
    "AU": 27,
    "CA": 50,
    "CN": 150,
    "DE": 80,
    "FR": 54,
    "JP": 59,
    "US": 170
  },
  "care_setting_treatment_gap": {
    "academic_oncology": 146,
    "community_oncology": 45,
    "community_urology": 294,
    "mixed_pathway": 105
  },
  "segment_treatment_gap": {
    "high": 125,
    "low": 134,
    "medium": 331
  }
}
```

## Remaining warnings

- All records and effect relationships are synthetic and are not population-representative.
- Clinical assumptions and guideline classifications still require Bayer clinical review.
- Scan-market product detail is intentionally incomplete and must not be treated as absence.
- Referral variables are predictors only when their event/completion date is on or before the prediction index.
- Raw Synthea contributes only unique compatible archetypes; most records are generated independently.
