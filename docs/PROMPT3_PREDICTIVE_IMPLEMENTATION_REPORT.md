# Prompt 3 predictive implementation report

> **SYNTHETIC DEMONSTRATIONAL DATA ONLY. NOT REAL BAYER, PATIENT, CLINICAL,
> COMMERCIAL, OR POPULATION DATA.** This report describes implemented research controls. It does
> not declare any model externally validated, clinically useful or deployable.

**Implementation date:** 5 September 2026  
**Branch:** `dev`  
**Status:** source implementation and targeted verification complete; final clean-candidate run and
independent review pending

## Outcome

The previous one-holdout exploratory baselines have been replaced by a governed evaluation
subsystem with explicit target contracts, exact population derivation, nested preprocessing and
calibration, repeated temporal validation, an untouched final holdout, leave-one-market-out
evaluation, uncertainty, calibration, robustness, subgroup-support warnings, model cards and
technical non-deployment gates.

The implementation does not optimize for favorable AUC. In the development smoke run using the
historical local synthetic analytical snapshot, the qualitative conclusion remained honest: only
non-initiation met the internal continuation boundary and stayed `RESEARCH ONLY`; discontinuation,
switch and restart were automatically `REJECTED`. Those smoke values are not final v2.2 release
evidence and must not be used as presentation KPIs.

The post-smoke adversarial review further tightened the restart target: an undated eventual-restart
classification can no longer satisfy a fixed 365-day outcome. A positive now requires an explicit
restart date by day 365; non-events require observation through day 365; indeterminate records are
excluded and counted. The earlier restart smoke metrics therefore must not be reused after this
correction.

### Post-hardening diagnostic — not release evidence

The current source was exercised read-only against the historical v2.1 analytical/EDA snapshot with
20 rather than 200 bootstrap repetitions. This was a development diagnostic, not a clean, sealed or
candidate-bound run; intervals are therefore omitted here and must be taken from the final package.

| Model | Analysis n / events | Final holdout n / events | ROC AUC (difference from prior) | PR AUC (difference from prior) | Brier | Calibration intercept / slope | Diagnostic disposition |
|---|---:|---:|---:|---:|---:|---:|---|
| Non-initiation 90d | 2,281 / 581 | 454 / 113 | 0.675 (+0.007) | 0.396 (+0.002) | 0.176 | 0.289 / 1.032 | RESEARCH ONLY |
| Discontinuation 12m | 1,557 / 587 | 317 / 122 | 0.526 (+0.054) | 0.396 (+0.028) | 0.237 | 2.047 / 4.307 | REJECTED |
| Treatment switch 12m | 1,074 / 104 | 220 / 24 | 0.495 (-0.078) | 0.116 (-0.040) | 0.098 | -2.190 / -0.045 | REJECTED |
| Restart after gap | 453 / 76 | 93 / 15 | 0.479 (-0.046) | 0.166 (-0.227) | 0.136 | -3.256 / -1.015 | REJECTED |

The first three model-population counts reproduce the prior n. Restart differs by -134 because the
old n=587 included statuses that were not demonstrably ascertained inside the declared horizon.
The corrected non-initiation chain explicitly reconciles 10,000 analytical records to 2,369
recorded mHSPC pathway members, then 2,281 proposed-eligible/evaluable records; pathway grid rows are
no longer mislabeled as pathway members.
Across model-population and fold checks, 148 leakage sentinels passed and zero failed. Metric
differences also reflect the new nested evaluation structure, so exact reproduction is not claimed.

## Delivered controls

| Area | Implemented evidence |
|---|---|
| Target governance | Four complete machine-readable model contracts and one responsible-AI governance contract |
| Population | Automatic stepwise attrition with exact arithmetic and final-n reconciliation |
| Leakage | Feature/outcome/index timestamps, declared-horizon ascertainment, prohibited-feature checks, patient deduplication, strict temporal and market isolation |
| Nesting | Train-only imputation/encoding/scaling/model fit plus inner-temporal calibration in every outer fold |
| Validation | Repeated rolling temporal, one final untouched temporal holdout and development-only LOMO |
| Comparators | L2 logistic research baseline and constant training-prevalence comparator |
| Metrics | ROC AUC, PR AUC plus prevalence, Brier, calibration intercept/slope and flexible curves |
| Uncertainty | Patient-level percentile bootstrap for ROC AUC, PR AUC and Brier |
| Thresholds | Not reported because no prespecified operational threshold exists |
| Utility | Exact blocked DCA artifact; no invented decision workflow |
| Subgroups | n/events/missingness/performance/uncertainty with support warnings and no ranking |
| Robustness | Alternative windows/gaps, missingness, temporal/market shifts, feature removal, simplification and prevalence shift |
| Responsible AI | Harms, oversight, misuse, stop-use, drift, incident/rollback and external-validation requirements |
| Promotion | Rejected/research-only models are blocked from operational aliases by executable policy |
| Reporting | Four Markdown/JSON model cards, aggregate evidence report and interactive Model Evidence Lab |
| Integrity | Exact clean release-source commit, combined target/evaluation/governance/alias configuration identity, fresh output path, complete SHA-256 inventory and immutable manifest marker |

