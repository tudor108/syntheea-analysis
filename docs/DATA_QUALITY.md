# Data Quality and Readiness Gates

`validate_tables` executes critical cross-table rules. Any failure stops `run-all` before gold export. The generated report preserves rule, severity, status, failure count, and evidence.

Coverage includes:

- non-null/unique PKs for all 19 tables and zero orphan patient/provider/organization/treatment FKs;
- DOB/diagnosis and downstream chronology, positive intervals, valid state transitions, and no events after censor/death/LTFU;
- DOB-derived age, Gleason/ISUP, metastatic/hormonal coherence, and eligibility reconstruction/reasons;
- provider specialty/setting consistency, distinct referral endpoints, referral completion chronology, and treatment-specialty compatibility;
- regimen/component containment, intensification reconstruction, prescription sequence/coverage/summary agreement;
- switch/restart non-overlap, no old-line fills after switch, and AS transition logic;
- right-censor persistence, nullable status/flag agreement, and monotonic 30/60/90 sensitivity;
- patient/archetype split isolation and feature-timing leakage prevention;
- mart reconciliation for eligibility, initiation, outcomes, and care setting.

The independent readiness audit evaluates the 25 requested acceptance requirements. Each contributes four points; score is computed from actual results, not assigned. Outputs include:

- `readiness_requirement_matrix.csv` and `readiness_audit.md/json`;
- `readiness_scorecard.csv` by category;
- `adversarial_audit.md/json` and `adversarial_audit_scorecard.csv`, produced by a separate record-level recalculation that does not consume the readiness score;
- `schema_summary.csv`, `missingness_summary.csv`, and `market_summary.csv`;
- stable content/schema fingerprints for every table.

Full runs also generate every table twice with the same seed and require exact equality. `runtime_reproducibility_verified=true` is saved in the final configuration snapshot only after that check succeeds.

Run manually:

```powershell
python -m prostate_journey.cli validate --output-dir data/gold
python -m pytest -q
python -m ruff check src tests
```
