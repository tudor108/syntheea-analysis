# Changelog

All notable source changes are recorded here. Generated metrics remain in versioned release
manifests and are always synthetic.

## 2.2.0-rc1 — 2026-09-05

### Added

- Machine-readable 19-table, cohort, denominator, model-population and artifact contract.
- Executable `industry-check` gates for schemas, nullability, keys, chronology, censoring,
  denominators, leakage, release hashes, KPI parity, documentation links and frontend smoke.
- Locked `uv` environment, supported Python range, MyPy gate and pre-commit configuration.
- GitHub Actions gates on Python 3.11/3.13 with a deterministic quick-pipeline integration run.
- Artifact-level EDA and presentation provenance including release, commit, config hash, code
  version, timestamp and active definitions.
- Industry-readiness crosswalk, claim register, decision/risk logs, RACI, Stage-4 criteria,
  release control, generated-artifact policy and unresolved backlog.
- Responsive aggregate-only executive frontend with analysis-tactic drill-down, dynamic headline
  context and baseline keyboard/semantic accessibility improvements.
- A 14-entry machine-readable analysis/estimand registry and a deterministic event-priority/tie
  hierarchy for initiation, discontinuation, switch, restart, progression, hospitalization, death,
  loss to follow-up and administrative end.
- Reusable Kaplan–Meier/Greenwood, exact number-at-risk and Aalen–Johansen competing-risk outputs
  for four configured synthetic endpoints.
- A batched/parallel low/base/high simulation runner with at least 100 initial seeds per scenario,
  adaptive Monte Carlo precision, release-bound immutable child/parent manifests, a complete
  child-run inventory, and sensitivity-driver tables.
- Complete pre-missingness truth recovery across existing, MCAR, MAR and MNAR masks, including
  bias, RMSE, interval coverage, ESS, failures and delta/tipping-point sensitivity.
- Separate synthetic utility dimensions and explicitly blocked real-versus-synthetic, TSTR,
  nearest-neighbour, membership-inference and attribute-inference hooks.
- An aggregate-only `scientific_story.html` methods cockpit with uncertainty tabs, endpoint
  switching, searchable tactic dialogs and strict frontend JSON.
- Four machine-readable prediction-target contracts, exact model-population attrition, nested
  train-only preprocessing/temporal calibration, repeated rolling and untouched temporal
  validation, development-only leave-one-market-out evaluation, bootstrap uncertainty,
  prevalence comparator, calibration curves, subgroup-support warnings and robustness tests.
- Responsible-AI model harms, oversight, stop-use, misuse, drift, incident/rollback and external
  validation controls, with executable disposition/alias blocking and an exact blocked
  decision-curve artifact where no approved action or threshold exists.
- A sealed aggregate-only predictive evidence package, four synchronized model cards and an
  interactive `model_story.html` Model Evidence Lab integrated into the stakeholder presentation.
- Typed local application configuration with non-overlapping working, certified, presentation,
  temporary and future-experiment namespaces.
- An aggregate-only HTTP application with release/presentation hash verification, manifest-based
  file allow-list, `/health`, `/ready`, security headers and graceful signal handling.
- A digest-pinned Python 3.11 non-root image, read-only Docker Compose service, explicit read-only
  artifact mounts and container health/readiness smoke gates.
- JSON operation logs carrying run ID, release ID, operation, status, duration and error category.
- Local runbook, environment contract, AWS target/handoff/security contract, deployment contract,
  real-data block and compact Prompt-5 implementation state.
- Four-view certified Analytics experience with a persistent synthetic trust bar, denominator
  inspector, explicit evaluability/censoring ledger, evidence drawer, governed exports, responsive
  Presentation Mode, static fallback route, and accessible report.
- Canonical, typed, machine-readable ten-tactic registry with schema/source validation and stable
  tactic IDs for the future Evidence Copilot.
- Nine-slide executive narrative with Romanian speaker notes, deterministic five-minute demo,
  six pilot-governance templates, structural accessibility gate, and eight-perspective product
  red-team review.
- Optional AI Analysis Studio on a separate local service, with one-release aggregate retrieval,
  OpenAI File Search, Responses API structured output, deterministic metric/denominator tools,
  strict citation and numerical validation, bounded sessions/cost, tactic actions, accessible
  frontend, threat model, runbook, and fail-closed adversarial tests.
