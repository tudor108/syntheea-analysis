# AI Analysis Studio threat model

**Scope:** read-only evidence explanation plus explicitly confirmed isolated synthetic experiments  
**Trust level:** experimental analytical companion, never an authority  
**Out of scope:** patient-level output, clinical decision support, autonomous action, certification,
deployment, and release writes

## Assets to protect

- OpenAI credentials and provider identifiers;
- release integrity, source hashes, and certification context;
- aggregate evidence definitions and denominators;
- prohibited patient-level datasets;
- users from unsupported clinical, causal, commercial, and real-market claims;
- availability of the deterministic Analytics product.

## Trust boundaries

1. Browser to local AI service: untrusted questions and filter context.
2. AI service to deterministic evidence tools: strict schemas and stable IDs.
3. AI service to local artifacts: explicit allow-list, path containment, release and hash checks.
4. AI service to OpenAI: bounded evidence packet and server-side credential.
5. OpenAI output to user: untrusted until schema, citation, number, release, and safety validation.
6. AI service to Analytics: links only; no shared readiness or write dependency.
7. Specialist orchestrator to immutable release: deterministic read-only analytical functions after
   explicit confirmation; no rows reach the model or browser.
8. Specialist orchestrator to experiment namespace: new run directory only.
9. Proposed method to sandbox worker: sanitized aggregate JSON and a fixed operation enum only.

## Threats and controls

| Threat | Control | Residual risk |
|---|---|---|
| Prompt injection inside evidence | Every artifact wrapper labels content untrusted; system rule forbids following embedded instructions | Novel indirect injection requires continuing evaluation |
| User instruction override | High-risk patterns refused before provider call; model receives fixed instructions | Pattern matching is not a complete classifier |
| Cross-release contamination | One-release catalogue validation, release metadata filter, active-release vector-state fingerprint | Incorrect upstream certification cannot be corrected by AI |
| Hallucinated metrics | Exact values originate in deterministic tools; post-validation rejects numbers absent from those tools | Narrative qualitative overstatement still needs review |
| False citation | Output citations are intersected with packet artifact IDs; unknown IDs are removed | A valid artifact may still be interpreted poorly |
| Path traversal/arbitrary read | Tools accept stable artifact IDs only; resolved paths must remain inside project root | A wrongly allow-listed file could expose content |
| Patient reconstruction | Patient-level directories/types are forbidden; only aggregate artifacts are indexed or exported | Small-cell policy is upstream and still requires governance |
| Secret leakage | Server-side `SecretStr`, excluded serialization, ignored `.env`, CSP, no key in JS/HTML or metadata | Any key pasted into chat must be rotated |
| Remote code/SQL/shell execution | No such tools exist; the sandbox accepts no code and only one fixed aggregate operation | A future tool expansion requires a new threat review |
| Web-derived unsupported claims | No web-search capability in the application | Base-model memory can influence prose; grounding validation limits but cannot prove semantic purity |
| Clinical or commercial misuse | Persistent watermark, prohibited-use text, refusal rules, no operational action tool | Human copy/paste misuse remains possible |
| Cost exhaustion | Token cap, top-k cap, bounded memory, request timeout, per-session budget and visible estimate | Estimates can diverge from actual provider billing |
| Provider outage | Studio reports failure; Analytics remains independently healthy | AI explanation is unavailable during outage |
| Malicious frontend content | CSP permits same-origin assets only; dynamic evidence is inserted with `textContent` | Browser/platform vulnerabilities remain |
| Unauthorized persistence | In-memory sessions, `store=false`, experiment-only local outputs | Provider file/vector retention must be governed separately |
| Silent analysis execution | Fixed state machine, full preview, HMAC-bound spec token, and exact `RUN THIS ANALYSIS` action | Browser/session compromise remains possible without production authentication |
| Confirmation replay or parameter substitution | One-use in-memory token bound to the complete validated spec SHA-256 | Tokens are local-session controls, not production authorization |
| Certified release mutation | Read-only source access, path-separated run namespace, before/after hash regression tests | Host administrator can still alter local files |
| Sandbox escape/network access | No generated code; isolated interpreter; network monkeypatch; fixed schema; timeout; CPU/memory/input/output caps | OS-level containment is incomplete on local Windows; production requires container/process policy |
| Failed analysis interpreted as evidence | QA failure suppresses interpretation, export, and review submission | Reviewers must still verify upstream methodology |
| False promotion to certified | Interactive badges exclude `CERTIFIED`; review record states certification unchanged | Human copy/paste can strip labels |

## Abuse tests

Automated tests cover:

- ten golden tactic IDs;
- exact numerator/denominator parity;
- extra-field rejection in tool schemas;
- traversal and patient-level path rejection;
- stale release rejection;
- clinical and patient-level request refusal;
- user/narrative numbers excluded from the quantitative allow-list;
- hallucinated-number fail-closed behavior;
- secret exclusion from serialization;
- AI service health without OpenAI.
- all nine request modes and seven expert lenses;
- unsupported parameters and incomplete contracts;
- exact parameter and denominator previews;
- confirmation tampering and replay;
- output namespace isolation and unchanged release hashes;
- sandbox network denial and wall-clock timeout;
- QA fail-closed behavior and promotion prevention;
- aggregate-only export, run comparison, and review submission.

Required pre-release red-team tests also include conflicting artifacts, prompt injection inside an
approved document, citation laundering, multilingual unsafe requests, encoded traversal, session
budget races, provider timeouts, malformed SSE, responsive keyboard interaction, and independent
clinical/RWE review.

## Security decision

The current implementation is conditionally suitable for a local synthetic evidence and
specialist-workflow demonstration with a
rotated, budget-limited development credential. It is not approved for production, Bayer systems,
real-world data, personal data, regulated decisions, or public internet exposure. Production use
requires identity and authorization, managed secrets, private networking, centralized audit,
provider data-governance approval, rate limiting, monitoring, incident response, penetration
testing, and independent privacy/security sign-off.
