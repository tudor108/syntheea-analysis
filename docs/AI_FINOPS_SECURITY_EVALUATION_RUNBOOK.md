# AI FinOps, security, and evaluation runbook

**Scope:** optional AI Analysis Studio only  
**Data boundary:** synthetic, aggregate, release-scoped evidence  
**Analytics dependency:** none; deterministic Analytics on port 8080 remains independent

## Operating contract

All model prices, tool prices, request envelopes, session/run/evaluation budgets, warning levels,
and security limits come from `configs/ai_cost_controls.yaml`. The effective pricing date and
source note must be reviewed before a price is changed. Prices must never be copied into another
runtime module.

The initial price source is the official OpenAI API pricing documentation, verified on the
effective date in the configuration. `gpt-5.6-luna` is the default evidence/router/summary model.
`gpt-5.6-terra` is available only for explicitly confirmed specialist methodology planning. Web
Search and Code Interpreter are disabled.

The application limits are:

| Boundary | Default |
|---|---:|
| Evidence request | $0.02 maximum reservation |
| Specialist planning request | $0.50 maximum reservation |
| Specialist run | $0.55 hard stop |
| Interactive session warning | $1.20 |
| New specialist work soft stop | $1.50 |
| Interactive session | $2.00 hard stop |
| Live evaluation warning | $1.60 |
| Live evaluation | strictly below $2.00 |
| Authenticated user/day | $5.00 hard stop |
| Monthly project warning/critical alert configuration | $10.00 / $20.00 |

Provider/model and built-in-tool charges are tracked in the atomic ledger. Local or cloud compute
is recorded separately and is never presented as provider spend.

## Reservation lifecycle

For every provider-backed request, the server:

1. selects one named request profile;
2. calculates a worst-case reservation from uncached input, output, permitted File Search calls,
   maximum model iterations, and the configured safety margin;
3. starts a SQLite `BEGIN IMMEDIATE` transaction;
4. atomically checks request, session, specialist-run, user-day, and live-evaluation limits;
5. reserves funds before File Search or model execution;
6. sends one idempotent provider request through the centralized client;
7. reconciles against returned token/tool usage and releases the difference;
8. conservatively charges the reservation if a partial/unknown provider failure returns no usage;
9. emits allow-listed audit metadata without prompts, answers, credentials, or patient data.

The ledger defaults to `outputs/experiments/ai_studio/budget_ledger.sqlite3` with WAL and full
synchronous writes. The audit stream defaults to `outputs/experiments/ai_studio/audit.jsonl`.
Both are mutable experiment artifacts, not certified evidence.

## Local setup

Create a local ignored `.env` from `.env.example` and set `OPENAI_API_KEY` only there or in a
managed server-side environment. Never put a key in JavaScript, YAML, Markdown, a shell command,
or a committed file. If a key was pasted into chat, a ticket, or another shared channel, revoke it
and issue a replacement before use.

```powershell
uv sync --frozen --extra dev --extra ai
uv run --extra ai prostate-journey ai-catalogue
uv run --extra ai prostate-journey ai-check
uv run --extra ai prostate-journey ai-specialist-check
uv run --extra ai prostate-journey ai-offline-eval
uv run --extra ai prostate-journey ai-studio
```

Open `http://127.0.0.1:8090/`. The Cost & usage drawer shows charged and reserved dollars, token
and File Search totals by model, request status, latency, warning level, and remaining session
budget. `GET /api/cost?session_id=<id>` returns the same session-scoped telemetry.

## Authentication and browser security

Local loopback may use `authentication_mode: local`. Every non-local/environment binding fails
configuration validation unless bearer authentication and `AI_STUDIO_ACCESS_TOKEN` are set. A
production deployment must place the service behind organization identity/RBAC; the built-in
bearer boundary is a minimum transport gate, not a full enterprise IAM solution.

The HTTP boundary enforces exact-origin CORS, CSRF tokens on mutating POST requests, request-body
limits, 30-minute session expiry, rate limits, no-store responses, correlation IDs, CSP,
frame-denial, MIME sniffing denial, and sanitized error bodies. API tokens are compared in constant
time and hashed before a user/day ledger identity is stored.

No upload endpoint exists. Indexed files must be on the explicit catalogue allowlist, use approved
text types, remain below the configured size limit, match the active release where required, and
pass path/hash checks. No patient-level, raw, gold, Parquet, DuckDB, archive, source code, secret,
or experiment artifact is indexable.

## Prompt-injection response

User instructions requesting credential access, patient rows, release switching, certified-output
mutation, arbitrary execution, unavailable tools, external transfer, fabricated Bayer evidence,
or concealed denominator changes are blocked before provider use. Retrieved content is enclosed in
an explicit untrusted-evidence boundary. Instruction-like text in content, filenames, metadata,
tactic descriptions, or tool results is removed before model context construction. Model output
still passes deterministic number, citation, tactic, release, and schema validation.

Run the offline red team after any retrieval, tool, prompt, catalogue, or model-output change:

```powershell
uv run --extra ai prostate-journey ai-offline-eval
uv run pytest tests/test_ai_prompt_injection.py tests/test_ai_finops.py
```

The offline suite is deliberately larger than the live suite and performs no API call. Review each
failed case in the run-specific JSON/Markdown report; an average score never suppresses failures.

## Live evaluation

The fixed live suite contains 25 Luna evidence questions and five Terra methodology plans. The
configuration proves the worst-case reserved amount is below $2 before startup. Each request still
performs an atomic preflight, and the suite aborts after a provider/budget failure to avoid repeated
charges. File Search calls are capped at 35; web and code execution are absent.

```powershell
uv run --extra ai prostate-journey ai-live-eval
```

Every attempt writes a complete report under
`outputs/experiments/ai_studio/evaluations/live/<run-id>/`, including planned/completed counts,
every failed case, latency, known metered cost from completed responses, conservative ledger charge,
models, tokens, cache-use, tools, and the hard-stop state. `NOT_RUN` or `FAIL` is not evidence that
the sub-$2 live acceptance criterion passed. A provider stream that ends before returning usage
remains conservatively charged; provider billing is authoritative for the eventual invoice.

## Incident and failure handling

- **Credit/quota exhausted:** no retry; preserve the report, replenish/repair provider controls,
  then start a new evaluation run.
- **Timeout, connection, 408/409/5xx, or provider rate limit:** at most one explicit retry, already
  covered by the reservation; no recursive or autonomous retry loop.
- **Malformed/partial response:** release no answer; conservatively reconcile and return a safe
  provider-unavailable response.
- **File Search unavailable:** use only local allow-listed retrieval; never load a stale store or
  broad filesystem fallback.
- **Vector/release mismatch:** mark vector retrieval unavailable; rebuild the catalogue and create
  a fresh release-partitioned store.
- **Budget exhausted:** reject before provider/tool use. Reset creates a new session, not a ledger
  rewrite.
- **Backend restart:** in-memory conversation/confirmation state expires. Persisted costs remain;
  users must start a new session and reconfirm analyses.
- **Sandbox timeout/resource/QA failure:** terminate the worker, suppress interpretation/export,
  preserve the failed aggregate run evidence, and leave the certified release unchanged.
- **Suspected key exposure:** revoke immediately, inspect the allow-listed audit stream and provider
  usage, replace the secret, and rerun secret/security gates.

AI security or evaluation success does not authorize real patient data, clinical use, real-world
evidence claims, Bayer-performance claims, or production deployment.
