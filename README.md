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
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# Fast development profile
python -m prostate_journey.cli run-all --config configs/prostate_scenario_quick.yaml

# Full 10,000-patient analytical profile and exact same-seed verification
python -m prostate_journey.cli run-all --config configs/prostate_scenario.yaml

# Fresh final certification; refuses dirty source, reused folders, partial scores, or mismatches
python -m prostate_journey.cli final-release --config configs/prostate_scenario.yaml

# Tests and static checks
python -m pytest -q
python -m ruff check src tests
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

`final-release` creates a uniquely named folder under `data/releases`. It reloads and reconciles
the exported CSV, Parquet, and DuckDB artifacts; reruns Ruff and pytest; writes a field-level data
dictionary, market/uncertainty/leakage/realism/reconciliation evidence and the strict 11-dimension
scorecard; then creates separate immutable analytical and QA ZIP archives with SHA-256 manifests.

See [architecture](docs/ARCHITECTURE.md), [data dictionary](docs/DATA_DICTIONARY.md), [business rules](docs/BUSINESS_RULES.md), [data quality](docs/DATA_QUALITY.md), [synthetic assumptions](docs/SYNTHETIC_ASSUMPTIONS.md), and [runbook](docs/RUNBOOK.md).

## Limitations

- Clinical and market distributions are explicit synthetic assumptions, not calibrated estimates.
- The prostate pathway is Python post-processing, not a clinically validated Synthea disease module.
- Scan-market granularity is intentionally lower and documented as structural/market-dependent missingness.
- Associations are probabilistic and useful for pipeline/diagnostic exercises, not treatment-effect estimation.
- No output is population representative; `population_representative_flag` is always false.
