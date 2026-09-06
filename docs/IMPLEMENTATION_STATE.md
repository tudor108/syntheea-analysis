# Compact implementation state

**Updated:** 5 September 2026  
**Current decision:** CONDITIONAL GO for a provider-free local synthetic demonstration; NO-GO for any
real-data, clinical, Bayer, production, or certified use. A shared demonstration remains
conditional on credential rotation, access control, and independent review. This is not Stage-4,
clinical, RWE, production, or Bayer approval.

## Current product

The stakeholder application resolves exactly one accepted immutable release and builds an
aggregate-only presentation package. The active release is
`BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z`, with 10,000 synthetic records,
seven configured scenarios, 2,281 eligible records, 1,700 initiators by day 90, 1,614 evaluable
12-month initiators, 941 meeting the operational 60-day-gap persistence definition, and 86
censored before that persistence horizon.

The release is historical v2.1 evidence. Its manifest warns that it was generated from a dirty
analysis worktree and uses legacy decision wording. The application exposes those warnings; it
does not reinterpret them as approval.

## Architecture

1. `prostate-journey presentation-package` reads one accepted release and never silently falls
   back to mutable `data/gold`.
2. `executive_story.html` provides Executive, Analyst, Methodology, and Governance views from one
   embedded aggregate payload and the canonical tactic registry.
3. `prostate-journey serve` verifies release and presentation hashes, serves only allow-listed
   aggregate files, and exposes `/health` and `/ready`.
4. Optional AI Analysis Studio is isolated on port 8090. No OpenAI package, key, call, vector
   store, or AI output is required by deterministic Analytics on port 8080.
5. Specialist runs read one immutable synthetic release after confirmation and write only below
   `outputs/experiments/ai_studio/interactive_runs/`; no patient rows are returned or exported.
6. AWS remains a documented handoff only. No cloud deployment was performed.

## Implemented in Prompt 5

- persistent synthetic trust bar with release, scenario, cohort, denominator, initiation window,
  persistence gap, analytical status, and Reset to Certified View;
- denominator-first KPI contracts, live denominator-change announcement, Denominator Inspector,
  nested cohort ledger, separate evaluability and censoring counts;
- responsive four-view product with progressive disclosure and deterministic Presentation Mode;
- ten versioned tactics in `configs/tactic_registry.yaml`, validated by typed Pydantic schema and
  consumed by both the builder and generated `tactic_registry.json`;
- appropriate aggregate visuals: denominator ledger, attrition bars, proportion dots, market
  comparison table/dots, missingness heatmap/table, transition summary, and honest model disposition;
- release-matched evidence drawer, pilot-hypothesis template, aggregate CSV, accessible report,
  evidence manifest, presentation PNG, print/PDF, and shareable filter-state controls;
- no patient-level export, clinical recommendation, market ranking, causal claim, AI confidence
  score, chatbot, specialist agent, or OpenAI dependency;
- nine-part executive presentation narrative, Romanian speaker notes, deterministic five-minute
  demo, four static fallback visuals, six pilot-governance templates, accessibility report, and
  adversarial red-team review.

## Implemented in Prompt 6

- separate `Ask the Evidence` HTTP/SSE service and accessible frontend with persistent synthetic,
  release, scenario, evidence-count, model, session-cost, and prohibited-use context;
- explicit 46-artifact catalogue with 45 indexable entries, one active release, SHA-256
  verification, stable artifact IDs, and hard exclusions for patient-level, raw, gold, archive,
  experiment, secret, code, Parquet, DuckDB, and stale-release content;
- OpenAI File Search release partition plus local narrative fallback; the remote store contains
  45/45 approved artifacts, expires after seven days, and records no patient-level content;
- ten strict deterministic tools for metrics, denominators, tactics, release context, comparisons,
  bounded sections, and retrieval—without arbitrary paths, SQL, shell, source writes, or web search;
- Responses API structured output using configurable `gpt-5.6-luna`, low reasoning/verbosity,
  bounded top-k, tokens, recent turns, summary, timeout, visible estimated cost, and session budget;
