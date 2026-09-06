# AI Analysis Studio handoff

**Status:** final four-view product experience and deterministic presentation package implemented; live acceptance is reported separately  
**Parent evidence release:** `BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z`  
**Data status:** synthetic scenario data and aggregate outputs only  
**Certification effect:** none

## Product boundary

AI Analysis Studio is an optional service on port 8090. Deterministic Analytics remains an
independent service on port 8080. The Studio has four visibly separate modes:

1. **Ask the Evidence** explains one certified, aggregate-only evidence catalogue. It is read-only.
2. **Explore Tactics** browses the ten canonical tactic contracts at three disclosure levels.
3. **Specialist Analysis** prepares and executes explicitly confirmed synthetic experiments in an
   isolated experiment namespace.
4. **Run History** separates completed re-runs, proposed analyses, failures, review submissions,
   and expired runs without inserting them into certified Analytics.

An interactive run cannot overwrite the parent release, presentation package, source tables,
canonical tactic card, official KPI, or production configuration. It cannot become certified by
being exported or submitted for review. No patient-level export exists.

## Implementation map

| Responsibility | Path |
|---|---|
| Shared AI Studio service and run settings | `configs/ai_studio.yaml`, `src/prostate_journey/ai_studio_config.py` |
| Versioned prices, request envelopes, budgets, and security limits | `configs/ai_cost_controls.yaml`, `src/prostate_journey/ai_finops.py` |
| Central provider client, retry policy, idempotency, and cache keys | `src/prostate_journey/ai_client.py` |
| Seven selectable expert lenses | `configs/expert_lenses.yaml` |
| Strict request, specification, preview, QA, run, and review contracts | `src/prostate_journey/specialist_contracts.py` |
| Luna request routing and Terra method-planning boundary | `src/prostate_journey/specialist_openai.py` |
| One controlled state-machine orchestrator | `src/prostate_journey/specialist_orchestrator.py` |
| Sixteen allow-listed server-side analysis tools | `src/prostate_journey/specialist_tools.py` |
| Fixed no-code isolated worker and parent controls | `src/prostate_journey/specialist_worker.py`, `src/prostate_journey/specialist_sandbox.py` |
| HTTP API, atomic SQLite budget ledger, CSRF/auth/CORS/rate boundaries, and confirmation state | `src/prostate_journey/ai_studio.py` |
| Four-view accessible frontend and presentation mode | `src/prostate_journey/frontend/ai_studio.html`, `ai_studio.css`, `ai_studio.js` |
| Deterministic ten-frame static demo fallback | `src/prostate_journey/ai_demo.py`, `outputs/experiments/ai_studio/demo_fallback/` |
| Specialist regression and abuse suite | `tests/test_specialist_analysis.py` |
| Offline/live evaluation runners and golden/adversarial fixtures | `src/prostate_journey/ai_evaluation.py`, `configs/ai_evaluation.yaml`, `tests/fixtures/` |
| FinOps/security/evaluation operations | `docs/AI_FINOPS_SECURITY_EVALUATION_RUNBOOK.md` |
| Final demo, user, security/cost, and red-team guidance | `docs/AI_STUDIO_DEMO_SCRIPT.md`, `docs/AI_STUDIO_USER_GUIDE.md`, `docs/AI_STUDIO_SECURITY_AND_COST.md`, `docs/AI_STUDIO_RED_TEAM_REPORT.md` |

The canonical tactic metadata remains `configs/tactic_registry.yaml`. The analytical definitions
remain `contracts/analysis_registry.yaml`. The current certified release resolver and evidence
catalogue remain in `src/prostate_journey/release_integrity.py` and
`src/prostate_journey/ai_artifact_catalog.py`.

## Controlled workflow

Every executable request uses this fixed order:

`UNDERSTAND → RETRIEVE → SELECT EXPERT LENS → CREATE ANALYSIS SPEC → VALIDATE → ESTIMATE COST → PREVIEW PARAMETER DIFF → PREVIEW DENOMINATOR → USER CONFIRMATION → EXECUTE → QA → INTERPRET → EXPORT OR SUBMIT FOR REVIEW`

Validation, cost estimation, exact parameter diff, denominator preview, explicit confirmation,
and post-run QA cannot be skipped. Confirmation is bound to the SHA-256 of the complete validated
specification with an in-memory HMAC token. A changed specification or replayed token is rejected.
The browser must submit the exact action `RUN THIS ANALYSIS`.

