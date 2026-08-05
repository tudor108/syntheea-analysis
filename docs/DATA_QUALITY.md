# Data Quality

Critical rules stop `run-all`; warnings are reported and permit continuation. Outputs are `data_quality_summary.json`, `.csv`, and `data_quality_report.md`. Checks cover uniqueness, male-only cohort, all requested chronology constraints, mHSPC/eligibility implications, persistence observability, switch/restart/death/LTFU evidence, no events after death, separation of death/LTFU from adherence, refill coverage and every patient/provider foreign key. The executable definitions in `data_quality.py` are authoritative and tested. Missingness is a warning because configured nulls are intentional.

