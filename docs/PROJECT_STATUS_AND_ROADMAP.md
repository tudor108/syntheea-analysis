# Project Status, Maturity Assessment, and Industry Roadmap

> **Historical assessment notice (v2.1):** this file records the pre-v2.2 gap assessment that
> motivated the modernization. Statements below such as “no CI”, “dependencies are not locked”
> and “type check fails” are no longer current. Use the
> [Industry Readiness Baseline crosswalk](INDUSTRY_READINESS_CROSSWALK.md),
> [changelog](../CHANGELOG.md), [Stage-4 criteria](STAGE4_EXIT_CRITERIA.md) and
> [unresolved backlog](IMPLEMENTATION_BACKLOG.md) for current status. Historical synthetic metrics
> remain labelled by their v2.1 release and must not be mixed with the v2.2 candidate.

> **Current v2.2 source addendum:** the engineering baseline, scientific framework (Prompt 2), and
> predictive research-evaluation framework (Prompt 3) are implemented with targeted automated
> verification. The predictive layer now has four target contracts, nested train-only temporal
> calibration, repeated rolling validation, an untouched final holdout, development-only
> leave-one-market-out evaluation, uncertainty/calibration/subgroup/robustness outputs, automatic
> non-deployment dispositions, sealed aggregate evidence, and `model_story.html`. The clean
> candidate-bound run, independent reviews, and browser sign-off remain pending; therefore no v2.2
> result or deployment-readiness claim is approved. See
> [predictive methods](PREDICTIVE_METHODS_V2.2.md) and the
> [Prompt 3 report](PROMPT3_PREDICTIVE_IMPLEMENTATION_REPORT.md).

**Assessment date:** 5 September 2026  
**Repository:** `prostate-patient-journey-synthetic`  
**Assessed branch:** `dev`, including current uncommitted healthcare-analysis and presentation-package work  
**Intended use:** synthetic healthcare analytics demonstration and analytical-method development  
**Not intended for:** clinical decision support, causal inference, real-world market sizing, treatment recommendations, or claims about Bayer data

## Executive assessment

The repository is a **validated analytical demo (maturity stage 3 of 5)**. It is substantially more advanced than a typical portfolio proof of concept: it has a normalized longitudinal data model, deterministic generation, explicit censoring, versioned clinical assumptions, leakage controls, independent quality audits, immutable release packaging, cohort analysis, longitudinal analysis, and transparent predictive baselines.

It is not yet a pilot-ready or production-grade healthcare analytics product. The main constraints are not basic coding quality. They are:

1. multiple analytical snapshots are visible at the same time and report different headline KPIs;
2. statistical validation is exploratory and based on one synthetic scenario rather than external or multi-scenario evidence;
3. software delivery is not automated through CI and the declared type-checking gate does not pass;
4. the presentation layer is information-rich but too dense and not yet organized around one executive decision story;
5. interoperability, clinical sign-off, real-data governance, and operational monitoring are future work.

**Recommended presentation claim:**

> We built a reproducible, audit-ready synthetic patient-journey analytics accelerator that demonstrates how governed cohort, treatment-gap, persistence, pathway, and predictive analyses can be developed safely before access to real data.

Do not describe the project as a validated clinical model, a real-world evidence study, or a production data platform.

## What has been delivered

### Data product and generation

- 10,000 independent synthetic patient archetypes across seven markets: US, DE, JP, FR, CN, AU, and CA.
- 19 normalized and analytical tables exported as CSV and Parquet, plus a DuckDB analytical database.
- 105 governed fields in the patient-level analytical mart.
- Explicit market-depth profiles, clinical assumptions, eligibility rules, treatment logic, outcomes, missingness, and observation windows in versioned YAML.
- Optional use of unique Synthea source rows without cloning; deterministic fallback to independent generated archetypes.
- Same-seed exact reproducibility checks for full runs.

### Healthcare analytics

- Eligibility and 30/60/90-day treatment-initiation funnels with censor-aware denominators.
- Referral completion and delay analysis.
- Active-surveillance pathway analysis kept separate from advanced disease pathways.
- Treatment episode, regimen, component, dispensing, refill-gap, switch, restart, and discontinuation logic.
- Kaplan-Meier-style time-to-initiation and persistence analyses with 30/60/90-day gap sensitivity.
- Market, care-setting, provider, payer/access, and missingness stratification.
- Driver associations and four contract-driven logistic research models with exact attrition,
  leakage-safe nested temporal evaluation, final holdout, market holdouts, calibration, uncertainty,
  robustness, subgroup support warnings, and governed dispositions.