## Main source changes

- `contracts/model_target_contracts.yaml`
- `contracts/model_governance.yaml`
- `configs/model_evaluation.yaml`
- `configs/model_aliases.yaml`
- `src/prostate_journey/predictive_modeling.py`
- `src/prostate_journey/model_governance.py`
- `src/prostate_journey/predictive_evidence.py`
- `src/prostate_journey/predictive_dashboard.py`
- `src/prostate_journey/presentation.py`
- `src/prostate_journey/industry_readiness.py`
- `src/prostate_journey/cli.py`
- `tests/test_predictive_framework.py`
- `tests/test_presentation_package.py`
- `contracts/analytical_data_contract.yaml`

## Generated package contract

The final command will generate, for one clean candidate release:

```text
outputs/predictive/<dataset-version>/
  model_population_derivation.csv
  validation_metrics.csv
  flexible_calibration_curves.csv
  leakage_audit.csv
  validation_fold_registry.csv
  subgroup_metrics.csv
  robustness_metrics.csv
  prior_claim_reproduction.csv
  model_disposition.csv
  decision_curve_status.json
  decision_curve_status.md
  model_cards/
  predictive_frontend_summary.json
  PREDICTIVE_EVALUATION_REPORT.md
  predictive_evidence_manifest.json
  IMMUTABLE_PREDICTIVE_EVIDENCE
```

No patient-level predictions, scores or Parquet records enter this package or the stakeholder
presentation. Candidate evidence generation fails before writing if `HEAD` differs from the release
source commit or the Git worktree contains tracked or untracked changes.

## Verification completed during implementation

- Predictive framework unit/adversarial tests pass.
- A complete small synthetic package builds, seals and passes all predictive industry gates.
- Post-seal artifact mutation is detected.
- The historical 10,000-record local snapshot completed an end-to-end smoke run.
- Its aggregate package passed manifest, metadata, population, validation, nesting/leakage and
  responsible-AI gates.
- A release/commit-matched integration fixture generated `model_story.html`, copied four model cards
  and passed presentation identity, hash, KPI, frontend and aggregate-only gates.
- Ruff and focused MyPy checks pass for the changed production modules.

The complete repository suite, full 200-bootstrap candidate evaluation, final multi-seed study,
clean v2.2 release and browser/accessibility sign-off remain intentionally deferred to the final
project verification step.

## Current disposition semantics

- `REJECTED`: weak, non-evaluable or gate-failing evidence; redesign or close. No promotion.
- `RESEARCH ONLY`: technically evaluable synthetic research signal; may inform an approved external
  validation protocol but cannot drive action.
- `CANDIDATE FOR EXTERNAL VALIDATION`: impossible through the automatic pipeline; requires named
  evidence and approval.
- `APPROVED FOR A SPECIFIED USE`: impossible without actual external/clinical/operational evidence
  and explicit approval for one use.

## Final-step command order

After all requested prompts are implemented and source is committed/reviewed:

1. Build a fresh full v2.2 candidate release from that exact clean commit.
2. Regenerate release-matched EDA/cohort and longitudinal artifacts.
3. Run `predictive-evidence` with the certified analytical directory and matching EDA directory.
4. Run scientific and multi-seed evidence packages.
5. Rebuild the presentation so Journey, Science and Model Evidence labs share release and commit.
6. Run formatting, Ruff, MyPy, full pytest and `industry-check` with every package path.
7. Perform independent statistical/model-risk, clinical/RWE, claim and browser/accessibility review.

Until those steps pass, the project remains Stage 3/5 with a stronger Stage-4 research-evaluation
foundation—not a pilot, production or clinical model system.
