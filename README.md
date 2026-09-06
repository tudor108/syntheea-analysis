# Prostate Patient Journey Synthetic

> **SYNTHETIC DEMO DATA — NOT REAL BAYER, PATIENT, OR CLINICAL DATA**

This repository generates a deterministic, seven-market prostate patient-journey dataset for diagnostic analysis of:

`eligible population → initiated treatment → sustained treatment → realised synthetic outcomes`

It supports eligible-but-untreated cohorts, initiation windows, regimen intensification, active surveillance, provider/referral pathways, 30/60/90-day persistence sensitivity, right censoring, outcomes, market segmentation, and leakage-safe feature definitions. It does not make treatment recommendations or causal/real-world claims.

## Markets and profiles

The full profile creates 10,000 independent archetypes with explicit unequal sizes:

- Deep: United States 2,600; Germany 1,800; Japan 1,600.
- Scan: France 1,100; China 1,200; Australia 800; Canada 900.

Population, stage, access, care setting, provider density, referral, treatment, follow-up, coding detail, and missingness assumptions are versioned in `configs/markets.yaml`. Deep markets have materially richer event detail. The quick profile creates 550 patients using the configured per-market quick counts.

## Install and run

```powershell
cd C:\Endava\EndevLocal\zzzzzzzzzzdate\prostate-patient-journey-synthetic
uv sync --frozen --extra dev --python 3.13

# Fast development profile
uv run prostate-journey run-all --config configs/prostate_scenario_quick.yaml

# Full 10,000-patient analytical profile and exact same-seed verification
uv run prostate-journey run-all --config configs/prostate_scenario.yaml

# Fresh candidate; refuses dirty source, reused folders, partial scores, or mismatches
uv run prostate-journey final-release `
  --config configs/prostate_scenario.yaml `
  --release-name BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1

# Stakeholder package from the newest complete accepted release only
uv run prostate-journey presentation-package

# Verify and serve the release-matched aggregate frontend
uv run prostate-journey application-check
uv run prostate-journey serve

# Optional AI Analysis Studio: evidence, tactic exploration, isolated specialist runs
uv sync --frozen --extra dev --extra ai
uv run --extra ai prostate-journey ai-catalogue
uv run --extra ai prostate-journey ai-check
uv run --extra ai prostate-journey ai-specialist-check
uv run --extra ai prostate-journey ai-offline-eval
# Explicit metered suite with a strict application cutoff below $2
uv run --extra ai prostate-journey ai-live-eval
uv run --extra ai prostate-journey ai-sync-vector-store
uv run --extra ai prostate-journey ai-studio
# Provider-free ten-frame fallback plus one explicit deterministic isolated run
uv run --extra ai prostate-journey ai-demo-package --confirm-run

# Release-locked survival, competing-risk, missingness and utility evidence
uv run prostate-journey scientific-evidence

# Low/base/high multi-seed study (100 seeds per scenario, adaptive if needed)
uv run prostate-journey simulation-study `
  --release <dataset-version> `
  --output-dir outputs/simulations/<dataset-version>

# Leakage-safe predictive research evaluation from release-matched EDA inputs
uv run prostate-journey predictive-evidence `
  --dataset-dir data/releases/<dataset-version>/analytical_dataset `
  --eda-dir outputs/eda

# Rebuild after evidence packages exist to add the Science and Model Evidence labs
uv run prostate-journey presentation-package

# Complete local quality gates
uv run ruff format --check src tests eda
uv run ruff check src tests eda
uv run mypy src
uv run pytest
uv run prostate-journey industry-check --allow-missing-release
```

Synthea CSV input in `data/raw/synthea` is optional. Eligible raw patient rows are used at most once; any shortfall is filled with newly generated independent archetypes, never by cloning. With no raw input, the generator is fully offline and records `source_record_type=generated_archetype`.

## Outputs

`data/gold` contains 19 relational/analytical tables in CSV and Parquet plus `prostate_journey.duckdb`. `data/reports` contains:

- DQ results in JSON, CSV, and Markdown;
- a 25-requirement readiness matrix and 0–100 scorecard;
- a separate 25-attack adversarial audit that recalculates eligibility, persistence,
  chronology, provider/referral coherence, leakage and deliverable metrics directly from records;
- schema, missingness, market, KPI, and cohort summaries;
- configuration snapshot, run metadata, SHA-256 file hashes, and table fingerprints;
- a self-contained HTML dashboard.

`run-all` and `report` also create healthcare analysis extracts: a censor-aware 30/60/90-day
initiation funnel, 12-month persistence sensitivity, referral delay summary, and market-level
missingness profile. See [healthcare data analysis](docs/HEALTHCARE_DATA_ANALYSIS.md) for the
recommended tactics and guardrails.

