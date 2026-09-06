# Predictive-model research methods v2.2

> **SYNTHETIC DEMONSTRATIONAL DATA ONLY. NOT REAL BAYER, PATIENT, CLINICAL,
> COMMERCIAL, OR POPULATION DATA.** Internal temporal and market validation is not external or
> clinical validation, transportability, real-world utility, or evidence of patient benefit.

## Purpose and standards boundary

This subsystem evaluates whether four prespecified synthetic prediction questions are technically
and statistically worth further research. It is designed using the reporting concepts in the
[TRIPOD+AI statement](https://www.bmj.com/content/385/bmj-2023-078378) and the development-quality,
evaluation-bias, fairness and applicability domains in
[PROBAST+AI](https://www.bmj.com/content/388/bmj-2024-082505). These are review lenses, not a claim
of checklist completion, low risk of bias, regulatory compliance, clinical validity or approval.

TRIPOD+AI is a reporting guideline rather than a development prescription. PROBAST+AI separately
examines model-development quality and risk of bias in performance evaluation. The repository
therefore keeps target reporting, evaluation design, generated evidence and disposition controls
separate.

## Prespecified model questions

The authoritative definitions are in `contracts/model_target_contracts.yaml`.

| Model ID | Prediction time | Horizon | Binary outcome | Development population |
|---|---|---:|---|---|
| `non_initiation_90d` | Eligibility date | 90 days | Not initiated versus initiated by day 90 | Proposed-eligible records with a determinable 90-day status; earlier censoring excluded and counted |
| `discontinuation_12m` | Treatment start | 365 days | 60-day permissible-gap persistence failure by day 365 | Initiators with failure by day 365 or event-free observation beyond day 365; earlier competing/censoring states excluded |
| `treatment_switch_12m` | Treatment start | 365 days | Explicit switch by day 365 | Initiators with switch by day 365 or event-free observation beyond day 365; earlier non-switch failure, death and censoring excluded |
| `restart_after_gap` | Treatment start | 365 days | Explicit dated restart by day 365 versus no restart through day 365 | Initiators with a qualifying 60-day gap failure by day 365 and dated restart or complete 365-day restart ascertainment |

The restart model is deliberately fixed at treatment start. It is not a gap-triggered operational
model, and membership in its gap-failure population is not knowable at prediction time. Undated
restart classifications and early-censored indeterminate records are excluded and counted. A future
operational gap-triggered question would require a new target contract. No current model contract
defines an approved patient action, threshold range or comparison strategy.

## Reproducible population derivation

`build_model_datasets` creates a one-row-per-patient model frame and an attrition chain. Every chain
records step order, reason, entered n, excluded n, retained n and a reconciliation difference.
Generation fails if:

- `entered_n != excluded_n + retained_n` at any step;
- the next step does not begin with the preceding retained n;
- the final retained n differs from the actual model frame;
- patient IDs are duplicated;
- time zero, target or market is missing;
- the target is not binary.

The sealed output is `model_population_derivation.csv`. Differences among model sample sizes are
therefore explained by eligibility, initiation, horizon observability, competing/censoring states
and outcome determinability rather than left implicit.

## Predictor timing and leakage controls

The feature set and prohibited set are versioned in `configs/model_evaluation.yaml`. Candidate
predictors include baseline demographics/proxies, disease state, prior utilization, prior treatment,
care setting, provider characteristics, referral status, insurance, market and calendar period.

Controls include:

- prediction-index and outcome timestamps;
- target ascertainment no later than the declared horizon;
- encounter, referral/completion and prior-treatment maximum feature timestamps;
- metastasis information only when the metastasis date is on or before prediction time;
- explicit rejection of outcome labels, treatment dates and post-index event fields as predictors;
- one patient in one side of each outer fold;
- strict earlier-training/later-evaluation cutoffs for temporal folds;
- complete market keys and complete exclusion of the held-out market from LOMO training;
- adversarial tests that insert a future feature timestamp or prohibited target-derived feature and
  require a `LeakageViolation`.

Any failed leakage audit stops evidence generation. The aggregate audit is retained in
`leakage_audit.csv`.

## Nested model pipeline

The principal evidence never uses a random row split. For every outer partition:

1. Select only the outer training records.
2. Split those records chronologically into an inner model-fit subset and an inner calibration
   subset.
3. Fit numeric medians, means and scales on the inner model-fit subset only.
4. Fit categorical levels on the inner model-fit subset; missingness is explicit and unseen levels
   map to a reserved category.
5. Fit an L2-regularized logistic model on the inner model-fit subset.
6. Fit Platt calibration only on the later inner calibration subset. If minimum support is absent,
   use a declared identity fallback; never fit calibration on the outer evaluation records.
7. Apply the frozen encoder, model and calibrator to the outer evaluation records.
8. Fit a constant training-prevalence comparator without using outer outcomes.

No feature selection is performed. If selection is introduced later, it must be fitted inside every
resampling structure.

## Validation design

Each target receives:

- repeated rolling-origin temporal evaluation during development;
- one final, untouched later temporal holdout;
- leave-one-market-out evaluation restricted to the development period;
- the same nested preprocessing and calibration logic in every evaluable fold.

The fold registry reports outer train n, model-fit n, calibration n, validation n, last training
time, first evaluation time, holdout market and fit scope. Market results are synthetic stress tests
and must not be ranked.

## Performance and uncertainty

For the regularized logistic model and prevalence comparator, the package reports:

- validation n, events, non-events and event prevalence;
- ROC AUC with patient-level percentile-bootstrap 95% interval;
- average precision (PR AUC) with its interval and event prevalence beside it;
- Brier score with interval;
- calibration intercept and slope;
- a Gaussian-kernel descriptive flexible calibration curve with local effective support and local
  normal-approximation bands.

The calibration curve bands are not simultaneous confidence bands. Sensitivity, specificity and
confusion matrices are absent because no threshold is prespecified. AUC alone cannot authorize
promotion.

## Decision utility

Decision-curve analysis is blocked until a named human decision, plausible threshold range,
false-positive/false-negative consequences and approved comparison strategies exist. The exact
generated statement is:

> **DECISION CURVE NOT INTERPRETABLE — OPERATIONAL ACTION AND THRESHOLD TRADE-OFF NOT DEFINED.**

No workflow or threshold is invented to make a net-benefit chart possible.

## Subgroups and robustness

Configured subgroup dimensions are market, disease state, age band, care setting and missingness
pattern. Each final-holdout row reports n, events/non-events, prevalence, predictor missingness,
discrimination, calibration and bootstrap uncertainty. Rows below support minima are marked
`INSUFFICIENT SUPPORT — DO NOT RANK`; all rows set `ranking_allowed=false`.

The robustness battery covers:

- 30/60/90-day initiation definitions;
- 30/60/90-day permissible persistence gaps;
- added predictor missingness while preserving structural validation keys;
- repeated temporal shifts and market holdouts;
- removal of access/market-related features;
- a prespecified four-feature simplified logistic model;
- outcome-stratified resampling to prespecified event-odds shifts, preserving within-class score
  distributions and evaluating without model refit.

These analyses diagnose fragility. They are not a search for the most favorable result.

## Responsible-AI disposition

The allowed states are `REJECTED`, `RESEARCH ONLY`, `CANDIDATE FOR EXTERNAL VALIDATION` and
`APPROVED FOR A SPECIFIED USE`. Automated evaluation can never exceed `RESEARCH ONLY`.

The current engineering continuation boundary rejects a model when mandatory leakage/support gates
fail, final discrimination is not evaluable, or final ROC AUC is below the prespecified boundary.
This boundary is a conservative internal triage rule, not clinical acceptance evidence.

`configs/model_aliases.yaml` is machine-checked against `contracts/model_governance.yaml`.
Operational aliases accept only `APPROVED FOR A SPECIFIED USE`, which itself requires actual approval
evidence. Rejected and research-only models cannot be promoted through configuration.

## Sealed evidence and presentation

`predictive-evidence` writes a fresh-path-only package under
`outputs/predictive/<dataset-version>`. It contains only aggregate CSV/JSON/Markdown/YAML evidence,
four model cards, a complete artifact hash inventory and `IMMUTABLE_PREDICTIVE_EVIDENCE`. No
patient-level probability or score export is included. Generation fails before writing unless the
analysis runs from the exact release source commit with a clean Git worktree.
Its predictive configuration identity is one canonical hash over the target, evaluation,
responsible-AI and alias configurations; each component snapshot also has its own SHA-256 entry.

When release and source commit match, `presentation-package` verifies the sealed package, copies an
allow-listed aggregate subset and creates `model_story.html`. The interactive lab exposes target
contracts, attrition, final/rolling/market evidence, calibration, subgroup support, robustness,
disposition and the blocked utility decision.

## Evidence required before further discussion

Before `CANDIDATE FOR EXTERNAL VALIDATION`: approved intended use, target and workflow; protocol/SAP;
governed data access; source/phenotype/outcome validation; privacy/security approval; and named
clinical, RWE, statistics and model-risk review.

Before any specified operational use: independent temporal and geographic external validation;
calibration, utility and subgroup-harm evidence at an approved threshold; workflow/human-factors
testing; monitoring limits; incident/rollback readiness; and explicit approval for one population,
use, model version and alias. Synthetic evidence cannot satisfy these requirements.
