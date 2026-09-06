# Generated artifact and source-of-truth policy

## Authority order

1. Git commit: implementation, configuration, tests, contracts and governance documents.
2. Immutable release directory: generated analytical dataset and QA evidence for that commit.
3. EDA/scientific/simulation/presentation manifests: hash mappings to one source identity.
4. Working `data/gold`, `data/reports` and local outputs: disposable development artifacts with no
   presentation authority.

## Repository policy

The following generated paths are intentionally ignored and must not be committed as source:

```text
data/generated/
data/releases/
data/gold/* (except .gitkeep)
data/reports/* (except .gitkeep)
outputs/eda/
outputs/presentation/
outputs/industry_readiness/
outputs/scientific/
outputs/simulations/
analysis_extensions/*/outputs/
```

Existing local files were untracked, not deleted. They may be used for forensic comparison but may
not become a presentation source. A clean clone starts without those snapshots.

## Selection rules

- EDA, models and stakeholder packages resolve the newest complete accepted release or an explicit
  analytical directory whose parent manifest identifies it as that release.
- `data/gold` requires explicit `EDA_ALLOW_WORKING_GOLD=1` or CLI `--allow-working-gold` and must be
  labelled non-release.
- Presentation building never permits working-gold fallback.
- A candidate directory is never reused or overwritten.
- Scientific and simulation packages use fresh output paths and immutable child/parent hash markers.
- Presentation copies only declared aggregate scientific artifacts; complete truth and event-record
  Parquet files never enter the stakeholder package.
- Manual copying between release, EDA, scientific, simulation and presentation directories is
  prohibited.

## Required provenance

Every released or stakeholder artifact must be represented in a manifest with:

- dataset release ID;
- source commit;
- configuration SHA-256;
- code/generator version;
- UTC generation timestamp;
- active analytical definition;
- artifact byte size and SHA-256;
- synthetic-only/prohibited-use boundary.

The `industry-check` command verifies this mapping for the release, scientific package, multi-seed
study, and presentation and can also validate the EDA artifact manifest.

## Retention and publication

Retention, legal hold, region, encryption and deletion schedules require organizational approval
before real data. For the current synthetic project, preserve the selected candidate plus its QA
archive in an approved artifact location; old local working outputs can be regenerated and have no
release status.
