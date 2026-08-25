"""Materialize generated Parquet contracts in DuckDB."""

from __future__ import annotations

from pathlib import Path

import duckdb

TABLES = (
    "patient",
    "diagnosis",
    "disease_state_event",
    "eligibility",
    "organization",
    "provider",
    "encounter",
    "referral",
    "active_surveillance",
    "observation",
    "treatment_episode",
    "treatment_regimen",
    "treatment_regimen_component",
    "prescription_event",
    "adverse_event",
    "outcome",
    "patient_split",
    "feature_timing",
    "patient_journey",
)


def load_duckdb(gold_dir: str | Path) -> Path:
    """Load every normalized table and analytical views into one database."""
    root = Path(gold_dir)
    db_path = root / "prostate_journey.duckdb"
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    for table in TABLES:
        path = (root / f"{table}.parquet").as_posix().replace("'", "''")
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_parquet('{path}')")
    con.execute(
        "CREATE OR REPLACE VIEW vw_eligible_population AS "
        "SELECT * FROM patient_journey WHERE eligibility_flag"
    )
    con.execute(
        "CREATE OR REPLACE VIEW vw_eligible_not_initiated AS "
        "SELECT * FROM patient_journey WHERE eligible_not_initiated_90d"
    )
    con.execute(
        "CREATE OR REPLACE VIEW vw_treatment_initiation AS "
        "SELECT * FROM patient_journey WHERE treatment_initiated"
    )
    con.execute(
        "CREATE OR REPLACE VIEW vw_persistence AS SELECT patient_id, market_code, "
        "persistence_3m_status, persistence_6m_status, persistence_12m_status, "
        "censor_reason FROM patient_journey WHERE treatment_initiated"
    )
    con.execute(
        "CREATE OR REPLACE VIEW vw_active_surveillance AS "
        "SELECT * FROM patient_journey WHERE active_surveillance_status <> 'not_applicable'"
    )
    con.execute(
        "CREATE OR REPLACE VIEW vw_referral_pathway AS SELECT patient_id, market_code, "
        "referral_status, referral_delay_days, decision_owner_specialty, "
        "initial_care_setting FROM patient_journey"
    )
    con.execute(
        """CREATE OR REPLACE VIEW vw_treatment_gap_by_segment AS
        SELECT market_code, initial_care_setting, complexity_segment, region,
        CASE WHEN age_at_index < 65 THEN '<65'
             WHEN age_at_index < 75 THEN '65-74' ELSE '75+' END AS age_group,
        count(*) FILTER (WHERE eligibility_flag) AS eligible,
        count(*) FILTER (WHERE initiated_within_90d) AS initiated_90d,
        count(*) FILTER (WHERE eligible_not_initiated_90d) AS treatment_gap
        FROM patient_journey GROUP BY ALL"""
    )
    con.execute(
        """CREATE OR REPLACE VIEW vw_market_opportunity AS
        SELECT market_code, market_depth, count(*) AS patients,
        count(*) FILTER (WHERE eligibility_flag) AS eligible,
        count(*) FILTER (WHERE treatment_initiated) AS initiated,
        count(*) FILTER (WHERE eligible_not_initiated_90d) AS treatment_gap,
        count(*) FILTER (WHERE persistence_12m_status = 'PERSISTENT') AS persistent_12m,
        count(*) FILTER (WHERE persistence_12m_status = 'CENSORED_NOT_EVALUABLE') AS censored_12m
        FROM patient_journey GROUP BY ALL"""
    )
    con.close()
    return db_path