`final-release` creates a uniquely named candidate folder under `data/releases`. It reloads and reconciles
the exported CSV, Parquet, and DuckDB artifacts; reruns formatting, Ruff, MyPy, contract and pytest
gates; writes a field-level data
dictionary, market/uncertainty/leakage/realism/reconciliation evidence and the strict 11-dimension
scorecard; then creates separate immutable analytical and QA ZIP archives with SHA-256 manifests.

`presentation-package` creates an aggregate-only package under `outputs/presentation/<dataset-version>`.
It locks every report and dashboard to one accepted immutable release, records source and analysis provenance,
and fails if headline cohort and dashboard KPIs disagree. Open `executive_story.html` for the
four-view Executive, Analyst, Methodology, and Governance product with synchronized analytical
context, denominator-change notices, evidence drawers, Presentation Mode, and governed exports, or
`cohort_dashboard.html` for the compact analytical view. The interactive view also contains a
searchable ten-tactic library sourced from `configs/tactic_registry.yaml`; each tactic opens its
question, population, numerator, denominator, method, result, limitation, and release evidence.
No patient-level export or AI dependency is included. Use `accessible_report.html` for the linear
report and `demo_fallback.html` if interactive presentation is unavailable. When the release-matched scientific and simulation
packages exist, it also creates `scientific_story.html`: an interactive methods cockpit with three
separate uncertainty layers, endpoint switching, survival/competing-risk summaries, missingness
truth recovery, utility dimensions, and openable scientific tactic cards.
When a release/commit-matched sealed predictive package exists, it also creates
`model_story.html`, with interactive target contracts, exact population attrition, temporal and
market validation, prevalence-aware discrimination, calibration, robustness, subgroup-support
warnings, dispositions and the explicitly blocked decision-utility gate.

`scientific-evidence` creates a fresh, sealed package under `outputs/scientific/<dataset-version>`.
It includes the analysis registry snapshots, Kaplan–Meier/Greenwood output, exact at-risk tables,
Aalen–Johansen cumulative incidence, Wilson estimator intervals, MCAR/MAR/MNAR truth-recovery
evidence, dimension-specific utility checks, strict frontend JSON, and an artifact manifest.

`simulation-study` creates immutable child runs plus within-scenario intervals, Monte Carlo error,
low/base/high scenario envelopes, sensitivity drivers, plain-language explanations, and a sealed
parent manifest. Regeneration, scenario, and estimator uncertainty are never combined under one
generic confidence-interval label. See the [v2.2 scientific methods](docs/SCIENTIFIC_METHODS_V2.2.md)
and [scientific implementation status](docs/PROMPT2_SCIENTIFIC_IMPLEMENTATION_REPORT.md).

`predictive-evidence` creates a fresh, sealed, aggregate-only package under
`outputs/predictive/<dataset-version>`. Four model contracts are evaluated with train-only nested
preprocessing, inner-temporal calibration, repeated rolling validation, one untouched temporal
holdout, development-only leave-one-market-out stress, patient-bootstrap uncertainty, flexible
calibration, subgroup support and a prespecified robustness battery. Automatic disposition cannot
exceed `RESEARCH ONLY`; rejected/research-only models cannot enter an operational alias. See the
[predictive methods](docs/PREDICTIVE_METHODS_V2.2.md) and
[Prompt 3 implementation report](docs/PROMPT3_PREDICTIVE_IMPLEMENTATION_REPORT.md).
Generation fails unless the analysis runs from the exact release source commit with a clean Git
worktree.

See [architecture](docs/ARCHITECTURE.md), [data dictionary](docs/DATA_DICTIONARY.md),
[business rules](docs/BUSINESS_RULES.md), [data quality](docs/DATA_QUALITY.md),
[synthetic assumptions](docs/SYNTHETIC_ASSUMPTIONS.md), and [runbook](docs/RUNBOOK.md).

The v2.2 control set is documented in the [industry-readiness crosswalk](docs/INDUSTRY_READINESS_CROSSWALK.md),
[claim–evidence register](docs/CLAIM_EVIDENCE_REGISTER.md), [risk register](docs/RISK_REGISTER.md),
[Stage-4 exit criteria](docs/STAGE4_EXIT_CRITERIA.md), [release/change control](docs/RELEASE_AND_CHANGE_CONTROL.md),
and [ranked unresolved backlog](docs/IMPLEMENTATION_BACKLOG.md). These are review lenses and internal
controls, not formal compliance claims.

For the current maturity assessment and presentation plan, see the
[project status and industry roadmap](docs/PROJECT_STATUS_AND_ROADMAP.md) and
[presentation storyboard](docs/PRESENTATION_STORYBOARD.md). Use the separate
[current project handoff](docs/PROJECT_HANDOFF_CURRENT_STATE.md) for everything delivered so far
and the [GPT-5 Pro meta-prompt](docs/GPT5_PRO_META_PROMPT.md) as the copy-ready prompt for
generating the next specialized review and implementation prompts.

