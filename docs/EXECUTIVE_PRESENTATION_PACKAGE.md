# Executive presentation package

**Audience:** Bayer executives, oncology/RWE/statistics specialists, Data & AI, engineering, and
governance reviewers.  
**Source rule:** generate every number from one explicitly selected certified presentation package.
Do not copy a KPI from this document.  
**Mandatory footer:** `SYNTHETIC SCENARIO — NOT REAL PATIENT, BAYER, CLINICAL, COMMERCIAL, OR POPULATION DATA`.

## Slide 1

**English title:** A confident denominator beats a confident prediction  
**Concise copy:** Trust starts with who enters the analysis, when observation begins, and whether
follow-up is sufficient. The product makes these contracts visible before any model is discussed.  
**Visual:** denominator ledger with excluded and censored branches.  
**Romanian speaker notes:** „Începem cu populația și timpul zero. Un scor predictiv nu poate repara
un denominator greșit sau un follow-up insuficient.”  
**Appendix:** cohort definitions; attrition reconciliation.  
**Likely objection:** Why not lead with AI?  
**Truthful answer:** Because no AI metric is interpretable until population, target, timing, and
evaluability are stable.

## Slide 2

**English title:** Build the analytical contract before real-data onboarding  
**Concise copy:** Synthetic data lets the team test schemas, chronology, QA, reproducibility, and
communication boundaries without claiming real-world validity.  
**Visual:** configuration → 19 analytical tables → QA → immutable release → aggregate product.  
**Romanian speaker notes:** „Valoarea de acum este metoda și infrastructura de evidence engineering,
nu ratele sintetice.”  
**Appendix:** data contract; release manifest; real-data readiness checklist.  
**Likely objection:** Does this prove the source will work?  
**Truthful answer:** No. Source fit, phenotype, endpoint, privacy, security, and clinical validation
remain mandatory.

## Slide 3

**English title:** One longitudinal journey, not disconnected tables  
**Concise copy:** Eligibility, referral, initiation, treatment episodes, switching, discontinuation,
restart, censoring, and persistence share one temporal contract and reconciled patient journey.  
**Visual:** restrained state sequence with transition counts; no causal arrows.  
**Romanian speaker notes:** „Nu lipim dashboarduri independente. Evenimentele au ordine, grain,
chei și limite temporale comune.”  
**Appendix:** ER diagram; event hierarchy; chronology tests.  
**Likely objection:** Is the pathway clinically validated?  
**Truthful answer:** It is an engineering definition on synthetic records and still requires SME and
source validation.

## Slide 4

**English title:** Every number has a denominator  
**Concise copy:** Headline results show numerator, denominator, population, time window, release,
and censoring. A denominator change is announced rather than hidden.  
**Visual:** selected-release KPI cards and Denominator Inspector.  
**Romanian speaker notes:** „Pentru persistență nu folosim automat toți inițiatorii. Denominatorul
oficial include doar înregistrările evaluabile, iar cenzura este separată.”  
**Appendix:** presentation KPI export; numerator/denominator definitions.  
**Likely objection:** Why do n/N values differ between analyses?  
**Truthful answer:** Different questions require different evaluability windows; the product makes
the transition explicit.

## Slide 5

**English title:** Longitudinal answers change when follow-up or definitions change  
**Concise copy:** Initiation landmarks and persistence gap sensitivities are displayed separately.
Scenario range, simulation variability, and estimation uncertainty are never conflated.  
**Visual:** initiation bars plus 30/60/90-day persistence dot plot with exact n/N.  
**Romanian speaker notes:** „Diferența dintre regulile de gap este sensibilitate de definiție, nu un
interval de încredere. Pentru release-ul curent, incertitudinea științifică absentă este marcată.”  
**Appendix:** scientific methods; persistence evidence.  
**Likely objection:** Which gap is clinically correct?  
**Truthful answer:** The current primary rule is configured, not clinically validated; domain review
and source behavior must decide an approved definition.

## Slide 6

**English title:** Every result opens to method, limitation, and evidence  
**Concise copy:** Tactic Library v2 uses one machine-readable registry. Every material result opens
to release, commit, configuration, analysis/tactic IDs, n/N, evidence file, QA state, and limitation.  
**Visual:** tactic card Levels 1–3 and Evidence & Provenance Drawer.  
**Romanian speaker notes:** „Executivul vede mesajul simplu; specialistul ajunge în maximum două
interacțiuni la contract și provenance.”  
**Appendix:** `tactic_registry.json`; `evidence_manifest.json`.  
**Likely objection:** Are card descriptions maintained separately?  
**Truthful answer:** No. The frontend and future Evidence Copilot consume the same validated registry.

## Slide 7

**English title:** Weak or unavailable models show us where not to automate  
**Concise copy:** Model status is consumed only from release-matched verified evidence. No AUC-only
approval, AI confidence score, patient ranking, threshold, or deployment alias is created.  
**Visual:** model-disposition cards, or the explicit “unavailable for selected release” state.  
**Romanian speaker notes:** „Pentru release-ul istoric curent nu inventăm rezultate Prompt 3. Dacă
evidence package-ul nu este aliniat cu release-ul, interfața afișează indisponibil.”  
**Appendix:** predictive methods; model governance; alias registry.  
**Likely objection:** Can an exploratory model be piloted operationally?  
**Truthful answer:** No. External validation, calibration, approved action/threshold, harms, human
factors, monitoring, and named approvals are absent.

## Slide 8

**English title:** From synthetic evidence engineering to a governed pilot  
**Concise copy:** The product converts an observation into a review draft containing population,
mechanism hypothesis, workflow, source fields, method, validation, harms, owner, approvals, and stop
criterion.  
**Visual:** Create Pilot Hypothesis workflow; mark all examples synthetic.  
**Romanian speaker notes:** „Nu producem recomandări. Pregătim o întrebare testabilă și condițiile în
care merită sau nu merită analizată pe o sursă aprobată.”  
**Appendix:** pilot charter, scope, RACI, risk register, source fit-for-use.  
**Likely objection:** Is the suggested mechanism established?  
**Truthful answer:** No. It is explicitly a hypothesis requiring an approved design and real-data
validation.

## Slide 9

**English title:** Pilot one question, not an entire platform  
**Concise copy:** Select one decision, one source, one population, one accountable owner, and one
stop criterion. Scale only after source, clinical, statistical, privacy, security, and workflow
evidence passes.  
**Visual:** Stage-4 decision path: blocked → feasibility → independently reviewed decision.  
**Romanian speaker notes:** „Închidem cu o decizie mică și controlabilă. Nu cerem aprobare pentru date
reale sau producție prin această demonstrație.”  
**Appendix:** Stage-4 decision memo template; deployment contract.  
**Likely objection:** Is the application ready for production?  
**Truthful answer:** It is a conditional local Stage-4 candidate. Real-data onboarding, independent
review, security validation, cloud deployment, and operational authorization remain blocked.

## Presentation controls

- Use `Presentation Mode`; Next/Previous apply only approved deterministic states.
- Keep the trust bar visible and controls locked during the live sequence.
- Use `Reset Demo` before and after rehearsal.
- Use `demo_fallback.html` and the four `fallback/*.svg` boards if live interaction fails.
- Exported PNG, accessible report, aggregate CSV, and evidence manifest must retain release and
  prohibited-use context.

