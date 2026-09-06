# AI Analysis Studio runbook

AI Analysis Studio is optional. The deterministic Analytics service does not require the OpenAI
SDK, an API key, a vector store, or this service.

## Local setup

```powershell
uv sync --frozen --extra dev --extra ai
Copy-Item .env.example .env
# Set OPENAI_API_KEY in .env locally. Never commit or paste it into documentation.
uv run --extra ai prostate-journey ai-catalogue
uv run --extra ai prostate-journey ai-check
uv run --extra ai prostate-journey ai-specialist-check
uv run --extra ai prostate-journey ai-demo-package --confirm-run
uv run --extra ai prostate-journey ai-sync-vector-store
uv run --extra ai prostate-journey ai-studio
```

Open:

- deterministic Analytics: `http://127.0.0.1:8080/`
- AI Analysis Studio: `http://127.0.0.1:8090/`
- AI liveness: `http://127.0.0.1:8090/health`
- AI readiness/context: `http://127.0.0.1:8090/ready`
- specialist contract: `http://127.0.0.1:8090/api/specialist/context`

The File Search store expires seven days after last activity. Re-run
`ai-sync-vector-store` after an approved catalogue change or expiry.

Set `AI_ANALYSIS_STUDIO_ENABLED=false` to prevent the optional AI service, routes, and assets from
starting. Standard Analytics remains independent. Interactive run files remain in the ignored
experiment namespace, but compare/export/review actions expire after
`AI_STUDIO_INTERACTIVE_RUN_TTL_DAYS` (seven days by default).
Set `AI_STUDIO_PROVIDER_ENABLED=false` for the safe provider-free presentation: the Studio and
deterministic tools remain available, but OpenAI and vector-search calls are suppressed.

## Startup validation

`ai-check` must report:

- one release ID;
- `patient_level_data_included: false`;
- ten tactics;
- deterministic smoke metric `initiated_90d = 1700 / 2281` for the current package;
- whether OpenAI and vector search are configured.

`ai-specialist-check` must report ten tactics, seven expert lenses, sixteen allow-listed tools, an
explicit preview denominator, `confirmation_required: true`, `run_created: false`, and no
patient-level data.

The catalogue and vector state may be written only under
`outputs/experiments/ai_studio/`. Those files are experimental runtime state, not certified
evidence.

## Safe operating sequence

1. Start or verify Analytics independently.
2. Run `ai-catalogue` and inspect the release ID.
3. Run `ai-check`; stop on a hash or release mismatch.
4. Synchronize the vector store only after catalogue review.
5. Start AI Studio.
6. Ask the 90-day initiation smoke question.
7. Confirm the answer shows numerator 1,700 and denominator 2,281, the active release, synthetic
   status, a limitation, and at least one source.
8. Ask for patient-level records and confirm it refuses before calling the model.
9. Stop AI Studio and verify Analytics remains healthy.

For an interactive rerun:

1. Open **Specialist Analysis** and select one registered, runnable tactic.
2. Select an expert lens and only configured parameters.
3. Inspect validation, cost, exact parameter diff, population, denominator, exclusions, censoring,
   and the complete `AnalysisSpec`.
4. Click `RUN THIS ANALYSIS`; ordinary chat text is not execution approval.
5. Require QA `PASS` before reading interpretation, exporting aggregate CSV, comparing, or
   submitting for review.
6. Confirm the run remains below `outputs/experiments/ai_studio/interactive_runs/` and the parent
   release hashes are unchanged.

For a proposed method, explicitly accept the displayed Terra planning ceiling first. The resulting
operation remains proposed, unverified, aggregate-only, sandboxed, and subject to human review.

For a five-minute provider-free presentation, open **Presentation mode** and use its fixed
Previous/Next controls. Filters and ordinary navigation are locked to prevent state drift; the
only intentional execution action is **RUN THIS ANALYSIS**. See `docs/AI_STUDIO_DEMO_SCRIPT.md` and
keep the generated ten-frame fallback open in a second tab.

## Failure behavior

| Condition | Expected behavior |
|---|---|
| Missing API key | Studio catalogue and deterministic tools load; chat reports AI unavailable |
| OpenAI request failure | Validated answer is not fabricated; Analytics remains unaffected |
| Missing/expired vector store | Local retrieval remains available; no cross-release fallback |
| Catalogue hash mismatch | Startup/check fails closed |
| Unsupported question | `NOT FOUND IN THE CURRENT CERTIFIED ARTIFACTS` |
| Unsafe clinical/patient/credential/code request | Refused before provider invocation |
| Session budget exhausted | New model calls stop until reset or configuration change |
| Missing certified release | No fallback to mutable gold or stale presentation data |
| Invalid/unsupported parameter | Preview fails; no confirmation token or run is created |
| Changed or replayed confirmation token | Execution is rejected |
| Sandbox network attempt or timeout | Worker is terminated/fails closed; no interpretation |
| Post-run QA failure | `ANALYSIS FAILED VALIDATION`; export and review are disabled |
| Disabled feature flag | AI Studio does not start; standard Analytics continues on port 8080 |
| Expired interactive run | History remains visible; compare, export, and review actions return an explicit expiry state |

## Validation commands

```powershell
uv run ruff format --check src tests eda scripts
uv run ruff check src tests eda scripts
uv run mypy src
uv run pytest
uv run pytest tests/test_ai_analysis_studio.py
uv run pytest tests/test_specialist_analysis.py
node --check src/prostate_journey/frontend/ai_studio.js
uv run python scripts/check_no_secrets.py --root .
uv run python scripts/check_markdown_links.py --root .
uv run prostate-journey application-check
uv run prostate-journey industry-check --allow-missing-release
```

Manual accessibility checks remain required for keyboard order, screen readers, 200%/400% zoom,
forced colours, responsive reflow, live status announcements, and citation-drawer focus.

## Key rotation

If a key is exposed in chat, a terminal capture, or any shared channel:

1. revoke it in the provider console immediately;
2. create a replacement with the minimum required project permissions and budget;
3. replace only the local environment value;
4. re-run `ai-check` and the provider smoke test;
5. review provider usage and audit logs;
6. never store the replacement in Git, frontend code, container images, logs, docs, or test
   fixtures.

## Operational limits

Sessions, preview specifications, confirmation tokens, and replay state are in memory and
intentionally short lived. The local title and bounded turn summary are not certified evidence.
Responses use `store=false`. Interactive run manifests and aggregate outputs persist only in the
ignored experiment namespace; physical deletion is not automated in this local implementation,
while user actions are disabled after the configured TTL.
Provider-side file objects and vector-store IDs are operational metadata and must be governed and
deleted according to the target environment's retention policy.
