# RACI and approval boundaries

`R` = Responsible, `A` = Accountable, `C` = Consulted, `I` = Informed. Role assignments are
profiles until named people are formally appointed. A repository maintainer cannot self-approve
clinical, RWE, privacy, security, model-risk or production fitness.

| Activity / decision | Principal engineer | Data/analytics lead | Clinical/RWE lead | Statistician/epidemiologist | Privacy/legal | Security/cloud platform | Model-risk/independent QA | Product/business owner |
|---|---|---|---|---|---|---|---|---|
| Synthetic generator and schema implementation | A/R | C | C | C | I | I | C | I |
| Machine-readable data contract | R | A | C | C | C | I | C | I |
| Cohort, index, exposure and endpoint definitions | C | R | A | R | I | I | C | C |
| Censoring, missing-data and statistical analysis plan | C | C | A | R | I | I | C | I |
| Feature timing and leakage controls | R | A | C | C | I | I | C | I |
| Model acceptance, thresholds and intended use | C | R | A | R | C | C | A | C |
| Release build and software quality gates | A/R | C | I | I | I | C | C | I |
| Independent release evidence review | C | C | C | C | C | C | A/R | I |
| Presentation claims and synthetic guardrail | C | R | A | C | C | I | C | A |
| Real-data onboarding and data processing authority | I | C | C | C | A/R | C | C | I |
| AWS landing zone, IAM/KMS, logging, artifact storage and network controls | C | I | I | I | C | A/R | C | I |
| Production deployment approval | R | C | C | C | C | A | A | A |
| Accessibility conformance review | R | I | I | I | C | C | A | C |
| Incident response, monitoring and retirement | C | C | C | C | C | A/R | A | I |

## Mandatory segregation of duties

- The code author may run gates but may not be the sole independent QA approver.
- Clinical/RWE definitions require the Clinical/RWE accountable role.
- Real patient data requires Privacy/Legal and Security/Platform approval before access.
- A model cannot be deployed because a synthetic release passes; model-risk and intended-use
  approval are separate decisions.
- External wording must be checked against the [claim–evidence register](CLAIM_EVIDENCE_REGISTER.md).
