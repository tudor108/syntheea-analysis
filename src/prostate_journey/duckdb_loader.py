"""Load normalized exports into DuckDB and create analytics views."""
from __future__ import annotations

from pathlib import Path
import duckdb


def load_duckdb(gold_dir: str | Path) -> Path:
    """Materialize all Parquet tables and documented analytical views."""
    root = Path(gold_dir); db_path = root / "prostate_journey.duckdb"
    con = duckdb.connect(str(db_path))
    for table in ("patient", "diagnosis", "provider", "encounter", "treatment", "outcome", "patient_journey"):
        path = (root / f"{table}.parquet").as_posix().replace("'", "''")
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_parquet('{path}')")
    con.execute("CREATE OR REPLACE VIEW vw_eligible_population AS SELECT * FROM patient_journey WHERE eligible_for_arpi")
    con.execute("CREATE OR REPLACE VIEW vw_eligible_not_initiated AS SELECT * FROM patient_journey WHERE eligible_not_initiated_90d")
    con.execute("CREATE OR REPLACE VIEW vw_treatment_initiation AS SELECT * FROM patient_journey WHERE treatment_initiated")
    con.execute("CREATE OR REPLACE VIEW vw_persistence AS SELECT patient_id, persistent_3m, persistent_6m, persistent_12m FROM patient_journey WHERE treatment_initiated")
    con.execute("CREATE OR REPLACE VIEW vw_switches AS SELECT * FROM patient_journey WHERE switch_flag")
    con.execute("CREATE OR REPLACE VIEW vw_referral_delays AS SELECT patient_id, initial_care_setting, referral_delay_days FROM patient_journey")
    con.execute("CREATE OR REPLACE VIEW vw_final_outcomes AS SELECT patient_id, final_outcome_status, death_flag, lost_to_follow_up_flag FROM patient_journey")
    con.execute("""CREATE OR REPLACE VIEW vw_treatment_gap_by_segment AS
        SELECT initial_care_setting AS care_setting, initial_provider_specialty AS provider_specialty, region,
        CASE WHEN age_at_index < 65 THEN '<65' WHEN age_at_index < 75 THEN '65-74' ELSE '75+' END AS age_group,
        CASE WHEN comorbidity_score < 2 THEN 'low' WHEN comorbidity_score < 4 THEN 'medium' ELSE 'high' END AS comorbidity_group,
        count(*) FILTER (WHERE eligible_for_arpi) AS eligible,
        count(*) FILTER (WHERE initiated_within_90d) AS initiated_90d,
        count(*) FILTER (WHERE eligible_not_initiated_90d) AS treatment_gap
        FROM patient_journey GROUP BY ALL""")
    con.close()
    return db_path
