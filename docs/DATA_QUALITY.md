# Data Quality

Critical rules stop `run-all`; warnings are reported and permit continuation. Outputs are `data_quality_summary.json`, `.csv`, and `data_quality_report.md`. Checks cover uniqueness, male-only cohort, all requested chronology constraints, mHSPC/eligibility implications, persistence observability, switch/restart/death/LTFU evidence, no events after death, separation of death/LTFU from adherence, refill coverage and every patient/provider foreign key.

Prescription-event checks additionally enforce unique event IDs, valid patient and treatment foreign keys, patient/treatment and drug/treatment agreement, synthetic product identifiers, service dates within treatment episodes, positive supply and quantity, the coverage-date formula, nonnegative and chronologically correct refill gaps, an `initial_fill` followed only by `refill` events, exactly one initial fill per treatment, explicit synthetic provenance, and agreement between event-level and treatment-level maximum refill gaps.

The executable definitions in `data_quality.py` are authoritative and tested. Missingness is a warning because configured nulls are intentional.
