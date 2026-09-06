# GPT-5 Pro meta-prompt — Bayer and Data & AI advancement

**Purpose:** Copy the complete prompt below into GPT-5 Pro. This file contains only the prompt; the factual project handoff is in `PROJECT_HANDOFF_CURRENT_STATE.md`.

---

You are a senior multidisciplinary review panel helping us transform a synthetic healthcare
analytics repository into an exceptional, credible, pilot-ready accelerator and presentation for:

1. senior stakeholders at Bayer;
2. healthcare data scientists and real-world-evidence specialists;
3. the Data & AI community;
4. cloud, data-engineering, governance, and MLOps reviewers.

Think simultaneously as:

- a pharma RWE and HEOR analytics lead;
- a biostatistician and epidemiologist;
- an oncology clinical-domain reviewer;
- a senior data scientist and responsible-AI reviewer;
- a data architect and AWS/ECS MLOps architect;
- a product designer specializing in analytical storytelling;
- a skeptical Bayer executive deciding whether to fund a pilot;
- an adversarial auditor looking for leakage, denominator, provenance, and overclaiming problems.

## Project context

We have built a deterministic synthetic prostate patient-journey analytics accelerator with:

- 10,000 synthetic patients across US, DE, JP, FR, CN, AU, and CA;
- 19 normalized and analytical tables;
- 105 fields in a patient-level analytical mart;
- versioned market, clinical, eligibility, treatment, missingness, and persistence assumptions;
- explicit index dates, denominators, eligibility, exclusions, observation windows, and censoring;
- initiation windows at 30/60/90 days;
- active surveillance, referrals, treatment episodes, regimens, dispensing, persistence,
  discontinuation, switch, restart, outcomes, and leakage-safe feature timing;
- 90 data-quality checks, 25 readiness checks, and 25 adversarial checks;
- an immutable certified release with hashes, provenance, analytical and QA archives;
- 56 passing automated tests and passing Ruff checks;
- an aggregate-only presentation package locked to one certified release;
- a responsive HTML/CSS/JavaScript frontend with synchronized market filtering;
- a searchable ten-tactic analysis library where each tactic opens its method, current result,
  interpretation, limitation, and evidence file;
- a local container and AWS deployment handoff; the old Google Cloud checklist is superseded.

The certified presentation source currently has:

- total synthetic cohort: 10,000;
- eligible: 2,281;
- initiated within 90 days among eligible: 1,700;
- eligible and evaluable but not initiated within 90 days: 581;
- evaluable at 12 months among eligible 90-day initiators: 1,614;
- persistent at 12 months in that evaluable cohort: 941;
- censored before the 12-month persistence assessment: 86.

Predictive baselines on temporal holdouts:

- non-initiation: ROC AUC 0.668, PR AUC 0.394 — moderate exploratory signal;
- discontinuation: ROC AUC 0.472 — not useful;
- switch: ROC AUC 0.573 — weak;
- restart: ROC AUC 0.525 — near random.

All data and results are synthetic scenario outputs. They are not real Bayer data, clinical
evidence, causal evidence, market-size estimates, treatment recommendations, or population
estimates. Do not invent metrics, validation, users, approvals, integrations, or business impact.

Current maturity is Stage 3/5: validated analytical demonstration. Our realistic next target is
Stage 4/5: pilot-ready accelerator. Stage 5 requires governed real data, external validation,
clinical/privacy/security approval, interoperability, operations, and monitoring.

## Your mission

Challenge the project deeply and design the strongest truthful route to make the work memorable,
technically impressive, commercially relevant, and credible to skeptical experts.

Do not give generic suggestions such as “improve the model,” “add more charts,” or “use AI.” Every
recommendation must state:

- the problem it solves;
- the concrete deliverable;
- required inputs and dependencies;
- implementation outline;
- acceptance criteria;
- presentation value;
- scientific or operational risk;
- effort and priority;
- whether it can be completed using synthetic data or requires real data/SME approval.

## Required output

### A. Brutal but constructive assessment

1. Identify the ten strongest parts of the project.
2. Identify the ten biggest credibility risks or missing pieces.
3. List the questions a Bayer executive, oncologist, RWE lead, statistician, data engineer,
   responsible-AI reviewer, and security reviewer would each ask.
4. Identify any claims that should be removed, softened, or better evidenced.

### B. “Wow without hype” presentation concept

