# Runbook

## Environment

```powershell
cd C:\Endava\EndevLocal\zzzzzzzzzzdate\prostate-patient-journey-synthetic
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

The official optional raw input location is `data/raw/synthea`. With no usable `patients.csv`, generation uses independent offline archetypes and logs that choice.

## Fast profile

```powershell
python -m prostate_journey.cli run-all `
  --config configs/prostate_scenario_quick.yaml `
  --output-dir data/gold_quick
```

This produces 550 patients with the configured seven-market quick allocation. It runs all DQ checks; rare-event readiness coverage can remain partial and therefore the quick config does not enforce the final readiness gate.

## Full analytical profile

```powershell
python -m prostate_journey.cli run-all `
  --config configs/prostate_scenario.yaml `
  --seed 42 `
  --output-dir data/gold
```

The full run creates 10,000 patients, verifies an exact second same-seed generation, runs DQ/readiness/adversarial gates, exports 19 CSV and 19 Parquet tables, builds DuckDB views, and writes reports/dashboard/config/provenance. Expect the reproducibility check to approximately double generation time.

## Verify

```powershell
python -m pytest -q
python -m ruff check src tests
python -m prostate_journey.cli validate --output-dir data/gold
```

Open `data/reports/adversarial_audit.md`, `data/reports/readiness_audit.md`, `data/reports/data_quality_report.md`, and `data/reports/cohort_dashboard.html`.

## Failure recovery

The exception names the failed critical DQ/readiness rules. Inspect the matching CSV/JSON where available, correct generation logic, and rerun. Do not bypass `fail_on_p0_p1` for a final dataset. Quick-profile partial coverage is not evidence that the full dataset is ready.

Generated output is deterministic for scenario inputs and seed. Report timestamps can differ, while all 19 generated tables must remain exactly equal.
