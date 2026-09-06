# Source fit-for-use template

## Administrative identity

- SOURCE NAME: **TO BE AGREED**
- SOURCE OWNER: **TO BE AGREED**
- TARGET MARKET / REGION: **TO BE AGREED**
- APPROVED PURPOSE: **TO BE AGREED**
- REFRESH / LATENCY: **TO BE AGREED**
- RETENTION: **TO BE AGREED**
- ASSESSMENT VERSION / DATE: **TO BE AGREED**

## Governance gate

- [ ] privacy approval
- [ ] security approval
- [ ] legal approval
- [ ] source-owner approval
- [ ] clinical/RWE approval
- [ ] approved region, retention, access model, encryption, audit, and incident process

## Analytical fit

| Question | Required evidence | Assessment |
|---|---|---|
| Can the target population be identified? | Phenotype logic, codes, completeness, validation sample | TO BE AGREED |
| Is time zero observable and temporally reliable? | Event timestamp provenance, latency, same-day ordering | TO BE AGREED |
| Are numerator and denominator fields available? | Field mapping and reconciliation counts | TO BE AGREED |
| Are outcomes and competing events captured? | Endpoint definition, sensitivity/specificity, external linkage | TO BE AGREED |
| Is censoring/loss to follow-up observable? | Enrollment/coverage/end-of-data logic | TO BE AGREED |
| Is treatment exposure measurable? | Order/administration/dispensing provenance and days supply | TO BE AGREED |
| Are referral and workflow events observable? | Referral creation, status, completion, responsible organization | TO BE AGREED |
| Is missingness diagnosable? | Structural vs incidental absence, source/subgroup/time patterns | TO BE AGREED |
| Are subgroup fields appropriate and permitted? | Definitions, consent/legal basis, support and harm review | TO BE AGREED |
| Can lineage and versioning be reproduced? | Extract version, transformations, hashes, data contract | TO BE AGREED |

## Field-level mapping

For every required field record: canonical name, source table/column, grain, data type, code system,
validity interval, availability at prediction/index time, missingness, transformation, QA rule, and
owner. Do not map an unavailable field to a proxy without explicit methodological approval.

## Decision

- FIT / CONDITIONALLY FIT / NOT FIT: **TO BE AGREED**
- APPROVED ANALYSES: **TO BE AGREED**
- PROHIBITED ANALYSES: **TO BE AGREED**
- CONDITIONS, OWNER, DUE DATE: **TO BE AGREED**
- SIGN-OFF REFERENCES: **TO BE AGREED**

