# Referral / Handoff Pathway Analysis

> Descriptive synthetic pathway analysis only; no causal or clinical interpretation.

The 90-day pathway reuses the governed eligible `mhspc_mcspc` denominator and initiation fields, then follows relevant referral creation, completion, treatment initiation, and scenario-supported component-derived intensification.

Within the evaluable denominator of 2,281, 1,713 patients had a relevant referral completed by 90 days. See `referral_pathway_summary.csv` for the aggregate and limited segment results, and `referral_timing.csv` for timing statistics.

Referral creation timing is included only as a small descriptive note because it has little variation in this synthetic cohort. Referral completion is structurally coupled by the generator to initiation probability, treatment timing, provider selection, and chemotherapy availability; observed patterns must not be treated as causal or real-world evidence.

The reconciliation file records valid synthetic cases treated or intensified without a completed referral as report-only observations, not data errors. It also records any mismatch between the specified relevant-referral definition and source rows.

All data are synthetic. This analysis does not rank providers, model causality, estimate financial value, or modify upstream cohort/treatment logic.
