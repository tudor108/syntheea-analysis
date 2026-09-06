# Scientific methods package v2.2

> All values, patients, events, markets, and results are synthetic demonstration artifacts. This
> document is an engineering methods specification, not a protocol, statistical analysis plan,
> clinical validation, regulatory position, or Bayer finding.

## Intended scope

The package makes the current descriptive, longitudinal, exploratory-association, and predictive
questions explicit and reproducible. It does not identify causal effects. A causal analysis may be
added only after a separate question, causal estimand, design, identification assumptions,
confounding strategy, diagnostics, and validation plan are approved.

The machine-readable source of truth is
[`contracts/analysis_registry.yaml`](../contracts/analysis_registry.yaml). Each entry states the
target and study populations, numerator, denominator, eligibility, time zero, event, horizon,
competing and censoring events, estimator, assumptions, source variables, sensitivities, boundary,
and review state. `SME REVIEWED` and `SOURCE VALIDATED` are unavailable without linked evidence.

The structure follows the discipline of explicitly defining the treatment/condition, population,
variable or endpoint, intercurrent-event handling, and summary measure described by
[ICH E9(R1)](https://database.ich.org/sites/default/files/E9-R1_Step4_Guideline_2019_1203.pdf),
while remaining a non-causal synthetic implementation.

## Three uncertainty layers

The system never labels all uncertainty as one generic confidence interval.

| Layer | Question answered | Output and label |
|---|---|---|
| Estimator uncertainty | How precise is an estimator inside one fixed generated dataset? | Wilson score intervals and Greenwood log-log pointwise bands with censoring-mark counts, explicitly labelled estimator uncertainty |
| Regeneration variation | How much does a result change when new synthetic patients are generated under the same assumptions? | Within-scenario empirical simulation interval and Monte Carlo standard error |
| Assumption variation | How much does the scenario mean move when the coherent care-friction assumptions change? | Low/base/high scenario envelope, explicitly not a confidence interval or real-world range |

The multi-seed design uses 100 initial seeds per scenario, four configurable local workers, and can
extend in configured batches up to 150 when the maximum monitored Monte Carlo standard error is
above tolerance. Each child stores its
configuration, metric payload, SHA-256 values, source commit, seed, and immutable marker. The
parent inventories every child manifest, so a missing, added, or changed seed is detected. The
simulation structure and Monte Carlo error reporting follow the ADEMP-style principles described by
[Morris, White, and Crowther](https://pmc.ncbi.nlm.nih.gov/articles/PMC6492164/) and the need to report
simulation error separately from method performance described by
[Koehler, Brown, and Haneuse](https://pmc.ncbi.nlm.nih.gov/articles/PMC3337209/).

Low/base/high are coherent engineering bundles along one `care_pathway_friction` axis. They change
access, referral, initiation, refill-gap, follow-up, and missingness assumptions in a consistent
direction. They are marked `NOT YET VALIDATED` and `REQUIRES SME REVIEW`; they are not sourced
clinical parameters or market forecasts.

## Time-to-event and competing-risk methods

The endpoint configuration is
[`configs/event_hierarchy.yaml`](../configs/event_hierarchy.yaml). It covers initiation,
discontinuation, switch, restart, progression, hospitalization, death, loss to follow-up,
administrative end, and the analysis horizon.

For each configured endpoint, the implementation:

1. selects the declared population and time zero;
2. limits events to the declared horizon;
3. selects the first date and then the configured event priority for calendar-day ties;
4. records the target, competing, and censor counts separately;
5. reconciles the exact number at risk before and after every event time;
6. estimates Kaplan–Meier net target-event survival with Greenwood log-log pointwise bands;
7. estimates Aalen–Johansen cumulative incidence for the target and configured competing causes.

Death is a competing event whenever it prevents the event of interest; it is not silently treated as
ordinary censoring. `1 - Kaplan–Meier` is not presented as absolute risk when competing events exist.
The distinction and use of cumulative incidence/Aalen–Johansen are consistent with modern
[competing-risk guidance](https://pmc.ncbi.nlm.nih.gov/articles/PMC13007359/). Cause-specific models
are not fitted because no current approved question requires a covariate-adjusted cause-specific
hazard interpretation.

Calendar-day data cannot establish within-day clinical order. The configured death-first tie rule is
a conservative engineering proposal that requires oncology, RWE, and biostatistics approval.

## Missing-data truth recovery

A separate generation run sets configured missingness to zero and retains complete pre-missingness
PSA plus the synthetic mechanism drivers. Repeated masks then apply:

- the existing configured mechanism;
- MCAR with constant probability;
- MAR using observed synthetic market, access, and comorbidity drivers;
- MNAR using the unobserved complete synthetic PSA value.

Complete-case estimates are always compared with known truth. Oracle inverse-probability weighting
is shown only where mask probabilities are known and the mechanism is not MNAR; it is an evaluation
device, not proof that MAR is plausible in practice. MNAR uses a configurable delta grid for
tipping-point sensitivity. Outputs report bias, RMSE, interval coverage, effective sample size,
realized missingness, and failures. Delta-adjusted single imputation is sensitivity analysis only;
its simple interval does not represent full multiple-imputation uncertainty.

The role of explicit MNAR assumptions and tipping-point analysis is described in
[Cro et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC8479366/). No real-data missingness strategy is
selected by this synthetic experiment.

## Synthetic utility and realism

No universal realism score is produced. Separate rows evaluate structural schema, keys, temporal
validity, state transitions, configured marginal and conditional directions, longitudinal patterns,
analytical-task feasibility, impossible journeys, rare combinations, and accidental source-row
cloning. A `PASS` means only that an internal synthetic engineering rule passed.

Real-versus-synthetic fidelity, train-synthetic/test-real, nearest-neighbour disclosure,
membership-inference, and attribute-inference hooks are specified in
[`contracts/real_data_evaluation_hooks.yaml`](../contracts/real_data_evaluation_hooks.yaml) and remain
`BLOCKED` until governed comparison data and the named privacy, security, data-owner, RWE,
biostatistics, and model-risk approvals exist.

## Output contract

Every chart-ready CSV includes: numerator, denominator, population definition, time zero, horizon,
scenario, seed summary, release, assumptions, limitation, and a synthetic-data flag. Scientific and
simulation packages are fresh-path-only and sealed by a manifest plus SHA-256 marker. Frontend JSON
uses strict JSON values and keeps estimator, regeneration, and scenario uncertainty visibly separate.

Run the components with:

```powershell
uv run --frozen --extra dev python -m prostate_journey.cli scientific-evidence
uv run --frozen --extra dev python -m prostate_journey.cli simulation-study
```

## Approval questions still open

- Is each population, time zero, endpoint, horizon, competing event, censoring event, and same-day
  priority clinically and operationally appropriate for the approved intended use?
- Are the persistence, discontinuation, switch, restart, progression, and hospitalization
  definitions recoverable from the governed source?
- Which estimators and sensitivity analyses belong in the approved protocol/SAP?
- Which missingness mechanisms and delta range are plausible after source-data diagnostics?
- Which real-data utility, privacy-risk, transportability, subgroup, and harm thresholds apply?

Until those questions have named approvals and evidence, the result is suitable only for an
internal, non-operational scientific sandbox.
