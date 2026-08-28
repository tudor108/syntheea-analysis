# Exploratory driver-analysis model card

> **Synthetic demonstrational data only; not clinical guidance, diagnosis, causal evidence, real Bayer data, or a real-world market-size estimate.**

## Intended use and prohibited use

This layer ranks transparent baseline associations and tests whether a simple logistic model can predict governed synthetic EDA targets on a later temporal holdout. **This is not causal inference and is not a clinical decision-support model.** It must not be used to recommend treatment, rank patients for care, infer clinical barriers, evaluate provider quality, or estimate commercial/financial impact.

Association, prediction and causality are separate: odds ratios are univariate associations; standardized multivariable coefficients and permutation importance are predictive/model-dependent; **causality is not established** for any row. SHAP/feature importance would not change that interpretation.

## Target audit

- `non_initiated_within_90_days` — MODELLED; n=2,281, positives=581 (25.5%): Eligible/observable primary mHSPC cohort without qualifying treatment initiation by day 90. Limitation: Synthetic governed eligibility and normalized treatment start; not clinical eligibility.
- `discontinued_within_12_months` — MODELLED; n=1,557, positives=587 (37.7%): 60-day permissible-gap persistence failure by day 365; competing events before day 365 excluded. Limitation: Gap-based endpoint is assumption-dependent and dispensing is not ingestion.
- `switched_treatment` — MODELLED; n=1,074, positives=104 (9.7%): Explicit switch by day 365 versus remaining event-free through day 365; early competing events excluded. Limitation: Conditional risk set excludes early competing events and is not treatment effectiveness.
- `restarted_after_gap` — MODELLED; n=587, positives=217 (37.0%): Temporary gap with observed restart versus non-restarted discontinuation among 60-day gap failures by day 365. Limitation: Conditional on an observed/assumed 60-day gap failure; threshold-dependent.
- `initiated_within_90_days` — NOT_SEPARATELY_MODELLED_EXACT_COMPLEMENT; n=2,281, positives=1,700 (74.5%): Exact complement of non_initiated_within_90_days in the same risk set. Limitation: A duplicate model would contain identical information with reversed signs.

`initiated_within_90_days` is not fitted separately because it is the exact complement of the non-initiation target. mCRPC and nmCRPC are not combined with the governed primary mHSPC cohort.

## Leakage controls

- Patient/provider IDs never enter a design matrix. Provider identity is reduced to specialty, setting and a fixed volume band.
- All encounter, referral and prior-treatment features are reconstructed with timestamps no later than the prediction index.
- Initiation prediction excludes all post-eligibility encounters and referrals. In this release every referral for the primary initiation cohort occurs after eligibility.
- Discontinuation, switch, restart, censoring, future treatment dates, final outcomes and outcome-derived flags are target/risk-set construction only.
- Temporal splitting uses the latest approximately 25% of prediction-index dates as the locked holdout; each patient appears in only one split.
- Imputation, standardization, category references and zero-variance filtering are fit on training data only.

## Model and evaluation

The baseline is an L2-regularized logistic regression implemented with transparent NumPy IRLS because the controlled environment contains no scikit-learn/statsmodels. Numeric coefficients are per training-set standard deviation; categories are reference-coded. Coefficient intervals are approximate penalized-Hessian intervals, not causal/inferential confidence intervals. Metric intervals use 200 temporal-test bootstrap samples.

- `non_initiated_within_90_days`: n=2,281, temporal test n=565, PR-AUC=0.394 (0.326-0.483), ROC-AUC=0.668, Brier=0.175, recall at ~20% capacity=0.367.
- `discontinued_within_12_months`: n=1,557, temporal test n=392, PR-AUC=0.368 (0.300-0.430), ROC-AUC=0.472, Brier=0.245, recall at ~20% capacity=0.179.
- `switched_treatment`: n=1,074, temporal test n=271, PR-AUC=0.156 (0.093-0.255), ROC-AUC=0.573, Brier=0.097, recall at ~20% capacity=0.345.
- `restarted_after_gap`: n=587, temporal test n=152, PR-AUC=0.393 (0.311-0.496), ROC-AUC=0.525, Brier=0.249, recall at ~20% capacity=0.228.

