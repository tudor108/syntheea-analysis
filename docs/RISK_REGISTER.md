# Risk register

Scores use likelihood (L) and impact (I) from 1–5; exposure is `L × I`. Residual ratings are
engineering judgments for this synthetic repository, not organizational risk acceptance.

| Rank | Risk | L | I | Exposure | Existing control | Residual status | Owner profile | Required treatment / exit evidence |
|---:|---|---:|---:|---:|---|---|---|---|
| 1 | Synthetic definitions or results are mistaken for clinical/RWE evidence. | 4 | 5 | 20 | Guardrails, claim register, candidate wording, frontend notices | Critical/open | Clinical + RWE governance | Approved protocol/definitions and human review of every external artifact. |
| 2 | A model is used on real patients without external validation or intended-use approval. | 3 | 5 | 15 | No deployable model; per-target contracts/cards; conservative dispositions; rejected/research-only operational-alias block | Critical/open | Model-risk accountable owner | Independent external validation, benefit/harm assessment, threshold/workflow and specified-use approval. |
| 3 | Real data is introduced without privacy, legal and security authorization. | 3 | 5 | 15 | Synthetic-only repository boundary; aggregate presentation | Critical/open | Privacy + security | DPIA/TRA, DPA, data classification, IAM/KMS/logging and approved environment. |
| 4 | Real source data cannot implement the current cohort/outcomes reliably. | 4 | 4 | 16 | Explicit contract and feasibility checklist | High/open | Data strategy + RWE | Source-to-concept mapping, capture/completeness study and adjudicated phenotype validation. |
| 5 | Confounding, selection, missingness or target misclassification produces misleading associations or predictions. | 4 | 4 | 16 | Target contracts, fixed-horizon ascertainment, censoring, missingness and sensitivity outputs | High/open | Epidemiology/statistics | Approved objective, target/estimand, DAG/design, bias assessment and sensitivity analysis. |
| 6 | Market scenario differences are presented as real rankings or opportunity estimates. | 3 | 5 | 15 | Synthetic labels and prohibited claims | High/open | Commercial governance + RWE | Claim review and real representative evidence if comparison is ever proposed. |
| 7 | Stale outputs contaminate a deck or model run. | 2 | 4 | 8 | Strict resolver, ignored generated paths, release/KPI/hash gates | Mitigated/monitor | Principal engineer + QA | Candidate artifact manifests pass and no manual source substitution occurs. |
| 8 | Dependency or CI supply-chain compromise affects reproducibility/security. | 2 | 4 | 8 | `uv.lock`, bounded dependencies, SHA-pinned actions, Dependabot | Medium/open | Platform security | SBOM, vulnerability/license scanning, signed provenance and patch SLA. |
| 9 | Type exceptions hide a pandas runtime defect. | 3 | 3 | 9 | MyPy gate plus tests; exceptions scoped by module | Medium/open | Python maintainer | Replace row iteration with typed adapters and reduce overrides to zero. |
| 10 | Accessibility barriers prevent use of the interactive frontend. | 3 | 3 | Semantic HTML, skip link, visible focus, keyboard controls | Medium/open | Frontend + accessibility specialist | Axe plus keyboard, zoom, contrast and screen-reader audit; remediate all A/AA findings. |
| 11 | Cloud deployment is unreliable, insecure or unexpectedly costly. | 3 | 4 | No deployment; architecture checklist only | High/blocked | Cloud platform + security | Approved landing zone, IaC, budgets, SLO/DR tests, threat model and operational ownership. |
| 12 | Exact reproducibility differs across OS/runtime despite a lock. | 2 | 3 | Python matrix, full same-seed check, hashes | Medium/monitor | Release engineer | Clean-clone reproduction on independent runner and documented platform variance decision. |
| 13 | Small synthetic subgroups create unstable or disclosure-like visual behavior. | 2 | 3 | Aggregate-only package, explicit support minima, uncertainty and `DO NOT RANK` state | Medium/open | Statistics + privacy | Confirm threshold with privacy/RWE owners and suppress/aggregate as approved. |
| 14 | Release language or internal 100/100 score is read as formal compliance. | 2 | 5 | Candidate scope fields and crosswalk disclaimer | Medium/monitor | Governance reviewer | Remove internal score from executive deck; verify wording against claim register. |
| 15 | Temporal drift, prevalence change or calibration failure makes a research model misleading. | 3 | 4 | Rolling/market/shift robustness, calibration intercept/slope/curves, stop-use and blocked drift thresholds | High/open | Model risk + statistics + operations | Governed external data, approved alert boundaries, monitoring cadence, fallback and tested rollback. |

Critical/high open risks are not accepted by this document. They are dependencies for Stage 4 or
for any real-data/cloud activity.
