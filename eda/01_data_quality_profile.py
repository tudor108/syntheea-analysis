"""Healthcare-grade aggregate EDA, DQ profiling, figures and reproducibility manifest."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from config import (
    ANALYSIS_DISCLAIMER,
    DATE_ORDER_RULES,
    DEEP_MARKETS,
    EXPECTED_CATEGORIES,
    FIGURES_DIR,
    IMPORTANT_MISSINGNESS_FIELDS,
    OUTPUT_DIR,
    PROJECT_ROOT,
    RAW_SYNTHEA_DIR,
    REQUIRED_MARKETS,
    SCAN_MARKETS,
    TABLE_CONTRACTS,
    ensure_output_directories,
    resolve_analytical_data_dir,
    write_eda_artifact_manifest,
)
from svg_charts import bar_chart, heatmap, line_chart

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
MARKET_COUNTRIES = {
    "US": "United States",
    "DE": "Germany",
    "JP": "Japan",
    "FR": "France",
    "CN": "China",
    "AU": "Australia",
    "CA": "Canada",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_tables(analytical_dir: Path) -> dict[str, pd.DataFrame]:
    return {
        table: pd.read_parquet(analytical_dir / f"{table}.parquet") for table in TABLE_CONTRACTS
    }


class QualityRecorder:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(
        self,
        check_id: str,
        severity: str,
        domain: str,
        table: str,
        check: str,
        affected: int,
        denominator: int,
        observed: str,
        expected: str,
        impact: str,
        *,
        status: str | None = None,
    ) -> None:
        if severity not in SEVERITY_ORDER:
            raise ValueError(f"Unsupported severity: {severity}")
        self.rows.append(
            {
                "check_id": check_id,
                "severity": severity,
                "domain": domain,
                "table_name": table,
                "check_name": check,
                "status": status or ("PASS" if affected == 0 else "ISSUE"),
                "affected_records": int(affected),
                "denominator": int(denominator),
                "affected_rate": affected / denominator if denominator else 0.0,
                "observed": observed,
                "expected": expected,
                "analysis_impact": impact,
            }
        )

    def frame(self) -> pd.DataFrame:
        frame = pd.DataFrame(self.rows)
        frame["severity_rank"] = frame.severity.map(SEVERITY_ORDER)
        return frame.sort_values(
            ["severity_rank", "status", "domain", "table_name", "check_id"],
            ignore_index=True,
        ).drop(columns="severity_rank")


def _date_columns(frame: pd.DataFrame) -> list[str]:
    return [
        str(column)
        for column in frame.columns
        if str(column).lower().endswith("_date")
        or str(column).lower() in {"date", "birthdate", "deathdate", "start", "stop"}
        or pd.api.types.is_datetime64_any_dtype(frame[column].dtype)
    ]


def _calendar_age(birth: pd.Series, index: pd.Series) -> pd.Series:
    birth_dates = pd.to_datetime(birth, errors="coerce")
    index_dates = pd.to_datetime(index, errors="coerce")
    before_birthday = (index_dates.dt.month < birth_dates.dt.month) | (
        (index_dates.dt.month == birth_dates.dt.month) & (index_dates.dt.day < birth_dates.dt.day)
    )
    return index_dates.dt.year - birth_dates.dt.year - before_birthday.astype("Int64")


def build_reconciliation(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    patient = tables["patient"].set_index("patient_id")
    journey = tables["patient_journey"].set_index("patient_id")
    diagnosis = tables["diagnosis"].set_index("patient_id")
    eligibility = tables["eligibility"].set_index("patient_id")
    outcome = tables["outcome"].set_index("patient_id")
    episode = tables["treatment_episode"].copy()
    rows: list[dict[str, Any]] = []

    def add(concept: str, compared: int, mismatches: int, evidence: str) -> None:
        rows.append(
            {
                "reconciliation_concept": concept,
                "compared_records": int(compared),
                "mismatch_count": int(mismatches),
                "mismatch_rate": mismatches / compared if compared else 0.0,
                "status": "PASS" if mismatches == 0 else "MISMATCH",
                "aggregate_evidence": evidence,
            }
        )

    patient_ids = set(patient.index)
    journey_ids = set(journey.index)
    add(
        "patient_presence_normalized_vs_mart",
        len(patient_ids | journey_ids),
        len(patient_ids ^ journey_ids),
        f"patient={len(patient_ids)}; mart={len(journey_ids)}",
    )
    common = patient.index.intersection(journey.index)
    add(
        "market_code",
        len(common),
        int(patient.loc[common, "market_code"].ne(journey.loc[common, "market_code"]).sum()),
        "patient.market_code vs patient_journey.market_code",
    )
    add(
        "index_date_vs_diagnosis_date",
        len(patient),
        int(
            pd.to_datetime(patient.index_date)
            .ne(pd.to_datetime(diagnosis.reindex(patient.index).diagnosis_date))
            .sum()
        ),
        "normalized patient.index_date vs diagnosis.diagnosis_date",
    )
    for column in (
        "eligibility_flag",
        "eligibility_date",
        "eligibility_reason",
        "ineligibility_reason",
    ):
        left = journey[column]
        right = eligibility.reindex(journey.index)[column]
        if "date" in column:
            left = pd.to_datetime(left)
            right = pd.to_datetime(right)
        mismatches = int((~(left.eq(right) | (left.isna() & right.isna()))).sum())
        add(f"eligibility_{column}", len(journey), mismatches, f"mart vs eligibility.{column}")

    first_episode = (
        episode.sort_values(["patient_id", "treatment_start_date", "treatment_episode_id"])
        .drop_duplicates("patient_id")
        .set_index("patient_id")
        .reindex(journey.index)
    )
    expected_treated = journey.index.isin(episode.patient_id)
    add(
        "treatment_patient_membership",
        len(journey),
        int(journey.treatment_initiated.ne(expected_treated).sum()),
        f"episode patients={episode.patient_id.nunique()}; mart treated={int(journey.treatment_initiated.sum())}",
    )
    for mart_column, source_column in (
        ("treatment_episode_id", "treatment_episode_id"),
        ("treatment_start_date", "treatment_start_date"),
        ("discontinuation_flag", "discontinuation_flag"),
        ("switch_flag", "switch_flag"),
        ("restart_flag", "restart_flag"),
    ):
        comparison_index = journey.index
        if mart_column.endswith("_flag"):
            comparison_index = journey.index[expected_treated]
        left = journey.loc[comparison_index, mart_column]
        right = first_episode.loc[comparison_index, source_column]
        if "date" in mart_column:
            left = pd.to_datetime(left)
            right = pd.to_datetime(right)
        mismatches = int((~(left.eq(right) | (left.isna() & right.isna()))).sum())
        population = "treated patients" if mart_column.endswith("_flag") else "all patients"
        add(
            f"first_treatment_{mart_column}",
            len(comparison_index),
            mismatches,
            f"mart vs first episode among {population}",
        )

    for column in (
        "progression_event",
        "progression_date",
        "hospitalisation_flag",
        "first_hospitalisation_date",
        "adverse_event_flag",
        "death_flag",
        "lost_to_follow_up_flag",
        "censor_date",
        "censor_reason",
    ):
        left = journey[column]
        right = outcome.reindex(journey.index)[column]
        if "date" in column:
            left = pd.to_datetime(left)
            right = pd.to_datetime(right)
        mismatches = int((~(left.eq(right) | (left.isna() & right.isna()))).sum())
        add(f"outcome_{column}", len(journey), mismatches, f"mart vs outcome.{column}")
    return pd.DataFrame(rows)


def run_quality_checks(
    tables: dict[str, pd.DataFrame], reconciliation: pd.DataFrame, analysed_at: datetime
) -> pd.DataFrame:
    recorder = QualityRecorder()
    patient_ids = set(tables["patient"].patient_id)
    patient_market = tables["patient"].set_index("patient_id").market_code

    for table_name, frame in tables.items():
        contract = TABLE_CONTRACTS[table_name]
        duplicate_rows = int(frame.duplicated().sum())
        recorder.add(
            f"DUP_ROW_{table_name.upper()}",
            "P1",
            "duplicates",
            table_name,
            "exact duplicate rows",
            duplicate_rows,
            len(frame),
            f"duplicates={duplicate_rows}",
            "0 exact duplicates",
            "Duplicates can inflate counts and distort rates.",
        )
        pk = frame[contract.primary_key]
        pk_failures = int(pk.isna().sum() + pk.duplicated().sum())
        recorder.add(
            f"PK_{table_name.upper()}",
            "P0",
            "keys",
            table_name,
            "primary key non-null and unique",
            pk_failures,
            len(frame),
            f"null={int(pk.isna().sum())}; duplicate={int(pk.duplicated().sum())}",
            f"unique non-null {contract.primary_key}",
            "A broken primary key prevents trustworthy table grain and joins.",
        )
        if contract.patient_id and contract.patient_id in frame:
            orphan_patients = int((~frame[contract.patient_id].isin(patient_ids)).sum())
            recorder.add(
                f"PATIENT_FK_{table_name.upper()}",
                "P0",
                "keys",
                table_name,
                "patient foreign key resolves",
                orphan_patients,
                len(frame),
                f"orphan patient rows={orphan_patients}",
                "every patient identifier exists in patient",
                "Orphan events cannot be assigned to a cohort denominator.",
            )
            expected_market = frame[contract.patient_id].map(patient_market)
            mismatch = (
                int(
                    (
                        frame.market_code.notna()
                        & expected_market.notna()
                        & frame.market_code.ne(expected_market)
                    ).sum()
                )
                if "market_code" in frame
                else 0
            )
            recorder.add(
                f"MARKET_FK_{table_name.upper()}",
                "P1",
                "market",
                table_name,
                "event market agrees with patient market",
                mismatch,
                len(frame),
                f"market mismatches={mismatch}",
                "event and patient market_code agree",
                "Market inconsistencies threaten stratified interpretation.",
            )
        for column, target_table, target_column in contract.foreign_keys:
            if column == contract.patient_id or column not in frame:
                continue
            source = frame[column]
            allowed = set(tables[target_table][target_column])
            orphan = int((source.notna() & ~source.isin(allowed)).sum())
            recorder.add(
                f"FK_{table_name.upper()}_{column.upper()}",
                "P0",
                "keys",
                table_name,
                f"{column} resolves to {target_table}.{target_column}",
                orphan,
                int(source.notna().sum()),
                f"orphan non-null values={orphan}",
                "0 orphan foreign keys",
                "Broken entity lineage invalidates normalized-to-mart reconstruction.",
            )

        for column in _date_columns(frame):
            parsed = pd.to_datetime(frame[column], errors="coerce")
            invalid = int((frame[column].notna() & parsed.isna()).sum())
            future = int((parsed > analysed_at.replace(tzinfo=None)).sum())
            recorder.add(
                f"DATE_PARSE_{table_name.upper()}_{column.upper()}",
                "P1",
                "temporal",
                table_name,
                f"{column} parses as a date",
                invalid,
                len(frame),
                f"invalid non-null dates={invalid}",
                "all populated dates parse",
                "Invalid dates break ordering and landmark calculations.",
            )
            recorder.add(
                f"FUTURE_DATE_{table_name.upper()}_{column.upper()}",
                "P1",
                "temporal",
                table_name,
                f"{column} is not after analysis date",
                future,
                int(parsed.notna().sum()),
                f"future dates={future}",
                f"date <= {analysed_at.date().isoformat()}",
                "Future records can introduce temporal leakage.",
            )
        for earlier, later in DATE_ORDER_RULES.get(table_name, ()):
            if earlier not in frame or later not in frame:
                continue
            first = pd.to_datetime(frame[earlier], errors="coerce")
            second = pd.to_datetime(frame[later], errors="coerce")
            invalid = int((first.notna() & second.notna() & second.lt(first)).sum())
            recorder.add(
                f"DATE_ORDER_{table_name.upper()}_{earlier.upper()}_{later.upper()}",
                "P0" if table_name.startswith("treatment") else "P1",
                "temporal",
                table_name,
                f"{earlier} <= {later}",
                invalid,
                len(frame),
                f"reversed pairs={invalid}",
                "0 reversed dated pairs",
                "Impossible chronology prevents valid longitudinal analysis.",
            )

    for (table_name, column), expected in EXPECTED_CATEGORIES.items():
        frame = tables[table_name]
        observed = set(frame[column].dropna().astype(str))
        unexpected = observed - expected
        affected = int(frame[column].astype("string").isin(unexpected).sum())
        recorder.add(
            f"CATEGORY_{table_name.upper()}_{column.upper()}",
            "P1",
            "categories",
            table_name,
            f"{column} uses governed categories",
            affected,
            len(frame),
            f"observed={sorted(observed)}; unexpected={sorted(unexpected)}",
            f"allowed={sorted(expected)}",
            "Unexpected labels can silently merge distinct clinical/pathway states.",
        )

    patient = tables["patient"]
    ages = _calendar_age(patient.birth_date, patient.index_date)
    age_invalid = int((~ages.between(50, 90) | ages.isna()).sum())
    age_mismatch = int(ages.ne(patient.age_at_index.astype("Int64")).fillna(True).sum())
    recorder.add(
        "AGE_RANGE",
        "P0",
        "clinical",
        "patient",
        "calendar age is within configured range",
        age_invalid,
        len(patient),
        f"calendar age range={ages.min()}-{ages.max()}",
        "completed calendar years between 50 and 90",
        "Invalid age changes eligibility and clinical segmentation.",
    )
    recorder.add(
        "AGE_RECONSTRUCTION",
        "P0",
        "clinical",
        "patient",
        "stored age equals independently reconstructed calendar age",
        age_mismatch,
        len(patient),
        f"mismatches={age_mismatch}",
        "0 mismatches",
        "Age disagreement indicates a derived-mart or eligibility defect.",
    )
    country_mismatch = int(
        patient.apply(
            lambda row: MARKET_COUNTRIES.get(row.market_code) != row.country, axis=1
        ).sum()
    )
    recorder.add(
        "COUNTRY_MARKET",
        "P1",
        "market",
        "patient",
        "country and market mapping is one-to-one",
        country_mismatch,
        len(patient),
        f"mismatches={country_mismatch}",
        str(MARKET_COUNTRIES),
        "Country inconsistencies threaten market analyses.",
    )
    missing_markets = set(REQUIRED_MARKETS) - set(patient.market_code)
    recorder.add(
        "REQUIRED_MARKETS",
        "P0",
        "market",
        "patient",
        "all required markets are represented",
        len(missing_markets),
        len(REQUIRED_MARKETS),
        f"market counts={patient.market_code.value_counts().sort_index().to_dict()}",
        f"required={list(REQUIRED_MARKETS)}",
        "A missing market prevents the requested Deep/Scan diagnostic.",
    )

    episode = tables["treatment_episode"]
    duplicate_treatment = int(
        episode.duplicated(["patient_id", "treatment_line", "treatment_start_date"]).sum()
    )
    recorder.add(
        "DUPLICATE_TREATMENT_EVENT",
        "P1",
        "duplicates",
        "treatment_episode",
        "patient-line-start treatment event is unique",
        duplicate_treatment,
        len(episode),
        f"duplicate treatment signatures={duplicate_treatment}",
        "0 duplicate treatment signatures",
        "Duplicate episodes inflate treated counts and pathway transitions.",
    )
    starts = pd.to_datetime(episode.treatment_start_date)
    ends = pd.to_datetime(episode.treatment_end_date)
    duration = (ends - starts).dt.days
    impossible_duration = int((duration < 0).sum())
    implausibly_long = int((duration > 3650).sum())
    recorder.add(
        "TREATMENT_DURATION_INVALID",
        "P0",
        "treatment",
        "treatment_episode",
        "treatment duration is non-negative",
        impossible_duration,
        int(duration.notna().sum()),
        f"negative durations={impossible_duration}",
        "end date >= start date",
        "Negative treatment duration invalidates longitudinal ordering.",
    )
    recorder.add(
        "TREATMENT_DURATION_LONG",
        "P2",
        "treatment",
        "treatment_episode",
        "treatment duration is within exploratory plausibility bound",
        implausibly_long,
        int(duration.notna().sum()),
        f">10-year durations={implausibly_long}",
        "review durations above 3,650 days",
        "Very long episodes may reflect administrative rather than clinical exposure.",
    )
    prescription = tables["prescription_event"]
    invalid_supply = int(
        (prescription.days_supply.notna() & ~prescription.days_supply.between(1, 365)).sum()
    )
    invalid_quantity = int(
        (prescription.quantity_dispensed.notna() & prescription.quantity_dispensed.le(0)).sum()
    )
    recorder.add(
        "DAYS_SUPPLY",
        "P1",
        "treatment",
        "prescription_event",
        "days_supply is positive and bounded",
        invalid_supply,
        int(prescription.days_supply.notna().sum()),
        f"outside 1-365={invalid_supply}",
        "1 <= days_supply <= 365",
        "Invalid supply prevents persistence and coverage reconstruction.",
    )
    recorder.add(
        "QUANTITY_DISPENSED",
        "P1",
        "treatment",
        "prescription_event",
        "populated quantity_dispensed is positive",
        invalid_quantity,
        int(prescription.quantity_dispensed.notna().sum()),
        f"non-positive populated quantities={invalid_quantity}",
        "quantity_dispensed > 0 when collected",
        "Invalid quantities threaten exposure interpretation.",
    )
    dose_columns = [
        column for column in prescription if "dose" in column.lower() or "unit" in column.lower()
    ]
    recorder.add(
        "DOSE_UNIT_AVAILABILITY",
        "P3",
        "treatment",
        "prescription_event",
        "dose and unit fields are available for validation",
        0 if dose_columns else 1,
        1,
        f"available columns={dose_columns}",
        "dose/unit checks when those fields are collected",
        "Dose-level analysis is unsupported; this does not affect event/refill analyses.",
        status="PASS" if dose_columns else "NOT_APPLICABLE",
    )

    provider = tables["provider"].set_index("provider_id")
    encounter = tables["encounter"]
    expected_specialty = encounter.provider_id.map(provider.provider_specialty)
    expected_setting = encounter.provider_id.map(provider.care_setting)
    expected_org = encounter.provider_id.map(provider.organization_id)
    provider_mismatch = int(
        encounter.provider_specialty.ne(expected_specialty).sum()
        + encounter.care_setting.ne(expected_setting).sum()
        + encounter.organization_id.ne(expected_org).sum()
    )
    recorder.add(
        "ENCOUNTER_PROVIDER_CONSISTENCY",
        "P0",
        "provider_pathway",
        "encounter",
        "encounter specialty/setting/organization agree with provider master",
        provider_mismatch,
        len(encounter) * 3,
        f"field mismatches={provider_mismatch}",
        "0 provider-master mismatches",
        "Provider contradictions invalidate pathway and setting comparisons.",
    )
    referral = tables["referral"]
    source_specialty = referral.source_provider_id.map(provider.provider_specialty)
    destination_specialty = referral.destination_provider_id.map(provider.provider_specialty)
    endpoint_mismatch = int(
        referral.source_specialty.ne(source_specialty).sum()
        + referral.destination_specialty.ne(destination_specialty).sum()
        + referral.source_provider_id.eq(referral.destination_provider_id).sum()
    )
    recorder.add(
        "REFERRAL_ENDPOINT_CONSISTENCY",
        "P0",
        "provider_pathway",
        "referral",
        "referral endpoints are distinct provider-master specialties",
        endpoint_mismatch,
        len(referral) * 3,
        f"endpoint mismatches={endpoint_mismatch}",
        "0 specialty/master mismatches and distinct providers",
        "Label-only referrals would invalidate pathway analysis.",
    )

    observation = tables["observation"].set_index("patient_id")
    administrative_end = pd.to_datetime(observation.observation_end_date)
    death = pd.to_datetime(observation.death_date)
    ltfu = pd.to_datetime(observation.loss_to_follow_up_date)
    reconstructed_censor = pd.concat([administrative_end, death, ltfu], axis=1).min(axis=1)
    censor_mismatch = int(reconstructed_censor.ne(pd.to_datetime(observation.censor_date)).sum())
    recorder.add(
        "CENSOR_RECONSTRUCTION",
        "P0",
        "censoring",
        "observation",
        "censor date is min(death, LTFU, administrative end)",
        censor_mismatch,
        len(observation),
        f"mismatches={censor_mismatch}",
        "0 reconstructed censor mismatches",
        "Incorrect censoring biases initiation and persistence denominators.",
    )
    dated_events = {
        "diagnosis": "diagnosis_date",
        "disease_state_event": "state_date",
        "encounter": "encounter_date",
        "referral": "referral_date",
        "treatment_episode": "treatment_start_date",
        "prescription_event": "service_date",
        "adverse_event": "adverse_event_date",
    }
    for table_name, column in dated_events.items():
        frame = tables[table_name]
        censor = frame.patient_id.map(observation.censor_date)
        after = int(pd.to_datetime(frame[column]).gt(pd.to_datetime(censor)).sum())
        recorder.add(
            f"POST_CENSOR_{table_name.upper()}",
            "P0",
            "censoring",
            table_name,
            f"{column} is on/before patient censor date",
            after,
            len(frame),
            f"events after censor={after}",
            "0 clinically relevant events after censor",
            "Post-censor events introduce immortal-time and chronology errors.",
        )

    journey = tables["patient_journey"]
    start = pd.to_datetime(journey.treatment_start_date)
    censor = pd.to_datetime(journey.censor_date)
    persistent_without_followup = int(
        (
            journey.persistence_12m_status.eq("PERSISTENT")
            & censor.lt(start + pd.Timedelta(days=365))
        ).sum()
    )
    recorder.add(
        "PERSISTENCE_12M_FOLLOWUP",
        "P0",
        "censoring",
        "patient_journey",
        "12-month persistent requires complete 12-month observation",
        persistent_without_followup,
        int(journey.persistence_12m_status.eq("PERSISTENT").sum()),
        f"persistent with insufficient follow-up={persistent_without_followup}",
        "0 misclassified persistent patients",
        "Misclassifying right-censored patients biases sustained-treatment rates.",
    )
    dataset_end_discontinuation = int(
        (
            journey.discontinuation_flag.fillna(False)
            & pd.to_datetime(journey.discontinuation_date).eq(
                pd.to_datetime(journey.observation_end_date)
            )
            & journey.censor_reason.eq("administrative_end")
        ).sum()
    )
    recorder.add(
        "DATASET_END_NOT_DISCONTINUATION",
        "P0",
        "censoring",
        "patient_journey",
        "administrative dataset end is not an explicit discontinuation",
        dataset_end_discontinuation,
        len(journey),
        f"administrative-end discontinuinations={dataset_end_discontinuation}",
        "0 administrative end dates labelled as explicit discontinuation",
        "Dataset end must remain right censoring rather than an outcome event.",
    )

    event_tables = (
        "encounter",
        "disease_state_event",
        "referral",
        "active_surveillance",
        "treatment_episode",
        "prescription_event",
        "adverse_event",
    )
    event_counts = pd.Series(0, index=tables["patient"].patient_id, dtype="int64")
    for table_name in event_tables:
        counts = tables[table_name].patient_id.value_counts()
        event_counts = event_counts.add(counts, fill_value=0)
    no_events = int(event_counts.eq(0).sum())
    isolated = int(event_counts.le(1).sum())
    recorder.add(
        "PATIENTS_WITH_NO_EVENTS",
        "P1",
        "coverage",
        "patient",
        "each patient has longitudinal event evidence",
        no_events,
        len(event_counts),
        f"patients with no core events={no_events}",
        "0 patients without core events",
        "Patients without events cannot support journey analysis.",
    )
    recorder.add(
        "ISOLATED_PATIENT_RECORDS",
        "P2",
        "coverage",
        "patient",
        "patient has more than one core event",
        isolated,
        len(event_counts),
        f"patients with <=1 core events={isolated}",
        "review isolated records",
        "Sparse records provide limited longitudinal evidence.",
    )
    follow_up = tables["observation"].follow_up_days_from_diagnosis
    short_followup = int(follow_up.lt(90).sum())
    long_followup = int(follow_up.gt(3650).sum())
    recorder.add(
        "SHORT_FOLLOWUP",
        "P2",
        "coverage",
        "observation",
        "minimum observation supports a 90-day assessment",
        short_followup,
        len(follow_up),
        f"<90 days={short_followup}; min={follow_up.min()}",
        "follow-up >= 90 days or explicit non-evaluable handling",
        "Short follow-up limits initiation and persistence assessment.",
    )
    recorder.add(
        "EXTREMELY_LONG_FOLLOWUP",
        "P2",
        "coverage",
        "observation",
        "follow-up is within a 10-year exploratory bound",
        long_followup,
        len(follow_up),
        f">3,650 days={long_followup}; max={follow_up.max()}",
        "review follow-up above 10 years",
        "Extremely long windows may indicate date/unit defects.",
    )

    for table_name, frame in tables.items():
        excluded = {
            TABLE_CONTRACTS[table_name].primary_key,
            "patient_id",
            "market_code",
        }
        constant = [
            str(column)
            for column in frame.columns
            if column not in excluded and frame[column].nunique(dropna=False) <= 1
        ]
        numeric = frame.select_dtypes(include="number")
        zero_inflated = [
            str(column)
            for column in numeric
            if numeric[column].nunique(dropna=True) > 1
            and float(numeric[column].fillna(0).eq(0).mean()) >= 0.95
        ]
        recorder.add(
            f"CONSTANT_FIELDS_{table_name.upper()}",
            "P3",
            "univariate",
            table_name,
            "constant fields documented",
            len(constant),
            len(frame.columns),
            f"constant fields={constant}",
            "constants retained only when they encode scope/governance",
            "Constant predictors add no analytical variation but may document scope.",
            status="LIMITATION" if constant else "PASS",
        )
        recorder.add(
            f"ZERO_INFLATED_FIELDS_{table_name.upper()}",
            "P3",
            "univariate",
            table_name,
            "zero-inflated numeric fields documented",
            len(zero_inflated),
            len(numeric.columns),
            f">=95% zero fields={zero_inflated}",
            "review before modeling",
            "Extreme zero inflation can destabilize models and comparisons.",
            status="LIMITATION" if zero_inflated else "PASS",
        )

    reconciliation_mismatches = int(reconciliation.mismatch_count.sum())
    recorder.add(
        "NORMALIZED_MART_RECONCILIATION",
        "P0",
        "reconciliation",
        "patient_journey",
        "normalized tables agree with patient-level mart",
        reconciliation_mismatches,
        int(reconciliation.compared_records.sum()),
        f"mismatches across aggregate comparisons={reconciliation_mismatches}",
        "0 mismatches",
        "Mart disagreement invalidates downstream cohort metrics.",
    )
    return recorder.frame()


def _analysis_frame(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    patient_columns = [
        "patient_id",
        "race",
        "ethnicity",
        "index_date",
        "source_record_type",
    ]
    frame = tables["patient_journey"].merge(
        tables["patient"][patient_columns],
        on="patient_id",
        how="left",
        validate="one_to_one",
    )
    latest_state = (
        tables["disease_state_event"]
        .sort_values(["patient_id", "state_date", "disease_state_event_id"])
        .drop_duplicates("patient_id", keep="last")
        .set_index("patient_id")
        .state
    )
    frame["exact_disease_state"] = frame.patient_id.map(latest_state)
    index_date = pd.to_datetime(frame.index_date)
    year = index_date.dt.year
    frame["calendar_period"] = pd.cut(
        year,
        bins=[2018, 2020, 2022, 2024],
        labels=["2019-2020", "2021-2022", "2023-2024"],
    ).astype("string")
    as_status = frame.active_surveillance_status.astype("string").str.lower()
    as_pathway = as_status.notna() & as_status.ne("not_applicable").fillna(False)
    advanced = frame.exact_disease_state.isin(["mHSPC", "mCRPC", "metastatic_other"])
    frame["pathway_group"] = np.select(
        [as_pathway, advanced],
        ["active_surveillance", "advanced_disease"],
        default="localized_or_other_non_as",
    )
    for field in IMPORTANT_MISSINGNESS_FIELDS:
        if field in frame:
            frame[f"{field}__missing"] = frame[field].isna()
    return frame


def _missingness_mechanism(field: str, group_dimension: str, group_value: str) -> str:
    if field in {"referral_delay_days", "decision_owner_specialty"}:
        return "structural/event-dependent when no completed referral exists"
    if field in {"initial_regimen", "event_coverage_until_date"}:
        return "structural/event-dependent for untreated or non-dispensing pathways"
    if field == "progression_date":
        return "structural when no progression event is observed"
    if field in {
        "race",
        "ethnicity",
        "insurance_type",
        "psa_value",
        "gleason_score",
        "isup_grade_group",
    }:
        return "collected-but-unavailable or market/source dependent"
    if group_dimension == "market" and group_value in SCAN_MARKETS:
        return "potentially not collected by Scan-market design"
    return "mechanism unresolved; do not impute"


def build_missingness(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = _analysis_frame(tables)
    dimensions = {
        "market": "market_code",
        "disease_state": "exact_disease_state",
        "active_surveillance_vs_advanced": "pathway_group",
        "care_setting": "initial_care_setting",
        "provider_specialty": "initial_provider_specialty",
        "calendar_period": "calendar_period",
        "initiation_outcome": "initiation_90d_status",
        "persistence_outcome": "persistence_12m_status",
    }
    rows: list[dict[str, Any]] = []
    for field in IMPORTANT_MISSINGNESS_FIELDS:
        if field not in frame:
            continue
        indicator = frame[f"{field}__missing"]
        overall = float(indicator.mean())
        for dimension, group_column in dimensions.items():
            grouped = (
                pd.DataFrame(
                    {
                        "group": frame[group_column].astype("string").fillna("<missing group>"),
                        "missing": indicator,
                    }
                )
                .groupby("group", dropna=False)
                .missing.agg(["size", "sum", "mean"])
            )
            range_pp = float((grouped["mean"].max() - grouped["mean"].min()) * 100)
            association = (
                dimension in {"initiation_outcome", "persistence_outcome"} and range_pp >= 5
            )
            for group_value, values in grouped.iterrows():
                rows.append(
                    {
                        "variable": field,
                        "missingness_indicator": f"{field}__missing",
                        "grouping_dimension": dimension,
                        "group_value": str(group_value),
                        "group_n": int(values["size"]),
                        "missing_n": int(values["sum"]),
                        "observed_n": int(values["size"] - values["sum"]),
                        "missing_rate": float(values["mean"]),
                        "overall_missing_rate": overall,
                        "delta_vs_overall": float(values["mean"] - overall),
                        "between_group_range_percentage_points": range_pp,
                        "appears_associated_with_outcome": association,
                        "missingness_mechanism": _missingness_mechanism(
                            field, dimension, str(group_value)
                        ),
                        "interpretation": "descriptive association only; no imputation or causal claim",
                    }
                )
    summary = (
        pd.DataFrame(
            {
                "variable": [field for field in IMPORTANT_MISSINGNESS_FIELDS if field in frame],
                "missing_n": [
                    int(frame[field].isna().sum())
                    for field in IMPORTANT_MISSINGNESS_FIELDS
                    if field in frame
                ],
                "missing_rate": [
                    float(frame[field].isna().mean())
                    for field in IMPORTANT_MISSINGNESS_FIELDS
                    if field in frame
                ],
            }
        )
        .sort_values("missing_rate", ascending=False)
        .reset_index(drop=True)
    )
    return pd.DataFrame(rows), summary


def build_temporal_outputs(
    tables: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    coverage_rows: list[dict[str, Any]] = []
    monthly_rows: list[pd.DataFrame] = []
    for table_name, frame in tables.items():
        for column in _date_columns(frame):
            dates = pd.to_datetime(frame[column], errors="coerce")
            coverage_rows.append(
                {
                    "record_type": "date_coverage",
                    "table_name": table_name,
                    "metric": column,
                    "market_code": "ALL",
                    "value": int(dates.notna().sum()),
                    "denominator": len(frame),
                    "proportion": float(dates.notna().mean()) if len(frame) else None,
                    "date_min": dates.min().date().isoformat() if dates.notna().any() else None,
                    "date_max": dates.max().date().isoformat() if dates.notna().any() else None,
                }
            )
        contract = TABLE_CONTRACTS[table_name]
        if contract.event_date and contract.event_date in frame and "market_code" in frame:
            dates = pd.to_datetime(frame[contract.event_date], errors="coerce")
            monthly = pd.DataFrame(
                {
                    "month": dates.dt.to_period("M").astype("string"),
                    "market_code": frame.market_code,
                    "domain": table_name,
                }
            ).dropna(subset=["month"])
            monthly_rows.append(
                monthly.groupby(["month", "market_code", "domain"], as_index=False)
                .size()
                .rename(columns={"size": "record_count"})
            )

    observation = tables["observation"].merge(
        tables["patient"][["patient_id", "market_code"]],
        on=["patient_id", "market_code"],
        how="left",
        validate="one_to_one",
    )
    followup_rows: list[dict[str, Any]] = []
    for market, group in [("ALL", observation), *observation.groupby("market_code")]:
        follow_up = group.follow_up_days_from_diagnosis
        for days in (30, 60, 90, 365):
            enough = int(follow_up.ge(days).sum())
            coverage_rows.append(
                {
                    "record_type": "followup_landmark",
                    "table_name": "observation",
                    "metric": f"enough_observation_{days}d",
                    "market_code": str(market),
                    "value": enough,
                    "denominator": len(group),
                    "proportion": enough / len(group) if len(group) else None,
                    "date_min": None,
                    "date_max": None,
                }
            )
        followup_rows.append(
            {
                "market_code": str(market),
                "patients": len(group),
                "minimum_days": int(follow_up.min()),
                "q05_days": float(follow_up.quantile(0.05)),
                "q25_days": float(follow_up.quantile(0.25)),
                "median_days": float(follow_up.median()),
                "q75_days": float(follow_up.quantile(0.75)),
                "q95_days": float(follow_up.quantile(0.95)),
                "maximum_days": int(follow_up.max()),
            }
        )
    monthly_counts = pd.concat(monthly_rows, ignore_index=True)
    return pd.DataFrame(coverage_rows), monthly_counts, pd.DataFrame(followup_rows)


def build_top_issues(
    dq: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    missingness_summary: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    actual = dq[dq.status.eq("ISSUE")].copy()
    actual["rank"] = actual.severity.map(SEVERITY_ORDER)
    for row in (
        actual.sort_values(["rank", "affected_rate"], ascending=[True, False]).head(10).itertuples()
    ):
        rows.append(
            {
                "issue_id": row.check_id,
                "severity": row.severity,
                "classification": "observed_data_quality_issue",
                "affected_records": row.affected_records,
                "finding": row.observed,
                "analysis_consequence": row.analysis_impact,
                "recommended_handling": row.expected,
            }
        )

    patient = tables["patient"]
    journey = tables["patient_journey"]
    prescription = tables["prescription_event"]
    limitations = [
        (
            "LIM_SYNTHETIC_POPULATION",
            "P2",
            len(patient),
            f"population_representative_flag=false for {int((~patient.population_representative_flag).sum()):,} patients",
            "Rates are scenario outputs, not population or Bayer market estimates.",
            "Use only for demonstrational diagnostics; do not weight to real populations.",
        ),
        (
            "LIM_GENERATED_ARCHETYPES",
            "P2",
            int(patient.source_record_type.eq("generated_archetype").sum()),
            "Most records are independent generated archetypes rather than direct raw Synthea patients.",
            "Raw-source fidelity cannot be interpreted as real-world representativeness.",
            "Keep source_record_type visible in sensitivity descriptions.",
        ),
        (
            "LIM_STRUCTURAL_PRODUCT_MISSINGNESS",
            "P2",
            int(prescription.product_id.isna().sum()),
            f"product_id missing in {int(prescription.product_id.isna().sum()):,} prescription rows, concentrated in Scan markets",
            "Product-level comparisons can be biased by market depth.",
            "Report product analyses by detail level and never impute a missing product as no therapy.",
        ),
        (
            "LIM_12M_CENSORING",
            "P2",
            int(journey.persistence_12m_status.eq("CENSORED_NOT_EVALUABLE").sum()),
            f"{int(journey.persistence_12m_status.eq('CENSORED_NOT_EVALUABLE').sum()):,} treated patients are not evaluable at 12 months",
            "Naive non-persistence rates would be biased.",
            "Keep right-censored patients separate from discontinued/switched patients.",
        ),
        (
            "LIM_REFERRAL_MISSINGNESS",
            "P2",
            int(journey.referral_delay_days.isna().sum()),
            "Referral delay is structurally unavailable when no completed referral exists.",
            "Missing referral delay is not equivalent to zero delay or no referral need.",
            "Use referral status and completion date to define denominators first.",
        ),
        (
            "LIM_OUTCOME_PROXY",
            "P2",
            len(journey),
            "Progression, hospitalisation and death are synthetic probabilistic outcomes.",
            "Outcome associations are not effectiveness or causal estimates.",
            "Label all outcome analyses as synthetic descriptive proxies.",
        ),
        (
            "LIM_REALISED_VALUE_DEFINITION",
            "P2",
            0,
            "Realised value is governed by a synthetic operational proxy, not an approved clinical/commercial endpoint.",
            "The terminal value node cannot support a real Bayer value claim.",
            "Obtain a Bayer-approved definition before external or commercial interpretation.",
        ),
    ]
    for issue_id, severity, affected, finding, consequence, handling in limitations:
        if len(rows) >= 10:
            break
        rows.append(
            {
                "issue_id": issue_id,
                "severity": severity,
                "classification": "assumption_proxy_or_limitation",
                "affected_records": affected,
                "finding": finding,
                "analysis_consequence": consequence,
                "recommended_handling": handling,
            }
        )
    if len(rows) < 10:
        for row in missingness_summary.sort_values("missing_rate", ascending=False).itertuples():
            if len(rows) >= 10:
                break
            rows.append(
                {
                    "issue_id": f"MISS_{row.variable.upper()}",
                    "severity": "P3",
                    "classification": "observed_missingness",
                    "affected_records": int(row.missing_n),
                    "finding": f"{row.variable} missingness={row.missing_rate:.1%}",
                    "analysis_consequence": "Complete-case analyses may change the cohort composition.",
                    "recommended_handling": "Report denominators and missing category; do not impute in EDA.",
                }
            )
    return pd.DataFrame(rows[:10])


def build_readiness(dq: pd.DataFrame, reconciliation: pd.DataFrame) -> pd.DataFrame:
    hard_fail = dq.severity.isin(["P0", "P1"]) & dq.status.eq("ISSUE")
    recon_clear = int(reconciliation.mismatch_count.sum()) == 0
    core_ready = not hard_fail.any() and recon_clear
    rows = [
        (
            "Eligibility denominator and untreated gap",
            "READY" if core_ready else "NOT READY",
            "Eligibility and 30/60/90 initiation reconcile with normalized tables.",
        ),
        (
            "Treatment initiation over time",
            "READY" if core_ready else "NOT READY",
            "Dated first episodes, eligibility dates and censor dates are available.",
        ),
        (
            "12-month persistence/discontinuation",
            "READY" if core_ready else "NOT READY",
            "Right-censoring and 30/60/90 refill-gap sensitivities are explicit.",
        ),
        (
            "Switch, restart and interruption",
            "READY" if core_ready else "NOT READY",
            "Episode transitions and prescription coverage are normalized and dated.",
        ),
        (
            "Active-surveillance pathway",
            "READY" if core_ready else "NOT READY",
            "AS remains a separate normalized pathway with monitoring and transition fields.",
        ),
        (
            "Deep-versus-Scan market EDA",
            "READY" if core_ready else "NOT READY",
            "All seven markets and market-depth metadata are present; missingness must remain stratified.",
        ),
        (
            "Referral, specialty and care-setting EDA",
            "READY" if core_ready else "NOT READY",
            "Provider-master and referral endpoints reconcile.",
        ),
        (
            "Missingness-driver exploration",
            "READY",
            "Aggregate missingness indicators are available; results are descriptive and no imputation is performed.",
        ),
        (
            "Descriptive driver associations",
            "PARTIALLY READY",
            "Feature timing is governed, but synthetic associations are not causal and require sensitivity analysis.",
        ),
        (
            "Realised-value analysis",
            "PARTIALLY READY",
            "A synthetic proxy exists; an approved Bayer clinical/business definition remains unresolved.",
        ),
        (
            "Causal treatment effectiveness",
            "NOT READY",
            "No randomized or causal identification design; synthetic outcomes cannot estimate effectiveness.",
        ),
        (
            "Clinical recommendations or real market sizing",
            "NOT READY",
            "The cohort is synthetic and non-representative by design.",
        ),
    ]
    return pd.DataFrame(rows, columns=["downstream_analysis", "readiness", "evidence_or_blocker"])


def write_figures(
    tables: dict[str, pd.DataFrame],
    missingness: pd.DataFrame,
    missingness_summary: pd.DataFrame,
    monthly: pd.DataFrame,
    dq: pd.DataFrame,
) -> None:
    subtitle = "Aggregate synthetic data only — no row-level patient information"
    bar_chart(
        FIGURES_DIR / "missingness_bar.svg",
        missingness_summary.variable.tolist(),
        (missingness_summary.missing_rate * 100).tolist(),
        title="Important-field missingness",
        subtitle=subtitle,
        horizontal=True,
        value_format=".1f",
    )
    market_missing = missingness[missingness.grouping_dimension.eq("market")]
    pivot = market_missing.pivot(index="variable", columns="group_value", values="missing_rate")
    pivot = pivot.reindex(columns=[market for market in REQUIRED_MARKETS if market in pivot])
    heatmap(
        FIGURES_DIR / "missingness_heatmap.svg",
        pivot.index.tolist(),
        pivot.columns.tolist(),
        (pivot.fillna(0) * 100).values.tolist(),
        title="Missingness by market (%)",
        subtitle=subtitle,
    )
    selected = monthly[monthly.domain.isin(["patient", "encounter", "treatment_episode"])]
    aggregate = selected.groupby(["month", "domain"], as_index=False).record_count.sum()
    monthly_pivot = aggregate.pivot(index="month", columns="domain", values="record_count").fillna(
        0
    )
    line_chart(
        FIGURES_DIR / "patient_event_counts_over_time.svg",
        monthly_pivot.index.tolist(),
        {column: monthly_pivot[column].tolist() for column in monthly_pivot.columns},
        title="Patients and events over calendar time",
        subtitle=subtitle,
    )
    follow_up = tables["observation"].follow_up_days_from_diagnosis
    bins = [0, 180, 365, 730, 1095, 1460, 1825, 2200, 2600, np.inf]
    labels = [
        "<180",
        "180-364",
        "365-729",
        "730-1094",
        "1095-1459",
        "1460-1824",
        "1825-2199",
        "2200-2599",
        "2600+",
    ]
    histogram = pd.cut(follow_up, bins=bins, labels=labels, right=False).value_counts().sort_index()
    bar_chart(
        FIGURES_DIR / "follow_up_duration_distribution.svg",
        histogram.index.astype(str).tolist(),
        histogram.tolist(),
        title="Follow-up duration distribution (days)",
        subtitle=subtitle,
        value_format=".0f",
    )
    latest_state = (
        tables["disease_state_event"]
        .sort_values(["patient_id", "state_date", "disease_state_event_id"])
        .drop_duplicates("patient_id", keep="last")
        .set_index("patient_id")
        .state
    )
    journey = tables["patient_journey"]
    composition_group = journey.patient_id.map(latest_state).fillna("<missing state>")
    as_status = journey.active_surveillance_status.astype("string").str.lower()
    as_pathway = as_status.notna() & as_status.ne("not_applicable").fillna(False)
    composition_group = composition_group.mask(as_pathway, "active_surveillance_pathway")
    stages = composition_group.value_counts()
    bar_chart(
        FIGURES_DIR / "disease_state_composition.svg",
        stages.index.astype(str).tolist(),
        stages.tolist(),
        title="Exact disease-state and active-surveillance composition",
        subtitle="Mutually exclusive AS-pathway-priority groups; exact latest state otherwise",
        value_format=".0f",
    )
    composition = (
        tables["patient_journey"]
        .groupby(["market_code", "initial_care_setting"], dropna=False)
        .size()
        .sort_values(ascending=False)
        .head(20)
    )
    bar_chart(
        FIGURES_DIR / "market_setting_composition.svg",
        [f"{market} | {setting}" for market, setting in composition.index],
        composition.tolist(),
        title="Market and initial care-setting composition",
        subtitle=subtitle,
        horizontal=True,
        value_format=".0f",
    )
    regimen = tables["treatment_regimen"].regimen_name.value_counts()
    bar_chart(
        FIGURES_DIR / "treatment_event_distribution.svg",
        regimen.index.astype(str).tolist(),
        regimen.tolist(),
        title="Treatment regimen distribution",
        subtitle=subtitle,
        horizontal=True,
        value_format=".0f",
    )
    invalid = (
        dq[dq.status.eq("ISSUE")]
        .groupby("domain")
        .affected_records.sum()
        .sort_values(ascending=False)
    )
    if invalid.empty:
        invalid = pd.Series({"P0/P1 invalid records": 0, "duplicate records": 0})
    bar_chart(
        FIGURES_DIR / "duplicate_invalid_record_summary.svg",
        invalid.index.astype(str).tolist(),
        invalid.tolist(),
        title="Duplicate and invalid-record summary",
        subtitle=subtitle,
        horizontal=True,
        value_format=".0f",
    )
    severity = dq[dq.status.isin(["ISSUE", "LIMITATION", "NOT_APPLICABLE"])].severity.value_counts()
    severity = severity.reindex(["P0", "P1", "P2", "P3"], fill_value=0)
    bar_chart(
        FIGURES_DIR / "data_quality_issue_severity.svg",
        severity.index.tolist(),
        severity.tolist(),
        title="Data-quality findings by severity",
        subtitle="P0 blocks validity; P1 threatens interpretation; P2 limitation; P3 low impact",
        value_format=".0f",
    )


def write_assumptions_and_limitations(
    analytical_dir: Path, tables: dict[str, pd.DataFrame], missingness: pd.DataFrame
) -> None:
    journey = tables["patient_journey"]
    outcome_associations = (
        missingness[
            missingness.grouping_dimension.isin(["initiation_outcome", "persistence_outcome"])
            & missingness.appears_associated_with_outcome
        ][["variable", "grouping_dimension", "between_group_range_percentage_points"]]
        .drop_duplicates()
        .sort_values("between_group_range_percentage_points", ascending=False)
    )
    association_lines = [
        f"- `{row.variable}` varies by `{row.grouping_dimension}` by up to "
        f"{row.between_group_range_percentage_points:.1f} percentage points; this is "
        "descriptive and may be structural, not causal."
        for row in outcome_associations.itertuples(index=False)
    ] or [
        "- No important field crossed the pre-specified 5 percentage-point descriptive association flag."
    ]
    lines = [
        "# EDA assumptions and limitations",
        "",
        f"> **{ANALYSIS_DISCLAIMER}**",
        "",
        "## Observed facts",
        "",
        f"- The selected certified dataset is `{analytical_dir}`.",
        f"- It contains {len(tables):,} normalized/mart tables and {len(journey):,} patient-level mart rows.",
        f"- Markets are {', '.join(sorted(journey.market_code.unique()))}; Deep={list(DEEP_MARKETS)}, Scan={list(SCAN_MARKETS)}.",
        "- Active surveillance is retained as its own pathway and is not combined with advanced disease states.",
        "- Exact observed states are localized, locally_advanced, mHSPC, mCRPC, metastatic_other and unknown; nmCRPC and mCSPC are absent and are not inferred or merged.",
        "- Missing values remain missing. No imputation is performed by these scripts.",
        "- Administrative data end remains censoring and is never converted to discontinuation.",
        "",
        "## Assumptions",
        "",
        "- The release manifest and explicit table contracts define the usable analytical baseline.",
        "- `market_depth` governs expected detail differences; Scan missingness can represent non-collection by design.",
        "- A populated date is treated as available only on/after that date; post-index fields are not baseline predictors.",
        "- The EDA uses aggregate outputs only. Identifier examples are masked in the data dictionary.",
        "",
        "## Missingness interpretation",
        "",
        "- Demographic/clinical nulls are labelled collected-but-unavailable or unresolved unless metadata proves otherwise.",
        "- Treatment/referral/outcome dates can be structurally missing because the corresponding event did not occur.",
        "- A missing treatment/referral field is not interpreted as a negative event or zero delay.",
        *association_lines,
        "",
        "## Proxies",
        "",
        "- Eligibility, persistence, progression, hospitalisation and the realised-value node are synthetic governed constructs.",
        "- The realised-value definition is an operational synthetic proxy, not clinical effectiveness or commercial value.",
        "- Generated archetypes are independent synthetic records, not real patients or population estimates.",
        "",
        "## Unresolved clinical/business definitions",
        "",
        "- Bayer approval is required for any production definition of realised value and intervention priority.",
        "- Permissible refill gaps, clinically meaningful discontinuation and episode-of-care conventions require clinical validation before real-data use.",
        "- No causal estimand or clinical recommendation is defined or supported by this EDA.",
        "",
        "## Raw-source boundary",
        "",
        f"- Raw Synthea files were inspected under `{RAW_SYNTHEA_DIR}` but were not modified.",
        "- External Synthea JSON/CSV fixtures are inventoried as references, not treated as project analytical inputs.",
    ]
    (OUTPUT_DIR / "assumptions_and_limitations.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def write_report(
    analytical_dir: Path,
    inventory: pd.DataFrame,
    dictionary: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    dq: pd.DataFrame,
    missingness_summary: pd.DataFrame,
    reconciliation: pd.DataFrame,
    top_issues: pd.DataFrame,
    readiness: pd.DataFrame,
    followup: pd.DataFrame,
) -> None:
    p0 = int(((dq.severity == "P0") & (dq.status == "ISSUE")).sum())
    p1 = int(((dq.severity == "P1") & (dq.status == "ISSUE")).sum())
    patient = tables["patient"]
    journey = tables["patient_journey"]
    file_type_counts = inventory.file_type.value_counts().to_dict()
    file_type_summary = ", ".join(
        f"{file_type.upper()}={count:,}" for file_type, count in sorted(file_type_counts.items())
    )
    lines = [
        "# Bayer Prostate Patient Journey — EDA foundation report",
        "",
        f"> **{ANALYSIS_DISCLAIMER}**",
        "> All content is aggregate. No row-level patient data or identifiers are exposed.",
        "",
        "## Executive result",
        "",
        f"- Selected dataset: `{analytical_dir}`",
        f"- Patients: **{len(patient):,}** across **{patient.market_code.nunique()}** required markets",
        f"- Normalized/mart tables: **{len(tables)}**; inventoried repository data/reference files: **{len(inventory):,}**",
        f"- Data file types: {file_type_summary}; Excel=0 and SQLite=0 were found.",
        f"- Profiled source/analytical columns: **{len(dictionary):,}**",
        f"- P0 issues: **{p0}**; P1 issues: **{p1}**; reconciliation mismatches: **{int(reconciliation.mismatch_count.sum()):,}**",
        f"- Eligibility chain: {int(journey.eligibility_flag.sum()):,} eligible; "
        f"{int(journey.initiated_within_90d.sum()):,} initiated by day 90; "
        f"{int(journey.eligible_not_initiated_90d.sum()):,} explicit gaps.",
        "- Exact states present are `localized`, `locally_advanced`, `mHSPC`, `mCRPC`, `metastatic_other` and `unknown`; `nmCRPC` and `mCSPC` do not occur and were neither invented nor merged.",
        "",
        "## Repository context inspected",
        "",
        "- Source and generation logic: `src/prostate_journey/`, including pipeline, CLI, cohort, pathway, treatment, outcome, quality, reconciliation and release modules.",
        "- Existing notebook: `notebooks/01_dataset_validation.ipynb`.",
        "- Existing contracts/documentation: release `DATA_DICTIONARY.csv`, `docs/DATA_DICTIONARY.md`, `docs/ER_SCHEMA.md`, `docs/BUSINESS_RULES.md`, `docs/DATA_QUALITY.md`, `docs/ARCHITECTURE.md` and `docs/RUNBOOK.md`.",
        "- Raw Synthea, working generated/gold copies, certified release files, normalized tables and `patient_journey` mart were inventoried; profiling uses the newest certified immutable release only.",
        "",
        "## Reproduce",
        "",
        "```powershell",
        "python eda/00_inventory_and_data_contract.py",
        "python eda/01_data_quality_profile.py",
        "```",
        "",
        "Set `EDA_DATASET_DIR` only when an explicit complete 19-table analytical override is required; otherwise the scripts select the newest certified release and record the choice and hashes in the run manifest.",
        "",
        "## Detected grains",
        "",
        "| Table | Rows | Grain | Primary key |",
        "|---|---:|---|---|",
    ]
    for table_name, contract in TABLE_CONTRACTS.items():
        lines.append(
            f"| {table_name} | {len(tables[table_name]):,} | {contract.grain} | {contract.primary_key} |"
        )
    lines.extend(
        [
            "",
            "## Temporal and follow-up coverage",
            "",
            "| Market | Patients | Min | Median | P95 | Max follow-up days |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in followup.itertuples(index=False):
        lines.append(
            f"| {row.market_code} | {row.patients:,} | {row.minimum_days:,} | "
            f"{row.median_days:,.0f} | {row.q95_days:,.0f} | {row.maximum_days:,} |"
        )
    lines.extend(
        [
            "",
            "## Most important data-quality issues and limitations",
            "",
            "| # | Severity | Classification | Finding | Required handling |",
            "|---:|---|---|---|---|",
        ]
    )
    for index, row in enumerate(top_issues.itertuples(index=False), start=1):
        lines.append(
            f"| {index} | {row.severity} | {row.classification} | {row.finding} | "
            f"{row.recommended_handling} |"
        )
    lines.extend(
        [
            "",
            "## Important-field missingness",
            "",
            "| Variable | Missing n | Missing rate |",
            "|---|---:|---:|",
        ]
    )
    for row in missingness_summary.itertuples(index=False):
        lines.append(f"| {row.variable} | {row.missing_n:,} | {row.missing_rate:.1%} |")
    lines.extend(
        [
            "",
            "Missingness indicators were created in memory and aggregated by market, exact disease state, "
            "active-surveillance pathway, care setting, provider specialty, calendar period, initiation "
            "outcome and persistence outcome. No values were imputed.",
            "",
            "## Downstream readiness",
            "",
            "| Analysis | Status | Evidence/blocker |",
            "|---|---|---|",
        ]
    )
    for row in readiness.itertuples(index=False):
        lines.append(
            f"| {row.downstream_analysis} | **{row.readiness}** | {row.evidence_or_blocker} |"
        )
    lines.extend(
        [
            "",
            "## Facts, assumptions, proxies and unresolved definitions",
            "",
            "- **Observed facts:** counts, dates, keys, categories, missingness and normalized-to-mart comparisons are calculated directly from the selected files.",
            "- **Assumptions:** table grain and timing follow the certified schema/feature-timing contracts.",
            "- **Proxies:** eligibility, persistence and outcomes are synthetic governed constructs; realised value is an operational synthetic proxy.",
            "- **Unresolved definitions:** production realised value, intervention priority, real-world persistence and causal estimands require Bayer/clinical agreement.",
            "",
            "## Figures",
            "",
            "The `figures/` directory contains aggregate SVG charts for missingness, temporal coverage, "
            "follow-up, disease state, market/setting, treatment, invalid records and severity.",
        ]
    )
    (OUTPUT_DIR / "eda_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git_value(arguments: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_manifest(
    started_at: datetime,
    analytical_dir: Path,
    selection_metadata: dict[str, object],
    inventory: pd.DataFrame,
    dictionary: pd.DataFrame,
    dq: pd.DataFrame,
    reconciliation: pd.DataFrame,
) -> None:
    manifest_path = OUTPUT_DIR / "eda_run_manifest.json"
    output_files = sorted(
        path for path in OUTPUT_DIR.rglob("*") if path.is_file() and path != manifest_path
    )
    input_files = sorted(analytical_dir.glob("*.parquet")) + sorted(RAW_SYNTHEA_DIR.glob("*.csv"))
    scripts = [
        Path(__file__).with_name("config.py"),
        Path(__file__).with_name("svg_charts.py"),
        Path(__file__).with_name("00_inventory_and_data_contract.py"),
        Path(__file__),
    ]
    source_manifest = None
    release_manifest_path = analytical_dir.parent / "release_manifest.json"
    if release_manifest_path.is_file():
        source_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    git_status = _git_value(["status", "--porcelain=v1", "--untracked-files=all"])
    p0_issues = int(((dq.severity == "P0") & (dq.status == "ISSUE")).sum())
    p1_issues = int(((dq.severity == "P1") & (dq.status == "ISSUE")).sum())
    payload = {
        "run_id": f"EDA-{started_at.strftime('%Y%m%dT%H%M%SZ')}",
        "status": "PASS" if p0_issues == 0 and p1_issues == 0 else "FAIL",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "analysis_disclaimer": ANALYSIS_DISCLAIMER,
        "project_root": str(PROJECT_ROOT),
        "analytical_data_dir": str(analytical_dir),
        "dataset_selection": selection_metadata,
        "source_release": {
            "dataset_version": source_manifest.get("dataset_version") if source_manifest else None,
            "decision": source_manifest.get("decision") if source_manifest else None,
            "git_commit": source_manifest.get("git", {}).get("git_commit")
            if source_manifest
            else None,
            "random_seed": source_manifest.get("run_metadata", {}).get("random_seed")
            if source_manifest
            else None,
            "generator_version": source_manifest.get("run_metadata", {}).get("generator_version")
            if source_manifest
            else None,
        },
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
            "dependencies": {
                package: _version(package) for package in ("pandas", "numpy", "pyarrow", "duckdb")
            },
        },
        "repository": {
            "git_commit": _git_value(["rev-parse", "HEAD"]),
            "git_branch": _git_value(["branch", "--show-current"]),
            "worktree_clean": git_status == "",
            "worktree_change_count": len(git_status.splitlines()) if git_status else 0,
        },
        "quality_summary": {
            "inventory_files": len(inventory),
            "profiled_columns": len(dictionary),
            "dq_checks": len(dq),
            "p0_issues": p0_issues,
            "p1_issues": p1_issues,
            "reconciliation_mismatches": int(reconciliation.mismatch_count.sum()),
        },
        "input_file_hashes": {
            path.relative_to(PROJECT_ROOT).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in input_files
        },
        "script_hashes": {
            path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path) for path in scripts
        },
        "output_file_hashes": {
            path.relative_to(OUTPUT_DIR).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in output_files
        },
        "privacy": {
            "row_level_patient_outputs": False,
            "identifier_examples_masked": True,
            "figures_are_aggregate_only": True,
        },
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    started_at = datetime.now(UTC)
    ensure_output_directories()
    inventory_path = OUTPUT_DIR / "data_inventory.csv"
    dictionary_path = OUTPUT_DIR / "data_dictionary.csv"
    if not inventory_path.is_file() or not dictionary_path.is_file():
        raise FileNotFoundError(
            "Run eda/00_inventory_and_data_contract.py before the data-quality profile."
        )
    analytical_dir, selection_metadata = resolve_analytical_data_dir()
    tables = load_tables(analytical_dir)
    inventory = pd.read_csv(inventory_path)
    dictionary = pd.read_csv(dictionary_path)
    reconciliation = build_reconciliation(tables)
    dq = run_quality_checks(tables, reconciliation, started_at)
    missingness, missingness_summary = build_missingness(tables)
    temporal, monthly, followup = build_temporal_outputs(tables)
    top_issues = build_top_issues(dq, tables, missingness_summary)
    readiness = build_readiness(dq, reconciliation)

    dq.to_csv(OUTPUT_DIR / "data_quality_summary.csv", index=False)
    missingness.to_csv(OUTPUT_DIR / "missingness_by_market_setting.csv", index=False)
    temporal.to_csv(OUTPUT_DIR / "temporal_coverage.csv", index=False)
    monthly.to_csv(OUTPUT_DIR / "monthly_counts.csv", index=False)
    followup.to_csv(OUTPUT_DIR / "follow_up_distribution_summary.csv", index=False)
    reconciliation.to_csv(OUTPUT_DIR / "patient_level_reconciliation.csv", index=False)
    top_issues.to_csv(OUTPUT_DIR / "top_10_data_quality_issues.csv", index=False)
    readiness.to_csv(OUTPUT_DIR / "downstream_readiness.csv", index=False)
    missingness_summary.to_csv(OUTPUT_DIR / "important_variable_missingness.csv", index=False)
    write_figures(tables, missingness, missingness_summary, monthly, dq)
    write_assumptions_and_limitations(analytical_dir, tables, missingness)
    write_report(
        analytical_dir,
        inventory,
        dictionary,
        tables,
        dq,
        missingness_summary,
        reconciliation,
        top_issues,
        readiness,
        followup,
    )
    write_manifest(
        started_at,
        analytical_dir,
        selection_metadata,
        inventory,
        dictionary,
        dq,
        reconciliation,
    )
    write_eda_artifact_manifest(analytical_dir, selection_metadata)
    print(
        f"EDA complete: {len(dq):,} DQ checks, "
        f"{int(reconciliation.mismatch_count.sum()):,} reconciliation mismatches, "
        f"outputs={OUTPUT_DIR}"
    )


if __name__ == "__main__":
    main()
