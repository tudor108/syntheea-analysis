# AI Studio final red-team report

**Review scope:** final four-view AI Analysis Studio, deterministic demo, interactive run boundary,
and continued independence of certified Analytics.  
**Release:** `BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z`  
**Outcome:** zero unresolved implementation blockers for a provider-free local synthetic demo.

## Findings

| Attack or failure | Reviewer lens | Result and control | Final class |
|---|---|---|---|
| Fabricated answer or number | Bayer executive / biostatistician | Generated numbers are rejected unless allow-listed by deterministic metric tools; fallback returns a deterministic answer. | Fixed blocker |
| Wrong release | RWE / data engineering | One release per catalogue and citation; stale/mismatched catalogues fail closed. | Fixed blocker |
| Hidden denominator change | RWE / biostatistician | Typed diff and per-market numerator, denominator, exclusion, censoring, and evaluability preview precede execution. | Fixed blocker |
| Unsupported market claim or ranking | Executive / RWE | Only configured synthetic markets validate; copy and comparison contracts prohibit ranking and real-market inference. | Fixed blocker |
| Treatment recommendation | Oncologist | Request classifier refuses clinical/treatment/patient decisions at zero model cost. | Fixed blocker |
| Patient-level request | Privacy / security | Retrieval and exports are aggregate-only; patient-level paths and reconstruction requests are blocked. | Fixed blocker |
| Prompt injection or API-key request | AI security | User and artifact injection patterns, recursive sanitization, secret-request blocking, redacted audit fields, and allow-listed sources. | Fixed blocker |
| Arbitrary code request | AI security / data engineering | No shell, SQL, Python, path, or code tool exists; custom work uses one declarative network-denied sandbox. | Fixed blocker |
| Duplicate run | FinOps / MLOps | Idempotency, atomic reservation, one-use HMAC confirmation, and replay rejection. | Fixed blocker |
| Budget exhaustion | FinOps | Per-request/session/user/live-suite ceilings fail before provider execution; partial failures retain conservative reservation. | Fixed blocker |
| AI backend failure | MLOps | Error is scoped to AI Studio; deterministic Analytics and provider-free tactic/demo paths remain available. | Fixed blocker |
| Malformed `AnalysisSpec` | RWE / engineering | Extra fields forbidden; population, time zero, outcome, window, market, parameters, and methods validate before confirmation. | Fixed blocker |
| Custom-analysis QA failure | Biostatistician / MLOps | QA failure suppresses interpretation and export; failed status remains in experiment lineage. | Fixed blocker |
| Unsupported deployment claim | Responsible AI / executive | Model disposition comes from the verified registry; browse-only weak evidence cannot run or be labeled deployable. | Fixed blocker |
| Keyboard-only workflow | Accessibility | Semantic tabs, roving keys, labels, focus visibility, drawer trap/restore, Escape close, live regions, and text status are implemented and structurally tested. | Minor: manual AT validation open |
| Mobile workflow | Accessibility | Responsive single-column layout, reflowing controls/tables, and reduced motion are implemented. | Minor: physical-device validation open |
| Broken citation | RWE / engineering | Artifact IDs, path confinement, release/hash verification, and 404/fail-closed behavior prevent silent fallback. | Fixed blocker |
| Stale artifact index | AI security / MLOps | Remote vector state must match release and catalogue fingerprint; otherwise local allow-listed retrieval is used. | Fixed blocker |

## Hostile reviewer conclusions

- **Bayer executive:** the demo is legible and honest, but synthetic scenario results cannot support
  a commercial, quality, or market decision.
- **RWE lead:** denominator/time-zero/censoring controls are inspectable; real-source fitness and a
  protocol remain prerequisites.
- **Oncologist:** no treatment recommendation or patient action is permitted; oncology definitions
  still require independent review.
- **Biostatistician:** arithmetic and QA are deterministic; active v2.1 has no release-matched
  multi-seed uncertainty package and interactive comparisons are descriptive only.
- **Data engineer:** experiment and certified namespaces are separated; enterprise retention,
  identity, observability, and capacity controls are not implemented.
- **AI security reviewer:** injection and tool surfaces fail closed. The development key exposed in
  chat must be revoked before any further live call.
- **MLOps reviewer:** run manifests and model dispositions are governed; live provider reliability
  acceptance has not passed.
- **Accessibility reviewer:** no automated accessibility-critical blocker remains; manual screen
  reader, forced-colour, high-zoom, and physical-device checks are still required.
- **FinOps reviewer:** deterministic demo cost is zero; live totals and conservative charges are
  visible and below the hard stop, but quota failure prevents a live GO.

## Open risks

| Risk | Class | Required action |
|---|---|---|
| Exposed development provider key | Major; blocks live-provider use | Revoke and rotate outside the repository before another live request. |
| Incomplete live provider evaluation | Major; blocks live/provider reliability acceptance | Restore quota and pass the fixed 25-Luna/5-Terra suite under the hard stop. |
| Manual WCAG and assistive-technology sign-off incomplete | Minor for local demo; major for shared/production use | Run keyboard, screen-reader, 200%/400% zoom, forced-colour, mobile, and independent audit. |
| Local authentication and process-local controls | Major for production | Add enterprise IAM/RBAC, managed secrets, distributed controls, monitoring, retention, and incident response. |
| Historical v2.1 lacks release-matched v2.2 uncertainty/model package | Major for scientific claims | Create a clean v2.2 release; never backfill historical certified evidence. |

## Decision

**CONDITIONAL GO** for the provider-free local synthetic demonstration and expert review using the
deterministic path and static fallback. **NO-GO** for live-provider use until key rotation and a
complete passing live evaluation. **NO-GO** for production, real/patient data, clinical support,
RWE claims, Bayer performance, commercial use, market decisions, or certification of interactive
results.
