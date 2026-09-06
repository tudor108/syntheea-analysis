# Project handoff — current state and completed work

> **v2.2 modernization addendum:** the repository now includes a locked environment, Python
> support policy, CI, a passing source type gate, machine-readable analytical contracts,
> executable industry-readiness checks, strict release-only EDA/presentation resolution,
> artifact-level provenance and the governance set linked from the
> [Industry Readiness Baseline](INDUSTRY_READINESS_CROSSWALK.md). The v2.1 figures below are retained
> as historical handoff evidence only. The reserved v2.2 candidate is
> `BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1`; never mix release IDs or copy the v2.1
> values into v2.2 artifacts.

> **Scientific-methods addendum:** Prompt 2 is implemented in source. It adds a 14-analysis
> estimand-style registry, deterministic event hierarchy, Kaplan–Meier/Greenwood and
> Aalen–Johansen outputs, exact risk tables, coherent low/base/high multi-seed simulation with
> Monte Carlo error, complete-truth MCAR/MAR/MNAR sensitivity, dimension-specific synthetic
> utility, blocked governed-real-data evaluation hooks, executable scientific gates, and an
> interactive aggregate `scientific_story.html`. Targeted scientific/presentation/industry tests
> pass; the full candidate-bound evidence run and browser sign-off remain final-step activities.

> **Predictive-methods addendum:** Prompt 3 is implemented in source. Four versioned target
> contracts now drive exact model-population derivation, train-only nested preprocessing and
> temporal calibration, repeated rolling validation, an untouched final holdout,
> development-only leave-one-market-out evaluation, bootstrap uncertainty, calibration curves,
> subgroup support/no-ranking warnings and a prespecified robustness battery. Responsible-AI
> harms, oversight, stop-use, drift and incident controls are machine checked; rejected and
> research-only models cannot enter an operational alias. A sealed aggregate package and
> interactive `model_story.html` are integrated. The final candidate-bound 200-bootstrap run and
> independent statistical/model-risk/browser review remain final-step activities.

**Updated:** 5 September 2026  
**Project:** `prostate-patient-journey-synthetic`  
**Current maturity:** Stage-4 engineering candidate, conditional — validated synthetic analytical
demonstration with local runtime; final v2.2 evidence and independent approvals remain pending  
**Target:** Stage 4/5 — pilot-ready healthcare analytics accelerator  

> **SYNTHETIC DEMONSTRATIONAL DATA ONLY. NOT REAL BAYER, PATIENT, CLINICAL,
> COMMERCIAL, OR POPULATION DATA.**

## 1. Executive summary

The project is a governed synthetic prostate patient-journey analytics accelerator. It demonstrates
how a healthcare analytics team can design, validate, explain, package, and eventually deploy
cohort, treatment-gap, persistence, pathway, and predictive analyses before receiving governed
real-world data.

The strongest presentation claim is:

> We built a reproducible and audit-ready synthetic patient-journey analytics accelerator that
> allows data, clinical, and business teams to align on definitions, test analytical methods,
> identify data requirements, and prepare a secure cloud deployment before real data is available.

The project must not be presented as:

- a clinically validated model;
- a real-world evidence study;
- an estimate of Bayer performance, market size, or undertreatment;
- a treatment recommendation or clinical decision-support product;
- a production system already approved for real patient data.

## 2. What has been built

### Synthetic data product

- 10,000 deterministic synthetic patient archetypes.
- Seven configured markets: US, DE, JP, FR, CN, AU, and CA.
- Three deep-analysis markets and four scan markets.
- 19 normalized and analytical tables.
- 105 governed fields in the `patient_journey` mart.
- CSV, Parquet, and DuckDB analytical outputs.
- Versioned YAML configuration for markets, clinical rules, missingness, referrals, treatment,
  follow-up, persistence, and outcomes.
- Optional Synthea ingestion without cloning source patient rows.
- Exact same-seed reproducibility controls.

### Patient-journey methodology

- Explicit index date, denominator, eligibility, exclusions, and data-sufficiency rules.
- 30-, 60-, and 90-day treatment-initiation windows.
- Separate reporting of patients censored before an outcome window.
- Eligible-but-not-initiated treatment-gap cohort.
- Active-surveillance pathway kept separate from advanced-disease pathways.
- Provider, organization, encounter, referral, treatment-episode, regimen, component,
  prescription, adverse-event, and outcome domains.