- Three-mode AI Analysis Studio with Explore Tactics and Specialist Analysis; one orchestrator,
  seven expert lenses, strict `AnalysisSpec`, Luna routing, explicitly budgeted Terra method
  planning, immutable-release analytical adapters, HMAC-bound `RUN THIS ANALYSIS` confirmation,
  no-code network-denied sandbox, post-run QA, isolated manifests, aggregate export, comparisons,
  and non-promoting human-review submission.
- Centralized versioned Luna/Terra/File Search prices and bounded request profiles; atomic SQLite
  reservation/reconciliation across request, session, specialist-run, user/day, and live-eval
  budgets; strict $2 application limits; explicit transient-only retry and idempotency controls.
- AI Studio bearer/local authorization boundary, exact CORS, CSRF, rate/body/session/file/disk
  limits, safe audit IDs/redaction, cost-and-token dashboard, and expanded nine-surface
  prompt-injection protection.
- Provider-free 109-case AI evaluation suite, fixed 25-Luna/5-Terra metered suite with a strict
  below-$2 cutoff, golden and recorded-response fixtures, per-case reports, and an operator runbook.
- Final four-view AI Analysis Studio with source filtering, professional tactic catalogue,
  chat/form/spec synchronization, top-level run history, seven-day action expiry, permanent
  interactive/certified separation, locked ten-step Presentation mode, and professional failure
  states.
- Deterministic ten-frame SVG demo fallback generated from one certified release and an explicitly
  confirmed DE/FR 60-day aggregate re-run with QA, provenance, zero provider cost, and before/after
  certified-release hash verification.
- Final AI Studio user guide, demo script, security/cost note, feature flag, integration/isolation
  tests, and nine-perspective red-team report.

### Changed

- Stakeholder reports, dashboards, EDA and models now default to accepted immutable releases.
- Working-gold fallback requires explicit opt-in and remains non-authoritative.
- Persistence definition advanced to `PERSISTENCE-SYN-v2.2` consistently across configuration,
  generation, quality controls and evidence.
- Release wording now states `CANDIDATE — INTERNAL SYNTHETIC CONTRACT PASSED` and explicitly denies
  Bayer approval or regulatory/clinical/production compliance.
- Release QA now runs formatting, Ruff, MyPy, data-contract checks and pytest.
- Scientific evidence and simulation packages are fresh-path-only, hash sealed, and validated by
  executable industry gates without combining estimator, regeneration and scenario uncertainty.
- Predictive evidence is fresh-path-only and hash sealed; presentation and industry gates require
  an exact clean release-source commit, nested-fit proof, zero leakage failures, non-deployable
  dispositions and aggregate-only artifacts.
- Restart-after-gap ascertainment now requires an explicit dated restart inside the declared
  365-day horizon or complete no-restart observation through that horizon; undated and
  early-censored statuses are excluded and counted.
- Prevalence robustness now changes observed event odds through documented outcome-stratified
  resampling; it no longer mislabels a prediction-intercept perturbation as a prevalence shift.
- Mutable CLI outputs now fail when they overlap the certified release namespace, while the local
  service serves only release-matched aggregate files and treats future experiments as untrusted.
- The former Google Cloud target is explicitly superseded; AWS is documented only as a proposed
  handoff and no cloud operation is performed by the application or test suite.
- CI now checks the frozen lock/dependency graph, common secret formats, local documentation links,
  container build/liveness and health-versus-readiness behavior.
- Frontend styles and behavior are packaged as versioned CSS/JavaScript assets; presentation
  provenance now includes an independently downloadable evidence manifest.

### Removed from source control

- Stale generated gold tables, reports, EDA/model outputs, extension outputs and bundled archives.
  Local copies were not deleted; future outputs are stored as ignored release artifacts.

### Known limitations

- No real data, clinical/RWE approval, external model validation, privacy/security authorization,
  AWS deployment, independent vulnerability/SBOM approval, operational load evidence or WCAG
  conformance audit exists.
- MyPy covers production `src`; scoped pandas-stubs exceptions and untyped EDA remain backlog work.

## 2.1.0 — 2026-08-25

- Established the prior deterministic synthetic release, independent reconciliation, QA evidence
  archives, longitudinal EDA and exploratory predictive baselines.