- fail-closed post-validation: quantitative prose may use only numbers returned by deterministic
  metric tools, and citations may reference only active packet artifact IDs;
- canonical ten-tactic actions, market context, source drawer, loading/error states, keyboard
  labels, responsive reflow, reduced motion, strict CSP, and structural accessibility checks;
- server-side-only `SecretStr` credential loading from environment or ignored local `.env`;
- golden, scope, stale-release, injection, hallucinated-number, secret, outage, health, and
  independent-service tests, plus implementation handoff, runbook, and threat model.

## Implemented in Prompt 7

- the original three Studio views—Ask Evidence, Explore Tactics, and Specialist Analysis—under a
  persistent synthetic/release trust boundary; the final product extension adds Run History;
- one controlled orchestrator with the exact 13-step state machine and nine mutually exclusive
  request modes;
- seven selectable expert lenses backed by `configs/expert_lenses.yaml`, without independent agent
  credentials, execution permissions, or evidence stores;
- strict extra-fields-forbidden `AnalysisSpec` covering the population, numerator, denominator,
  time zero, outcome, horizon, event hierarchy, markets, subgroups, parameters, method,
  assumptions, tests, source fields, prohibited interpretations, and SME review;
- bounded `gpt-5.6-luna` request classification/parameter extraction and user-initiated,
  cost-approved `gpt-5.6-terra` medium-reasoning method planning only when a registered tactic is
  insufficient; no web search or GPT-6 runtime;
- sixteen server-side tools with no shell, SQL, arbitrary Python, arbitrary path, source-control,
  deployment, certification, or patient-action interface;
- exact parameter diff and denominator preview before execution, including population, exclusions,
  time zero, evaluability, and censoring;
- one-use HMAC confirmation bound to the validated spec and the exact `RUN THIS ANALYSIS` action;
- post-confirmation calls to existing healthcare-analysis functions over hash-identified, read-only
  immutable-release Parquet snapshots; rows never reach OpenAI, the browser, logs, or exports;
- fixed no-code declarative custom-analysis worker with sanitized aggregate input, network denial,
  isolated interpreter, timeout, CPU/memory/input/output limits, and no generated-code merge path;
- isolated run folders with spec, diff, aggregate results, QA, code/input hashes, cost, workflow,
  limitations, provenance, comparison, aggregate CSV, and non-promoting human-review submission;
- QA fail-closed behavior: failed population, arithmetic, duplicates, missingness, chronology,
  filter/window, reconciliation, schema, patient-output, or synthetic-status checks suppress
  interpretation, export, and review submission;
- badges that keep parent `CERTIFIED EVIDENCE` separate from `INTERACTIVE RE-RUN`, `PROPOSED METHOD`,
  `FAILED VALIDATION`, `REQUIRES SME REVIEW`, and `SUBMITTED FOR REVIEW`.

## Implemented in Prompt 8

- one versioned pricing/budget/security contract at `configs/ai_cost_controls.yaml`, including
  effective date, official source note, Luna/Terra token and cache prices, File Search price,
  disabled tool prices, safety margin, request profiles, and all hard/soft limits;
- one hardened provider client with SDK retries disabled, at most one explicit transient retry,
  stable prompt-cache and idempotency keys, and sanitized operational failure categories;
- a WAL/full-synchronous SQLite ledger using `BEGIN IMMEDIATE` to reserve before provider/tool use
  and reconcile after metered usage across request, session, specialist-run, authenticated-user/day,
  and live-evaluation budgets;
- $1.20 session warning, $1.50 specialist soft stop, $2.00 interactive hard stop, and a strict live
  gate that rejects any reservation that would reach the $2.00 evaluation limit;
- server-side-only secrets, exact CORS, CSRF on mutating actions, loopback-or-bearer authentication,
  rate/body/session/file/sandbox limits, request/run IDs, and redacted allow-listed audit events;
- prompt-injection classification and removal across untrusted user/content/filename/metadata fields,
  plus explicit blocks for release switching, patient access, certified mutation, arbitrary tools or
  code, external transfer, fabricated Bayer evidence, and concealed denominator changes;