- Longitudinal persistence at 3, 6, and 12 months.
- Persistence sensitivity under 30-, 60-, and 90-day permissible refill gaps.
- Switch, discontinuation, restart, progression, hospitalization, death, and loss-to-follow-up logic.
- Leakage-safe feature timing and temporal analytical splits.
- Machine-readable definitions for all current analytical tactics and four predictive targets.
- Four reusable time-to-event endpoints with target/competing/censor states and deterministic
  calendar-day tie handling.
- Greenwood log-log estimator bands, event/censor counts, number-at-risk reconciliation, and
  Aalen–Johansen cumulative incidence.
- Three separate uncertainty layers: estimator, same-assumption regeneration, and changed-scenario
  variation.
- Complete pre-missingness truth recovery across existing, MCAR, MAR, and MNAR stress tests.

### Data analysis completed

- Cohort attrition and treatment-opportunity funnel.
- Censor-aware initiation analysis.
- Time-to-initiation summaries and Kaplan–Meier-style analysis.
- Persistence and refill-gap sensitivity analysis.
- Referral completion and delay analysis.
- Market, care-setting, provider, stage, access, and missingness segmentation.
- Normalized-table-to-mart reconciliation.
- Important-field and market-dependent missingness profiling.
- Driver associations and an intervention-hypothesis backlog.
- Four transparent predictive research baselines with exact target contracts, nested repeated
  temporal/final/market evaluation, calibration, uncertainty, robustness and automatic disposition.

### Historical v2.1 predictive baselines — honest interpretation

| Target | Analysis n | Event rate | ROC AUC | PR AUC | Current interpretation |
|---|---:|---:|---:|---:|---|
| Non-initiation within 90 days | 2,281 | 25.5% | 0.668 | 0.394 | Moderate exploratory ranking signal |
| Discontinuation within 12 months | 1,557 | 37.7% | 0.472 | 0.368 | No useful discrimination demonstrated |
| Switch within 12 months | 1,074 | 9.7% | 0.573 | 0.156 | Weak exploratory signal |
| Restart after a gap | 587 | 37.0% | 0.525 | 0.393 | Near-random discrimination |

These values are historical v2.1 claims that the new candidate-bound framework must reproduce and
compare; they are not final v2.2 metrics. The weak models are useful negative results. They show where feature collection, outcome
ascertainment, scenario design, and external validation must improve. They must not be hidden or
described as deployable AI.

## 3. Quality, governance, and release engineering

- 90 data-quality checks on the working analytical data.
- 25 formal readiness requirements.
- 25 independent adversarial checks.
- Primary-key, foreign-key, chronology, censoring, eligibility, treatment, persistence, leakage,
  reproducibility, and reconciliation controls.
- Certified immutable release with separate analytical and QA evidence archives.
- SHA-256 hashes, run metadata, configuration snapshots, source commits, and release manifest.
- Data dictionary, architecture, business rules, assumptions, model card, runbook, and prohibited
  use documentation.
- Ruff passes.
- 93 automated tests pass in the current Prompt-4 local suite.

The internal release score of 100/100 means that the artifact passed its own explicit synthetic
data contract. It does not mean 100% model accuracy, clinical validity, production readiness, or
real-world representativeness.

## 4. Single source of truth implemented

The repository previously exposed two snapshots with different headline results:

- old working `data/gold`: 1,691 initiations and 590 treatment gaps;
- certified v2.1 release: 1,700 initiations and 581 treatment gaps.

To prevent presentation errors, the following controls were implemented:

- a strict analytical-dataset resolver;
- automatic selection of the newest complete certified release;
- no implicit `data/gold` fallback for stakeholder presentation packages;
- explicit source-release and analysis-code provenance;
- cross-report headline-KPI consistency checks;
- presentation KPIs with their denominator encoded in the metric name and definition;
- an aggregate-only stakeholder package with no patient-level exports.

Generate the presentation package with:

```powershell
python -m prostate_journey.cli presentation-package
```

The package is written under:

```text
outputs/presentation/<certified-dataset-version>/
```

## 5. Current official presentation KPIs

The presentation package currently resolves to:

```text
BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z
```