- Intervention backlog linking analytical signals to measurement or workflow hypotheses.

### Quality, governance, and release engineering

- 90 current data-quality checks, all passing on the working gold data.
- 25 readiness requirements and 25 independent adversarial checks, all passing on their assessed snapshots.
- Primary-key, foreign-key, chronology, censoring, eligibility, regimen, dispensing, persistence, split-isolation, leakage, and mart-reconciliation controls.
- Immutable certified release with separate analytical and QA archives, file hashes, manifests, provenance, and artifact parity checks.
- Explicit model card, assumptions register, data dictionary, ER schema, runbook, and prohibited-use language.

### Repository evidence

| Area | Evidence observed |
|---|---:|
| Production source modules | 31 files / approximately 10,796 lines |
| EDA modules | 14 files / approximately 7,507 lines |
| Test modules | 15 files / approximately 1,437 lines |
| Current test functions | 56 |
| Current automated test result | 56 passed |
| Ruff result | passed |
| Generated visual artifacts | 22 PNG/SVG/HTML files |
| Certified release score | 100/100 against the project's internal release contract |

The internal 100/100 score means that the artifact satisfies its own explicit synthetic-data contract. It must not be presented as 100% clinical validity, production readiness, model accuracy, or real-world representativeness.

## Historical v2.1 analytical results: defensible interpretation

The certified release used by the EDA contains 10,000 patients, 2,369 mHSPC pathway members, 2,281 eligible and 90-day evaluable patients, 1,700 observed initiations by day 90, and 581 non-initiations by day 90 (25.5%). These are synthetic scenario results, not estimates of real treatment gaps.

The historical v2.1 predictive layer is appropriately described as exploratory:

| Target | Analysis n | Event rate | Temporal-test ROC AUC | Temporal-test PR AUC | Assessment |
|---|---:|---:|---:|---:|---|
| Non-initiation by 90 days | 2,281 | 25.5% | 0.668 | 0.394 | moderate exploratory signal |
| Discontinuation by 12 months | 1,557 | 37.7% | 0.472 | 0.368 | no useful discrimination shown |
| Switch by 12 months | 1,074 | 9.7% | 0.573 | 0.156 | weak exploratory signal |
| Restart after gap | 587 | 37.0% | 0.525 | 0.393 | near-random discrimination |

The non-initiation baseline historically showed the strongest ranking signal, but this was neither
external validation nor evidence of usefulness. These values are prior claims to be reproduced and
compared by the v2.2 framework; they are not current model dispositions. Weak and negative findings
remain visible and cannot be promoted to operational use.

## Critical source-of-truth finding

Three valid but different layers are currently visible:

| Layer | Provenance | Scenario | Initiated within 90d | 90d gap | Presentation status |
|---|---|---|---:|---:|---|
| `data/gold` and `data/reports` | commit `498e2f2`, generated 25 Aug 2026 09:34 UTC | `diagnostic-v2.0` | 1,691 | 590 | stale; do not use in final deck |
| certified release | commit `f71bf03`, generated 25 Aug 2026 11:26 UTC | `diagnostic-v2.1-release` | 1,700 | 581 | current certified analytical source |
| `outputs/eda` | EDA code through commit `1107175`, run 28 Aug 2026 | reads the certified release | 1,700 | 581 | preferred analytical outputs |

The existing HTML cohort dashboard reads the older `data/gold` snapshot and therefore displays 1,691/590, while the newer EDA figures display 1,700/581. This is the highest-priority pre-presentation issue.

### Required resolution

- **Implemented:** `presentation-package` now selects the newest complete certified release,
  creates an aggregate-only stakeholder package, records source/analysis provenance, and fails
  a cross-report headline-KPI consistency gate.
- **Implemented:** presentation KPIs now state their cohort and denominator explicitly, including
  12-month persistence among eligible patients initiated within 90 days.
- **Implemented:** a responsive, aggregate-only executive frontend now provides a guided project
  explanation, synchronized market filtering, funnel/context/referral views, and a plain-language
  methods glossary from the same certified source.
- **Implemented:** the frontend now uses progressive disclosure through a searchable 10-tactic
  analysis library. Each tactic exposes the question, method, current-market result,
  interpretation, limitation, and evidence file on demand.
- Commit the current source/config/test/documentation work.
- Create one new clean certified release from the selected commit.
- Generate the remaining EDA charts, model card, and slide inputs from that new release only.
- Extend visible provenance from the presentation dashboard to every EDA chart and model output.
- Extend the current report/dashboard gate to EDA and model artifacts.
- Archive or clearly label all older working outputs as superseded.

