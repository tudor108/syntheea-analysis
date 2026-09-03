# Analysis Extensions

## Purpose

This folder contains analytical extensions that complement the existing governed `eda/` workflow.

## Current Analysis Baseline

The current `dev` branch already contains the implemented EDA workflow under the repository's `eda/` directory:

- `eda/00_inventory_and_data_contract.py`
- `eda/01_data_quality_profile.py`
- `eda/02_cohort_engine.py`
- `eda/03_funnel_and_treatment_gap.py`
- `eda/04_treatment_episode_builder.py`
- `eda/05_time_to_initiation_and_persistence.py`
- `eda/06_driver_analysis.py`
- `eda/07_intervention_backlog.py`

Together, this workflow covers:

- data inventory and contracts;
- data-quality profiling and reconciliation;
- cohort definitions;
- mHSPC/mCSPC, mCRPC, and Active Surveillance analysis;
- 30/60/90-day initiation funnel;
- treatment-gap segmentation;
- longitudinal treatment episodes;
- time-to-initiation;
- persistence;
- switch, discontinuation, and restart;
- leakage-safe exploratory driver analysis;
- intervention-validation backlog.

## Treatment Intensification Analysis

**IMPLEMENTED AND VALIDATED** in `treatment_intensification/`.

The analysis separates `UNTREATED`, `TREATED_NOT_INTENSIFIED`, and `INTENSIFIED` because any treatment initiation is not equivalent to scenario-supported treatment intensification. It reuses the governed mHSPC cohort and existing censor-aware 30/60/90-day denominators rather than redefining eligibility. Intensification timing is derived from qualifying ARPI/chemotherapy component start dates, so delayed add-on intensification can be represented.

At 90 days, 74.5% had initiated any treatment, 45.0% were intensified, 29.5% were treated but not intensified, and 25.5% remained untreated. Timing, category identity, monotonicity, component/regimen, and governed-EDA reconciliation checks passed. The analysis remains synthetic, descriptive, exploratory, and non-causal; detailed results remain in `treatment_intensification/`.

## Referral / Handoff Pathway Analysis

**IMPLEMENTED AND VALIDATED** in `referral_pathway/` after a LIMITED_GO feasibility assessment. The extension was intentionally limited to a descriptive 90-day pathway from governed eligible mHSPC through relevant referral creation, referral completion, any treatment initiation, and scenario-supported intensification.

In the 2,281-patient evaluable denominator, 2,281 referrals were created, 1,713 were completed by 90 days, 1,700 patients initiated treatment, and 1,026 were intensified. The main referral-to-completion timing was a 30-day median with an 18-43 day IQR. All chronology, governed-EDA, Stage 2, and source-definition reconciliation checks passed.

Referral completion is structurally coupled in the synthetic generator to treatment initiation probability, treatment start timing, provider selection, and chemotherapy availability. Results are therefore descriptive synthetic process findings only, not causal or real-world referral-effect evidence. Detailed results remain in `referral_pathway/`.

## Current Coverage and Future Gaps

The existing governed persistence workflow already covers persistence, switch, discontinuation, restart, censoring, and refill-gap sensitivity. No additional persistence extension is currently required unless a future analytical gap is identified. ARPI-specific persistence and robustness/sensitivity analysis remain **PLANNED / CONDITIONAL** only if such a gap is established.

## Analytical Guardrails

- All data are synthetic.
- All findings are exploratory.
- No causal claims or clinical recommendations.
- No real-world market-size claims.
- No financial impact should be invented.
- Results must remain aligned with governed cohort definitions and censoring rules.