| KPI | Synthetic count | Explicit analytical meaning |
|---|---:|---|
| Total cohort | 10,000 | All synthetic patients |
| Markets | 7 | Distinct configured markets |
| Eligible | 2,281 | `eligibility_flag = true` |
| Initiated within 90 days | 1,700 | Eligible and initiated by day 90 |
| Treatment gap at 90 days | 581 | Eligible and evaluable but not initiated by day 90 |
| Evaluable at 12 months | 1,614 | Eligible 90-day initiators with sufficient follow-up |
| Persistent at 12 months | 941 | Evaluable eligible 90-day initiators meeting the persistence rule |
| Censored at 12 months | 86 | Eligible 90-day initiators without sufficient 12-month observation |

These values are scenario outputs, not estimates of real patients or treatment gaps.

## 6. Interactive frontend implemented

The presentation package contains a self-contained HTML/CSS/JavaScript frontend:

```text
executive_story.html
```

It includes:

- guided, plain-language project onboarding;
- synchronized filtering across seven markets;
- headline KPI cards and a strictly nested patient funnel;
- 30/60/90-day initiation views;
- 12-month persistence with explicit evaluability;
- disease-stage mix and care-setting context;
- referral volume, completion, and median delay;
- interactive market-comparison table;
- definitions and prohibited-use explanations;
- responsive desktop and mobile layouts;
- visible certified dataset and source-commit provenance;
- no patient identifiers or patient-level exports.

### Interactive analysis-tactics library

The frontend has a searchable and filterable library of ten tactics:

1. Cohort definition.
2. Censor-aware initiation funnel.
3. Censoring control.
4. Persistence sensitivity.
5. Time-to-initiation analysis.
6. Referral pathway analysis.
7. Segmented treatment-gap analysis.
8. Missingness profiling.
9. Active-surveillance pathway analysis.
10. Quality, lineage, and reproducibility.

Each `Open tactic` action displays:

- the question answered;
- how the method works;
- why it is used;
- the live result for the selected market;
- supporting metrics;
- a plain-language interpretation;
- the key limitation;
- a link to the aggregate evidence file;
- an action to copy the result for presentation notes.

### Interactive scientific evidence lab

When release-matched scientific and simulation evidence exists, the presentation also contains:

```text
scientific_story.html
```

It provides switchable estimator/regeneration/scenario uncertainty layers, endpoint selectors,
eight openable scientific-method cards, survival/competing-risk summaries, missingness
truth-recovery performance, dimension-specific utility status, explicit blocked real-data hooks,
and links to aggregate evidence. Complete truth and event-level Parquet files are excluded from the
stakeholder package.

### Interactive model evidence lab

When release-matched predictive evidence exists, the presentation also contains:

```text
model_story.html
```

It explains the four target contracts, exact attrition, temporal and market validation,
PR-versus-prevalence comparisons, calibration, subgroup support, robustness checks and automatic
model dispositions. Decision-curve analysis remains visibly blocked until an operational action and
threshold trade-off are approved. Only aggregate evidence is included; patient-level scores are not
exported.

### Run the frontend on localhost

From the repository root:

```powershell
python -m http.server 8765 --bind 127.0.0.1 `
  --directory outputs/presentation/BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z
