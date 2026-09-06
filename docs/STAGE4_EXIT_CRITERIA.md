# Scientific Stage-4 entry and exit criteria

## Decision represented by this baseline

The v2.2 candidate can support **beginning** a governed scientific Stage-4 upgrade. It does not
authorize real-data ingestion, a pilot, clinical interpretation, cloud deployment or model use.

## Entry criteria to begin Stage 4

| Criterion | Required evidence | Current state |
|---|---|---|
| One clean, reproducible synthetic release | v2.2 manifest, hashes, locked environment and passing gates | Implemented; candidate build must complete |
| One source for EDA/presentation | Dataset resolver and cross-artifact release/KPI check | Implemented |
| Explicit synthetic analytical contract | YAML tables/cohorts/model populations/artifacts | Implemented |
| Registered questions and estimand elements | Registry for current tactics and predictive targets | Implemented as engineering/proposed definitions; SME review pending |
| Scientific stress-test framework | Sealed multi-seed, competing-risk, missingness and utility evidence | Implemented; final candidate evidence run pending |
| Predictive research-evaluation framework | Target contracts, exact populations, nested temporal/market validation, calibration, robustness and dispositions | Implemented; final candidate evidence run and independent review pending |
| Transparent limitations and claims | Crosswalk, risk and claim registers | Implemented |
| Accountable work plan | RACI and ranked unresolved backlog | Implemented as role profiles; names pending |

## Exit criteria for a pilot-ready analytical accelerator

Every mandatory criterion below must have objective evidence and named approval. “Not tested” is
not a pass.

| ID | Mandatory exit criterion | Automated evidence | Human approval | Current classification |
|---|---|---|---|---|
| S4-01 | Approved intended use, research question and prohibited uses | Versioned metadata completeness | Product + Clinical/RWE + Model Risk | MISSING |
| S4-02 | Approved protocol and statistical analysis plan, including estimand-style population/index/event/summary definitions | Registry exists; protocol/SAP link and approval gate remain required | RWE + statistician | PARTIALLY IMPLEMENTED |
| S4-03 | Governed real-data source and legal processing authority | Data-catalog and environment checks | Privacy/Legal + data owner | REQUIRES REAL DATA |
| S4-04 | Source-to-contract mapping, terminology and phenotype validation | Schema/value/lineage tests | Clinical/RWE + data steward | REQUIRES REAL DATA |
| S4-05 | Data fitness: completeness, capture, linkage, temporal coverage and missingness | Real-data DQ suite with thresholds | RWE + statistician | REQUIRES REAL DATA |
| S4-06 | Bias/confounding/misclassification assessment and sensitivity plan | Reproducible diagnostics | Epidemiology/statistics | REQUIRES REAL DATA |
| S4-07 | Cohort/endpoint adjudication and denominator sign-off | Reconciliation and sample review evidence | Clinical/RWE | REQUIRES CLINICAL/RWE/PRIVACY/SECURITY APPROVAL |
| S4-08 | External temporal and geographic model validation, including calibration and uncertainty | Internal synthetic framework implemented; locked independent evaluation still required | Model risk + clinical/statistics | FRAMEWORK IMPLEMENTED — REQUIRES REAL DATA |
| S4-09 | Fairness/harms assessment with justified subgroups and mitigations | Synthetic support/uncertainty and no-ranking gates implemented; real subgroup harm/threshold evidence required | Model risk + clinical + privacy | FRAMEWORK IMPLEMENTED — REQUIRES REAL DATA |
| S4-10 | Approved privacy/security architecture and threat model | IaC/security scans/log tests | Privacy + security | REQUIRES CLINICAL/RWE/PRIVACY/SECURITY APPROVAL |
| S4-11 | Cloud reliability, backup/restore, SLO, DR and cost controls tested | Deployment/restore/load evidence | Platform owner + security | MISSING |
| S4-12 | Model registry, approval promotion, monitoring, drift, incident and retirement controls | Local disposition/alias/stop-use/rollback contract exists; end-to-end governed MLOps test required | Model risk + operations | PARTIALLY IMPLEMENTED |
| S4-13 | Full WCAG 2.2 AA audit for the published interface | Automated accessibility report | Accessibility specialist/manual audit | MISSING |
| S4-14 | Independent reproduction from a clean clone/environment | Signed reproduction report | Independent QA | PARTIALLY IMPLEMENTED |
| S4-15 | All external claims map to current evidence and approvals | Claim-register gate | Governance + business owner | PARTIALLY IMPLEMENTED |
| S4-16 | No unresolved critical/high risk without explicit accountable acceptance | Risk-register status gate | All accountable owners | MISSING |

## Stage-4 exit decision rule

- `GO`: all S4-01 through S4-16 pass with named approvals.
- `CONDITIONAL GO`: allowed only for a time-boxed, non-operational scientific sandbox with no
  patient-facing or commercial decision and explicit conditions/expiry.
- `NO-GO`: any missing legal authority, privacy/security approval, clinical definition, real-data
  fitness, or unresolved critical patient/business harm risk.