- a Cost & usage UI/API showing spent/reserved/remaining amounts and model, token, cache, tool,
  latency, warning, and hard-stop context;
- versioned golden, recorded-response, and nine-surface injection fixtures; a 109-case offline suite
  with no provider requests; and a fixed 25-Luna/5-Terra live runner that always writes a complete
  per-case cost/quality report and stops after a provider/budget failure;
- operator procedures in `docs/AI_FINOPS_SECURITY_EVALUATION_RUNBOOK.md` and current evidence in
  `docs/AI_EVALUATION_REPORT.md`.

## Final AI Studio experience

- one optional top-level AI Analysis Studio service with four internal views: Ask the Evidence,
  Explore Tactics, Specialist Analysis, and Run History; deterministic Analytics stays independent;
- permanent certified-versus-interactive labeling, active release/scenario/cost context, exact
  answer-status vocabulary, and aggregate/methodology/governance source filters;
- professional cards for all ten canonical tactics with seven filter dimensions and actions whose
  execution availability follows the verified adapter registry;
- synchronized natural-language interpretation, structured controls, typed `AnalysisSpec`, exact
  parameter diff, market-specific denominator preview, assumptions, limitations, cost, confirmation,
  QA, result, export, and review states;
- run-history categories, complete release/question/lens/parameter/cost/QA/output/manifest/timestamp
  details, and a default seven-day action-expiry boundary;
- `AI_ANALYSIS_STUDIO_ENABLED` service-level failure-isolation flag; when false, AI routes and
  assets do not start and the standard Analytics service remains unaffected;
- keyboard-operable four-tab navigation, labeled forms, accessible transcripts/tables/drawers,
  focus trap/restoration, live status messages, reduced motion, tablet/mobile reflow, and structural
  WCAG checks;
- locked ten-step Presentation mode with no provider requirement and a generated ten-frame SVG
  fallback at `outputs/experiments/ai_studio/demo_fallback/<release-id>/`;
- explicit deterministic fallback run `iar_4d5440a3b0944e488df6`: DE 261/385 and FR 127/222 at the
  60-day initiation landmark, QA PASS, provider cost `$0.000000`, stored outside the release;
- final guidance in `docs/AI_STUDIO_DEMO_SCRIPT.md`, `docs/AI_STUDIO_USER_GUIDE.md`,
  `docs/AI_STUDIO_SECURITY_AND_COST.md`, and `docs/AI_STUDIO_RED_TEAM_REPORT.md`.

The active historical v2.1 package has no release-matched low/base/high regenerated simulation
evidence. The UI exposes the certified scenario only and does not synthesize or silently substitute
scenario results.

## Final verification evidence — 2026-09-06

- final repository regression: `152` tests passed; `55` collected tests directly cover AI Studio,
  specialist analysis, FinOps, and prompt injection; Ruff passed on `108` files; MyPy passed on
  `62` source files;
- final provider-free evaluation: `109 / 109 PASS`, zero OpenAI requests, `$0.00` provider cost;
- final deterministic presentation fallback: ten valid SVG frames; DE 261/385 and FR 127/222 at
  day 60; QA `PASS`; provider cost `$0.000000`; certified hashes unchanged;
- controlled live evaluation did not pass: the most complete run attempted 25 Luna cases and one
  Terra case, recorded `$0.001986` known metered cost and `$0.227826` conservative ledger cost, then
  stopped below `$2.00` on stream failures and `budget_or_quota_exhausted`;
- current full-suite worst-case reservation is `$0.62340000`; atomic race, duplicate, restart,
  malformed/partial response, stale-vector, sandbox, and prompt-injection failure tests pass;
- current local AI catalogue has `51` artifacts (`50` indexable), no patient-level content; remote
  vector retrieval is deliberately unavailable until a fresh release/hash-matched store is synced;

- certified release `CHECKSUMS.sha256` remained
  `A3EF3EA9D5A3B68CCD301DD5E1FD540DC8580DF04C13691108870AB4DF93BAE5` before and after presentation
  regeneration;
