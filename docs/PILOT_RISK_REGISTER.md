# Pilot risk register

| ID | Risk | Potential harm | Required control | Owner | Current state |
|---|---|---|---|---|---|
| PILOT-R01 | Synthetic results are mistaken for Bayer or real-patient evidence | Misallocated attention or unsupported external claim | Persistent watermark; no transfer of synthetic rates; reviewer briefing | TO BE AGREED | BLOCKED pending owner |
| PILOT-R02 | Population or denominator changes silently | Biased or incomparable result | Versioned cohort contract, denominator inspector, reconciliation gate | RWE/statistics: TO BE AGREED | Control designed |
| PILOT-R03 | Source fields do not support time zero, endpoint, or censoring | Misclassification and immortal-time/leakage risk | Source fit-for-use and temporal mapping before analysis | Data/RWE: TO BE AGREED | BLOCKED pending source |
| PILOT-R04 | Missingness differs across source or subgroup | Biased or non-transportable estimate | Missingness diagnostics, prespecified strategy, sensitivity analysis | Statistics: TO BE AGREED | BLOCKED pending source |
| PILOT-R05 | Association is communicated causally | Incorrect clinical or commercial inference | Claim/evidence review and separate causal protocol if needed | RWE/clinical: TO BE AGREED | Guardrail implemented |
| PILOT-R06 | Weak model is used operationally | False action, missed review, inequity, burden | No operational alias; disposition gate; human oversight; stop-use | Model risk: TO BE AGREED | Operational use blocked |
| PILOT-R07 | Real data are accessed without complete approval | Privacy, legal, and security incident | REAL PATIENT DATA — BLOCKED gate; least privilege; audit evidence | Privacy/security: TO BE AGREED | BLOCKED |
| PILOT-R08 | Export loses provenance or filters | Stale or irreproducible decision evidence | Release, source, filters, n/N, method, timestamp, prohibition in export | QA: TO BE AGREED | Control implemented |
| PILOT-R09 | Accessibility excludes reviewers | Review error or inability to inspect evidence | WCAG 2.2 AA target, keyboard/screen-reader/manual audit | Accessibility: TO BE AGREED | Manual audit pending |
| PILOT-R10 | Workflow cannot absorb false positives or overrides | Operational burden or patient impact | Capacity test, approved thresholds, fallback, incident and rollback | Workflow owner: TO BE AGREED | BLOCKED pending workflow |

No risk is accepted by this template. Formal acceptance requires a named accountable owner, rationale,
expiry/review date, and approval evidence.

