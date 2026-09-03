# Referral / Handoff Pathway Analysis

## Purpose

This is a small descriptive extension for the governed synthetic `mhspc_mcspc` pathway. It follows the operational handoff from eligibility/index through relevant referral creation, referral completion, any treatment initiation, and scenario-supported intensification.

## Inputs

- `outputs/eda/cohort_patient_flags.parquet`, including the governed 90-day eligibility, evaluability, index, censoring, and treatment-initiation fields;
- certified `referral.parquet`, `treatment_episode.parquet`, and `treatment_regimen_component.parquet`, resolved through the repository's analytical-dataset resolver;
- the validated Stage 2 `intensification_funnel.csv` for 90-day intensification reconciliation.

## Operational Definitions

The primary denominator is the governed eligible, 90-day-evaluable `mhspc_mcspc` cohort. A relevant referral is a row with `referral_reason = advanced_prostate_pathway_review` and `destination_specialty = medical_oncology`.

Any treatment initiation uses the existing governed `initiated_within_90d` field. Scenario-supported intensification uses the validated Stage 2 rule: the earliest linked post-index, pre-censor treatment component with `drug_class` equal to `ARPI` or `chemotherapy`. ADT monotherapy is not intensified.

## 90-Day Pathway

The core pathway is:

```text
governed eligible mHSPC
    -> relevant referral created
    -> relevant referral completed by 90 days
    -> any treatment initiated by 90 days
    -> scenario-supported intensified by 90 days
```

The summary output also includes overall, market, and initial-care-setting rows where the evaluable segment has at least 30 patients. Referral creation timing is reported only as a small descriptive timing metric because it has little variation in this cohort.

## Timing Metrics

`referral_timing.csv` reports median and IQR days for referral-to-completion, completion-to-treatment, and completion-to-intensification when both linked events are observed. It also reports eligibility-to-referral timing as a limited descriptive note.

## Run

From the repository root:

```text
.\\.venv\\Scripts\\python.exe analysis_extensions/referral_pathway/referral_pathway_analysis.py
```

The script writes only aggregate outputs under `analysis_extensions/referral_pathway/outputs/` and fails on hard chronology or reconciliation violations. Treatment or intensification without completed referral is reported as a valid synthetic case, not silently removed.

## Outputs

- `referral_pathway_summary.csv`: core 90-day pathway and limited segment summaries;
- `referral_timing.csv`: process timing summaries;
- `referral_reconciliation.csv`: chronology, governed EDA, Stage 2, and source-definition checks;
- `referral_summary.md`: concise human-readable interpretation and limitations.

## Limitations and Guardrails

Referral completion is structurally coupled in the synthetic generator to initiation probability, treatment start timing, provider selection, and chemotherapy availability. Results therefore describe synthetic process patterns only and do not establish causal effects or real-world evidence.

All data are synthetic. The analysis is descriptive and exploratory, with no causal modelling, ML, provider ranking, clinical recommendation, real-world market-size claim, or financial/value calculation. Post-index referral variables are process measures and must not be used as baseline predictors of treatment non-initiation.