## Maturity assessment

| Dimension | Current stage | Evidence | What prevents the next stage |
|---|---|---|---|
| Data architecture | strong | normalized event model, mart, DuckDB, explicit grain and keys | no standard healthcare CDM mapping |
| Data quality | strong | extensive record-level and cross-table checks | checks are custom; no external benchmark suite |
| Reproducibility | strong | locked environment, supported runtime policy, seed/config/source hashes, CI and immutable-release controls | create and independently reproduce the clean v2.2 candidate |
| Cohort methodology | strong demo | explicit index, denominator, censoring, sensitivity | definitions require clinical SME approval on real use case |
| Longitudinal statistics | strong synthetic-method demo | Kaplan–Meier/Greenwood bands, exact risk tables, Aalen–Johansen competing risks and deterministic event hierarchy | final candidate run plus approved protocol/SAP and independent biostatistical review |
| Predictive modeling | governed research framework | target contracts, nested repeated temporal/final/market validation, comparators, calibration, bootstrap uncertainty, subgroup/robustness evidence and dispositions | final candidate run, model-risk/clinical review and governed external validation; no model is deployable |
| Synthetic validity | intermediate | transparent assumptions and rule reconstruction | no calibration to an authoritative external reference distribution |
| Interoperability | early | relational schema and dictionary | no OMOP/FHIR mapping or standard terminology layer |
| Software delivery | strong local/CI baseline | package, CLI, lock, supported runtime, lint/type/test/industry gates and release checks | final clean-candidate execution and independent reproduction |
| Governance | strong engineering baseline | model cards, RACI, risk/claim/decision/change registers, provenance, stop-use and prohibited-use controls | named organizational approvals and real-data governance remain absent |
| Presentation | strong interactive prototype | release-bound executive, scientific and model evidence stories with aggregate-only allow-lists | final candidate generation, browser/accessibility sign-off and rehearsal |

### Overall position

- **Stage 1 — concept:** completed.
- **Stage 2 — reproducible prototype:** completed.
- **Stage 3 — validated analytical demo:** current stage.
- **Stage 4 — pilot-ready analytics accelerator:** achievable after the P0/P1 roadmap.
- **Stage 5 — production/clinical-grade system:** requires real-data governance, interoperability, external validation, domain approval, security, operations, and monitoring; it is outside the current synthetic-demo evidence.

## Priority roadmap

### P0 — before the presentation

#### 1. Freeze one authoritative release

Implement the source-of-truth resolution above. The deck must cite one dataset version and one KPI table. Never mix `data/gold` with certified-release EDA.

#### 2. Create an executive analytical summary

Produce one machine-generated table containing:

- cohort and evaluable denominators;
- initiation at 30/60/90 days with uncertainty;
- 12-month persistence under 30/60/90-day gap rules;
- referral completion and median/P90 delay;
- censoring and missingness rates;
- exact dataset and code provenance.

Every chart should read from this table or from a traceable child table.

#### 3. Simplify and standardize visuals

- Replace the pixel/monospace chart font with the corporate presentation font.
- Use sentence-case titles that state the finding, not only the metric name.
- Use a color-blind-safe palette and reserve red for risk/failure.
- Add denominator, `n`, uncertainty, dataset version, and “synthetic” in every visual.
- Replace the dense four-pathway funnel and heatmap with one primary mHSPC story plus appendix views.
- Do not combine the labels `mHSPC/mCSPC` unless both states exist and the mapping is clinically approved; the current release explicitly contains mHSPC but not mCSPC.
- Add confidence bands and a number-at-risk table to survival plots.
- Show calibration as points with uncertainty and sample size per bin; avoid connecting sparse bins as if they were a stable time series.

#### 4. Make the live demo deterministic

- Use a pre-generated certified release during the presentation.
- Keep a five-minute fallback recording or screenshots.
- Add a single `make demo` or PowerShell equivalent that validates the environment and opens only certified outputs.
- Include a visible “synthetic data” banner and dataset version on every screen.

#### 5. Fix delivery hygiene

- Rebuild the main `.venv`; it currently lacks `pytest` and `ruff` despite the setup instructions.
- Add a dependency lock file with hashes and a documented supported Python version.
- Make MyPy a real gate or remove it from the declared dev contract until configured. Current MyPy execution reports 58 errors, including missing stubs and genuine optional-value/assignment findings.
- Add CI for install, lint, tests, a quick pipeline run, deterministic-output check, and documentation-link validation.

