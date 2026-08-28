"""Inventory repository data and build a field-level exploratory data contract.

The inventory covers every CSV, Parquet, Excel, JSON, DuckDB and SQLite-like file
outside development/cache/output directories. Field profiling is deliberately
limited to the usable certified analytical tables and their raw Synthea inputs;
external Synthea test fixtures remain visible in the file inventory as references.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow.parquet as pq
from config import (
    DATA_EXTENSIONS,
    EXCLUDED_SCAN_PARTS,
    OUTCOME_OR_FUTURE_TOKENS,
    OUTPUT_DIR,
    PROJECT_ROOT,
    RAW_GRAINS,
    RAW_SYNTHEA_DIR,
    TABLE_CONTRACTS,
    ensure_output_directories,
    resolve_analytical_data_dir,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_data_files() -> list[Path]:
    files: list[Path] = []

    def ignore_error(_error: OSError) -> None:
        return None

    for directory, names, filenames in os.walk(PROJECT_ROOT, onerror=ignore_error):
        names[:] = [name for name in names if name not in EXCLUDED_SCAN_PARTS]
        root = Path(directory)
        for filename in filenames:
            path = root / filename
            if path.suffix.lower() in DATA_EXTENSIONS:
                files.append(path.resolve())
    return sorted(files)


def _csv_shape_and_columns(path: Path) -> tuple[int | None, int | None, list[str], str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
            reader = csv.reader(handle)
            columns = next(reader, [])
            rows = sum(1 for _ in reader)
        return rows, len(columns), columns, ""
    except (OSError, csv.Error) as error:
        return None, None, [], str(error)


def _parquet_shape_and_columns(path: Path) -> tuple[int | None, int | None, list[str], str]:
    try:
        metadata = pq.ParquetFile(path).metadata
        schema = pq.read_schema(path)
        return metadata.num_rows, metadata.num_columns, schema.names, ""
    except (OSError, ValueError) as error:
        return None, None, [], str(error)


def _json_shape_and_columns(path: Path) -> tuple[int | None, int | None, list[str], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            columns = sorted(
                {str(key) for item in payload[:100] if isinstance(item, dict) for key in item}
            )
            return len(payload), len(columns), columns, ""
        if isinstance(payload, dict):
            return 1, len(payload), [str(key) for key in payload], ""
        return 1, 1, ["value"], ""
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, None, [], str(error)


def _duckdb_shape_and_columns(path: Path) -> tuple[int | None, int | None, list[str], str]:
    try:
        connection = duckdb.connect(str(path), read_only=True)
        try:
            objects = connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY table_name"
            ).fetchall()
            row_count = 0
            column_count = 0
            names = []
            for (table_name,) in objects:
                quoted = table_name.replace('"', '""')
                row_count += int(
                    connection.execute(f'SELECT count(*) FROM "{quoted}"').fetchone()[0]
                )
                column_count += len(connection.execute(f'DESCRIBE "{quoted}"').fetchall())
                names.append(table_name)
            return row_count, column_count, names, ""
        finally:
            connection.close()
    except (OSError, duckdb.Error) as error:
        return None, None, [], str(error)


def _sqlite_shape_and_columns(path: Path) -> tuple[int | None, int | None, list[str], str]:
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            row_count = 0
            column_count = 0
            for table in tables:
                quoted = table.replace('"', '""')
                row_count += int(
                    connection.execute(f'SELECT count(*) FROM "{quoted}"').fetchone()[0]
                )
                column_count += len(connection.execute(f'PRAGMA table_info("{quoted}")').fetchall())
            return row_count, column_count, tables, ""
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        return None, None, [], str(error)


def _excel_shape_and_columns(path: Path) -> tuple[int | None, int | None, list[str], str]:
    try:
        frame = pd.read_excel(path)
        return len(frame), len(frame.columns), [str(column) for column in frame.columns], ""
    except (OSError, ValueError, ImportError) as error:
        return None, None, [], str(error)


def _file_shape(path: Path) -> tuple[int | None, int | None, list[str], str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _csv_shape_and_columns(path)
    if suffix == ".parquet":
        return _parquet_shape_and_columns(path)
    if suffix == ".json":
        return _json_shape_and_columns(path)
    if suffix == ".duckdb":
        return _duckdb_shape_and_columns(path)
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        return _sqlite_shape_and_columns(path)
    if suffix in {".xlsx", ".xls"}:
        return _excel_shape_and_columns(path)
    return None, None, [], "unsupported file type"


def _scope(path: Path, analytical_dir: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT)
    parts = relative.parts
    if path.is_relative_to(analytical_dir):
        return "certified_analytical_dataset"
    if parts[:3] == ("data", "raw", "synthea"):
        return "raw_source_dataset"
    if parts[:2] == ("data", "gold"):
        return "generated_working_dataset"
    if parts[:2] == ("data", "reports"):
        return "generated_report"
    if parts and parts[0] == "external":
        return "external_reference_or_fixture"
    if "qa_evidence" in parts:
        return "certified_qa_evidence"
    return "repository_reference_or_aggregate"


def _contract_details(path: Path, columns: list[str], analytical_dir: Path) -> tuple[str, str, str]:
    stem = path.stem
    canonical = stem in TABLE_CONTRACTS and (
        path.is_relative_to(analytical_dir) or path.is_relative_to(PROJECT_ROOT / "data" / "gold")
    )
    if canonical:
        contract = TABLE_CONTRACTS[stem]
        foreign_keys = "; ".join(
            f"{column}->{target_table}.{target_column}"
            for column, target_table, target_column in contract.foreign_keys
        )
        return contract.grain, contract.primary_key, foreign_keys
    if path.parent.resolve() == RAW_SYNTHEA_DIR.resolve() and stem in RAW_GRAINS:
        grain, primary_key = RAW_GRAINS[stem]
        candidate_fks = [
            column
            for column in columns
            if column.upper() in {"PATIENT", "ENCOUNTER", "PROVIDER", "ORGANIZATION", "PAYER"}
        ]
        return grain, primary_key or "", "; ".join(candidate_fks)
    if path.suffix.lower() == ".json":
        return "reference/configuration JSON object", "", ""
    if path.suffix.lower() in {".duckdb", ".db", ".sqlite", ".sqlite3"}:
        return "database container with multiple table grains", "", ""
    if "report" in path.name.lower() or "summary" in path.name.lower():
        return "aggregated report rows", "", ""
    return "unknown/reference table; inspect before analytical use", "", ""


def build_inventory(analytical_dir: Path, analysed_at: datetime) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in iter_data_files():
        row_count, column_count, columns, error = _file_shape(path)
        grain, primary_key, foreign_keys = _contract_details(path, columns, analytical_dir)
        lower_columns = {column.lower() for column in columns}
        patient_id_available = bool(
            {"patient_id", "patient", "id"} & lower_columns
            or any("patient" in column for column in lower_columns)
        )
        event_date_available = any(
            any(token in column for token in ("date", "start", "stop", "time"))
            and not column.startswith("days_")
            for column in lower_columns
        )
        rows.append(
            {
                "file_name": path.name,
                "relative_path": path.relative_to(PROJECT_ROOT).as_posix(),
                "file_type": path.suffix.lower().lstrip("."),
                "data_scope": _scope(path, analytical_dir),
                "row_count": row_count,
                "column_count": column_count,
                "database_or_json_objects": "; ".join(columns[:25]),
                "file_size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "analysis_date_utc": analysed_at.date().isoformat(),
                "suspected_grain": grain,
                "candidate_primary_key": primary_key,
                "candidate_foreign_keys": foreign_keys,
                "patient_identifier_available": patient_id_available,
                "event_date_available": event_date_available,
                "inspection_error": error,
            }
        )
    return pd.DataFrame(rows).sort_values(["data_scope", "relative_path"], ignore_index=True)


def _read_profile_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def _looks_like_date(column: str, series: pd.Series) -> bool:
    name = column.lower()
    explicit = (
        name.endswith("_date")
        or name in {"date", "birthdate", "deathdate", "start", "stop"}
        or name.endswith("date")
    )
    return explicit or pd.api.types.is_datetime64_any_dtype(series.dtype)


def _semantic_role(column: str, series: pd.Series) -> str:
    name = column.lower()
    if name.endswith("_id") or name in {"id", "patient", "encounter", "provider"}:
        return "identifier_or_foreign_key"
    if _looks_like_date(column, series):
        return "temporal"
    if any(token in name for token in ("outcome", "progression", "death", "persistence")):
        return "outcome_or_endpoint"
    if any(token in name for token in ("treatment", "regimen", "drug", "refill", "supply")):
        return "treatment_or_medication"
    if any(token in name for token in ("stage", "gleason", "isup", "psa", "metastatic")):
        return "clinical_state_or_measure"
    if any(token in name for token in ("market", "country", "region", "setting", "specialty")):
        return "market_or_pathway_segment"
    if name.endswith("_flag") or pd.api.types.is_bool_dtype(series.dtype):
        return "indicator"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "numeric_measure"
    return "categorical_or_descriptive"


def _timing_and_leakage(
    column: str, timing_lookup: dict[str, tuple[str, bool, bool]], source_group: str
) -> tuple[str, str]:
    if source_group == "analytical" and column in timing_lookup:
        stage, future, target = timing_lookup[column]
        risk = (
            "HIGH: target/outcome-derived; never use as predictor"
            if target
            else "HIGH: future/post-index information"
            if future
            else "CONDITIONAL: enforce documented availability cutoff"
            if stage not in {"baseline", "diagnosis", "identifier"}
            else "LOW at the documented index"
        )
        return stage, risk
    name = column.lower()
    if any(token in name for token in OUTCOME_OR_FUTURE_TOKENS):
        return "outcome_or_post_index", "HIGH unless used only as target/descriptive endpoint"
    if _looks_like_date(column, pd.Series(dtype="object")):
        return "event_time", "CONDITIONAL: require date <= analysis/prediction cutoff"
    return "baseline_or_source_dependent", "UNKNOWN until source timing is confirmed"


def _safe_examples(column: str, series: pd.Series) -> str:
    name = column.lower()
    if name.endswith("_id") or name in {
        "id",
        "patient",
        "encounter",
        "provider",
        "organization",
        "source_patient_id",
        "source_archetype_id",
        "first",
        "middle",
        "last",
        "maiden",
        "name",
        "address",
        "ssn",
        "drivers",
        "passport",
        "phone",
        "email",
        "birthdate",
        "deathdate",
    }:
        return "<direct/quasi-identifier values masked>"
    values = series.dropna().astype("string").drop_duplicates().head(3)
    return " | ".join(str(value)[:60] for value in values)


def _missingness_type(column: str) -> str:
    if column in {
        "referral_delay_days",
        "decision_owner_specialty",
        "initial_regimen",
        "event_coverage_until_date",
        "progression_date",
        "death_date",
    }:
        return "mixed_structural_or_event_dependent"
    if column in {"product_id", "drug_name"}:
        return "may_be_not_collected_by_market_design"
    return "collected_but_unavailable_or_unknown"


def build_data_dictionary(analytical_dir: Path) -> pd.DataFrame:
    timing = pd.read_parquet(analytical_dir / "feature_timing.parquet")
    timing_lookup = {
        str(row.feature_name): (
            str(row.availability_stage),
            bool(row.future_information_flag),
            bool(row.target_label_flag),
        )
        for row in timing.itertuples(index=False)
    }
    profile_sources: list[tuple[str, str, Path]] = [
        ("analytical", table, analytical_dir / f"{table}.parquet") for table in TABLE_CONTRACTS
    ]
    profile_sources.extend(
        ("raw_synthea", path.stem, path) for path in sorted(RAW_SYNTHEA_DIR.glob("*.csv"))
    )
    rows: list[dict[str, Any]] = []
    for source_group, table_name, path in profile_sources:
        frame = _read_profile_table(path)
        contract = TABLE_CONTRACTS.get(table_name)
        candidate_pk = (
            contract.primary_key if contract else RAW_GRAINS.get(table_name, ("", None))[1]
        )
        for column in frame.columns:
            series = frame[column]
            missing_pct = float(series.isna().mean() * 100) if len(frame) else 0.0
            unique_values = int(series.nunique(dropna=True))
            numeric = (
                pd.to_numeric(series, errors="coerce")
                if pd.api.types.is_numeric_dtype(series.dtype)
                and not pd.api.types.is_bool_dtype(series.dtype)
                else None
            )
            dates = (
                pd.to_datetime(series, errors="coerce")
                if _looks_like_date(str(column), series)
                else None
            )
            timing_stage, leakage = _timing_and_leakage(str(column), timing_lookup, source_group)
            concerns: list[str] = []
            if missing_pct >= 20:
                concerns.append(f"high missingness ({missing_pct:.1f}%)")
            if unique_values <= 1 and len(frame):
                concerns.append("constant or all-missing field")
            if candidate_pk == column and (series.isna().any() or series.duplicated().any()):
                concerns.append("candidate primary key is null or duplicated")
            if dates is not None and series.notna().any() and dates.notna().mean() < 0.95:
                concerns.append("some date values do not parse")
            rows.append(
                {
                    "source_group": source_group,
                    "source_table": table_name,
                    "source_file": path.relative_to(PROJECT_ROOT).as_posix(),
                    "column_name": str(column),
                    "data_type": str(series.dtype),
                    "missing_percentage": round(missing_pct, 6),
                    "unique_values": unique_values,
                    "example_values": _safe_examples(str(column), series),
                    "numeric_min": numeric.min()
                    if numeric is not None and numeric.notna().any()
                    else None,
                    "numeric_q05": numeric.quantile(0.05)
                    if numeric is not None and numeric.notna().any()
                    else None,
                    "numeric_q25": numeric.quantile(0.25)
                    if numeric is not None and numeric.notna().any()
                    else None,
                    "numeric_median": numeric.median()
                    if numeric is not None and numeric.notna().any()
                    else None,
                    "numeric_q75": numeric.quantile(0.75)
                    if numeric is not None and numeric.notna().any()
                    else None,
                    "numeric_q95": numeric.quantile(0.95)
                    if numeric is not None and numeric.notna().any()
                    else None,
                    "numeric_max": numeric.max()
                    if numeric is not None and numeric.notna().any()
                    else None,
                    "date_min": dates.min().date().isoformat()
                    if dates is not None and dates.notna().any()
                    else None,
                    "date_max": dates.max().date().isoformat()
                    if dates is not None and dates.notna().any()
                    else None,
                    "likely_semantic_role": _semantic_role(str(column), series),
                    "timing_classification": timing_stage,
                    "possible_leakage_risk": leakage,
                    "missingness_interpretation": _missingness_type(str(column)),
                    "data_quality_concerns": "; ".join(concerns)
                    or "none observed in univariate profile",
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["source_group", "source_table", "column_name"], ignore_index=True
    )


def main() -> None:
    ensure_output_directories()
    analysed_at = datetime.now(UTC)
    analytical_dir, selection_metadata = resolve_analytical_data_dir()
    inventory = build_inventory(analytical_dir, analysed_at)
    dictionary = build_data_dictionary(analytical_dir)
    inventory.to_csv(OUTPUT_DIR / "data_inventory.csv", index=False)
    dictionary.to_csv(OUTPUT_DIR / "data_dictionary.csv", index=False)
    summary = {
        "analysis_started_at_utc": analysed_at.isoformat(),
        "analytical_data_dir": str(analytical_dir),
        "selection": selection_metadata,
        "inventory_files": len(inventory),
        "profiled_columns": len(dictionary),
        "inspection_errors": int(inventory.inspection_error.astype(bool).sum()),
    }
    (OUTPUT_DIR / "inventory_run_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(
        f"Wrote {len(inventory):,} inventory rows and {len(dictionary):,} field profiles "
        f"from {analytical_dir}"
    )


if __name__ == "__main__":
    main()
