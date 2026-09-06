# AI Analysis Studio five-minute demo

**Audience:** Bayer executive, RWE, oncology, biostatistics, Data & AI, engineering, governance  
**Parent release:** `BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z`  
**Data status:** synthetic aggregate evidence only  
**Decision boundary:** demonstration and expert review, not clinical/RWE/commercial use

## Before the meeting

1. Start deterministic Analytics with `uv run prostate-journey serve` and verify
   `http://127.0.0.1:8080/health`.
2. Start AI Studio with `uv run --extra ai prostate-journey ai-studio` and verify
   `http://127.0.0.1:8090/health`.
3. Open `http://127.0.0.1:8090/`, select **Presentation mode**, and choose **Reset demo**.
4. Keep the static fallback open from
   `outputs/experiments/ai_studio/demo_fallback/BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.1.0_20260825T112627Z/index.html`.
5. Do not run live-provider Q&A with the previously exposed development credential. Rotate it and
   complete the fixed live evaluation first. The presentation path itself is provider-free.

## Deterministic path

| Time | Step | Presenter action | Expected state | Fallback |
|---:|---:|---|---|---|
| 0:00 | 1 | Show the 90-day initiation answer. | `DETERMINISTIC DERIVATION`; numerator 1,700 / denominator 2,281; current synthetic release visible. | `step-01.svg` |
| 0:25 | 2 | Open the citation. | Release-scoped file, source commit, SHA-256, permitted-use statement, and bounded excerpt. | `step-02.svg` |
| 0:50 | 3 | Continue to the initiation tactic. | Population, denominator, method, limitation, source, parameters, and reviewer status. | `step-03.svg` |
| 1:20 | 4 | Show the prepared request for DE and FR at 60 days. | RWE lens; `initiation_landmarks`; DE/FR; 90 → 60 days; Luna routing and narrative summary off. | `step-04.svg` |
| 1:50 | 5 | Continue to preview. | Typed `AnalysisSpec`, exact diff, per-market denominator slices, assumptions, limitations, QA plan, and maximum cost. | `step-05.svg` |
| 2:25 | 6 | Click **RUN THIS ANALYSIS**. | One-use confirmation accepted; isolated deterministic Python runs; certified paths remain read-only. Next remains locked until completion. | `step-06.svg` |
| 3:00 | 7 | Continue to result. | DE 261/385 (67.8%) and FR 127/222 (57.2%), QA PASS, manifest, method, limitations, parent release, and provider cost `$0.000000`. Do not rank the markets. | `step-07.svg` |
| 3:35 | 8 | Open deterministic Analytics. | Standard Analytics remains available on port 8080 and the parent-release hashes are unchanged. | `step-08.svg` |
| 4:00 | 9 | Continue to model disposition. | Browse-only weak model evidence; no deployment claim, recommendation, or invented confidence score. | `step-09.svg` |
| 4:30 | 10 | Continue to Run History and close on the pilot message. | Run lineage remains outside certified Analytics; pilot one governed analytical question with a human owner and stop criterion. | `step-10.svg` |

## Presenter language

Opening: “This is a governed synthetic analytical design environment. It is not Bayer data, an
RWE study, clinical evidence, or a treatment recommender.”

Core message: “Every number is tied to a release, numerator, denominator, population, method, and
limitation. Any changed parameter is previewed before a separate, explicitly confirmed run.”

Close: “The pilot decision is whether one analytical contract is worth validating against an
approved real source—not whether this synthetic result is true in a real population.”

## Failure path

- AI provider unavailable: stay in the deterministic presentation path; standard Analytics and
  tactic contracts remain available.
- AI Studio unavailable: use the ten static SVG captures and then open Analytics on port 8080.
- Re-run fails QA: show the failure state. Interpretation and export must remain suppressed.
- Citation fails integrity: stop the AI demo. Do not substitute another or stale artifact.
- Any release mismatch: use **Reset demo**. If mismatch remains, use only the static package whose
  manifest matches the current certified release.

## Verified fallback run

The generated fallback manifest records run `iar_4d5440a3b0944e488df6`, QA `PASS`, zero provider
cost, ten SVG files, and identical before/after SHA-256 values for `CHECKSUMS.sha256` and
`release_manifest.json`. It is an experiment artifact, not certified output.