- certified `release_manifest.json` remained
  `3AEC73A64CEA531F8C1196731D5FE35D6A7E95723E4AD3AFC56AA0F1B9E7F401`;

### Historical regression evidence

- 104/104 repository tests passed;
- Ruff format and lint passed across 95 files; MyPy passed across 52 source files;
- Prompt-6 File Search synchronized 45/45 allow-listed artifacts; AI readiness, frontend, CSS,
  JavaScript, deterministic tools, structural accessibility, and secret scans passed;
- a live Responses API smoke answer returned the exact day-90 result of 1,700/2,281 with two
  release-scoped evidence sources and no validation failure;
- industry source gate passed 16 checks, with zero failures and one intentional release-dependent
  skip; dependency, lock, secret, Markdown-link, JavaScript syntax, and Git whitespace gates passed;
- the strict v2.2 release-dependent industry gate reports five expected failures against historical
  v2.1: legacy persistence/lineage requirements and absent scientific, simulation, and predictive
  packages. The immutable release was not rewritten to conceal those incompatibilities;
- generated frontend structural accessibility gate passed; manual browser/assistive-technology
  sign-off remains open because no in-app browser instance was available;
- wheel inspection confirmed packaged `frontend/analytics.css` and `frontend/analytics.js`;
- Docker image `sha256:907128148215f57de3775a53f6fa8272e731ec1ffb415802643747203b214e0f`
  built; the non-root/read-only Compose service is healthy at `http://127.0.0.1:8080`;
- health, readiness, frontend, CSS, JavaScript, accessible report, demo fallback, evidence manifest,
  and aggregate CSV returned HTTP 200; internal `presentation_manifest.json` returned HTTP 404.

## Honest limitations and unresolved work

- revoke and rotate the development API key because it was exposed in chat before being moved into
  the ignored local secret file; use a budget-limited key before any further demonstration;
- build a clean v2.2 release and release-matched EDA, scientific, multi-seed, predictive, and
  presentation packages; the current frontend correctly shows model evidence as unavailable;
- complete real-browser responsive interaction testing, 200%/400% zoom, forced-colours, NVDA/JAWS,
  VoiceOver/TalkBack, and independent WCAG 2.2 AA audit;
- obtain independent oncology, RWE, biostatistical, model-risk, responsible-AI, security, privacy,
  and Bayer workflow-owner review;
- complete SBOM, vulnerability, load/capacity, account-specific infrastructure, and real-data
  source-fit-for-use work;
- review and commit the accumulated Prompt 1-7 source changes. Cloud deployment and real-data
  onboarding remain unauthorized.

## Important commands

```powershell
uv sync --frozen --extra dev
uv run prostate-journey presentation-package
uv run prostate-journey application-check
uv run prostate-journey serve
uv run ruff format --check src tests eda scripts
uv run ruff check src tests eda scripts
uv run mypy src
uv run pytest
uv run prostate-journey industry-check --allow-missing-release
uv run python scripts/check_frontend_accessibility.py outputs/presentation/<release-id>
node --check src/prostate_journey/frontend/analytics.js
docker build --tag prostate-journey-analytics:local .
docker compose up -d --force-recreate --no-build
uv sync --frozen --extra dev --extra ai
uv run --extra ai prostate-journey ai-catalogue
uv run --extra ai prostate-journey ai-check
uv run --extra ai prostate-journey ai-specialist-check
uv run --extra ai prostate-journey ai-sync-vector-store
uv run --extra ai prostate-journey ai-studio
uv run python scripts/check_ai_studio_accessibility.py
```

## Historical Prompt-6 input contract (implemented)

Prompt 6 was required to extend this product without changing its certified analytical
computations or making the core application dependent on OpenAI. The paths and invariants below
remain the audit trail used by the implementation.

### Canonical registry and release resolution

