# Runbook

## Environment

```powershell
cd C:\Endava\EndevLocal\zzzzzzzzzzdate\prostate-patient-journey-synthetic
uv sync --frozen --extra dev --python 3.13
```

The official optional raw input location is `data/raw/synthea`. With no usable `patients.csv`, generation uses independent offline archetypes and logs that choice.

## Fast profile

```powershell
uv run prostate-journey run-all `
  --config configs/prostate_scenario_quick.yaml `
  --output-dir data/gold_quick
```

This produces 550 patients with the configured seven-market quick allocation. It runs all DQ checks; rare-event readiness coverage can remain partial and therefore the quick config does not enforce the final readiness gate.

## Full analytical profile

```powershell
uv run prostate-journey run-all `
  --config configs/prostate_scenario.yaml `
  --seed 42 `
  --output-dir data/gold
```

The full run creates 10,000 patients, verifies an exact second same-seed generation, runs DQ/readiness/adversarial gates, exports 19 CSV and 19 Parquet tables, builds DuckDB views, and writes reports/dashboard/config/provenance. Expect the reproducibility check to approximately double generation time.

## Verify

```powershell
uv run ruff format --check src tests eda
uv run ruff check src tests eda
uv run mypy src
uv run pytest
uv run prostate-journey validate --output-dir data/gold
uv run prostate-journey industry-check `
  --dataset-dir data/gold `
  --allow-missing-release
```

Open `data/reports/adversarial_audit.md`, `data/reports/readiness_audit.md`, `data/reports/data_quality_report.md`, and `data/reports/cohort_dashboard.html`.

## Candidate release

Commit all source/config/test/documentation changes first, then run from the clean `dev` commit:

```powershell
uv run prostate-journey final-release `
  --config configs/prostate_scenario.yaml `
  --seed 42 `
  --release-name BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1
```

The command always uses a new staging and release name. It refuses a dirty/reused source, a quick
profile, a stale commit, any DQ/readiness/adversarial/reconciliation mismatch, any score below 100,
or a failed formatting/Ruff/MyPy/contract/pytest run. It reloads CSV/Parquet and checks DuckDB
parity before sealing. Passing means the internal synthetic contract passed; it is not Bayer,
clinical, regulatory, privacy, security or production approval:

```text
data/releases/<dataset-version>/
  analytical_dataset/
  qa_evidence/
  archives/<dataset-version>-analytical.zip
  archives/<dataset-version>-qa-evidence.zip
  RELEASE_DECISION.md
  release_manifest.json
  CHECKSUMS.sha256
  IMMUTABLE_RELEASE
```

Preserve the complete folder. The analytical and QA archives are intentionally separate; use the
hashes in `release_manifest.json` and `CHECKSUMS.sha256` to verify immutability.

## Scientific, multi-seed and predictive evidence

Build both packages only after the candidate exists, so every artifact points to the selected clean
source commit and release identity:

```powershell
$datasetVersion = "BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_v2.2.0_RC1"
$analytical = "data/releases/$datasetVersion/analytical_dataset"

# Build release-matched cohort and longitudinal inputs used by prediction targets.
$env:EDA_DATASET_DIR = $analytical
python eda/00_inventory_and_data_contract.py
python eda/01_data_quality_profile.py
python eda/02_cohort_engine.py
python eda/03_funnel_and_treatment_gap.py
python eda/04_treatment_episode_builder.py
python eda/05_time_to_initiation_and_persistence.py
python eda/06_driver_analysis.py
python eda/07_intervention_backlog.py

uv run prostate-journey scientific-evidence `
  --dataset-dir $analytical

uv run prostate-journey simulation-study `
  --release $datasetVersion `
  --output-dir "outputs/simulations/$datasetVersion"

uv run prostate-journey predictive-evidence `
  --dataset-dir $analytical `
  --eda-dir outputs/eda `
  --output-root outputs/predictive

# Run after all evidence packages exist; this adds scientific_story.html and model_story.html.
uv run prostate-journey presentation-package `
  --dataset-dir $analytical `
  --scientific-dir "outputs/scientific/$datasetVersion" `
  --simulation-dir "outputs/simulations/$datasetVersion" `
  --predictive-dir "outputs/predictive/$datasetVersion"

uv run prostate-journey industry-check `
  --dataset-dir $analytical `
  --scientific-dir "outputs/scientific/$datasetVersion" `
  --simulation-dir "outputs/simulations/$datasetVersion" `
  --predictive-dir "outputs/predictive/$datasetVersion" `
  --presentation-dir "outputs/presentation/$datasetVersion"
```

Scientific, simulation and predictive directories are fresh-path-only. Never edit a sealed package or child
run. If a run fails, retain or quarantine the partial directory for diagnosis and use a new output
name. The strict check requires at least 100 completed seeds in each low/base/high scenario, exact
manifest hashes, chart metadata, separate uncertainty labels, valid probability bounds, and exact
risk-set reconciliation.

The predictive command additionally requires the cohort and longitudinal EDA manifests to match
the selected release and their declared hashes. It rejects a dirty worktree, a
release/source-commit mismatch,
future or prohibited predictors, temporal overlap, patient duplication, held-out-market leakage,
post-seal mutation and any operational alias assignment for a rejected/research-only model. The
final configuration uses 200 patient-level bootstrap repetitions; reduced development smoke runs
must never be presented as release evidence.

Open `outputs/presentation/<dataset-version>/scientific_story.html` for the interactive aggregate
methods view. The presentation receives only aggregate CSV/JSON/Markdown evidence; complete
pre-missingness truth and time-to-event patient records stay outside the stakeholder package.

Open `outputs/presentation/<dataset-version>/model_story.html` for the aggregate Model Evidence
Lab. It contains no patient-level probabilities or score file. `RESEARCH ONLY` and `REJECTED`
states are non-deployable, and decision curves remain blocked until an approved action and
threshold trade-off exist.

## Failure recovery

The exception names the failed critical DQ/readiness rules. Inspect the matching CSV/JSON where available, correct generation logic, and rerun. Do not bypass `fail_on_p0_p1` for a final dataset. Quick-profile partial coverage is not evidence that the full dataset is ready.

Generated output is deterministic for scenario inputs and seed. Report timestamps can differ, while all 19 generated tables must remain exactly equal.