Design a 12-minute presentation plus a five-minute live demo:

- slide-by-slide title and objective;
- exact key message per slide;
- recommended visual;
- speaker notes;
- likely objection and answer;
- what belongs in the appendix;
- one memorable opening and one credible closing ask.

The narrative must work for non-technical executives and still survive expert scrutiny.

### C. Interactive analytics-product design

Review the described frontend and propose the next professional version:

- information architecture;
- executive, analyst, methodology, and governance views;
- filters and cross-filter interactions;
- tactic cards and drill-down behavior;
- chart selection;
- accessibility;
- responsive behavior;
- empty/loading/error states;
- provenance and synthetic-data labeling;
- export and presentation mode;
- actions that turn findings into testable workflow hypotheses.

Provide a prioritized component backlog and explicit acceptance criteria. Prefer progressive
disclosure and plain-language explanations over a dense wall of charts.

### D. Data-science advancement plan

Provide a technically specific roadmap for:

- multi-seed and low/base/high scenario simulation;
- separating sampling uncertainty from scenario uncertainty;
- survival confidence intervals and number-at-risk tables;
- competing-risk analysis;
- longitudinal and hierarchical market models;
- missing-data sensitivity and missingness mechanisms;
- predictive baselines, temporal validation, leave-one-market-out validation, calibration,
  decision curves, subgroup uncertainty, and drift tests;
- synthetic-data utility, realism, and disclosure-risk evaluation;
- honest criteria for deciding that a model should not be deployed.

For every method, specify the estimand or target, denominator, assumptions, outputs, tests, and
how it would be explained to a non-technical audience.

### E. Pilot-ready engineering and cloud plan

Design the minimum credible AWS architecture using private/versioned S3 artifacts, immutable ECR
images, ECS on Fargate only where an application process is required, CloudFront where static
delivery is appropriate, IAM role separation, Secrets Manager, CloudWatch, authentication, budget
controls, and audit evidence. Do not describe AWS as already deployed.

Separate:

- what should be implemented now;
- what should wait until a real use case exists;
- what is unnecessary overengineering;
- controls required before any real patient data is processed.

Include CI/CD gates, environment promotion, rollback, lineage, model/data monitoring, RACI, and
definition-of-done criteria.

### F. Deliver a library of copy-ready prompts

Create at least 15 high-quality prompts that we can run separately with GPT-5 Pro. Include prompts
for:

1. pharma executive narrative;
2. RWE methodology review;
3. oncology clinical-definition review;
4. biostatistical review;
5. cohort and denominator adversarial audit;
6. longitudinal and censoring audit;
7. predictive-model evaluation;
8. synthetic-data realism and utility;
9. responsible-AI and prohibited-use review;
10. AWS architecture and deployment-contract review;
11. MLOps and CI/CD implementation;
12. frontend UX and accessibility review;
13. visual and slide redesign;
14. hostile stakeholder Q&A rehearsal;
15. pilot proposal and statement of work;
16. Data & AI community technical talk;
17. final red-team review before presentation.

Each prompt must be self-contained and include:

- role;
- required context;
- task;
- constraints;
- expected output format;
- acceptance criteria;
- anti-hallucination instruction;
- explicit synthetic-data guardrail.

### G. Prioritized execution plan

Create:

- a top-ten backlog ranked by impact, credibility, effort, and dependency;
- a 7-day presentation sprint;
- a 30-day engineering and analysis plan;
- a 60–90-day pilot-readiness plan;
- a “do not build yet” list;
- objective exit criteria for Stage 4/5.

Use a table with owner profile, effort, dependencies, deliverable, validation, and presentation
impact.

### H. Final recommendation

End with:

1. the three changes most likely to impress Bayer;
2. the three changes most likely to impress the Data & AI community;
3. the three changes most important for scientific credibility;
4. the single next action we should take tomorrow morning;
5. a concise and truthful one-paragraph pitch.

## Quality bar

- Be specific, critical, and implementation-oriented.
- Distinguish facts, assumptions, proposals, and required external validation.
- Do not manufacture business value or clinical evidence.
- Treat weak model results honestly.
- Prefer a narrow credible pilot over a fake production claim.
- Use current primary/official sources and cite them when web access is available.
- Explain technical recommendations in language suitable for both experts and executives.
- Write the strategic explanation in Romanian, but provide presentation titles, slide copy,
  architecture labels, frontend copy, and all generated prompts in professional English.