- canonical tactic registry: `configs/tactic_registry.yaml`;
- typed registry/schema validation: `src/prostate_journey/tactic_registry.py`;
- generated browser/Copilot snapshot: `outputs/presentation/<release-id>/tactic_registry.json`;
- accepted-release resolver: `src/prostate_journey/dataset_resolver.py`;
- release and presentation integrity: `src/prostate_journey/release_integrity.py`;
- package builder and release matching: `src/prostate_journey/presentation.py`.

### Approved aggregate retrieval corpus

Prompt 6 may index only files verified by the selected package's
`outputs/presentation/<release-id>/evidence_manifest.json`. Primary approved paths are:

- `presentation_kpis.csv`, `aggregate_export.csv`, `cohort_kpis.csv`, `cohort_summary.md`;
- `healthcare_analysis_report.md` and the four `healthcare_*.csv` aggregate tables;
- `tactic_registry.json`, `accessible_report.html`, and `evidence_manifest.json`;
- release-matched `scientific_frontend_summary.json`, scientific aggregate tables, and
  `model_cards/` only when their sealed source package was accepted and copied by
  `src/prostate_journey/presentation.py`;
- release-matched `predictive_frontend_summary.json` only when its sealed evidence package is
  accepted. It is absent for the current release and must not be synthesized.

### Methodology, QA, and model-card sources

- methods: `contracts/analysis_registry.yaml`, `contracts/model_target_contracts.yaml`,
  `configs/event_hierarchy.yaml`, `docs/SCIENTIFIC_METHODS_V2.2.md`, and
  `docs/PREDICTIVE_METHODS_V2.2.md`;
- governance: `contracts/model_governance.yaml`, `configs/model_aliases.yaml`,
  `docs/CLAIM_EVIDENCE_REGISTER.md`, and `docs/STAGE4_EXIT_CRITERIA.md`;
- release QA: `data/releases/<release-id>/qa_evidence/final_scorecard.md`,
  `qa_evidence/reports/release_reconciliation.json`, `qa_evidence/reports/data_quality_summary.json`,
  and `qa_evidence/manifests/*.json`; expose aggregates and review status only;
- model cards: only `outputs/presentation/<release-id>/model_cards/*.md` and `*.json` entries present
  in the verified evidence manifest. There are no approved model cards in the active v2.1 package.

### Evidence interfaces and extension points

- frontend provenance interface: `openEvidence(...)` and the evidence drawer in
  `src/prostate_journey/frontend/analytics.js`;
- frontend extension point: add an optional Evidence Copilot panel beside the drawer, preserving
  all four deterministic views and working when Copilot is disabled;
- backend extension point: add an optional, separately configured service/route around
  `src/prostate_journey/application.py`; `/health`, deterministic asset serving, and analytics must
  stay independent of AI readiness;
- grounding contract: every answer must return release ID, tactic/analysis ID, evidence file,
  numerator, denominator, limitation, and synthetic/prohibited-use status.

### Files that must NOT be indexed

- anything below `data/releases/<release-id>/analytical_dataset/`, including CSV, Parquet, DuckDB,
  patient journey, event, provider, and regimen records;
- `data/gold/`, `data/raw/`, archives, patient-level EDA files, logs, temporary paths, `.env*`,
  secrets, credentials, and cloud configuration values;
- `outputs/experiments/`, unsealed scientific/predictive outputs, presentation packages from a
  different release, stale artifacts, or files absent from the active evidence manifest;
- patient-level predictions, features, explanations, exports, prompts, or model responses.

### Prompt 6 invariants

- one certified release per session and citation; fail closed on mismatch or missing evidence;
- aggregate-only retrieval and responses; no patient-level identifiers or row reconstruction;
- every numerical claim grounded to a verified file with numerator and denominator;
- no treatment, patient, market, clinical, causal, commercial, or operational recommendation;
- no inference of model disposition from AUC and no use of unavailable model evidence;
- synthetic watermark and prohibited-use language remain persistent;
- Prompt 6 output stays untrusted/experimental and cannot enter the certified release namespace;
- no OpenAI key is needed for analytics, application readiness, exports, or Presentation Mode;
- run all commands in the Important commands section plus Prompt 6 grounding, citation,
  authorization, prompt-injection, and fail-closed tests.