For local application/container operations and the proposed AWS handoff, see the
[local runbook](docs/LOCAL_RUNBOOK.md), [deployment contract](docs/DEPLOYMENT_CONTRACT.md), and
[AWS target architecture](docs/AWS_TARGET_ARCHITECTURE.md). The former
[Google Cloud checklist](docs/GCP_SETUP_CHECKLIST_RO.md) is retained as superseded history only.

For the polished deterministic stakeholder experience, see the
[executive presentation package](docs/EXECUTIVE_PRESENTATION_PACKAGE.md),
[five-minute demo](docs/FIVE_MINUTE_DEMO.md), [accessibility report](docs/ACCESSIBILITY_TEST_REPORT.md),
and [Prompt 5 red-team review](docs/PROMPT5_RED_TEAM_REVIEW.md). The exact Evidence Copilot handoff
and non-indexable paths are recorded under `NEXT: EVIDENCE COPILOT` in
[implementation state](docs/IMPLEMENTATION_STATE.md).

The optional AI companion and isolated specialist-analysis workflow are documented in the
[AI Analysis Studio handoff](docs/AI_ANALYSIS_STUDIO_HANDOFF.md),
[local runbook](docs/AI_ANALYSIS_STUDIO_RUNBOOK.md), and
[threat model](docs/AI_ANALYSIS_STUDIO_THREAT_MODEL.md). The final operator experience is covered
by the [five-minute AI demo](docs/AI_STUDIO_DEMO_SCRIPT.md),
[user guide](docs/AI_STUDIO_USER_GUIDE.md),
[security and cost note](docs/AI_STUDIO_SECURITY_AND_COST.md), and
[final red-team report](docs/AI_STUDIO_RED_TEAM_REPORT.md). It uses one release-scoped aggregate
catalogue, deterministic metric/denominator tools, validated citations, strict analysis specs,
explicit execution confirmation, read-only certified snapshots, isolated experiment outputs, and
a separate service. Models never receive patient-level data, and the product provides no
patient-level export. Interactive results cannot become certified without an independent controlled
release process.
AI prices and bounded request profiles are centralized in `configs/ai_cost_controls.yaml`; atomic
pre-request reservations prevent parallel session overspend and the Cost & usage view reconciles
metered tokens and File Search calls. See the
[AI FinOps/security/evaluation runbook](docs/AI_FINOPS_SECURITY_EVALUATION_RUNBOOK.md) and
[latest AI evaluation report](docs/AI_EVALUATION_REPORT.md). Offline CI does not call OpenAI; the
fixed live suite is an explicit metered operation that must stop below $2. The current live run is
reported as failed, not accepted, because provider availability/quota prevented all 30 cases from
completing.

## Exploratory data analysis foundation

The repository includes a reproducible, aggregate-only EDA foundation that inventories repository
data, profiles the accepted candidate schema, validates longitudinal healthcare rules, analyzes
missingness across market/pathway/outcome dimensions, reconciles normalized tables with the
patient-journey mart, and produces privacy-safe SVG figures.

```powershell
# Uses the newest complete accepted candidate release by default
python eda/00_inventory_and_data_contract.py
python eda/01_data_quality_profile.py

# Optional explicit accepted 19-table release dataset
$env:EDA_DATASET_DIR = "C:\path\to\analytical_dataset"

# Exploratory-only working gold opt-in (never a presentation source)
$env:EDA_ALLOW_WORKING_GOLD = "1"
```

Release-scoped EDA profiles the data and fields, executes quality and mart reconciliation checks,
and creates one `eda_artifact_manifest.json` that maps every output to the selected release,
configuration hash, source commit, code version and active definitions. Exact disease states such
as `mHSPC` and `mCRPC` remain distinct, active surveillance is a separate pathway, missing values
are not silently imputed, and dataset end is treated as censoring rather than discontinuation.

Key outputs are written under `outputs/eda/`:

- `eda_report.md`, assumptions, top issues and downstream readiness;
- data inventory, field dictionary, temporal coverage and aggregate missingness profiles;
- normalized-to-mart reconciliation and a hash-based reproducibility manifest;
- aggregate figures under `outputs/eda/figures/`.

Generated gold, reports, releases, EDA, scientific, simulation, predictive, and presentation files are
intentionally excluded from Git.
See the [generated-artifact policy](docs/GENERATED_ARTIFACT_POLICY.md); a clean clone cannot inherit
an old analytical snapshot silently.

## Limitations

- Clinical and market distributions are explicit synthetic assumptions, not calibrated estimates.
- The prostate pathway is Python post-processing, not a clinically validated Synthea disease module.
- Scan-market granularity is intentionally lower and documented as structural/market-dependent missingness.
- Associations are probabilistic and useful for pipeline/diagnostic exercises, not treatment-effect estimation.
- No output is population representative; `population_representative_flag` is always false.
