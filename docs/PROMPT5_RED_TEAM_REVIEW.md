# Prompt 5 adversarial product review

**Review date:** 5 September 2026  
**Scope:** deterministic certified Analytics experience only  
**Evidence:** active v2.1 presentation package, source tests, release-integrity checks, HTTP smoke,
and structural accessibility checks. No chatbot or specialist agent was reviewed.

## Outcome

**Zero unresolved BLOCKERS.** The product is a CONDITIONAL GO for Prompt 6, subject to preserving
the deterministic and aggregate-only boundary. It is not approved for real data, production,
clinical/RWE conclusions, Bayer use, or external decision-making.

## Findings

| Perspective | Severity | Finding | Resolution / status |
|---|---|---|---|
| Bayer executive | BLOCKER | Legacy UI could be read as real market performance and allowed analytical context to disappear. | Fixed: persistent synthetic trust bar, release/scenario/denominator context, prohibited-use text, no market ranking, and Reset to Certified View. |
| Oncologist | BLOCKER | A decorative funnel could imply that 941/1,700 was the official 12-month persistence rate. | Fixed: 941/1,614 is shown explicitly, 86 censored records are separate, and the denominator inspector explains evaluability and censoring. |
| RWE lead | BLOCKER | Tactic copy and result provenance were duplicated and could drift from the analytical contract. | Fixed: one validated ten-tactic registry feeds the UI and future Copilot metadata; each major result opens to method, definitions, limitation, and evidence. |
| Biostatistician | MAJOR | Simulation variability, scenario range, and statistical estimation uncertainty could be conflated. | Fixed where evidence exists: the three concepts are separately labelled. Current release-matched uncertainty evidence is absent and the UI says so rather than inventing intervals. |
| Data scientist | BLOCKER | Model status could be inferred from isolated metrics or stale predictive outputs. | Fixed: predictive evidence is accepted only when release/commit matched and sealed. The current package exposes no model metric or inferred disposition because no matched package exists. |
| Responsible-AI reviewer | BLOCKER | Pilot ideas could drift into recommendations or automated actions. | Fixed: the workflow creates a synthetic testable hypothesis with harm, owner, approval, and stop criterion; it explicitly excludes treatment and patient recommendations. |
| Data engineer | BLOCKER | External CSS/JavaScript initially existed in source but were missing from the built wheel. | Fixed: package-data configuration includes both assets; wheel inspection and Docker rebuild passed. Release and presentation serving remain hash/allow-list controlled. |
| Accessibility reviewer | MAJOR | No independent WCAG conformance or assistive-technology audit is available. | Open: semantic/keyboard/focus/reduced-motion/reflow/live-region structural gates pass. Real-browser and screen-reader checks remain required; the in-app browser inventory was empty during this review. |
| Cross-functional | MAJOR | Active v2.1 release records historical dirty-worktree and legacy wording warnings. | Open and visible: build a clean v2.2 release before external presentation. No fallback or warning suppression is allowed. |
| Cross-functional | MAJOR | Active release has no verified release-matched scientific, multi-seed, or predictive package. | Open and visible: unavailable evidence remains unavailable; no fake estimates or model cards are displayed. |
| Presentation owner | MINOR | PNG export is generated in-browser and lacks automated visual-regression comparison. | Open: deterministic SVG fallback assets and a static demo route exist; add approved screenshot baselines after browser sign-off. |
| Governance reviewer | ACCEPTED RISK | The application is deliberately static and aggregate-only, so exploratory flexibility is constrained. | Accepted for the certified demo. Flexibility must not weaken denominator/release controls. |

## Arithmetic and claim checks

- total synthetic cohort: 10,000;
- eligible: 2,281;
- day-90 initiators: 1,700;
- eligible and evaluable but not initiated by day 90: 581;
- persistence population: 1,700 initiators, 1,614 evaluable at month 12, 941 persistent under the
  60-day operational gap, and 86 censored;
- `1,700 + 581 = 2,281` and `1,614 + 86 = 1,700`;
- no real-market rank, causal wording, treatment-quality judgement, patient benefit, or operational
  model claim is used.

## Demo-failure review

- fixed analytical states and next/previous controls prevent filter drift in Presentation Mode;
- Reset Demo restores the certified view;
- `demo_fallback.html` and four standalone SVGs cover the critical non-AI story if interaction fails;
- the runtime fails closed if the release cannot be resolved and does not load stale placeholder KPIs;
- HTTP smoke passed for all public routes and confirmed that the internal presentation manifest is
  not publicly served.

## Required independent checks before external use

1. Clean v2.2 release and release-matched evidence generation.
2. Oncology, RWE, biostatistical, data-governance, and Bayer workflow-owner sign-off.
3. Real-browser desktop/tablet/mobile and zoom/forced-colours testing.
4. NVDA/JAWS, VoiceOver/TalkBack, and manual WCAG 2.2 AA audit.
5. Security/privacy review, SBOM/vulnerability scan, and approved deployment assessment.
