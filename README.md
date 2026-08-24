# Prostate Patient Journey Synthetic

> **SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA**

Reproducible Data & AI demo for studying synthetic prostate-cancer patient journeys. It describes cohorts and treatment gaps; it does **not** diagnose disease, recommend individual treatment, or provide clinical/commercial evidence. Configured distributions are scenario assumptions requiring validation.

## Architecture and provenance

[Synthea](https://github.com/synthetichealth/synthea) supplies base demographics and may supply conditions, encounters, providers, organizations, medications, observations and payer records through its CSV export. The Python enrichment adds the prostate-specific oversampled cohort, stage/mHSPC state, demo ARPI eligibility, provider pathway, referral, longitudinal treatment/refills, outcomes and analytics features. If `patients.csv` is absent, the pipeline creates a deterministic Synthea-shaped sample so the demo remains runnable offline; this fallback is clearly logged.

An **outcome** is a generated follow-up state/event. Initiation is first treatment after eligibility; persistence is coverage without a gap beyond the configured threshold; discontinuation is a definitive stop distinct from switch, temporary gap/restart, death, loss to follow-up and censoring; switch is a different drug within the configured window; censoring ends observable follow-up without treating it as an event.

## Install (Windows PowerShell)

Prerequisites: Git, Java JDK 17+, and Python 3.11+.

```powershell
cd C:\Endava\EndevLocal\zzzzzzzzzzdate\prostate-patient-journey-synthetic
powershell -ExecutionPolicy Bypass -File .\scripts\setup_environment.ps1
.\.venv\Scripts\Activate.ps1
```

Generate official Synthea CSV (default 25,000 base patients; can take substantial time):

```powershell
.\scripts\run_synthea.ps1 -Population 25000 -Seed 42 -State Massachusetts
```

Run the complete 10,000-patient enrichment or a quick sample:

```powershell
python -m prostate_journey.cli run-all --config configs/prostate_scenario.yaml --seed 42 --cohort-size 10000
.\scripts\run_pipeline.ps1 -CohortSize 1000 -Seed 42
```

Individual stages:

```powershell
python -m prostate_journey.cli generate --cohort-size 1000
python -m prostate_journey.cli validate
python -m prostate_journey.cli build-gold --cohort-size 1000
python -m prostate_journey.cli load-duckdb
python -m prostate_journey.cli report
python -m prostate_journey.cli run-all --cohort-size 1000
```

Test and lint:

```powershell
python -m pytest -q
python -m ruff check src tests
```

## Outputs

Every normalized table (`patient`, `diagnosis`, `provider`, `encounter`, `treatment`, `prescription_event`, `outcome`) and `patient_journey` is exported to CSV and Parquet in `data/gold`. DuckDB contains all tables and eight analytics views, including `vw_treatment_gap_by_segment`. Reports include DQ JSON/CSV/Markdown, cohort summary/KPIs, configuration snapshot, environment metadata and SHA-256 hashes.

The generated visual dashboard is [cohort_dashboard.html](data/reports/cohort_dashboard.html). Open it directly in a browser; it groups the cohort into cards and SVG charts for the funnel, stage, care setting, treatment gap, persistence, outcomes, treatments and high-gap segments. Regenerate it with `python -m prostate_journey.cli dashboard` or, on a machine without the Python environment installed, `py -3.13 scripts/create_cohort_dashboard.py`.

`population_representative_flag` is always false. Oversampling means prevalence and rates are not population estimates. See [business rules](docs/BUSINESS_RULES.md), [data dictionary](docs/DATA_DICTIONARY.md), [assumptions](docs/SYNTHETIC_ASSUMPTIONS.md), [DQ](docs/DATA_QUALITY.md), [architecture](docs/ARCHITECTURE.md), and [runbook](docs/RUNBOOK.md).

For a Romanian explanation of the implementation, data flow, business rules, tables, commands and outputs, see [Ghid de implementare în română](docs/GHID_DE_IMPLEMENTARE_RO.md).

## Limitations

- The prostate pathway is post-processing, not a clinical Synthea module.
- Scenario probabilities are illustrative and intentionally noisy, not calibrated estimates.
- The fallback base input is Synthea-shaped rather than an executed Synthea population.
- This release generates descriptive/model-ready baseline features but no clinical prediction model.
- Synthetic causal associations must not be interpreted as real treatment effects.
