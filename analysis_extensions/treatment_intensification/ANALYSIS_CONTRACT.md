# mHSPC Treatment Intensification Analysis Contract

## Status and Purpose

**Status: IMPLEMENTED AND VALIDATED.**

This contract defines a rigorous, descriptive analysis of synthetic mHSPC treatment intensification. It is an isolated extension built on the governed EDA workflow on `dev`. It does not change cohort definitions, treatment logic, generation logic, or existing analytical outputs.

## Population and Denominator

- **Primary pathway:** `mhspc_mcspc`.
- Reuse the existing governed cohort flags from `eda/02_cohort_engine.py`.
- Use the governed mHSPC cohort membership and eligibility flags; do not independently recreate eligibility or observability.
- Use the existing `cohort_index_date` as the index. For this pathway, that is the governed eligibility date when available, with the existing mHSPC state-date fallback.
- For each 30-, 60-, and 90-day landmark, include only governed eligible patients who are evaluable under the existing `observable_for_30d`, `observable_for_60d`, or `observable_for_90d` rule.
- Use the existing censor date: the earliest governed death, loss-to-follow-up, or administrative observation boundary. No event after censor is observable.

The evaluable denominator is therefore the governed eligible mHSPC population with sufficient follow-up to the selected landmark. Eligibility and observability are not redefined by this analysis.

## Treatment Concepts

### Any Treatment Initiation

Any treatment initiation is the existing normalized treatment initiation after the governed cohort index:

- identify the earliest linked `treatment_episode.treatment_start_date` on or after `cohort_index_date`;
- use the existing cohort initiation fields and censor-aware 30/60/90-day logic;
- do not replace or recalculate the governed initiation denominator independently.

### Synthetic Treatment Intensification

For this synthetic mHSPC contract, **scenario-supported intensification** means that a qualifying treatment component is added to the ADT backbone:

- qualifying `treatment_regimen_component.drug_class` is `ARPI` or `chemotherapy`;
- the component is linked through `regimen_id` and `treatment_episode_id` to the patient and normalized treatment episode;
- ADT monotherapy is not intensified;
- this is a synthetic analytical rule, not a real-world clinical guideline or recommendation.

The regimen-level `treatment_regimen.intensification_flag` is a reconciliation and consistency field. It must not be the sole source of intensification timing or status.

## Intensification Timing

Define `first_intensification_date` as the earliest qualifying linked component date that satisfies all of the following:

1. `component_start_date >= cohort_index_date`;
2. `drug_class` is `ARPI` or `chemotherapy`;
3. the component is within the governed observation period, with `component_start_date <= censor_date`;
4. the component's treatment episode is validly linked and its `treatment_start_date` is on or before the component start date;
5. the patient has a qualifying normalized treatment initiation after the index.

This component-derived date is required because add-on therapy can begin after the treatment episode starts. It must not be inferred only from `treatment_regimen.intensification_flag`.

For each landmark, a patient is intensified when `first_intensification_date` is on or before `cohort_index_date + landmark days` and the patient is governed as evaluable for that landmark.

## Landmark States

At each 30-, 60-, and 90-day landmark, classify every evaluable eligible patient into exactly one state, in this precedence order:

- **`UNTREATED`:** no qualifying treatment initiation by the landmark.
- **`TREATED_NOT_INTENSIFIED`:** treatment was initiated by the landmark, but no qualifying ARPI or chemotherapy component had started by the landmark.
- **`INTENSIFIED`:** a qualifying ARPI and/or chemotherapy component had started by the landmark.

The states are mutually exclusive and exhaustive for the evaluable denominator. A qualifying intensification cannot exist without treatment initiation.

## Primary Outputs and KPIs

Produce the following overall metrics for each landmark: 30, 60, and 90 days.

- evaluable eligible N;
- any-treatment initiation N and rate, using the existing governed initiation fields;
- intensified N and rate;
- treated-but-not-intensified N and rate;
- untreated N and rate;
- median and IQR days from cohort index to `first_intensification_date`, among patients with an observable intensification date;
- median and IQR days from first treatment start to intensification among patients with delayed add-on intensification, where `first_intensification_date > first treatment start date`.

Rates use the evaluable eligible N as denominator unless explicitly labeled otherwise. Timing summaries must state their applicable observed-event denominator.

## Reconciliation and Validation Requirements

The implementation must fail validation or clearly report the issue when any of these conditions is violated:

- `first_intensification_date` precedes the governed cohort index;
- `first_intensification_date` precedes the corresponding treatment episode start;
- `first_intensification_date` occurs after censoring;
- an intensified patient is not also treatment-initiated;
- `UNTREATED + TREATED_NOT_INTENSIFIED + INTENSIFIED` does not equal the evaluable denominator at any landmark;
- existing any-treatment counts do not reconcile with the governed cohort and funnel outputs;
- component-to-regimen, component-to-episode, or component-to-patient lineage is invalid;
- component-derived intensification status disagrees with regimen-level `intensification_flag`.

Component-derived status is authoritative for this analysis's timing rule, but mismatches with the regimen flag must be reported for review. The data must not be silently corrected.

Additional checks should confirm that landmark states are monotonic in the expected direction: a patient cannot move from `INTENSIFIED` back to `TREATED_NOT_INTENSIFIED` or `UNTREATED` at a later landmark.

## Initial Segmentation

Keep the first implementation limited to interpretable segments:

- overall;
- market;
- initial care setting.

Do not introduce a large subgroup catalogue before the core contract reconciles successfully.

## Analytical Guardrails

- Data are synthetic only.
- Results are exploratory and descriptive.
- No causal claims.
- No clinical recommendations.
- No real-world market-size claims.
- No invented financial value or financial impact.
- Use `synthetic intensification` or `scenario-supported intensification` where needed; do not present this rule as authoritative clinical guidance.
- Keep results aligned with governed cohort definitions, existing initiation fields, and censoring rules.

## Implementation and Output Structure

The implementation uses this structure:

```text
analysis_extensions/treatment_intensification/
    ANALYSIS_CONTRACT.md
    README.md
    treatment_intensification_analysis.py
    outputs/                                  # generated outputs
```

The implementation and generated aggregate outputs are maintained under this directory. The analytical definitions and guardrails above remain the governing contract.