## IMPLEMENTED: SPECIALIST ANALYSIS

Prompt 7 added specialist analytical reasoning after reading:

- `docs/AI_ANALYSIS_STUDIO_HANDOFF.md`;
- `docs/AI_ANALYSIS_STUDIO_THREAT_MODEL.md`;
- `configs/ai_studio.yaml`;
- `src/prostate_journey/ai_artifact_catalog.py`;
- `src/prostate_journey/ai_evidence_tools.py`;
- `src/prostate_journey/ai_openai.py`;
- `src/prostate_journey/ai_studio.py`;
- `tests/test_ai_analysis_studio.py`.

The implementation preserves the single-release catalogue, aggregate-only retrieval, exact denominator tools,
post-generation number/citation validation, synthetic labeling, prohibited-use language, bounded
cost/memory, no web search, no patient-level access, no source or certified-release writes, and
complete independence of deterministic Analytics. Specialist proposals are labeled as proposals,
require SME/governance approval, and cannot become clinical, patient, causal, commercial,
market-ranking, or operational recommendations. The full Prompt-7 implementation and operating
contract is in `docs/AI_ANALYSIS_STUDIO_HANDOFF.md`.

### Prompt-7 paths for future inspection

- tactic registry: `configs/tactic_registry.yaml`;
- expert lenses: `configs/expert_lenses.yaml`;
- analysis definitions: `contracts/analysis_registry.yaml`;
- release resolver and integrity: `src/prostate_journey/release_integrity.py`;
- strict contracts: `src/prostate_journey/specialist_contracts.py`;
- model boundary: `src/prostate_journey/specialist_openai.py`;
- state machine: `src/prostate_journey/specialist_orchestrator.py`;
- server tools and registered execution: `src/prostate_journey/specialist_tools.py`;
- no-code isolation: `src/prostate_journey/specialist_sandbox.py` and
  `src/prostate_journey/specialist_worker.py`;
- frontend: `src/prostate_journey/frontend/ai_studio.html`, `ai_studio.css`, and `ai_studio.js`;
- regression suite: `tests/test_specialist_analysis.py`;
- untrusted runtime outputs: `outputs/experiments/ai_studio/interactive_runs/`.

Do not index the interactive run directory, analytical Parquet/CSV rows, local secrets, logs,
temporary files, or any unsealed package. Do not add production authorization, real data, cloud
deployment, or certification by inference from this local implementation.

### Prompt-7 verification snapshot — 2026-09-05

- repository tests: `130 passed`;
- specialist analysis tests: `26 passed`;
- static quality: Ruff passed across `102 files`; MyPy passed across `58 source files`;
- catalogue contract: `47 approved artifacts`, `46 indexable`, no patient-level artifacts;
- File Search index: synchronized and `completed` for all `46` indexable artifacts; the exact
  superseded short-lived store was removed after the new store passed verification;
- runtime contract: `10 tactics`, `7 expert lenses`, `16 allowlisted server tools`, `13 states`;
- live deterministic services: Analytics `ok` on port 8080 and AI Studio `ok` on port 8090;
- live registered analysis: run `iar_048c0520bdd543af8624`, US 60-day initiation `350 / 675`,
  `COMPLETED`, QA `PASS`;
- live Luna structured routing and post-QA summary: passed;
- live Terra proposed-method plan: correctly failed closed when the provider returned HTTP 429
  `credit_balance_exhausted`; deterministic fallback and mocked Terra contract tests passed;
- certified release hashes: unchanged (`CHECKSUMS.sha256`
  `A3EF3EA9D5A3B68CCD301DD5E1FD540DC8580DF04C13691108870AB4DF93BAE5`, manifest
  `3AEC73A64CEA531F8C1196731D5FE35D6A7E95723E4AD3AFC56AA0F1B9E7F401`).

The local decision is **CONDITIONAL GO** for synthetic demonstration and expert review. It remains
**NO-GO** for shared production, real/patient data, clinical or commercial use, market inference,
certification of interactive runs, or deployment without the controls listed in the handoff.
