"""Cross-table data quality rules and machine-readable reporting."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pandas as pd

from . import DISCLAIMER


def _result(rule: str, severity: str, failures: int, detail: str) -> dict:
    return {"rule": rule, "severity": severity, "status": "pass" if failures == 0 else "fail", "failure_count": int(failures), "detail": detail}


def validate_tables(tables: dict[str, pd.DataFrame]) -> list[dict]:
    """Execute critical chronology, logic, uniqueness and FK rules."""
    p, d, pr, e, t, rx, o, j = (
        tables[k]
        for k in (
            "patient", "diagnosis", "provider", "encounter", "treatment",
            "prescription_event", "outcome", "patient_journey",
        )
    )
    results: list[dict] = []
    add: Callable[[str, str, int, str], None] = lambda rule, sev, count, detail: results.append(_result(rule, sev, count, detail))
    add("patient_unique", "critical", p.patient_id.duplicated().sum(), "patient_id must be unique")
    add("treatment_unique", "critical", t.treatment_id.duplicated().sum(), "treatment_id must be unique")
    add(
        "prescription_event_unique",
        "critical",
        rx.prescription_event_id.duplicated().sum(),
        "prescription_event_id must be unique",
    )
    add("male_only", "critical", (~p.sex.eq("male")).sum(), "prostate cohort contains males only")
    pdx = p[["patient_id", "birth_date"]].merge(d[["patient_id", "diagnosis_date", "metastatic_date"]], on="patient_id")
    add("birth_before_diagnosis", "critical", (pdx.birth_date >= pdx.diagnosis_date).sum(), "birth precedes diagnosis")
    add("diagnosis_before_metastatic", "critical", (pdx.metastatic_date.notna() & (pdx.diagnosis_date > pdx.metastatic_date)).sum(), "diagnosis <= metastatic")
    add("eligibility_before_treatment", "critical", (j.treatment_start_date.notna() & (j.eligibility_date > j.treatment_start_date)).sum(), "eligibility <= start")
    add("treatment_dates", "critical", (t.treatment_end_date.notna() & (t.treatment_start_date >= t.treatment_end_date)).sum(), "start < end")
    death_birth = p[["patient_id", "birth_date"]].merge(o[["patient_id", "death_date", "death_flag", "censor_date"]], on="patient_id")
    add("death_after_birth", "critical", (death_birth.death_date.notna() & (death_birth.death_date <= death_birth.birth_date)).sum(), "death after birth")
    add("death_censor_alignment", "critical", (death_birth.death_flag & (death_birth.death_date > death_birth.censor_date)).sum(), "death not after censor")
    add("mhspc_implies_metastatic", "critical", (j.mhspc_flag & ~j.metastatic_flag).sum(), "mHSPC => metastatic")
    add("mhspc_implies_hormone_sensitive", "critical", (j.mhspc_flag & ~j.hormone_sensitive_flag).sum(), "mHSPC => hormone sensitive")
    add("mhspc_excludes_cr", "critical", (j.mhspc_flag & j.castration_resistant_flag).sum(), "mHSPC excludes CR at index")
    add("eligibility_implies_mhspc", "critical", (j.eligible_for_arpi & ~j.mhspc_flag).sum(), "demo eligibility => mHSPC")
    for col in ("referral_delay_days", "days_to_initiation", "days_to_discontinuation", "days_to_switch", "days_to_progression"):
        add(f"nonnegative_{col}", "critical", (j[col].dropna() < 0).sum(), f"{col} cannot be negative")
    add("persistence_requires_followup", "warning", (j.persistent_12m & (j.follow_up_days < 365)).sum(), "12m persistence requires follow-up")
    add("switch_has_date", "critical", (j.switch_flag.fillna(False) & j.switch_date.isna()).sum(), "switch implies date")
    add("restart_has_date", "critical", (j.restart_flag.fillna(False) & j.restart_date.isna()).sum(), "restart implies date")
    add("death_has_date", "critical", (o.death_flag & o.death_date.isna()).sum(), "death implies date")
    add("ltfu_has_last_observed", "critical", (o.lost_to_follow_up_flag & o.last_observed_date.isna()).sum(), "LTFU implies last observed")
    death_map = o.set_index("patient_id").death_date
    add("no_switch_after_death", "critical", (t.switch_date.notna() & (t.switch_date > t.patient_id.map(death_map))).sum(), "no switch after death")
    add("no_treatment_after_death", "critical", (t.treatment_start_date.notna() & (t.treatment_start_date > t.patient_id.map(death_map))).sum(), "no treatment after death")
    add("death_not_nonadherence", "critical", t.discontinuation_reason.astype("string").eq("death").sum(), "death is a separate outcome")
    add("ltfu_not_discontinuation", "critical", t.discontinuation_reason.astype("string").eq("lost_to_follow_up").sum(), "LTFU is separate")
    add("persistence_requires_initiation", "critical", ((j[["persistent_3m", "persistent_6m", "persistent_12m"]].any(axis=1)) & ~j.treatment_initiated).sum(), "persistence requires initiation")
    add("refill_after_start", "critical", (t.refill_date < t.treatment_start_date).sum(), "refill >= start")
    add("coverage_after_refill", "critical", (t.covered_until_date < t.refill_date).sum(), "coverage >= refill")
    add("encounter_provider_fk", "critical", (~e.provider_id.isin(pr.provider_id)).sum(), "encounter provider exists")
    add("treatment_provider_fk", "critical", (~t.prescribing_provider_id.isin(pr.provider_id)).sum(), "prescriber exists")
    patient_ids = set(p.patient_id)
    fk_failures = sum((~frame.patient_id.isin(patient_ids)).sum() for frame in (d, e, t, rx, o, j))
    add("patient_foreign_keys", "critical", fk_failures, "all patient foreign keys exist")
    treatment_ids = set(t.treatment_id)
    add(
        "prescription_event_treatment_fk",
        "critical",
        (~rx.treatment_id.isin(treatment_ids)).sum(),
        "every prescription event references an existing treatment",
    )

    treatment_lookup = t.drop_duplicates("treatment_id").set_index("treatment_id")
    event_treatment_patient = rx.treatment_id.map(treatment_lookup.patient_id)
    add(
        "prescription_event_patient_matches_treatment",
        "critical",
        rx.patient_id.ne(event_treatment_patient).sum(),
        "event patient_id matches its treatment patient_id",
    )
    event_treatment_drug = rx.treatment_id.map(treatment_lookup.drug_name)
    add(
        "prescription_event_drug_matches_treatment",
        "critical",
        rx.drug_name.ne(event_treatment_drug).sum(),
        "event drug_name matches its treatment drug_name",
    )
    add(
        "prescription_event_synthetic_product",
        "critical",
        (~rx.product_id.astype("string").str.startswith("SYN-", na=False)).sum(),
        "product_id uses the synthetic identifier prefix",
    )
    event_service_date = pd.to_datetime(rx.service_date)
    event_covered_until = pd.to_datetime(rx.covered_until_date)
    event_start = pd.to_datetime(rx.treatment_id.map(treatment_lookup.treatment_start_date))
    event_end = pd.to_datetime(rx.treatment_id.map(treatment_lookup.treatment_end_date))
    add(
        "prescription_event_within_treatment",
        "critical",
        ((event_service_date < event_start) | (event_service_date > event_end)).sum(),
        "service_date is within the treatment episode",
    )
    add(
        "prescription_event_positive_supply",
        "critical",
        ((rx.days_supply <= 0) | (rx.quantity_dispensed <= 0)).sum(),
        "days_supply and quantity_dispensed are positive",
    )
    add(
        "prescription_event_coverage",
        "critical",
        event_covered_until.ne(
            event_service_date + pd.to_timedelta(rx.days_supply, unit="D")
        ).sum(),
        "covered_until_date equals service_date + days_supply",
    )
    add(
        "prescription_event_nonnegative_gap",
        "critical",
        (rx.refill_gap_days < 0).sum(),
        "refill_gap_days is nonnegative",
    )
    add(
        "prescription_event_synthetic",
        "critical",
        (~rx.synthetic_event_flag.fillna(False)).sum(),
        "all prescription events are explicitly synthetic",
    )

    ordered_events = rx.sort_values(
        ["treatment_id", "service_date", "prescription_event_id"]
    ).copy()
    event_number = ordered_events.groupby("treatment_id").cumcount()
    expected_event_type = pd.Series("refill", index=ordered_events.index)
    expected_event_type.loc[event_number.eq(0)] = "initial_fill"
    add(
        "prescription_event_type_sequence",
        "critical",
        ordered_events.event_type.ne(expected_event_type).sum(),
        "first event is initial_fill and subsequent events are refill",
    )
    previous_coverage = pd.to_datetime(
        ordered_events.groupby("treatment_id").covered_until_date.shift()
    )
    expected_gap = (
        pd.to_datetime(ordered_events.service_date) - previous_coverage
    ).dt.days.fillna(0)
    add(
        "prescription_event_gap_consistency",
        "critical",
        ordered_events.refill_gap_days.ne(expected_gap).sum(),
        "refill_gap_days equals service_date minus previous coverage",
    )
    initial_fill_counts = (
        rx.event_type.eq("initial_fill").groupby(rx.treatment_id).sum()
        .reindex(t.treatment_id, fill_value=0)
    )
    add(
        "prescription_event_treatment_coverage",
        "critical",
        initial_fill_counts.ne(1).sum(),
        "every treatment has exactly one initial fill",
    )
    event_max_gap = rx.groupby("treatment_id").refill_gap_days.max()
    add(
        "prescription_event_max_gap_consistency",
        "critical",
        t.max_refill_gap_days.ne(t.treatment_id.map(event_max_gap)).sum(),
        "treatment max_refill_gap_days matches its emitted events",
    )
    add("diagnosis_patient_coverage", "critical", len(patient_ids - set(d.patient_id)), "each patient has diagnosis")
    add("outcome_patient_coverage", "critical", len(patient_ids - set(o.patient_id)), "each patient has outcome")
    return results


def write_quality_report(results: list[dict], report_dir: str | Path) -> None:
    """Write JSON, CSV and Markdown summaries."""
    root = Path(report_dir); root.mkdir(parents=True, exist_ok=True)
    payload = {"disclaimer": DISCLAIMER, "rules": results, "critical_failures": sum(r["failure_count"] for r in results if r["severity"] == "critical")}
    (root / "data_quality_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    pd.DataFrame(results).to_csv(root / "data_quality_summary.csv", index=False)
    lines = [f"# Data Quality Report\n\n> **{DISCLAIMER}**\n", "| Rule | Severity | Status | Failures | Detail |", "|---|---|---:|---:|---|"]
    lines.extend(f"| {r['rule']} | {r['severity']} | {r['status']} | {r['failure_count']} | {r['detail']} |" for r in results)
    (root / "data_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def raise_on_critical(results: list[dict]) -> None:
    """Fail the pipeline when a critical rule fails."""
    failed = [r for r in results if r["severity"] == "critical" and r["failure_count"]]
    if failed:
        raise ValueError("Critical data-quality failures: " + ", ".join(r["rule"] for r in failed))