Predictive-readiness interpretation:

- `non_initiated_within_90_days`: directional temporal discrimination only; calibration and external validation remain required.
- `discontinued_within_12_months`: limited temporal discrimination; investigate measurement/target stability before operational use.
- `switched_treatment`: limited temporal discrimination; investigate measurement/target stability before operational use.
- `restarted_after_gap`: limited temporal discrimination; investigate measurement/target stability before operational use.

The operational threshold is the temporal-test top 20% predicted-risk capacity, reported transparently with its confusion matrix. ROC-AUC is secondary to PR-AUC. Calibration and Brier score are reported because ranking alone is insufficient.

Tree challengers were not run because no validated tree library is installed; dependencies were not added. A home-grown tree would add opaque implementation risk. Survival models were not run because competing-risk tooling is unavailable and the discontinuation endpoint is gap-assumption-dependent. SHAP is unavailable and inappropriate without a justified challenger, so `shap_summary.png` is intentionally absent.

## Top associated drivers

- `non_initiated_within_90_days` / `market_code` / `CN`: OR 3.074 (2.443-3.867), HIGHER_RISK.
- `non_initiated_within_90_days` / `insurance_type` / `urban_employee`: OR 2.994 (2.150-4.171), HIGHER_RISK.
- `non_initiated_within_90_days` / `insurance_type` / `urban_resident`: OR 2.846 (1.896-4.273), HIGHER_RISK.
- `non_initiated_within_90_days` / `insurance_type` / `self_pay_other`: OR 2.516 (1.297-4.880), HIGHER_RISK.
- `non_initiated_within_90_days` / `insurance_type` / `employee_health`: OR 0.459 (0.278-0.758), LOWER_RISK.
- `non_initiated_within_90_days` / `market_code` / `JP`: OR 0.506 (0.372-0.687), LOWER_RISK.
- `non_initiated_within_90_days` / `insurance_type` / `national_health_insurance`: OR 0.512 (0.339-0.772), LOWER_RISK.
- `discontinued_within_12_months` / `insurance_type` / `private`: OR 0.526 (0.294-0.943), LOWER_RISK.

These are synthetic unadjusted associations. A feature cannot be called a clinical barrier without external temporal, clinical and operational validation.

## Top predictive features

- `non_initiated_within_90_days` / `market_code`: mean temporal-test PR-AUC drop 0.1004.
- `non_initiated_within_90_days` / `insurance_type`: mean temporal-test PR-AUC drop 0.0582.
- `restarted_after_gap` / `comorbidity_score`: mean temporal-test PR-AUC drop 0.0231.
- `switched_treatment` / `care_setting`: mean temporal-test PR-AUC drop 0.0175.
- `switched_treatment` / `market_code`: mean temporal-test PR-AUC drop 0.0160.
- `switched_treatment` / `provider_volume_band`: mean temporal-test PR-AUC drop 0.0146.
- `restarted_after_gap` / `prior_healthcare_utilization_180d`: mean temporal-test PR-AUC drop 0.0109.
- `restarted_after_gap` / `frailty_proxy`: mean temporal-test PR-AUC drop 0.0108.

Permutation importance is model- and correlation-dependent. It does not supply direction, mechanism or causal attribution.

## Subgroup disparities and instability

- discontinued_within_12_months/care_setting: ROC-AUC spread 0.219
- discontinued_within_12_months/market_code: ROC-AUC spread 0.209
- non_initiated_within_90_days/age_band: ROC-AUC spread 0.173
- non_initiated_within_90_days/market_code: ROC-AUC spread 0.311
- restarted_after_gap/age_band: ROC-AUC spread 0.145
- restarted_after_gap/care_setting: ROC-AUC spread 0.144
- switched_treatment/care_setting: ROC-AUC spread 0.173
- switched_treatment/market_code: ROC-AUC spread 0.136