```

Then open:

```text
http://127.0.0.1:8765/executive_story.html
```

## 7. Supporting documents created

- `docs/PROJECT_STATUS_AND_ROADMAP.md` — maturity assessment and industry roadmap.
- `docs/PRESENTATION_STORYBOARD.md` — ten-slide presentation narrative.
- `docs/GCP_SETUP_CHECKLIST_RO.md` — superseded historical Google Cloud handoff; do not execute.
- `docs/AWS_DEPLOYMENT_HANDOFF.md` — current proposed AWS handoff; documentation only.
- `docs/DEPLOYMENT_CONTRACT.md` — current local and proposed AWS runtime contract.
- `docs/HEALTHCARE_DATA_ANALYSIS.md` — healthcare analysis playbook.
- `docs/PROJECT_HANDOFF_CURRENT_STATE.md` — this current-state and completed-work handoff.
- `docs/GPT5_PRO_META_PROMPT.md` — separate copy-ready GPT-5 Pro meta-prompt.
- `docs/SCIENTIFIC_METHODS_V2.2.md` — scientific definitions, methods, uncertainty taxonomy, and
  approval boundaries.
- `docs/PROMPT2_SCIENTIFIC_IMPLEMENTATION_REPORT.md` — Prompt 2 implementation status and Stage-4
  decision.
- `docs/PREDICTIVE_METHODS_V2.2.md` — target contracts, validation design, metrics, governance, and
  non-deployment boundaries.
- `docs/PROMPT3_PREDICTIVE_IMPLEMENTATION_REPORT.md` — Prompt 3 implementation and verification
  status.

## 8. Local application and AWS deployment handoff prepared

The project now has a typed local runtime, release-integrity verifier, aggregate-only HTTP service,
`/health` and `/ready`, structured JSON logs, a pinned non-root container, read-only Docker Compose
mounts, CI container gates and an explicit deployment contract.

The current proposed target is private/versioned S3 artifacts, an immutable ECR image, one ECS
service on Fargate when an application process is required, CloudWatch, and optional CloudFront plus
approved identity. No AWS credential, CLI/API call, resource, deployment, or cost was used. See the
[AWS deployment handoff](AWS_DEPLOYMENT_HANDOFF.md).

The former Google Cloud/Vertex AI checklist is retained and prominently marked
`SUPERSEDED — PREVIOUS GOOGLE CLOUD TARGET`; no GCP resources were created from this repository.

## 9. Honest maturity status

### Completed

- Stage 1 — concept.
- Stage 2 — reproducible prototype.
- Stage 3 — validated analytical demonstration.

### Required for Stage 4 — pilot-ready accelerator

1. Commit and review the current source, tests, configuration, documentation, and frontend.
2. Create a new clean certified v2.2 release from one selected commit.
3. Regenerate EDA, models, frontend, reports, and slide inputs from v2.2 only.
4. Run the implemented multi-seed and low/base/high framework against the final clean candidate;
   obtain SME review of scenario assumptions.
5. Review the implemented survival bands, number-at-risk tables, event priorities, and
   competing-risk methods in the approved protocol/SAP.
6. Run the implemented nested temporal/final-holdout/leave-one-market-out predictive framework on
   that candidate; obtain independent statistical and model-risk review.
7. Perform browser sign-off, finalize executive visuals, and rehearse a deterministic demonstration.
8. Assign the remaining named owners and collect RACI, clinical, privacy, and governance approvals.
9. Have the AWS/platform owner deploy the governed pilot architecture only after those approvals;
   the current repository work performs no cloud operation.

### Required for Stage 5 — production or clinical-grade system

- governed real-world data access;
- privacy, security, legal, and compliance approval;
- clinical and methodological SME sign-off;
- OMOP/FHIR and terminology mapping where required;
- external validation and transportability assessment;
- production monitoring, drift detection, incident response, and rollback;
- validated operational use case and human oversight;
- formal evidence that the system is safe and useful in its intended context.

Stage 5 cannot be claimed from synthetic data alone.

## 10. Recommended presentation structure

1. The problem: patient journeys are fragmented and definitions drift across teams.
2. The solution: a governed synthetic analytics accelerator before real-data onboarding.
3. The data product: seven markets, 19 tables, longitudinal patient journey.
4. The controlled funnel: 2,281 eligible → 1,700 initiated → 581 synthetic gaps.
5. Longitudinal depth: censoring, persistence, referrals, surveillance, and outcomes.
6. Trust: tests, audits, lineage, hashes, leakage controls, and certified releases.
7. Honest AI: one moderate exploratory baseline and three weak baselines.
8. Live interactive demonstration using `executive_story.html`.
9. Cloud and real-data onboarding architecture.
10. The ask: approve a narrowly scoped pilot, data-definition workshop, and SME review.

The presentation should create confidence through clarity and honesty, not through exaggerated AI
claims.

## 11. How to use the GPT-5 Pro output

Do not implement every generated idea automatically. Review it in this order:

1. Reject anything that invents real-world evidence or Bayer-specific claims.
2. Separate synthetic-data improvements from tasks requiring real data or SME approval.
3. Select the highest-impact items that strengthen credibility before adding visual complexity.
4. Convert accepted recommendations into repository issues with measurable acceptance criteria.
5. Run specialized prompts individually and compare their conclusions.
6. Use the adversarial-review prompt last, after the presentation and release candidate are ready.

The intended result is not the largest possible project. It is the clearest, most defensible, and
most professionally executed pilot proposal.
