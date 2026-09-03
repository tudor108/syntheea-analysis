# Synthetic mHSPC Treatment Intensification

> Exploratory, scenario-supported intensification analysis. Synthetic data only; not clinical guidance or causal evidence.

## Scope

The primary population is the governed `mhspc_mcspc` pathway from `outputs/eda/cohort_patient_flags.parquet`. Existing eligibility, index, censoring, observability, and treatment-initiation fields are reused.

Synthetic intensification is defined from the earliest post-index, pre-censor ARPI or chemotherapy component linked to an observed treatment episode. ADT monotherapy is not intensified. The regimen-level flag is reconciliation-only.

## Results

The aggregate KPI results are in `intensification_funnel.csv`; segment results are limited to overall, market, and initial care setting in `intensification_by_segment.csv`.

Timing summaries are in `intensification_timing.csv` and are restricted to evaluable patients with an observable component-derived date.

Validation recorded 3 failing check row(s). Component-versus-regimen mismatches: 0 patient(s). Review `intensification_reconciliation.csv` before interpreting results.

## Limitations and Guardrails

- All data are synthetic and all findings are exploratory/descriptive.
- No causal claims, clinical recommendations, real-world market-size claims, or invented financial value are supported.
- The ARPI/chemotherapy rule is scenario-supported synthetic intensification, not authoritative clinical guidance.
- Results depend on governed cohort definitions, normalized treatment lineage, and censor-aware 30/60/90-day evaluability.
- This work does not modify upstream cohort or treatment logic and does not infer events after censoring.
