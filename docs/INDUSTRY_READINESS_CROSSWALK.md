# Industry Readiness Baseline crosswalk

**Baseline date:** 5 September 2026  
**Candidate:** `BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1`  
**Scope:** internal engineering and analytical controls for synthetic demonstration data only

This document uses external frameworks as review lenses. It is not a declaration of ICH,
TRIPOD+AI, PROBAST+AI, NIST, AWS, WCAG, regulatory, clinical, privacy, security, or
production compliance. Consolidated rows are used where several detailed requirements share the
same evidence and disposition; an accountable specialist must perform the formal item-level review
before any regulated or real-data use.

Allowed classifications are exactly:

- `IMPLEMENTED AND VERIFIED`
- `PARTIALLY IMPLEMENTED`
- `MISSING`
- `REQUIRES REAL DATA`
- `REQUIRES CLINICAL/RWE/PRIVACY/SECURITY APPROVAL`
- `NOT APPLICABLE`

## Reference versions

| Lens | Version used | Authoritative reference |
|---|---|---|
| ICH M14 | Final guidance, March 2026 | [FDA publication of ICH M14](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/m14-general-principles-planning-designing-analyzing-and-reporting-non-interventional-studies-utilize) |
| ICH E9(R1) | Step 4, 2019 | [ICH E9(R1) guideline](https://database.ich.org/sites/default/files/E9-R1_Step4_Guideline_2019_1203.pdf) |
| TRIPOD+AI | 2024 | [TRIPOD+AI statement](https://www.bmj.com/content/385/bmj-2023-078378) |
| PROBAST+AI | 2025 | [PROBAST+AI paper](https://www.bmj.com/content/388/bmj-2024-082505) |
| NIST AI RMF | AI RMF 1.0, with revision status noted | [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) |
| AWS | Current AWS Well-Architected Framework and ECS guidance | [AWS Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html), [ECS best practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/intro.html) |
| Accessibility | WCAG 2.2 W3C Recommendation | [WCAG 2.2](https://www.w3.org/TR/WCAG22/) |

## ICH M14 lens

| Requirement group | Classification | Repository evidence | Gap or approval boundary |
|---|---|---|---|
| Purpose, research question and non-interventional study context | PARTIALLY IMPLEMENTED | [cohort analysis](COHORT_ANALYSIS.md), [business rules](BUSINESS_RULES.md) | Synthetic analytical questions exist; no approved RWE protocol or regulatory objective. |
| Pre-specified protocol and analysis plan | MISSING | [Stage-4 exit criteria](STAGE4_EXIT_CRITERIA.md) | Create a versioned protocol/SAP before real-data analysis. |
| Data-source provenance and traceability | IMPLEMENTED AND VERIFIED | Release manifest, config hash, source commit, artifact hashes; executable `industry-check` | Verification is limited to local synthetic inputs and generated outputs. |
| Data fitness for the research question | REQUIRES REAL DATA | [data contract](../contracts/analytical_data_contract.yaml) | Completeness, capture, coding, linkage and follow-up fitness cannot be inferred from synthetic data. |
| Target population and inclusion/exclusion criteria | PARTIALLY IMPLEMENTED | [cohort analysis](COHORT_ANALYSIS.md), versioned eligibility fields | Rules are executable but clinically demonstrational and not approved. |
| Index date, exposure, outcome and covariate operationalization | PARTIALLY IMPLEMENTED | [business rules](BUSINESS_RULES.md), `feature_timing` table | Technical definitions exist; real coding algorithms and clinical validity are absent. |
| Follow-up and censoring | IMPLEMENTED AND VERIFIED | Contract chronology/censoring gates and independent release reconciliation | Correct against the synthetic specification only. |
| Confounding and measured/unmeasured bias assessment | REQUIRES REAL DATA | [risk register](RISK_REGISTER.md) | Synthetic associations cannot establish confounding control or transportability. |
| Misclassification, selection bias and missing-data assessment | PARTIALLY IMPLEMENTED | Complete synthetic truth retention; existing/MCAR/MAR/MNAR masks; bias, RMSE, coverage, ESS and tipping-point outputs | Mechanisms and methods require source-specific diagnostics, protocol justification and statistical approval. |
| Statistical methods and denominator reconciliation | IMPLEMENTED AND VERIFIED | Machine-readable analysis registry; Kaplan–Meier/Greenwood, Aalen–Johansen, risk-set and denominator gates | Verified against the synthetic contract only; no approved SAP or clinical endpoint validation. |
| Sensitivity and robustness analyses | PARTIALLY IMPLEMENTED | 30/60/90-day definitions; low/base/high multi-seed intervals, Monte Carlo error, scenario envelopes and missingness truth recovery | Scenario values, real-data quantitative-bias analyses and protocol-specific methods require approval/data. |
| Reproducibility and audit trail | IMPLEMENTED AND VERIFIED | Locked environment, clean-commit release, hashes, CI, QA archive | External independent reproduction remains a Stage-4 activity. |
| Transparent reporting of limitations | IMPLEMENTED AND VERIFIED | Visible synthetic guardrails, claim register, model card and frontend limitations | Human presentation review remains required for each release. |
| Privacy, security and data governance | REQUIRES CLINICAL/RWE/PRIVACY/SECURITY APPROVAL | [RACI](RACI.md), [AWS security checklist](AWS_SECURITY_CHECKLIST.md), [real-data gate](REAL_DATA_READINESS_CHECKLIST.md) | No real patient data is authorized in this repository. |

## ICH E9(R1) estimand lens

The project is not an interventional trial. Estimand thinking is used only to make synthetic
questions, populations, events and summaries explicit.

| Estimand principle | Classification | Repository evidence | Gap or approval boundary |
|---|---|---|---|
| Treatment condition or strategy of interest | PARTIALLY IMPLEMENTED | Treatment episode/regimen contracts | Synthetic treatment classes are not an approved clinical comparison. |
| Population | PARTIALLY IMPLEMENTED | Analysis registry plus eligibility and model-population contracts | Requires clinical/RWE approval and real-data feasibility. |
| Variable or endpoint | PARTIALLY IMPLEMENTED | Registry and event hierarchy for initiation, discontinuation, switch, progression and hospitalization | Operational proxies are explicit but not clinically validated endpoints. |
| Intercurrent-event strategy | PARTIALLY IMPLEMENTED | Versioned event hierarchy; death and switch as competing events where configured; LTFU/administrative end separate | Strategies are engineering proposals; no approved estimand strategy exists. |
| Population-level summary | IMPLEMENTED AND VERIFIED | Explicit numerator/denominator and funnel reconciliation | Verified only against generated synthetic records. |
| Alignment of objective, estimand and estimator | MISSING | [Stage-4 exit criteria](STAGE4_EXIT_CRITERIA.md) | Must be defined in an approved protocol/SAP. |
| Main, sensitivity and supplementary analyses | PARTIALLY IMPLEMENTED | Gap-window, multi-seed, coherent scenario and MNAR delta sensitivities | Selection for an approved protocol/SAP and real-data robustness remain pending. |
| Handling of missing data | PARTIALLY IMPLEMENTED | Complete truth recovery, configured/MCAR/MAR/MNAR masking, justified oracle weighting example and tipping-point output | Real mechanism plausibility and analysis-specific strategy require governed data and statisticians. |

## TRIPOD+AI reporting lens

| Checklist area | Classification | Repository evidence | Gap or approval boundary |
|---|---|---|---|
| 1–2: title and abstract identify model purpose and AI context | PARTIALLY IMPLEMENTED | [project handoff](PROJECT_HANDOFF_CURRENT_STATE.md), model card | No manuscript-style structured abstract. |
| 3: background and objectives | IMPLEMENTED AND VERIFIED | README and [healthcare analysis](HEALTHCARE_DATA_ANALYSIS.md) | Objectives are explicitly synthetic. |
| 4–5: source, setting and dates | IMPLEMENTED AND VERIFIED | Release manifest and config snapshot | Dates/settings are generated scenarios, not observed care settings. |
| 6: participants and eligibility | IMPLEMENTED AND VERIFIED | Cohort contract and attrition outputs | Clinical applicability requires approval. |
| 7: outcome definition and assessment | PARTIALLY IMPLEMENTED | Outcome, initiation and persistence rules | No blinded/independent real outcome adjudication. |
| 8: predictor definition and assessment | IMPLEMENTED AND VERIFIED | `feature_timing`, feature dictionary and leakage gate | Real-world availability and measurement reliability are unknown. |
| 9: sample-size rationale | MISSING | Configured cohort size only | A formal sample-size/precision rationale is required for real modeling. |
| 10: missing-data handling | PARTIALLY IMPLEMENTED | Train-only preprocessing plus complete-case, added-missingness, and missingness-pattern robustness outputs | Real-data mechanism plausibility and protocol-specific handling require governed data and approval. |
| 11: model development specification | PARTIALLY IMPLEMENTED | Versioned target contracts, fixed feature sets, L2 logistic model, train-only encoding and nested temporal calibration | Final candidate run, independent review, challenger selection and any tuning strategy remain pending. |
| 12: performance measures | PARTIALLY IMPLEMENTED | ROC AUC, PR AUC versus prevalence, Brier score, calibration intercept/slope/curves and bootstrap intervals | Final candidate run is pending; synthetic internal evidence is not clinical utility or external validation. |
| 13: model updating | NOT APPLICABLE | No deployable model is released | Define only if a model proceeds to governed use. |
| 14: development/evaluation participant flow | PARTIALLY IMPLEMENTED | Contract-driven exact population derivation, exclusion counts, event/non-event support and fold registry | Candidate-bound reconciliation and independent review remain required. |
| 15: participant and predictor characteristics | PARTIALLY IMPLEMENTED | EDA summaries and missingness | No Table-1-style real cohort characterization. |
| 16: model specification sufficient for use | PARTIALLY IMPLEMENTED | Source code, locked dependencies, per-target model cards and immutable contract snapshots | Deliberately no production artifact, action, threshold or operational alias. |
| 17: model performance and uncertainty | PARTIALLY IMPLEMENTED | Repeated rolling temporal validation, untouched final temporal holdout, development-only leave-one-market-out evaluation, calibration and bootstrap uncertainty | Final candidate run and governed independent temporal/geographic external validation are still missing. |
| 18: model interpretation | PARTIALLY IMPLEMENTED | Automatic dispositions, historical-claim comparison, explicit weak/negative-result retention and no-ranking subgroup warnings | Candidate results and independent review are pending; no causal, clinical-benefit or patient-level interpretation is supported. |
| 19: limitations | IMPLEMENTED AND VERIFIED | Model card, claim register and risk register | Revalidate every release. |
| 20: interpretation in context | PARTIALLY IMPLEMENTED | Synthetic scenario narrative | Comparison with real external evidence is not complete. |
| 21: implications | PARTIALLY IMPLEMENTED | Intervention backlog framed as hypotheses | No action, impact or treatment recommendation is supported. |
| 22–27: supplementary information, protocol, registration, data/code access, funding/conflicts and patient/public involvement | PARTIALLY IMPLEMENTED | Code/release archive and governance documents | Registration, funding/conflict declarations, involvement statement and governed real-data access are project-owner responsibilities. |

## PROBAST+AI risk-of-bias lens

| Domain | Classification | Repository evidence | Gap or approval boundary |
|---|---|---|---|
| Participants and data sources | REQUIRES REAL DATA | Synthetic generator and source metadata | Selection, spectrum and transportability bias cannot be assessed here. |
| Predictors | PARTIALLY IMPLEMENTED | Timing metadata, predictor allow-list, missingness profile | Measurement reliability and availability at intended use require real data. |
| Outcomes | REQUIRES CLINICAL/RWE/PRIVACY/SECURITY APPROVAL | Versioned synthetic outcome rules | Outcome validity and blinded assessment require clinical/RWE review. |
| Analysis | PARTIALLY IMPLEMENTED | Nested repeated temporal/final-holdout/market evaluation, leakage gates, calibration, bootstrap intervals, simple comparator, subgroup support and prespecified robustness | Formal model-specific PROBAST+AI judgment, governed external validation, real-data transportability and protocol approval remain unresolved. |
| Applicability to intended population | REQUIRES REAL DATA | [risk register](RISK_REGISTER.md) | No real intended-use population has been approved. |
| Overall risk-of-bias judgment | MISSING | No formal PROBAST+AI assessment claimed | Must be completed independently for a specified model and real dataset. |

## NIST AI RMF 1.0 lens

| Function/category | Classification | Repository evidence | Gap or approval boundary |
|---|---|---|---|
| GOVERN: policies, roles and accountability | PARTIALLY IMPLEMENTED | [RACI](RACI.md), decision log, claim register | Named organizational owners and approvals are not assigned. |
| GOVERN: inventory and documentation | PARTIALLY IMPLEMENTED | Target/governance contracts, sealed manifest, per-model cards, disposition file, risk and claim registers | Limited to synthetic repository artifacts pending candidate and independent review. |
| GOVERN: third-party and supply-chain risk | PARTIALLY IMPLEMENTED | Locked dependencies and SHA-pinned CI actions | SBOM, vulnerability scanning and vendor review remain backlog items. |
| MAP: context and intended/prohibited use | IMPLEMENTED AND VERIFIED | Synthetic guardrail and prohibited-use fields | Real use case remains undefined. |
| MAP: affected stakeholders and impact | PARTIALLY IMPLEMENTED | Machine-readable harm register, misuse scenarios and human-oversight requirements | Requires named product, clinical, privacy, patient-impact and operational review. |
| MEASURE: validity, reliability and robustness | PARTIALLY IMPLEMENTED | Reproducibility, DQ, risk/denominator reconciliation, multi-seed/scenario separation and utility dimensions | Synthetic internal validity is not external validity. |
| MEASURE: bias and subgroup behavior | PARTIALLY IMPLEMENTED | Subgroup support/uncertainty without ranking plus market/access feature-removal robustness | Real fairness attributes, intersectional power, thresholds and harms require approval. |
| MEASURE: privacy/security/resilience | REQUIRES CLINICAL/RWE/PRIVACY/SECURITY APPROVAL | Aggregate presentation and no-real-data boundary | Threat modeling, DPIA and security testing are not complete. |
| MANAGE: risk prioritization and treatment | PARTIALLY IMPLEMENTED | Ranked risk register and exit criteria | Organizational risk acceptance is absent. |
| MANAGE: monitoring, incidents and retirement | PARTIALLY IMPLEMENTED | Stop-use conditions, drift dimensions, incident evidence preservation and rollback procedure | Thresholds, cadence, owners and operational testing are blocked until a real approved use exists. |

## AWS Well-Architected and deployment lens

| Pillar/control | Classification | Repository evidence | Gap or approval boundary |
|---|---|---|---|
| Operational excellence: versioned builds and runbooks | IMPLEMENTED AND VERIFIED | CI, lock file, [local runbook](LOCAL_RUNBOOK.md), release/change control | AWS operations have not been exercised. |
| Security, privacy and compliance | REQUIRES CLINICAL/RWE/PRIVACY/SECURITY APPROVAL | [AWS security checklist](AWS_SECURITY_CHECKLIST.md), [deployment handoff](AWS_DEPLOYMENT_HANDOFF.md) | IAM, KMS, network, CloudTrail/CloudWatch and approvals are not deployed/verified. |
| Reliability and disaster recovery | MISSING | Immutable local archives only | Define SLOs, backup/restore, regional strategy and DR tests. |
| Cost optimization | PARTIALLY IMPLEMENTED | No paid deployment; handoff requires budgets and anomaly alerts | FinOps controls need implementation in the target account. |
| Performance optimization | MISSING | Local quick/full profiles only | Establish workload targets and cloud benchmarks. |
| Sustainability | MISSING | No cloud workload | Measure and optimize only after architecture and workload exist. |
| MLOps: source/data/model lineage | PARTIALLY IMPLEMENTED | Release, sealed predictive evidence and presentation manifests with source/config hashes | S3 object versions, ECR digests and cloud promotion records are not deployed. |
| MLOps: automated validation and CI/CD | PARTIALLY IMPLEMENTED | Local/CI and container gates implemented | AWS promotion and approval environments are not configured. |
| MLOps: model registry and controlled deployment | PARTIALLY IMPLEMENTED | Alias policy blocks REJECTED/RESEARCH ONLY promotion; no operational alias is assigned | Registry, acceptance evidence and authorization are absent by design. |
| MLOps: monitoring, drift and retraining | PARTIALLY IMPLEMENTED | Drift dimensions, stop-use and incident/rollback specification | Requires real baseline data, approved thresholds, ownership and operational testing. |

## WCAG 2.2 AA lens

| Success-criterion group | Classification | Repository evidence | Gap or approval boundary |
|---|---|---|---|
| 1.1 text alternatives | PARTIALLY IMPLEMENTED | SVG/chart labels and semantic text | Visual/manual audit of every generated chart is required. |
| 1.2 time-based media | NOT APPLICABLE | No audio or video in the frontend | Reassess if a demo recording is published. |
| 1.3 adaptable structure and relationships | PARTIALLY IMPLEMENTED | Main landmark, headings, table caption/scopes and labels | Automated and screen-reader audit still required. |
| 1.4 distinguishable content | PARTIALLY IMPLEMENTED | High-contrast palette and reduced-motion rule | Contrast and zoom/reflow need tool and human verification. |
| 2.1 keyboard accessible | PARTIALLY IMPLEMENTED | Keyboard-operable market rows, controls and Escape-to-close | Full focus-trap and assistive-technology testing remain. |
| 2.2 enough time | NOT APPLICABLE | No timeout or auto-advance | Reassess if sessions/timeouts are added. |
| 2.3 seizures/physical reactions | IMPLEMENTED AND VERIFIED | No flashing content; reduced motion supported | Verify after visual changes. |
| 2.4 navigable and focus visible/not obscured | PARTIALLY IMPLEMENTED | Skip link, landmarks and visible `:focus-visible` style | Sticky-header/focus behavior needs multi-browser manual test. |
| 2.5 input modalities and target size | PARTIALLY IMPLEMENTED | Native controls and adequately sized primary buttons | Formal 24-by-24 CSS-pixel audit is pending. |
| 3.1 readable language | IMPLEMENTED AND VERIFIED | HTML `lang="en"` and plain-language definitions | Translation/localization is not in current scope. |
| 3.2 predictable interaction | PARTIALLY IMPLEMENTED | Consistent filter and modal behavior | Usability testing is pending. |
| 3.3 input assistance/authentication | NOT APPLICABLE | No forms, authentication or irreversible input | Reassess for hosted application. |
| 4.1 compatible name/role/value and status messages | PARTIALLY IMPLEMENTED | Native controls, ARIA dialog/status and labels | Axe, screen-reader and browser matrix tests remain. |
| Overall WCAG 2.2 AA conformance | MISSING | No conformance claim is made | Requires complete automated plus manual accessibility audit. |

## Baseline conclusion

The repository has a credible, executable synthetic engineering baseline. Scientific validity,
real-data fitness, clinical interpretation, privacy/security authorization, cloud operations,
formal model risk assessment and WCAG conformance remain outside the verified evidence. These
boundaries drive the [Stage-4 exit criteria](STAGE4_EXIT_CRITERIA.md) and the ranked
[implementation backlog](IMPLEMENTATION_BACKLOG.md).
