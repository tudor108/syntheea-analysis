# Healthcare data-analysis playbook

> **Synthetic demo only.** The methods below are suitable for pipeline and analytics development. They are not clinical guidance, effectiveness estimates, population estimates, or causal evidence.

## What fits this dataset

The dataset is a longitudinal, synthetic patient journey with explicit eligibility, referral, treatment events, refills, outcomes, observation end dates, and market-dependent missingness. The most defensible analyses are therefore denominator-first and descriptive:

| Tactic | Source | Output/target | Important guardrail |
|---|---|---|---|
| Cohort funnel | `patient_journey` | Eligible → initiated in 30/60/90 days | Use eligible patients as the denominator; do not count pre-window censoring as a treatment gap |
| Landmark persistence | `patient_journey`, `prescription_event` | 12-month persistence at 30/60/90-day allowable refill gaps | Keep `CENSORED_NOT_EVALUABLE` separate from non-persistence |
| Pathway/referral analysis | `referral`, `encounter`, `provider`, `organization` | Completion, delay, specialty and setting comparisons | Referral variables are post-index unless their dates are proven available at the prediction index |
| Missingness profiling | `patient_journey`, market metadata | Missing rate by market and field | Scan-market missingness can be structural; do not treat it as random without evidence |
| Equity-oriented stratification | `patient_journey` | Rates by market, insurance, socioeconomic proxy, or care setting | Show cell sizes and uncertainty; never interpret synthetic gaps as real-world disparities |
| Leakage-safe prediction setup | `feature_timing`, `patient_split` | Initiation, pathway-gap, or discontinuation feature sets | Use only features available at the task-specific cutoff and split by independent archetype |

## Recommended analysis sequence

1. **Define the index and denominator.** For initiation, use `eligibility_date`; for persistence, use `treatment_start_date`. Keep `NOT_ELIGIBLE`, `NOT_APPLICABLE`, and censored records out of the wrong denominator.
2. **Validate before aggregating.** Run the existing DQ, readiness, and adversarial checks. They enforce chronology, foreign keys, event coverage, censoring, and mart reconciliation.
3. **Describe the pathway.** Compare initiation windows, referral completion/delay, care setting, provider specialty, regimen snapshots, and active-surveillance transitions.
4. **Retain uncertainty.** The generated extracts include Wilson intervals for rates. They describe sampling variation within this synthetic cohort, not uncertainty about the real prostate-cancer population.
5. **Stress-test definitions.** Compare persistence under 30/60/90-day gaps and report the number censored. Avoid silently converting an alternative definition into a missing-data decision.
6. **Check missingness by design.** Compare deep versus scan markets and inspect `market_depth` before choosing complete-case analysis, imputation, or a missing category.
7. **Separate description from prediction.** Use the explicit feature timing metadata and patient/archetype split. Full-episode treatment, future refills, progression, discontinuation, and final outcomes are not baseline predictors.

## Existing feature contracts

Use these functions when creating model inputs:

- `treatment_initiation_features(journey)` for eligibility-time initiation analysis;
- `pathway_gap_features(journey)` for referral completion analysis;
- `discontinuation_features(journey)` for treatment-start predictors and the 12-month persistence target.

The resulting target and feature timing are documented in `feature_timing`. `patient_split` keeps one independent `source_archetype_id` in only one of train, validation, or test.

## Generated extracts

`run-all` and `report` write the following files under `data/reports`:

- `healthcare_initiation_funnel.csv` — eligible, evaluable, initiated, not initiated, and censored counts for 30/60/90 days;
- `healthcare_persistence_summary.csv` — persistent, discontinued, switched, evaluable, and censored counts for 30/60/90-day gap sensitivities;
- `healthcare_referral_summary.csv` — referral completion and delay distribution by market;
- `healthcare_missingness_by_market.csv` — missingness rates and deltas versus the overall rate;
- `healthcare_analysis_report.md` — an index and interpretation guardrails.

To regenerate them from the newest accepted immutable release:

```powershell
uv run prostate-journey report
```

Working gold requires the explicit exploratory-only `--allow-working-gold` flag and must never be
used as a presentation source.

To run the unit and integration checks:

```powershell
uv run ruff format --check src tests eda
uv run ruff check src tests eda
uv run mypy src
uv run pytest
uv run prostate-journey industry-check --allow-missing-release
```

## What this project should not claim

Do not use this synthetic cohort to estimate treatment effectiveness, comparative safety, adherence in a real population, unmet need, causal effects, or market shares. Treatment choice is generated by scenario rules, the sample is not population-representative, and associations can reflect the generator rather than care delivery.