### P1 — highest-value data-science improvements

#### 1. Quantify scenario uncertainty, not only sampling uncertainty

Wilson intervals within one fixed synthetic cohort do not represent uncertainty in the synthetic assumptions. Run a governed multi-seed and multi-scenario simulation:

- at least 30 seeds per approved scenario;
- low/base/high assumptions for access, referral, initiation, adherence, missingness, and censoring;
- report median and 5th–95th percentile results across simulated worlds;
- separate within-run sampling uncertainty from between-scenario uncertainty.

This is likely the single most valuable methodological upgrade for a synthetic project.

#### 2. Upgrade longitudinal analysis

- Add Greenwood confidence intervals and numbers at risk to Kaplan-Meier curves.
- Use Aalen-Johansen cumulative incidence when death/LTFU or switch/discontinuation are competing events.
- Add Cox or flexible parametric models only after checking proportional-hazards assumptions.
- Report restricted mean time-to-event when median survival is unstable or not reached.
- Keep dispensing persistence separate from medication ingestion/adherence.

Use maintained statistical libraries and regression tests against known examples rather than expanding custom statistical implementations indefinitely.

#### 3. Strengthen predictive evaluation

- **Implemented in source:** prevalence comparator; explicit train/calibration/final-test roles; repeated
  rolling temporal and development-only leave-one-market-out evaluation; calibration
  intercept/slope/curves; bootstrap intervals; penalized logistic baseline; exact attrition;
  leakage audits; prior-claim comparison; automatic `RESEARCH ONLY`/`REJECTED` dispositions.
- **Intentionally blocked:** threshold/capacity metrics and decision-curve/net-benefit analysis until
  a real operational action, review capacity, threshold trade-off and comparison strategy are
  approved without consulting the final holdout.
- **Still required:** run the full 200-bootstrap framework on the clean candidate, obtain independent
  statistical/model-risk/clinical review, preregister any challenger, and perform governed external
  temporal/geographic validation before considering a higher disposition.
- Weak models remain evidence about data/target limitations, never candidates for automatic
  deployment.

#### 4. Improve subgroup analysis

- **Implemented in source:** prespecified minimum cell/event/non-event support; uncertainty for
  supported groups; explicit insufficient-support labels; no ranking; and robustness after removing
  market/access proxies.
- Consider hierarchical or partially pooled estimation only for a preregistered real-data question;
  do not rank noisy market or subgroup results.
- Correct or explicitly control the false-discovery rate when many segments and associations are tested.
- Separate fairness diagnostics from real-world equity claims; synthetic disparities are generator behavior.

#### 5. Formalize missing-data semantics

Add a field-level missingness reason taxonomy:

- structurally not collected;
- not applicable;
- event did not occur;
- collected but unavailable;
- unknown/unresolved;
- censored before observable.

Then run complete-case, missing-category, and scenario-based sensitivity analyses. Multiple imputation should be used only when the mechanism and estimand justify it.

#### 6. Validate synthetic utility and realism

- Obtain clinical and market-SME sign-off on cohort and pathway definitions.
- Compare approved marginals and joint distributions with public or authorized reference data.
- Add plausibility checks for incidence-like patterns, temporal transitions, medication sequences, and cross-market relationships.
- Create a formal dataset datasheet covering motivation, composition, generation, preprocessing, uses, prohibited uses, maintenance, and known biases.
- If real records are ever used to fit the generator, add membership/disclosure risk testing; “synthetic” alone is not a privacy guarantee.

### P2 — pilot and production foundations

#### Healthcare interoperability

- Create an OMOP CDM mapping for person, condition, observation, visit, drug exposure, procedure, measurement, provider, and care-site concepts.
- Preserve source values while adding standard concept identifiers and vocabulary provenance.
- Add a small FHIR import/export demonstrator for Patient, Condition, Observation, Encounter, MedicationRequest/MedicationDispense, Procedure, and Organization where appropriate.
- Version phenotype definitions and terminology mappings independently of code releases.

OMOP is most relevant for analytical standardization; FHIR is most relevant for data exchange. They are complementary rather than competing targets.

#### Engineering and MLOps