The request router returns exactly one of:

- `artifact_question`;
- `explain_tactic`;
- `recommend_tactic`;
- `modify_existing_tactic`;
- `compare_existing_results`;
- `propose_new_analysis`;
- `execute_approved_analysis`;
- `prohibited_request`;
- `insufficient_evidence`.

## Expert lenses and model routing

One orchestrator exposes seven lenses: RWE & Epidemiology, Biostatistics, Oncology Definition
Review, Missing-Data Analysis, Predictive Modelling, Data Quality, and Market Scenario Analysis.
Lenses add checks and framing; they do not create independent agents, credentials, evidence stores,
or execution authority.

- `gpt-5.6-luna` may classify a request, recommend a tactic, extract allow-listed parameters, and
  produce bounded summaries. Its output remains subject to deterministic validation.
- `gpt-5.6-terra` with reasoning effort `medium` is available only after a user explicitly requests
  a proposed specialist method and accepts the displayed planning-cost ceiling.
- Terra does not calculate results, access the analytical dataset, execute tools, use web search,
  or alter the denominator, time zero, outcome, event hierarchy, release, or prohibited uses.
- Deterministic local Python performs registered calculations. The application has no GPT-6
  runtime dependency and no external web-search capability.

If provider routing fails, the deterministic classifier is identified as the routing source. A
new specialist method cannot proceed without its required, explicitly budgeted plan.

## AnalysisSpec contract

Execution requires a strict, extra-fields-forbidden `AnalysisSpec` containing request and parent
release IDs; analysis name; existing tactic or new-proposal status; expert lens; research question;
analysis type; target population; eligibility and exclusions; numerator and denominator;
index/time zero; outcome; observation window; competing and censoring events; markets; subgroups;
initiation window; persistence gap; scenario; seeds; missingness strategy; analytical method;
assumptions; parameters; expected outputs; validation checks; required source fields; prohibited
interpretations; and SME-review requirements.

The server rejects incomplete contracts, unsupported markets, unknown parameters, 45-day windows,
mixed `ALL` and individual markets, care-setting analyses outside the available 90-day aggregate,
and browse-only tactics without a release-matched execution adapter.

## Server-side tool surface

Only these specialist tools exist:

- `list_tactics`
- `get_tactic_contract`
- `recommend_tactics`
- `get_allowed_parameters`
- `validate_analysis_spec`
- `estimate_analysis_cost`
- `preview_population`
- `preview_denominator`
- `run_registered_analysis`
- `run_sandbox_analysis`
- `get_run_status`
- `get_run_manifest`
- `get_run_results`
- `compare_runs`
- `export_interactive_result`
- `submit_run_for_review`

There is no unrestricted shell, filesystem, SQL, Python, source-control, certification, deployment,
web-search, or patient action tool.

## Registered execution and isolation

Supported registered reruns call the existing functions in
`src/prostate_journey/healthcare_analysis.py` after explicit confirmation. The service reads the
parent release's immutable `patient_journey.parquet` or `referral.parquet` snapshot, records the
input file SHA-256 and size, and writes no data beside those files. Patient rows are never included
in prompts, browser responses, manifests, logs, or exports.

The current adapters support:

- cohort definition by configured synthetic market;
- 30/60/90-day initiation;
- 12-month censoring/evaluability;
- 30/60/90-day persistence-gap sensitivity;
- time-to-initiation landmarks;
- referral completion;
- market or 90-day initial-care-setting segmentation;
- configured aggregate missingness fields.

`model_disposition` and `evidence_governance` remain browseable but are not interactively rerunnable
because the parent v2.1 package has no release-matched model result adapter for this service.

Each run receives a new `iar_<20 hex>` directory below
`outputs/experiments/ai_studio/interactive_runs/`. The run contains the immutable specification,
parameter diff, aggregate results, QA report, and manifest. It records run and request IDs, parent
release, hashes, user request, lens, code identity, input snapshot, output files, QA, provider cost,
times, workflow, limitations, synthetic status, and prohibited use.

## Proposed-method sandbox

A proposed method is always labelled `PROPOSED UNVERIFIED ANALYSIS`, `PROPOSED METHOD`, and
`REQUIRES SME REVIEW`. Terra can plan it, but cannot generate executable code. Execution accepts
only a fixed declarative aggregate market-summary operation over a sanitized aggregate snapshot.

