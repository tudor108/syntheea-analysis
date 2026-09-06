# Prompt 2 — scientific implementation status

> Synthetic-data engineering evidence only. No result in this project is a real patient outcome,
> treatment gap, persistence rate, market estimate, clinical finding, causal result,
> comparative-effectiveness result, or Bayer insight.

## Implemented in source

- A 14-entry machine-readable registry covers the current frontend tactics and four predictive
  targets, with explicit populations, denominators, time zero, horizons, events, assumptions,
  required variables, sensitivities, boundaries, and honest review statuses.
- A configurable low/base/high multi-seed runner starts at 100 seeds per scenario, supports batching
  and parallel workers, adaptively extends on Monte Carlo error, and seals every child and parent
  artifact with release/configuration/source identity and SHA-256 evidence. The parent inventories
  every child, so a missing, added, or changed seed fails verification.
- Estimator uncertainty, same-assumption regeneration variation, and changed-assumption scenario
  variation have separate tables and labels.
- Kaplan–Meier, Greenwood log-log pointwise bands, censor/event counts, exact risk tables, and
  Aalen–Johansen cumulative incidence are reusable across four configured endpoints.
- Complete pre-missingness truth, existing/MCAR/MAR/MNAR masking, complete-case and justified oracle
  weighting examples, MNAR delta sensitivity, bias, RMSE, coverage, ESS, and failure reporting are
  implemented.
- Synthetic utility is reported by dimension; governed real-data fidelity, TSTR, nearest-neighbour,
  membership-inference, and attribute-inference work is explicitly `BLOCKED`.
- Scientific aggregate JSON/CSV is ready for the interactive presentation layer.

## Current evidence state

Targeted scientific tests pass. The full repository gate, 100-seed-per-scenario execution, final
v2.2 candidate, release-locked scientific package, and browser review are intentionally reserved for
the final verification step requested by the project owner. Final numeric results and exact artifact
paths will be added to the handoff after that run.

## Stage-4 decision

`CONDITIONAL GO` applies only to begin a time-boxed internal scientific sandbox. It is `NO-GO` for a
real-data pilot, production, clinical use, commercial decisions, or external claims until intended
use, protocol/SAP, clinical/RWE/biostatistics definitions, governed real data, privacy/security,
model-risk, accessibility, and independent validation requirements are approved.