Subgroup differences may be measurement artifacts, simulation effects or sampling noise. Performance is reported by market, disease state, age band, care setting and missingness pattern, including small-cell flags.

## Data-quality signals that may look like drivers

- At eligibility, only the diagnosis encounter is available for the primary cohort; pre-index utilization is zero and provider specialty is uniformly urology. These cannot support a meaningful utilization/specialty driver conclusion.
- Referrals occur after eligibility. Using referral completion for 90-day initiation prediction would be direct future-pathway leakage.
- Market, insurance and access categories may partly encode synthetic generation logic rather than modifiable real-world mechanisms.
- Gap-based discontinuation depends on the 60-day scenario and dispensing coverage is not ingestion.
- Missingness pattern performance can reflect data capture rather than patient risk.

## Features that must not be used

- `distance_or_rurality`: No legally/analytically justified field (leakage risk HIGH).
- `patient_id`: Identifier; split grouping only (leakage risk CRITICAL).
- `provider_id`: Replaced by safe specialty/setting/volume aggregates (leakage risk CRITICAL).
- `treatment_start_date`: Target/future information for initiation; index only for persistence (leakage risk CRITICAL).
- `days_to_initiation`: Directly encodes initiation target (leakage risk CRITICAL).
- `discontinuation_flag`: Target-derived future outcome (leakage risk CRITICAL).
- `switch_flag`: Target-derived future outcome (leakage risk CRITICAL).
- `restart_flag`: Target-derived future outcome (leakage risk CRITICAL).
- `hospitalisation_flag`: Final outcome flag; only pre-index encounter evidence allowed (leakage risk CRITICAL).
- `post_index_encounters`: Strict temporal leakage rule (leakage risk CRITICAL).
- `censor_reason`: Used only for risk-set construction (leakage risk CRITICAL).

## Candidate interventions for validation, not recommendations

- Validate referral timestamp completeness and define the operational prediction moment before testing any handoff intervention.
- Audit access/insurance proxy meaning and censor-aware delays by market; do not assume the association is an access barrier.
- Extend governed 180/365-day pre-index utilization history before reassessing pathway or provider drivers.
- Review comorbidity/frailty proxy validity with Medical before interpreting segment differences.
- Lock a future time period or independent dataset for calibration and subgroup validation.

No financial values, success probabilities or clinical-effectiveness estimates are provided. The separate intervention backlog assigns validation owners and measurable leading/outcome indicators only.

## Required validation ownership

- **Medical:** clinical coherence of eligibility, comorbidity/frailty, metastatic-site and gap endpoint definitions.
- **Commercial/Operations:** referral/handoff timestamps, operational capacity threshold and whether candidate workflow measures are actionable.
- **Data Strategy:** leakage audit, external temporal validation, baseline coverage, payer/market semantics, calibration and subgroup stability.

<!-- INTERVENTION_BACKLOG_GENERATED -->

## Generated intervention-validation backlog

These are measurement and validation hypotheses, not treatment recommendations. Priority reflects sequencing of validation work, not expected effectiveness or financial value.

### 1_HIGH_DATA_FOUNDATION

- **Hypothesis:** Improve timestamp capture for referral creation and completion before any future pathway-prediction use.
- **Segment:** Primary mHSPC eligibility pathway; all markets
- **Evidence:** DATA QUALITY SIGNAL: 0 pre-index referral records in the primary initiation cohort; Referral events occur after eligibility, so using them for initiation prediction would leak future pathway information.
- **Owner:** Data Strategy + Commercial Operations
- **Required validation:** Commercial must validate the real handoff workflow; Medical must confirm this does not encode a clinical decision.
- **KPI:** Censor-aware 90-day initiation reporting completeness; no effectiveness claim

### 2_HIGH_VALIDATION