The worker runs in a separate isolated Python process with:

- no user code, SQL, package import, arbitrary path, or operation name;
- network constructors blocked and proxy bypass disabled;
- read-only bounded JSON input;
- wall-clock timeout and CPU, memory, input, and output ceilings;
- a fixed aggregate result schema;
- termination on timeout or invalid output.

Generated code is never merged because generated code is never accepted. A proposal can reach
certification only through a separately authorized implementation, independent review, tests,
documentation, pull request, and new release.

## QA, badges, export, and review

Post-run QA checks population count, numerator/denominator bounds, duplicate aggregate keys,
missing required values, registered chronology, filter/window compatibility, exact reconciliation
to the preview, aggregate-only schema, and synthetic/release status. Any failed check produces
`ANALYSIS FAILED VALIDATION`; interpretation, export, and review submission are suppressed.

The status vocabulary is:

- `CERTIFIED EVIDENCE` only for unchanged parent evidence in Ask Evidence;
- `INTERACTIVE RE-RUN`;
- `PROPOSED METHOD`;
- `FAILED VALIDATION`;
- `REQUIRES SME REVIEW`;
- `SUBMITTED FOR REVIEW`.

Interactive manifests never use `CERTIFIED`. Aggregate CSV exports repeat run ID, badge, synthetic
status, parent release, active market/subgroup, numerator, denominator, rate, population, window,
method, generated time, and prohibited use. Submission creates a separate human-review record with
`certification_changed: false`; it does not mutate the run manifest or parent release.

## Prompt 8 FinOps, reliability, security, and evaluation controls

`configs/ai_cost_controls.yaml` is the sole pricing and budget source. It records model input,
cached-input, cache-write, output, File Search, disabled-tool prices, source, effective date, and a
1.20 reservation margin. Luna remains the default; Terra remains behind the specialist gate. There
is no premium fallback, web search, Code Interpreter, recursive agent loop, or SDK-managed retry.

Each provider-backed operation reserves its profile maximum in a SQLite `BEGIN IMMEDIATE`
transaction before File Search/model use. The ledger atomically applies request, $2 session, $0.55
specialist-run, $5 authenticated-user/day, and strictly-below-$2 live-evaluation limits. It
reconciles returned token/cache/tool usage and releases unused funds. Unknown partial failures keep
the conservative reservation. Stable provider idempotency keys prevent duplicate charging and the
one-use run confirmation prevents duplicate execution.

The service adds exact CORS, CSRF, loopback-or-bearer authentication, rate limiting, 64 KB bodies,
30-minute sessions, artifact and sandbox disk ceilings, request IDs, hashed session audit identity,
and allow-listed/redacted audit fields. The browser Cost & usage drawer and `/api/cost` expose
charged/reserved/remaining budget, model/token/cache/tool totals, latency, and thresholds without
prompt or secret content.

Evaluation inputs are versioned in `configs/ai_evaluation.yaml` and `tests/fixtures/`. Offline CI
replays deterministic tools, recorded provider failures, all tactics/KPIs, specialist routing,
refusals, and injection vectors from user, Markdown, JSON, CSV, HTML, tactic, tool, filename, and
metadata surfaces. The fixed live suite is 25 Luna evidence questions plus five Terra planning
requests and at most 35 File Search calls. It writes every case and failure; it cannot issue a
request whose reservation would reach the $2 live hard stop.

Operational details and incident handling are in
`docs/AI_FINOPS_SECURITY_EVALUATION_RUNBOOK.md`. The latest evidence summary is in
`docs/AI_EVALUATION_REPORT.md`; only a complete, real metered PASS may satisfy the live-cost
criterion.

## API and local operation

Principal endpoints are:

- `GET /api/specialist/context`
- `GET /api/specialist/tactics/{tactic_id}`
- `POST /api/specialist/preview`
- `POST /api/specialist/plan`
- `POST /api/specialist/execute`
- `GET /api/specialist/runs`
- `GET /api/specialist/runs/{run_id}`
- `GET /api/specialist/runs/{run_id}/export`
- `POST /api/specialist/compare`
- `POST /api/specialist/submit`

Run locally:

