# AI Analysis Studio user guide

AI Analysis Studio is a separate analytical design workspace beside deterministic Analytics. It
uses one certified synthetic aggregate release as read-only evidence and stores every interactive
run under `outputs/experiments/`. It is not an authorized processor of real patient data.

## Four views

### Ask the Evidence

Use this view to ask about supported cohorts, denominators, initiation, persistence, referrals,
missingness, methods, models, and provenance. Choose a synthetic market and optionally limit
narrative retrieval to aggregate results, methodology/model cards, or governance/QA/manifests.
The chosen filter is visible on the user message.

An answer may be labeled `CERTIFIED EVIDENCE`, `DETERMINISTIC DERIVATION`, `EXPERT EXPLANATION`,
`PROPOSED ANALYSIS`, `NOT FOUND`, or `REQUIRES SME REVIEW`. Exact quantitative claims are accepted
only from deterministic metric tools. Open a source citation to inspect its release, commit,
SHA-256, scope, and bounded excerpt.

### Explore Tactics

The library displays all ten canonical tactic contracts. Search or filter by analysis type,
journey stage, methodology, market applicability, temporal design, evidence type, and SME-review
requirement. Each card exposes its question, population, denominator, time window, method, current
synthetic result where available, limitation, evidence, supported parameters, and review status.

`Change parameters` and `Compare` are disabled where the active release has no deterministic
execution adapter. A browse-only tactic can still open evidence or begin a proposed method, which
is always labeled `PROPOSED METHOD — REQUIRES ANALYTICAL REVIEW`.

### Specialist Analysis

1. Describe a permitted aggregate question and select an expert lens and tactic.
2. Adjust only allow-listed structured controls. Chat interpretation, controls, and generated
   `AnalysisSpec` are synchronized after preview.
3. Inspect the selected tactic, lens, market(s), current certified scenario, exact parameter diff,
   numerator, denominator, exclusions, censoring, evaluability, assumptions, limitations, checks,
   expected output, and maximum provider cost.
4. Resolve validation errors. No run exists at this point.
5. Select **RUN THIS ANALYSIS**. The exact confirmation is bound to the validated specification and
   is one-use only.
6. Inspect aggregate results only after QA passes. Export or submit for review does not certify the
   result.

The active v2.1 package does not contain release-matched low/base/high regenerated simulation
scenarios. The scenario control therefore truthfully shows the current certified synthetic
scenario only; no fallback scenario is silently substituted.

### Run History

History groups successful interactive re-runs, proposed custom analyses, failed validation,
submitted runs, and expired runs. Each available item shows run and parent-release IDs, question,
lens, parameters, cost, status, QA, outputs, manifest, creation, completion, and expiry. Interactive
runs are never inserted into certified Analytics. Actions expire after seven days by default.

## Presentation mode

Presentation mode fixes the approved ten-step state and locks ordinary navigation and filter
controls to prevent drift. The only intentional execution action is **RUN THIS ANALYSIS** at step
6. **Reset demo** clears prior preview/result state and returns to the certified 90-day answer.
See `docs/AI_STUDIO_DEMO_SCRIPT.md` for the expected state at every step.

## Keyboard and accessibility

- Use the skip link to move to the workspace.
- Use Left/Right, Home, and End on the four mode tabs.
- Every form control has a visible label; tables carry text headers and all result cards repeat
  numerator and denominator in text.
- Streaming, filter changes, validation, denominator, cost, QA, and errors use live-region status
  announcements.
- Escape closes drawers; Tab and Shift+Tab remain trapped inside an open drawer; focus returns to
  the opening control.
- Reduced-motion preferences disable smooth movement. Mobile uses a single-column reading order.

Automated structural checks do not replace manual NVDA/JAWS, VoiceOver/TalkBack, 200%/400% zoom,
forced-colour, and touch-device review.

## Prohibited requests

Do not provide patient-level data, identifiers, source paths, arbitrary SQL/Python/shell, secrets,
API keys, treatment advice, clinical decisions, causal claims, Bayer performance claims, real-market
rankings, unsupported endpoints, or requests to overwrite certified evidence. The service should
refuse them and preserve deterministic Analytics.
