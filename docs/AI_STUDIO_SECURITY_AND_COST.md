# AI Studio security and cost operating note

**Scope:** optional local synthetic analytical design service  
**Production authorization:** none  
**Real/patient data authorization:** none

## Isolation and failure behavior

- AI Studio is a separate service on port 8090; deterministic Analytics is a separate service on
  port 8080 and has no OpenAI dependency.
- `AI_ANALYSIS_STUDIO_ENABLED=false` prevents the AI service, routes, and frontend assets from
  starting. It does not change the standard Analytics package.
- `AI_STUDIO_PROVIDER_ENABLED=false` keeps the Studio, tactic library, deterministic presentation,
  and local registered calculations available while suppressing provider and vector-search calls.
- Retrieval uses a release-isolated allow-list. Patient-level tables, source code, `.env`, logs,
  experiments, archives, stale packages, and unsealed evidence are excluded.
- Registered calculations use deterministic local Python. Proposed analysis uses the constrained,
  network-denied declarative sandbox. No arbitrary code, SQL, shell, or path input is accepted.
- Interactive writes are restricted to `outputs/experiments/ai_studio/interactive_runs/`; the
  certified release and presentation namespaces are read-only to this workflow.
- Exact CORS, CSRF, loopback-or-bearer authentication, body/rate/session bounds, HMAC confirmation,
  one-use execution, output quotas, audit redaction, and fail-closed artifact checks are enforced.

## Cost controls

All prices and request ceilings come from `configs/ai_cost_controls.yaml`. The interface shows
session spend, reservations, remaining budget, warning state, and the maximum cost before an
analysis can run. Atomic SQLite reservations cover concurrent requests, duplicate IDs, restarts,
partial responses, and provider failure. Unknown partial usage retains the conservative reservation.

The deterministic presentation path turns Luna routing and the optional narrative summary off.
The verified DE/FR 60-day run therefore cost `$0.000000` in provider usage.

Current live-evaluation evidence is not a passing acceptance run:

- most complete fixed-suite attempt: `$0.001986` known metered provider usage and `$0.227826`
  conservative ledger charge;
- all recorded development attempts: `$0.023977` known metered usage and `$0.276217` conservative
  ledger charge;
- current full 25-Luna/5-Terra suite worst-case reservation: `$0.62340000`, below the `$2.00` live
  hard stop.

The fixed suite remains failed because most Luna streams did not return final usage and Terra
reported quota/credit exhaustion. Do not describe the partial run as validated reliability.

## Credential incident requirement

A development API key was pasted into chat before being stored in the ignored local `.env` file.
Treat that key as compromised: revoke it in the provider console, rotate it, issue a budget-limited
replacement, and rerun the secret scan and fixed live evaluation. Do not copy the replacement into
documentation, source control, screenshots, logs, or chat.

## Operator checklist

Before a local provider-free demo:

1. Run `uv run python scripts/check_no_secrets.py --root .`.
2. Run `uv run --extra ai prostate-journey ai-check` and `ai-specialist-check`.
3. Generate the fallback with `ai-demo-package --confirm-run`; confirm provider cost is zero and
   release hashes match before/after.
4. Verify `/health` for ports 8080 and 8090 and open both interfaces.
5. Use Presentation mode. Do not enable the model router or narrative summary.

Before any live-provider or shared test:

1. Revoke/rotate the exposed key and verify account quota.
2. Use organization identity, managed secrets, private networking, distributed rate/concurrency
   controls, retention enforcement, monitoring, incident response, and provider spend alerts.
3. Run the fixed live evaluation once under the configured hard stop and preserve its complete
   usage response. Stop if the provider omits final usage.
4. Obtain security, privacy, RWE, biostatistics, oncology, accessibility, responsible-AI, model-risk,
   and Bayer workflow-owner approval.

Detailed threat and evaluation procedures remain in `docs/AI_ANALYSIS_STUDIO_THREAT_MODEL.md` and
`docs/AI_FINOPS_SECURITY_EVALUATION_RUNBOOK.md`.