```powershell
uv run --extra ai prostate-journey ai-catalogue
uv run --extra ai prostate-journey ai-check
uv run --extra ai prostate-journey ai-specialist-check
uv run --extra ai prostate-journey ai-offline-eval
# Explicit, metered, fixed suite; aborts safely below $2
uv run --extra ai prostate-journey ai-live-eval
uv run --extra ai prostate-journey ai-studio
```

Open `http://127.0.0.1:8090/`. Use Explore Tactics for contracts. In Specialist Analysis, choose a
lens and registered tactic, describe a permitted change, inspect the complete preview, and click
`RUN THIS ANALYSIS`. For a genuinely new question, select the proposed-method option, inspect and
accept the Terra planning ceiling, review the returned specification, and only then run the bounded
sandbox operation.

## Verification and unresolved risks

Automated checks cover strict schemas, all nine request modes, seven lenses, Luna routing, parameter
extraction, incompatible parameters, denominator preview, confirmation tampering/replay, output
isolation, manifest completeness, network denial, timeout enforcement, QA suppression, aggregate
export, run comparison, non-promoting review submission, unchanged release hashes, frontend labels,
accessibility structure, and separate HTTP preview/execute actions.

### Verification evidence — 2026-09-06

- full repository suite: `152 passed`;
- focused AI Studio, specialist, FinOps, and prompt-injection inventory: `55 tests`, all included
  in the passing full suite;
- Ruff formatting and lint: `108 files` checked, no findings;
- MyPy: `62 source files` checked, no findings;
- AI Studio structural accessibility check: passed;
- JavaScript syntax check for `ai_studio.js`: passed;
- secret scan and local Markdown-link check: passed;
- approved local evidence catalogue verified: `51` artifacts, `50` indexable, no patient-level
  artifacts. Remote vector search is fail-closed because the previous store hash is stale after the
  documentation updates; local allow-listed retrieval remains available;
- industry-readiness gate: `16 PASS`, `0 FAIL`, `1 intentionally skipped`;
- runtime contract: `10 tactics`, `7 lenses`, `16 allowlisted tools`, and `13 workflow states`;
- offline AI evaluation: `109 / 109 PASS`, zero provider requests and `$0.00` provider cost;
- deterministic demo fallback: ten valid SVG frames and one explicitly confirmed DE/FR 60-day
  run, QA `PASS`, provider cost `$0.000000`, with identical certified hashes before and after;
- most complete live evaluation: 25 Luna attempts and one Terra attempt; three Luna cases passed,
  the remaining streams did not return final usage, and Terra returned
  `budget_or_quota_exhausted`. Known metered cost was `$0.001986`; the fail-closed ledger charged
  `$0.227826`, below the `$2.00` hard stop. The live acceptance criterion remains failed until a
  complete 30-case run passes with a rotated, quota-enabled key;
- browser automation could not run because no browser surface was connected to the verification
  session. Structural accessibility, HTTP asset delivery, responsive CSS, and API interaction checks
  passed; manual keyboard, screen-reader, zoom, forced-colour, and device checks remain required.

The certified release was not modified. SHA-256 remained:

- `CHECKSUMS.sha256`: `A3EF3EA9D5A3B68CCD301DD5E1FD540DC8580DF04C13691108870AB4DF93BAE5`;
- `release_manifest.json`: `3AEC73A64CEA531F8C1196731D5FE35D6A7E95723E4AD3AFC56AA0F1B9E7F401`.

Before shared or production use:

- revoke and rotate any development key exposed through chat or another shared channel;
- complete a fresh 25-Luna/5-Terra live evaluation with working provider quota; do not use the
  current partial run as acceptance evidence;
- complete manual keyboard, screen-reader, responsive, zoom, and forced-colour testing;
- replace the local/bearer gate with organization identity and role-based authorization, and add
  managed secrets, distributed concurrency controls, retention policy, private networking, provider
  spend alerts, and production monitoring; the local service already enforces CSRF, exact CORS,
  process-local rate limits, and a redacted append-only audit stream;
- obtain independent security, privacy, RWE, biostatistics, oncology, accessibility, responsible-AI,
  and Bayer workflow-owner approval;
- create a clean v2.2 release with release-matched uncertainty and predictive evidence.

The current decision is **CONDITIONAL GO for a local synthetic demonstration and expert review**.
It is **NO-GO for Bayer deployment, real-world data, patient data, clinical use, production use, or
certification of any interactive result**.
