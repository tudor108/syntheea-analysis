# Five-minute deterministic non-AI demo

## Start state

Open `executive_story.html` from the release-matched presentation package or the local application.
Select `Reset Demo` before speaking. Expected state: Executive view, all configured scenarios,
90-day initiation, 60-day persistence gap, synthetic trust bar visible.

| Time | Action | Expected deterministic state | Talk track |
|---|---|---|---|
| 0:00 | Open Executive Overview | Synthetic warning, release, cohort, denominator, window, gap, and Stage-4 status visible | “This is a synthetic analytical contract, not Bayer or real-patient evidence.” |
| 0:25 | Show denominator ledger | Total, excluded, eligible, initiated, evaluable-not-initiated, and censored branches shown separately | “A confident denominator beats a confident prediction.” |
| 0:55 | Change 90-day to 60-day initiation | Context bar shows 60 days; exact event/gap/evaluability counts update; eligible denominator remains visible | “The outcome window changed; the product does not hide what did or did not change.” |
| 1:25 | Return to 90 days; open Analyst | Scenario dot plot and table show exact n/N with no ranking labels | “These are configured scenario differences, not real market performance.” |
| 1:55 | Select two scenario rows in turn | Whole-product denominator changes and `DENOMINATOR CHANGED` announces previous/current context | “Filter changes cannot silently alter the population.” |
| 2:25 | Reset; open Persistence tactic | Level 1 shows question/result; Level 2 method and denominator; Level 3 sources/review status | “One registry powers both the product and future Evidence Copilot.” |
| 3:10 | Open Evidence & Provenance | Release, commits, config hash, analysis/tactic IDs, n/N, method source, evidence, QA, limitation | “Evidence is one interaction from the result.” |
| 3:45 | Open Governance → model disposition | Current historical release displays release-matched model evidence unavailable | “We do not import or infer a model result from another release.” |
| 4:15 | Open Create Pilot Hypothesis | Synthetic observation, population, workflow, source, method, harm, owner, approval, stop criterion | “This creates a reviewable question, never a patient or treatment action.” |
| 4:45 | Reset Demo | Certified default state restored | “Pilot one governed question, not the entire platform.” |

## Presentation Mode

`Presentation Mode` locks manual market/window/gap controls. Next/Previous applies eight approved
states, including the 60-day demonstration, provenance, honest model status, and pilot hypothesis.
`Reset Demo` exits and restores the certified default.

## Fallback

- Static route: `demo_fallback.html`.
- Static visuals: `fallback/01-executive-overview.svg`,
  `fallback/02-denominator-ledger.svg`, `fallback/03-method-evidence.svg`, and
  `fallback/04-model-disposition.svg`.
- Accessible narrative: `accessible_report.html`.
- Before the actual presentation, capture organization-approved screenshots from the exact served
  package after manual browser/accessibility sign-off; do not edit KPI text in an image tool.

## Failure rule

If readiness fails, a release cannot be resolved, or the visible release differs from the rehearsal
release, stop the live demo. Do not load `data/gold`, an older dashboard, or a screenshot from a
different package.