- Add CI, code coverage thresholds, pre-commit hooks, dependency scanning, and secret scanning.
- Split very large modules into testable domain components; several core files exceed 1,000 lines.
- Add direct tests for EDA calculations, model metrics, bootstrap logic, calibration, and chart-data contracts.
- Add experiment tracking for dataset version, code commit, features, split, parameters, metrics, and artifacts.
- Add a changelog, contribution guide, license decision, ownership/RACI, and release approval checklist.
- Store large generated artifacts in an artifact registry or data-versioning system rather than normal Git history.

#### Production governance

- Define intended users, decisions, failure modes, escalation paths, and human review.
- Create a risk register aligned to `GOVERN`, `MAP`, `MEASURE`, and `MANAGE` activities.
- Define drift, data-quality, calibration, subgroup, and operational monitoring thresholds.
- Separate analytical approval, clinical approval, privacy/security approval, and production release approval.

## Industry-standard alignment

This is a pragmatic benchmark, not a claim of certification.

| Reference | Current alignment | Next action |
|---|---|---|
| FAIR data principles | strong on metadata, provenance and reuse; limited findability/interoperability outside the repo | stable dataset identifiers, catalog metadata, license, standard vocabularies |
| RECORD reporting | strong on cohort logic and limitations; synthetic project is not a RECORD study | use the checklist structure when transitioning to routinely collected real data |
| TRIPOD+AI | partial: target contracts, participant flow, leakage-safe development, temporal/market evaluation, comparator, metrics, calibration, uncertainty, cards and limitations are implemented in source | execute the candidate run; add real-data sample-size rationale and governed independent validation; complete independent item-level reporting review |
| PROBAST+AI | partial engineering preparation across participants/data, predictors, outcomes and analysis | perform independent model-specific risk-of-bias/applicability assessment on governed real data |
| NIST AI RMF | partial: harms, prohibited uses, subgroup controls, dispositions, stop-use, drift dimensions and incident/rollback definitions exist | assign accountable owners, approve thresholds and exercise controls in a governed operational context |
| OMOP CDM | custom relational model only | publish a documented mapping and terminology strategy |
| HL7 FHIR | no exchange layer | add an optional import/export adapter after the analytical source of truth is stable |
| FDA/IMDRF GMLP principles | useful as a stretch benchmark only; this is not a medical device | multidisciplinary review, representative intended-use data, independent evaluation, user information and lifecycle monitoring if scope ever becomes clinical |

Primary references:

- FAIR Guiding Principles: <https://doi.org/10.1038/sdata.2016.18>
- RECORD statement: <https://www.equator-network.org/reporting-guidelines/record/>
- TRIPOD+AI: <https://www.bmj.com/content/385/bmj-2023-078378>
- PROBAST+AI: <https://www.bmj.com/content/388/bmj-2024-082505>
- NIST AI RMF 1.0: <https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10>
- OHDSI OMOP Common Data Model: <https://ohdsi.github.io/CommonDataModel/>
- HL7 FHIR: <https://hl7.org/fhir/>
- FDA/IMDRF Good Machine Learning Practice: <https://www.fda.gov/medical-devices/software-medical-device-samd/good-machine-learning-practice-medical-device-development-guiding-principles>

## Definition of done for the next level

The project is ready to call **pilot-ready analytics accelerator** when all of the following are true:

- one clean certified release is the source for every presented number;
- CI installs from a lock file and passes lint, tests, type checks, quick generation, and consistency checks;
- the executive report and presentation are generated from one versioned KPI contract;
- clinical/business owners have approved the definitions and prohibited claims;
- the primary model has baseline comparisons, repeated temporal validation, calibration, subgroup uncertainty, and a documented decision use case;
- synthetic scenario uncertainty is quantified across seeds and assumptions;
- survival outputs include confidence intervals and at-risk information;
- an OMOP mapping and terminology strategy exist;
- data, model, risk, ownership, and release documentation have named approvers;
- the live demo can be reproduced from a clean machine or delivered from immutable artifacts.

## Recommended next implementation sequence

1. **Release consistency:** create one fresh release and regenerate every output from it.
2. **Presentation package:** build the 10-slide narrative in `PRESENTATION_STORYBOARD.md` and a one-page executive dashboard.
3. **Candidate verification:** run the existing CI, type, test, source, scientific, predictive and
   artifact-consistency gates against that one release; complete browser/accessibility sign-off.
4. **Independent methods review:** approve the scientific protocol/SAP and review the implemented
   survival, competing-risk, multi-seed, missingness and predictive-validation evidence.
5. **Interoperability:** OMOP mapping first, then a small FHIR adapter.
6. **Pilot governance:** SME sign-off, risk register, RACI, monitoring plan, and real-data transition protocol.