- **Hypothesis:** Validate market, payer and access-proxy semantics before investigating administrative pathway delay.
- **Segment:** CN and payer categories with elevated descriptive non-initiation odds
- **Evidence:** ASSOCIATED: OR=3.074 (95% approximate 2.443-3.867); One-versus-rest descriptive odds ratio with 0.5 continuity correction; not adjusted or causal. | ASSOCIATED: OR=2.994 (95% approximate 2.150-4.171); One-versus-rest descriptive odds ratio with 0.5 continuity correction; not adjusted or causal. | initiation temporal ROC-AUC=0.668
- **Owner:** Market Access + Data Strategy
- **Required validation:** Commercial/Market Access must establish whether categories represent modifiable processes; Medical must rule out clinical case-mix explanations.
- **KPI:** 90-day initiation and time-to-initiation by validated administrative segment

### 3_MEDIUM_PATHWAY_AUDIT

- **Hypothesis:** Audit pathway handoff and scheduling measurement by care setting and provider-volume band without ranking providers.
- **Segment:** Academic-oncology and high-volume provider-band pathways
- **Evidence:** ASSOCIATED: OR=1.299 (95% approximate 1.043-1.618); One-versus-rest descriptive odds ratio with 0.5 continuity correction; not adjusted or causal. | ASSOCIATED: OR=1.708 (95% approximate 1.335-2.185); One-versus-rest descriptive odds ratio with 0.5 continuity correction; not adjusted or causal.
- **Owner:** Commercial Operations + Data Strategy
- **Required validation:** Medical review of case mix; Commercial confirmation that milestones are operationally controlled; no provider-performance use.
- **KPI:** Censor-aware 90-day initiation by setting after case-mix validation

### 4_MEDIUM_MEDICAL_VALIDATION

- **Hypothesis:** Validate comorbidity and frailty proxy construction before investigating differentiated support workflows.
- **Segment:** Higher comorbidity/frailty proxy segments
- **Evidence:** ASSOCIATED: OR=1.186 (95% approximate 1.082-1.301); Univariate association; confounding and synthetic generation effects remain. | ASSOCIATED: OR=1.266 (95% approximate 1.071-1.497); Univariate association; confounding and synthetic generation effects remain.
- **Owner:** Medical + Data Strategy
- **Required validation:** Medical must approve interpretation; no care or treatment recommendation may be derived from the current association.
- **KPI:** Calibrated descriptive initiation/persistence reporting by validated burden band

### 5_MEDIUM_DATA_COVERAGE

- **Hypothesis:** Extend governed pre-index observation to measure 180/365-day utilization and prior hospitalization reliably.
- **Segment:** All initiation-risk-set patients
- **Evidence:** DATA QUALITY SIGNAL: Only diagnosis encounter at eligibility; provider specialty is urology for all rows; Lack of pre-index history prevents meaningful utilization or specialty driver estimation.
- **Owner:** Data Strategy
- **Required validation:** Data Strategy must establish provenance; Medical must define clinically meaningful baseline windows.
- **KPI:** Stability of baseline-driver estimates after complete lookback

### 6_MEDIUM_OUTCOME_QUALITY

- **Hypothesis:** Improve explicit stop, refill-gap reason, disenrollment and medication-administration capture before persistence prediction.
- **Segment:** Patients entering the 12-month persistence risk set
- **Evidence:** Gap-60 target is assumption-dependent; discontinuation temporal ROC-AUC=0.472, indicating no useful temporal discrimination from current baseline features.
- **Owner:** Medical + Data Strategy
- **Required validation:** Medical must approve discontinuation/restart definitions; Data Strategy must validate censoring and source completeness.
- **KPI:** Reduction in proxy/unknown persistence endpoints and stable 30/60/90-day sensitivity

### 7_RELEASE_GATE

- **Hypothesis:** Lock an independent future period and repeat calibration/subgroup testing before any operational pilot.
- **Segment:** All modelled targets and reported subgroups
- **Evidence:** Temporal performance is directional for initiation and weak for discontinuation/switch/restart; subgroup spread is present.
- **Owner:** Data Strategy + Model Risk
- **Required validation:** Medical, Commercial and Data Strategy must approve intended use and stopping rules before pilot.
- **KPI:** External PR-AUC, Brier score, calibration error and subgroup stability
