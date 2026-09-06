# AI Studio cost, security, and quality evaluation

**Evaluation date:** 2026-09-06  
**Certified parent release:** `BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z`  
**Data status:** synthetic and aggregate only

## Offline evaluation

The current provider-free suite passed 109/109 cases. It made zero OpenAI requests and incurred
$0.00 metered provider cost. The suite covers all ten tactics, all principal certified KPI
denominators, cohort/censoring/persistence/referral/missingness/model/governance questions, five
specialist routing/parameter cases, recorded malformed/partial/File Search failures, and 72 replayed
prompt-injection cases across user, Markdown, JSON, CSV, HTML, tactic, tool, filename, and metadata
surfaces.

All configured offline metrics were 1.00 except unsupported-claim rate, which was 0.00. No failed
case was omitted. The latest run-specific evidence is under:

`outputs/experiments/ai_studio/evaluations/offline/offline_20260905T213320Z_9f484cc0/`

## Live evaluation

**Status: FAIL — provider quota/availability blocked completion.** The fixed suite is configured for
25 Luna evidence calls and five Terra method-planning calls, with no more than 35 File Search calls.
Its current configuration-level maximum reservation is `$0.62340000`, and the atomic live ledger
rejects any request that would make total committed cost reach `$2.00`.

The most complete metered attempt was
`live_20260905T212349Z_7bff3f50`. It attempted 25 Luna requests and one Terra request before the
suite stopped. Three Luna cases passed all answer, release, denominator, citation, quantitative,
tactic, and prohibited-claim checks. Twenty-two Luna streams failed without final usage, and the
first Terra request returned `budget_or_quota_exhausted`. Known successful-response metered cost was
`$0.001986`; the fail-closed ledger retained a conservative `$0.227826` charge. It recorded 6,616
input tokens, including 2,089 cached-input tokens and 4,518 cache-write tokens, 676 output tokens,
zero File Search calls, and nine deterministic tool calls. The full per-case report is under:

`outputs/experiments/ai_studio/evaluations/live/live_20260905T212349Z_7bff3f50/`

After stream-error classification was hardened, a one-request diagnostic run
(`live_20260905T212741Z_a7d7efa0`) stopped immediately with `provider_unavailable`, `$0.00` known
metered usage, and a `$0.007560` conservative ledger charge. No retry loop continued against the
unavailable provider.

Across all provider-backed diagnostic attempts in this implementation session, reports contain
`$0.023977` of known successful-response metered usage and `$0.276217` in conservative ledger
charges. The provider invoice may differ for streams that failed before returning usage; confirm it
in the provider dashboard. A fresh run with a rotated, budget-limited key and working Luna/Terra
quota is required. Until all 30 cases complete and pass, this repository does **not** claim that the
live `$2` acceptance criterion passed.

## Interpretation boundary

Passing security or quality checks does not turn synthetic scenario output into Bayer evidence,
clinical evidence, real-world evidence, population estimates, treatment recommendations, or
production authorization.
