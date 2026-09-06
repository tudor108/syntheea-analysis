# REAL PATIENT DATA — BLOCKED

> **Current decision: NO-GO FOR REAL DATA.** The repository, local app, containers, analyses,
> dashboards, models, and proposed AWS architecture are authorized only for synthetic scenario data.

Real patient data cannot be onboarded until all items are complete with named owners, dates,
evidence links, scope, and expiry/review dates.

## Governance and intended use

- [ ] Intended use, users, decisions, population, geography, and prohibited uses approved.
- [ ] Source owner and data steward approve use, fields, linkage, refresh, and derived outputs.
- [ ] RWE/clinical owner approves definitions, protocol/SAP, terminology, and interpretation.
- [ ] Statistical/model-risk owner approves validation, uncertainty, calibration, subgroup and drift
      plans where applicable.
- [ ] Human oversight, escalation, stop-use, incident, and rollback authorities named.

## Privacy, legal, and ethics

- [ ] Privacy impact/data-protection assessment completed.
- [ ] Legal basis, contracts/DUAs, purpose limitation, consent/waiver and cross-border transfer
      conditions approved.
- [ ] Minimum-necessary field set and de-identification/pseudonymization risk assessed.
- [ ] Retention, deletion, subject-rights, secondary-use and output-disclosure policies approved.
- [ ] Approved Region/data residency and subprocessors documented.

## Security and platform

- [ ] Security architecture and threat model approved.
- [ ] Environment/account separation, private networking, ingress/egress and security groups tested.
- [ ] IAM least privilege, role separation, periodic access review and break-glass process tested.
- [ ] Encryption in transit/at rest, KMS ownership/rotation, Secrets Manager and backup controls tested.
- [ ] CloudTrail, access logging, CloudWatch alerts, SIEM routing and incident process tested.
- [ ] Vulnerability, dependency, container, IaC and penetration testing completed with accepted risk.
- [ ] Audit evidence retention, immutable artifact policy and recovery/rollback exercise complete.

## Data and analytical validation

- [ ] Source-to-target mapping and terminology standards approved.
- [ ] Completeness, conformance, plausibility, lineage and reconciliation run on governed data.
- [ ] Missingness, informative observation/censoring and transportability assessed.
- [ ] Synthetic assumptions removed from real-data inference and all claims re-estimated.
- [ ] External validation completed for any model use; thresholds and decision utility approved.
- [ ] No synthetic metric is represented as a real market, clinical, causal, or treatment estimate.

## Operations

- [ ] SLOs, capacity, availability, support hours, ownership, runbook and change control approved.
- [ ] Data refresh, schema drift, model/data drift, failure, rollback and stop-use drills completed.
- [ ] User authentication/authorization and aggregate/patient-level export controls tested.
- [ ] Cost estimate, budget controls, retention cost and operational owner approved.
- [ ] Final privacy, security, legal, source-owner, RWE/clinical and platform sign-offs recorded.

Only a formally authorized governance body may change the status from blocked. A code change,
passing test suite, container build, synthetic release, or successful cloud deployment cannot do so.
