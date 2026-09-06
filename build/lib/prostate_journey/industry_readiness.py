"""Executable Industry Readiness Baseline gates for synthetic project artifacts.

These checks validate the repository's own contracts. They are engineering and
analytical controls, not regulatory, clinical, privacy, security, or production
certification.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pandas as pd
import yaml

from . import DISCLAIMER, __version__
from .dashboard import eligible_cohort_funnel_counts
from .data_quality import validate_tables
from .dataset_resolver import (
    ACCEPTED_RELEASE_DECISIONS,
    AnalyticalDataset,
    resolve_analytical_dataset,
)
from .model_governance import (
    DISPOSITIONS,
    load_model_governance,
    load_model_target_contracts,
    validate_model_alias_configuration,
)
from .pipeline import TABLES, load_exported_tables
from .predictive_evidence import (
    DECISION_CURVE_BLOCK,
    load_model_evaluation_config,
    verify_predictive_evidence_manifest,
)
from .reporting import sha256
from .scientific_evidence import (
    load_analysis_registry,
    verify_scientific_evidence_manifest,
)
from .scientific_methods import load_event_hierarchy
from .simulation import load_simulation_spec, verify_simulation_manifest
from .synthetic_utility import load_real_data_hook_spec

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"
CONTRACT_RELATIVE_PATH = Path("contracts/analytical_data_contract.yaml")
SCIENTIFIC_CHART_FILES = (
    "survival_curves.csv",
    "number_at_risk.csv",
    "cumulative_incidence.csv",
    "estimator_uncertainty.csv",
    "missingness_method_performance.csv",
    "missingness_tipping_point.csv",
    "synthetic_utility_dimensions.csv",
)
SIMULATION_CHART_FILES = (
    "simulation_replicate_metrics.csv",
    "within_scenario_variability.csv",
    "monte_carlo_error.csv",
    "scenario_envelope.csv",
    "sensitivity_drivers.csv",
)
PREDICTIVE_CHART_FILES = (
    "model_population_derivation.csv",
    "validation_metrics.csv",
    "flexible_calibration_curves.csv",
    "leakage_audit.csv",
    "validation_fold_registry.csv",
    "subgroup_metrics.csv",
    "robustness_metrics.csv",
    "prior_claim_reproduction.csv",
    "model_disposition.csv",
)


@dataclass(frozen=True)
class CheckResult:
    """One machine-readable readiness gate result."""

    check_id: str
    category: str
    status: str
    detail: str
    evidence: str
    failure_count: int = 0


def _result(
    check_id: str,
    category: str,
    failures: int,
    detail: str,
    evidence: str,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        category=category,
        status=PASS if failures == 0 else FAIL,
        detail=detail,
        evidence=evidence,
        failure_count=int(failures),
    )


def _skip(check_id: str, category: str, detail: str, evidence: str) -> CheckResult:
    return CheckResult(check_id, category, SKIPPED, detail, evidence)


def load_contract(path: str | Path) -> dict[str, Any]:
    """Load the analytical YAML contract and reject a non-mapping root."""
    contract_path = Path(path)
    payload = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Analytical contract must be a mapping: {contract_path}")
    return payload


def validate_contract_structure(contract: dict[str, Any], evidence: str) -> list[CheckResult]:
    """Validate completeness and internal consistency of the YAML contract."""
    required_top = {
        "contract_version",
        "status",
        "synthetic_data_only",
        "tables",
        "cohort_rules",
        "model_populations",
        "artifact_schemas",
    }
    missing_top = required_top - set(contract)
    results = [
        _result(
            "contract.top_level",
            "data_contract",
            len(missing_top),
            "required contract sections are present"
            if not missing_top
            else f"missing sections: {sorted(missing_top)}",
            evidence,
        )
    ]
    tables = contract.get("tables")
    if not isinstance(tables, dict):
        results.append(
            _result(
                "contract.tables",
                "data_contract",
                1,
                "tables must be a mapping",
                evidence,
            )
        )
        return results

    expected_tables = set(TABLES)
    table_names = set(tables)
    failures: list[str] = []
    if table_names != expected_tables:
        failures.append(
            f"table set mismatch; missing={sorted(expected_tables - table_names)}, "
            f"extra={sorted(table_names - expected_tables)}"
        )
    for table_name, raw_spec in tables.items():
        if not isinstance(raw_spec, dict):
            failures.append(f"{table_name}: specification is not a mapping")
            continue
        required = raw_spec.get("required_columns", [])
        non_nullable = raw_spec.get("non_nullable_fields", [])
        nullable = raw_spec.get("nullable_fields", [])
        primary_key = raw_spec.get("primary_key")
        if not raw_spec.get("grain") or not primary_key:
            failures.append(f"{table_name}: grain or primary key missing")
        if (
            not isinstance(required, list)
            or not isinstance(non_nullable, list)
            or not isinstance(nullable, list)
        ):
            failures.append(f"{table_name}: field lists must be arrays")
            continue
        required_set = set(required)
        non_nullable_set = set(non_nullable)
        nullable_set = set(nullable)
        if primary_key not in required_set or primary_key not in non_nullable_set:
            failures.append(f"{table_name}: primary key must be required and non-nullable")
        if non_nullable_set & nullable_set:
            failures.append(f"{table_name}: nullable/non-nullable fields overlap")
        if required_set != non_nullable_set | nullable_set:
            failures.append(f"{table_name}: required fields are not fully nullability-classified")
        for foreign_key in raw_spec.get("foreign_keys", []):
            if not isinstance(foreign_key, dict):
                failures.append(f"{table_name}: foreign key is not a mapping")
                continue
            target_table = foreign_key.get("target_table")
            target_field = foreign_key.get("target_field")
            field = foreign_key.get("field")
            if field not in required_set:
                failures.append(f"{table_name}.{field}: foreign-key field is not required")
            target_spec = tables.get(target_table, {})
            if target_field not in target_spec.get("required_columns", []):
                failures.append(
                    f"{table_name}.{field}: target {target_table}.{target_field} is undefined"
                )
    results.append(
        _result(
            "contract.table_specs",
            "data_contract",
            len(failures),
            "all 19 table grains, keys, fields, nullability classes and references are coherent"
            if not failures
            else "; ".join(failures[:10]),
            evidence,
        )
    )

    cohort_rules = contract.get("cohort_rules", {})
    model_populations = contract.get("model_populations", {})
    artifact_schemas = contract.get("artifact_schemas", {})
    semantic_failures = int(not isinstance(cohort_rules, dict) or len(cohort_rules) < 2)
    semantic_failures += int(not isinstance(model_populations, dict) or len(model_populations) < 4)
    semantic_failures += int(not isinstance(artifact_schemas, dict) or len(artifact_schemas) < 4)
    results.append(
        _result(
            "contract.analysis_and_artifacts",
            "data_contract",
            semantic_failures,
            "cohort, denominator, model-population and output-artifact contracts are declared",
            evidence,
        )
    )
    synthetic_failures = int(contract.get("synthetic_data_only") is not True)
    results.append(
        _result(
            "contract.synthetic_boundary",
            "governance",
            synthetic_failures,
            "contract explicitly limits all records and outputs to synthetic demonstration use",
            evidence,
        )
    )
    return results


def _load_contract_tables(
    dataset_dir: Path, contract: dict[str, Any]
) -> tuple[dict[str, pd.DataFrame], list[CheckResult]]:
    table_specs = contract["tables"]
    missing = [name for name in table_specs if not (dataset_dir / f"{name}.parquet").is_file()]
    result = _result(
        "dataset.required_tables",
        "schema",
        len(missing),
        "all contract tables are present" if not missing else f"missing tables: {missing}",
        str(dataset_dir),
    )
    if missing:
        return {}, [result]
    return load_exported_tables(dataset_dir), [result]


def validate_dataset_contract(
    dataset_dir: str | Path, contract: dict[str, Any]
) -> list[CheckResult]:
    """Validate schemas, keys, categories, chronology and analytical semantics."""
    root = Path(dataset_dir).resolve()
    tables, results = _load_contract_tables(root, contract)
    if not tables:
        return results
    specs: dict[str, Any] = contract["tables"]

    schema_issues: list[str] = []
    null_failures = 0
    key_failures = 0
    category_failures = 0
    chronology_failures = 0
    for table_name, spec in specs.items():
        frame = tables[table_name]
        required = set(spec["required_columns"])
        missing_columns = required - set(frame.columns)
        extra_columns = set(frame.columns) - required
        if missing_columns or extra_columns:
            schema_issues.append(
                f"{table_name}: missing={sorted(missing_columns)}, extra={sorted(extra_columns)}"
            )
        available_non_null = set(spec["non_nullable_fields"]) & set(frame.columns)
        null_failures += sum(int(frame[field].isna().sum()) for field in available_non_null)
        primary_key = str(spec["primary_key"])
        if primary_key in frame:
            key_failures += int(frame[primary_key].isna().sum())
            key_failures += int(frame[primary_key].duplicated().sum())
        for field, values in spec.get("allowed_values", {}).items():
            if field not in frame:
                continue
            actual = set(frame[field].dropna().astype(str).unique())
            category_failures += len(actual - {str(value) for value in values})
        for invariant in spec.get("temporal_invariants", []):
            pair = invariant.get("before_or_equal", []) if isinstance(invariant, dict) else []
            if len(pair) != 2 or not set(pair).issubset(frame.columns):
                chronology_failures += 1
                continue
            left = pd.to_datetime(frame[pair[0]], errors="coerce")
            right = pd.to_datetime(frame[pair[1]], errors="coerce")
            parse_failures = frame[pair[0]].notna() & left.isna()
            parse_failures |= frame[pair[1]].notna() & right.isna()
            chronology_failures += int(parse_failures.sum())
            chronology_failures += int((left.notna() & right.notna() & left.gt(right)).sum())

    results.extend(
        [
            _result(
                "dataset.columns",
                "schema",
                len(schema_issues),
                "all table columns exactly match the contract"
                if not schema_issues
                else "; ".join(schema_issues[:8]),
                str(root),
            ),
            _result(
                "dataset.non_nullable",
                "schema",
                null_failures,
                "all contract non-nullable fields are populated",
                str(root),
            ),
            _result(
                "dataset.primary_keys",
                "key_integrity",
                key_failures,
                "all primary keys are non-null and unique",
                str(root),
            ),
            _result(
                "dataset.allowed_values",
                "schema",
                category_failures,
                "categorical values remain within contract domains",
                str(root),
            ),
            _result(
                "dataset.temporal_invariants",
                "chronology",
                chronology_failures,
                "all machine-readable before-or-equal invariants pass",
                str(root),
            ),
        ]
    )

    foreign_key_failures = 0
    for table_name, spec in specs.items():
        child = tables[table_name]
        for foreign_key in spec.get("foreign_keys", []):
            field = foreign_key["field"]
            if field not in child:
                foreign_key_failures += 1
                continue
            parent = tables[foreign_key["target_table"]]
            parent_values = parent[foreign_key["target_field"]]
            populated = child[field].dropna()
            foreign_key_failures += int((~populated.isin(parent_values)).sum())
    results.append(
        _result(
            "dataset.foreign_keys",
            "key_integrity",
            foreign_key_failures,
            "all populated foreign keys resolve to contract targets",
            str(root),
        )
    )

    dq = validate_tables(tables)
    critical_failures = sum(
        int(item["failure_count"]) for item in dq if item["severity"] == "critical"
    )
    failed_rules = [item["rule"] for item in dq if item["failure_count"]]
    results.append(
        _result(
            "dataset.implementation_quality",
            "analytical_integrity",
            critical_failures,
            f"{len(dq)} implementation-level DQ rules pass"
            if not failed_rules
            else f"failed rules: {failed_rules}",
            "src/prostate_journey/data_quality.py",
        )
    )
    results.extend(_validate_denominators(tables["patient_journey"], str(root)))
    results.append(_validate_leakage(tables, str(root)))
    return results


def _validate_denominators(journey: pd.DataFrame, evidence: str) -> list[CheckResult]:
    eligible = journey.eligibility_flag.fillna(False).astype(bool)
    initiated = eligible & journey.initiated_within_90d.fillna(False).astype(bool)
    gap = eligible & journey.eligible_not_initiated_90d.fillna(False).astype(bool)
    censored = eligible & journey.initiation_90d_status.eq("CENSORED_NOT_EVALUABLE")
    funnel = eligible_cohort_funnel_counts(journey)
    partition_failures = abs(
        funnel["eligible"]
        - funnel["initiated_90d"]
        - funnel["treatment_gap_90d"]
        - funnel["initiation_censored_not_evaluable_90d"]
    )
    partition_failures += int((initiated & gap).sum())
    partition_failures += int((initiated & censored).sum())
    partition_failures += int((gap & censored).sum())

    statuses = journey.persistence_12m_status
    evaluable = initiated & statuses.isin(["PERSISTENT", "DISCONTINUED", "SWITCHED"])
    persistence_censored = initiated & statuses.eq("CENSORED_NOT_EVALUABLE")
    persistence_failures = abs(
        int(initiated.sum()) - int(evaluable.sum()) - int(persistence_censored.sum())
    )
    persistence_failures += max(0, funnel["persistent_12m"] - funnel["evaluable_12m"])

    semantics_failures = int(
        (
            journey.initiated_within_90d.fillna(False).astype(bool)
            != journey.initiation_90d_status.eq("INITIATED_WITHIN_90D")
        ).sum()
    )
    semantics_failures += int(
        (
            journey.eligible_not_initiated_90d.fillna(False).astype(bool)
            != journey.initiation_90d_status.eq("NOT_INITIATED_WITHIN_90D")
        ).sum()
    )
    semantics_failures += int((journey.initiation_90d_status.eq("NOT_ELIGIBLE") != ~eligible).sum())
    semantics_failures += int(
        (statuses.eq("PERSISTENT") & ~journey.persistent_12m.fillna(False).astype(bool)).sum()
    )
    semantics_failures += int(
        (statuses.eq("CENSORED_NOT_EVALUABLE") & journey.persistent_12m.notna()).sum()
    )
    return [
        _result(
            "analysis.initiation_denominator",
            "denominator_reconciliation",
            partition_failures,
            "eligible = initiated within 90d + treatment gap + censored not evaluable",
            evidence,
        ),
        _result(
            "analysis.persistence_denominator",
            "denominator_reconciliation",
            persistence_failures,
            "90-day initiators partition into 12-month evaluable and censored states",
            evidence,
        ),
        _result(
            "analysis.censoring_semantics",
            "censoring",
            semantics_failures,
            "status fields, nullable flags and censoring states agree row by row",
            evidence,
        ),
    ]


def _validate_leakage(tables: dict[str, pd.DataFrame], evidence: str) -> CheckResult:
    timing = tables["feature_timing"]
    journey = tables["patient_journey"]
    split = tables["patient_split"]
    failures = int((timing.future_information_flag & timing.predictor_allowed_flag).sum())
    failures += int((timing.target_label_flag & timing.predictor_allowed_flag).sum())
    failures += len(set(journey.columns) - set(timing.feature_name))
    failures += int(timing.feature_name.duplicated().sum())
    failures += int(split.groupby("source_archetype_id").split.nunique().gt(1).sum())
    return _result(
        "analysis.leakage_controls",
        "leakage",
        failures,
        "future/target fields are excluded from predictors and archetypes do not cross splits",
        evidence,
    )


def validate_release_provenance(source: AnalyticalDataset) -> list[CheckResult]:
    """Validate release identity, source provenance and exported-file hashes."""
    manifest = source.release_manifest
    if not manifest:
        return [
            _skip(
                "release.provenance",
                "release_consistency",
                "working dataset has no release manifest",
                str(source.analytical_dir),
            )
        ]
    release_path = source.release_dir or source.analytical_dir.parent
    run = manifest.get("run_metadata", {})
    required = [
        manifest.get("dataset_version"),
        manifest.get("created_at"),
        manifest.get("git", {}).get("git_commit"),
        run.get("config_snapshot_sha256"),
        run.get("generator_version"),
        run.get("scenario_version"),
        run.get("clinical_rules_version"),
        manifest.get("code_version"),
        manifest.get("active_analytical_definition"),
    ]
    identity_failures = sum(value in (None, "") for value in required)
    identity_failures += int(manifest.get("dataset_version") != release_path.name)
    identity_failures += int(manifest.get("decision") not in ACCEPTED_RELEASE_DECISIONS)
    identity_failures += int(manifest.get("immutable") is not True)
    identity_failures += int(manifest.get("formal_compliance_claim") is not False)
    identity_failures += int(manifest.get("synthetic_data_only") is not True)

    hash_failures = 0
    declared_hashes = run.get("output_file_hashes", {})
    for table in TABLES:
        path = source.analytical_dir / f"{table}.parquet"
        declared = declared_hashes.get(path.name, {}).get("sha256")
        if not path.is_file() or not declared or sha256(path) != declared:
            hash_failures += 1
    return [
        _result(
            "release.identity_and_lineage",
            "release_consistency",
            identity_failures,
            (
                "release ID, commit, config hash, versions, timestamp and immutable "
                "decision are recorded"
            ),
            str(release_path / "release_manifest.json"),
        ),
        _result(
            "release.table_hashes",
            "release_consistency",
            hash_failures,
            "all analytical Parquet hashes match generation provenance",
            str(release_path / "release_manifest.json"),
        ),
    ]


def _markdown_files(project_root: Path) -> list[Path]:
    files = [project_root / "README.md", project_root / "CHANGELOG.md"]
    for directory in ("docs", "analysis_extensions", "experiments"):
        root = project_root / directory
        if root.is_dir():
            files.extend(
                path for path in root.rglob("*.md") if "outputs" not in path.relative_to(root).parts
            )
    return sorted({path for path in files if path.is_file()})


def validate_markdown_links(project_root: str | Path) -> CheckResult:
    """Check local Markdown targets while leaving external links to network tooling."""
    root = Path(project_root).resolve()
    pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    failures: list[str] = []
    checked = 0
    for document in _markdown_files(root):
        for line_number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            for raw_target in pattern.findall(line):
                target = raw_target.strip().strip("<>").split("#", 1)[0].strip()
                if not target or re.match(r"^(?:https?://|mailto:|tel:)", target, re.I):
                    continue
                if " " in target and not target.startswith(("./", "../")):
                    target = target.split(" ", 1)[0]
                checked += 1
                resolved = (document.parent / unquote(target)).resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    failures.append(
                        f"{document.relative_to(root)}:{line_number}: outside repository"
                    )
                    continue
                if not resolved.exists():
                    failures.append(f"{document.relative_to(root)}:{line_number}: missing {target}")
    return _result(
        "docs.local_links",
        "documentation",
        len(failures),
        f"{checked} local Markdown targets resolve" if not failures else "; ".join(failures[:12]),
        "README.md; docs/**/*.md",
    )


def validate_frontend_source(project_root: str | Path) -> CheckResult:
    """Smoke-test accessibility and dynamic-data markers in the frontend generator."""
    source = Path(project_root).resolve() / "src/prostate_journey/executive_dashboard.py"
    text = source.read_text(encoding="utf-8")
    required = [
        '<html lang="en">',
        "<main",
        'href="#main-content"',
        ":focus-visible",
        'role="dialog"',
        'aria-modal="true"',
        "Escape",
        "dashboardData",
    ]
    missing = [marker for marker in required if marker not in text]
    hardcoded = [
        marker
        for marker in (
            "10,000 synthetic patients",
            "seven synthetic markets",
            "7 configured markets",
        )
        if marker in text
    ]
    failures = len(missing) + len(hardcoded)
    detail = (
        (
            "frontend generator has semantic landmarks, keyboard dialog handling, "
            "visible focus and dynamic KPIs"
        )
        if not failures
        else f"missing={missing}; hardcoded={hardcoded}"
    )
    return _result(
        "frontend.source_smoke",
        "frontend",
        failures,
        detail,
        str(source.relative_to(Path(project_root).resolve())),
    )


def validate_scientific_frontend_source(project_root: str | Path) -> CheckResult:
    """Smoke-test the aggregate scientific frontend generator contract."""
    root = Path(project_root).resolve()
    source = root / "src/prostate_journey/scientific_dashboard.py"
    text = source.read_text(encoding="utf-8")
    required = [
        '<html lang="en">',
        '<main class="shell"',
        'href="#main-content"',
        ":focus-visible",
        'role="dialog"',
        'aria-modal="true"',
        "Escape",
        "scienceData",
        "Three different uncertainty questions",
        "No universal realism score",
    ]
    missing = [marker for marker in required if marker not in text]
    return _result(
        "frontend.scientific_source_smoke",
        "frontend",
        len(missing),
        "scientific frontend has uncertainty controls, method dialogs, boundaries and a skip link"
        if not missing
        else f"missing={missing}",
        str(source.relative_to(root)),
    )


def validate_predictive_frontend_source(project_root: str | Path) -> CheckResult:
    """Smoke-test the aggregate prediction-model frontend and its non-use boundaries."""
    root = Path(project_root).resolve()
    source = root / "src/prostate_journey/predictive_dashboard.py"
    text = source.read_text(encoding="utf-8")
    required = [
        '<html lang="en">',
        '<main class="shell"',
        'href="#main-content"',
        ":focus-visible",
        'role="dialog"',
        'aria-modal="true"',
        "Escape",
        "modelEvidenceData",
        "Prediction evidence, with every limitation visible",
        "0 deployable models",
        "never ranked",
    ]
    missing = [marker for marker in required if marker not in text]
    return _result(
        "frontend.predictive_source_smoke",
        "frontend",
        len(missing),
        "predictive frontend exposes model evidence, uncertainty, governance and non-use gates"
        if not missing
        else f"missing={missing}",
        str(source.relative_to(root)),
    )


def validate_predictive_source_specs(project_root: str | Path) -> list[CheckResult]:
    """Validate model contracts, nested evaluation policy, governance, and alias blocking."""
    root = Path(project_root).resolve()
    results: list[CheckResult] = []
    contract_path = root / "contracts/model_target_contracts.yaml"
    governance_path = root / "contracts/model_governance.yaml"
    evaluation_path = root / "configs/model_evaluation.yaml"
    aliases_path = root / "configs/model_aliases.yaml"
    contracts: dict[str, Any] | None = None
    governance: dict[str, Any] | None = None
    try:
        contracts = load_model_target_contracts(contract_path)
        expected_targets = {
            "non_initiated_within_90_days",
            "discontinued_within_12_months",
            "switched_treatment",
            "restarted_after_gap",
        }
        models = contracts["models"]
        failures = int({str(model["target_name"]) for model in models} != expected_targets)
        failures += sum(model["reviewer_status"] != "NOT YET VALIDATED" for model in models)
        failures += sum(bool(model["operational_action_defined"]) for model in models)
        failures += sum(not model["denominator_derivation"] for model in models)
        failures += sum(not model["simple_comparator"] for model in models)
        restart = next(model for model in models if model["model_id"] == "restart_after_gap")
        failures += int(int(restart["prediction_horizon_days"]) != 365)
        failures += int("restart_date" not in str(restart["outcome_definition"]))
        failures += int(not restart.get("retrospective_selection_warning"))
        results.append(
            _result(
                "prediction.target_contracts",
                "predictive_methods",
                failures,
                "four complete target contracts fix populations, timing, outcomes, harms and uses",
                str(contract_path.relative_to(root)),
            )
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        results.append(
            _result(
                "prediction.target_contracts",
                "predictive_methods",
                1,
                str(error),
                str(contract_path.relative_to(root)),
            )
        )

    try:
        evaluation = load_model_evaluation_config(evaluation_path)
        validation = evaluation["validation"]
        robustness = evaluation["robustness"]
        required_stresses = {
            "initiation_windows_days",
            "persistence_gap_days",
            "added_feature_missingness_rates",
            "feature_removal_sets",
            "prevalence_odds_multipliers",
            "include_simplified_model",
        }
        failures = int(evaluation["principal_validation"] != "repeated_rolling_temporal")
        failures += int(evaluation["random_row_split_allowed_as_principal_evidence"] is not False)
        failures += int(validation["calibration_method"] != "nested_temporal_platt")
        failures += int(validation["feature_selection"] != "none")
        failures += len(required_stresses - set(robustness))
        failures += int(
            evaluation["disposition_policy"]["maximum_automatic_disposition"] != "RESEARCH ONLY"
        )
        results.append(
            _result(
                "prediction.evaluation_spec",
                "predictive_methods",
                failures,
                (
                    "temporal, market, nested calibration, comparators, uncertainty and "
                    "stresses are fixed"
                ),
                str(evaluation_path.relative_to(root)),
            )
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        results.append(
            _result(
                "prediction.evaluation_spec",
                "predictive_methods",
                1,
                str(error),
                str(evaluation_path.relative_to(root)),
            )
        )

    try:
        governance = load_model_governance(governance_path)
        failures = int(governance["synthetic_data_only"] is not True)
        failures += int(set(governance["disposition_states"]) != DISPOSITIONS)
        failures += int(
            governance["drift_monitoring_specification"]["status"]
            != "BLOCKED PENDING GOVERNED REAL DATA AND APPROVED USE"
        )
        results.append(
            _result(
                "prediction.responsible_ai_spec",
                "governance",
                failures,
                "harms, oversight, stop-use, misuse, drift, incident and validation controls exist",
                str(governance_path.relative_to(root)),
            )
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        results.append(
            _result(
                "prediction.responsible_ai_spec",
                "governance",
                1,
                str(error),
                str(governance_path.relative_to(root)),
            )
        )

    try:
        if contracts is None or governance is None:
            raise ValueError("Target contracts and governance must pass before alias validation")
        dispositions = {
            str(model["model_id"]): str(model["current_disposition"])
            for model in contracts["models"]
        }
        validate_model_alias_configuration(aliases_path, dispositions, governance)
        aliases = yaml.safe_load(aliases_path.read_text(encoding="utf-8"))
        failures = int(aliases.get("assignments") != [])
        results.append(
            _result(
                "prediction.alias_policy",
                "governance",
                failures,
                "no rejected or research-only model can enter an operational alias",
                str(aliases_path.relative_to(root)),
            )
        )
    except (OSError, KeyError, PermissionError, TypeError, ValueError) as error:
        results.append(
            _result(
                "prediction.alias_policy",
                "governance",
                1,
                str(error),
                str(aliases_path.relative_to(root)),
            )
        )
    return results


def validate_scientific_source_specs(project_root: str | Path) -> list[CheckResult]:
    """Validate the scientific registry, event hierarchy, scenarios, and blocked hooks."""
    root = Path(project_root).resolve()
    results: list[CheckResult] = []
    try:
        registry = load_analysis_registry(root / "contracts/analysis_registry.yaml")
        identifiers = {str(item["analysis_id"]) for item in registry["analyses"]}
        registry_failures = int(len(identifiers) < 14)
        registry_failures += int(
            not {
                "cohort_definition",
                "initiation_funnel",
                "persistence_landmark",
                "missingness_profile_and_truth_recovery",
                "predict_non_initiation_90d",
                "predict_discontinuation_12m",
                "predict_treatment_switch",
                "predict_restart_after_gap",
            }.issubset(identifiers)
        )
        results.append(
            _result(
                "science.analysis_registry",
                "scientific_methods",
                registry_failures,
                f"{len(identifiers)} analyses have complete estimand-style metadata and "
                "honest statuses",
                "contracts/analysis_registry.yaml",
            )
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        results.append(
            _result(
                "science.analysis_registry",
                "scientific_methods",
                1,
                str(error),
                "contracts/analysis_registry.yaml",
            )
        )

    required_events = {
        "initiation",
        "discontinuation",
        "switch",
        "restart",
        "progression",
        "hospitalization",
        "death",
        "loss_to_follow_up",
        "administrative_data_end",
    }
    try:
        hierarchy = load_event_hierarchy(root / "configs/event_hierarchy.yaml")
        event_failures = len(required_events - set(hierarchy["events"]))
        event_failures += int(hierarchy.get("status") != "PROPOSED CLINICAL DEFINITION")
        results.append(
            _result(
                "science.event_hierarchy",
                "scientific_methods",
                event_failures,
                "minimum event set, deterministic priorities, and proposed status are declared",
                "configs/event_hierarchy.yaml",
            )
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        results.append(
            _result(
                "science.event_hierarchy",
                "scientific_methods",
                1,
                str(error),
                "configs/event_hierarchy.yaml",
            )
        )

    try:
        simulation = load_simulation_spec(root / "configs/simulation_scenarios.yaml")
        settings = simulation["simulation"]
        scenario_failures = int(int(settings["seeds_per_scenario"]) < 100)
        scenario_failures += int(int(settings["adaptive_batch_size"]) < 1)
        scenario_failures += int(float(settings["mcse_tolerance_rate"]) <= 0)
        for scenario in simulation["scenarios"].values():
            scenario_failures += int(scenario.get("requires_sme_review") is not True)
            scenario_failures += int(scenario.get("reviewer_status") != "NOT YET VALIDATED")
            scenario_failures += int(scenario.get("assumption_status") != "REQUIRES SME REVIEW")
        results.append(
            _result(
                "science.simulation_spec",
                "scientific_methods",
                scenario_failures,
                "low/base/high coherent stress tests start at 100 seeds and require SME review",
                "configs/simulation_scenarios.yaml",
            )
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        results.append(
            _result(
                "science.simulation_spec",
                "scientific_methods",
                1,
                str(error),
                "configs/simulation_scenarios.yaml",
            )
        )

    try:
        hooks = load_real_data_hook_spec(root / "contracts/real_data_evaluation_hooks.yaml")
        hook_failures = int(hooks.get("default_status") != "BLOCKED")
        hook_failures += int(len(hooks.get("hooks", [])) < 5)
        hook_failures += sum(item.get("status") != "BLOCKED" for item in hooks["hooks"])
        results.append(
            _result(
                "science.real_data_hooks",
                "governance",
                hook_failures,
                "real-data fidelity, TSTR, privacy-attack and distance evaluations remain BLOCKED",
                "contracts/real_data_evaluation_hooks.yaml",
            )
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        results.append(
            _result(
                "science.real_data_hooks",
                "governance",
                1,
                str(error),
                "contracts/real_data_evaluation_hooks.yaml",
            )
        )
    return results


def _chart_metadata_failures(
    root: Path,
    filenames: tuple[str, ...],
    required_columns: set[str],
) -> tuple[int, list[str]]:
    failures = 0
    details: list[str] = []
    for filename in filenames:
        path = root / filename
        if not path.is_file():
            failures += 1
            details.append(f"missing {filename}")
            continue
        try:
            frame = pd.read_csv(path)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
            failures += 1
            details.append(f"{filename}: {error}")
            continue
        missing = sorted(required_columns - set(frame.columns))
        if missing:
            failures += len(missing)
            details.append(f"{filename}: missing {missing}")
    return failures, details


def validate_scientific_package(
    scientific_dir: str | Path,
    source: AnalyticalDataset,
    contract: dict[str, Any],
) -> list[CheckResult]:
    """Validate scientific hashes, metadata, numerical reconciliation, and claim boundaries."""
    root = Path(scientific_dir).resolve()
    manifest_path = root / "scientific_evidence_manifest.json"
    if not manifest_path.is_file():
        return [
            _result(
                "science.package_manifest",
                "scientific_evidence",
                1,
                "scientific evidence manifest is missing",
                str(manifest_path),
            )
        ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_manifest = contract["artifact_schemas"]["scientific_evidence_manifest.json"][
        "required_fields"
    ]
    manifest_failures = sum(field not in manifest for field in required_manifest)
    manifest_failures += int(manifest.get("release") != source.dataset_version)
    manifest_failures += int(manifest.get("synthetic_data_only") is not True)
    manifest_failures += int(manifest.get("formal_clinical_or_regulatory_claim") is not False)
    manifest_failures += int(manifest.get("causal_interpretation_allowed") is not False)
    expected_commit = source.release_manifest.get("git", {}).get("git_commit")
    if expected_commit:
        manifest_failures += int(manifest.get("source_commit") != expected_commit)
    try:
        verify_scientific_evidence_manifest(root)
    except (OSError, KeyError, TypeError, ValueError) as error:
        manifest_failures += 1
        manifest_detail = f"sealed package verification failed: {error}"
    else:
        manifest_detail = "manifest, marker, release identity, boundaries, and artifact hashes pass"

    required_columns = set(
        contract["artifact_schemas"]["scientific_chart_ready_csv"]["required_columns"]
    )
    metadata_failures, metadata_details = _chart_metadata_failures(
        root, SCIENTIFIC_CHART_FILES, required_columns
    )

    numerical_failures = 0
    try:
        risk = pd.read_csv(root / "number_at_risk.csv")
        curves = pd.read_csv(root / "survival_curves.csv")
        cif = pd.read_csv(root / "cumulative_incidence.csv")
        numerical_failures += int(not risk.reconciliation_difference.eq(0).all())
        numerical_failures += sum(
            int(group.n_at_risk_after.iloc[-1] != 0)
            for _, group in risk.groupby("endpoint", sort=False)
        )
        for column in (
            "survival_probability",
            "net_event_probability",
            "confidence_lower",
            "confidence_upper",
        ):
            numerical_failures += int(not curves[column].between(0, 1).all())
        numerical_failures += int(not cif.cumulative_incidence.between(0, 1).all())
        numerical_failures += sum(
            int(not group.cumulative_incidence.is_monotonic_increasing)
            for _, group in cif.sort_values("time_days").groupby(["endpoint", "cause"])
        )
        for _, endpoint in cif.sort_values("time_days").groupby("endpoint"):
            latest = endpoint.groupby("cause").tail(1)
            probability_mass = float(latest.cumulative_incidence.sum()) + float(
                latest.all_event_survival.iloc[0]
            )
            numerical_failures += int(abs(probability_mass - 1.0) > 1e-8)
    except (OSError, KeyError, TypeError, ValueError, pd.errors.ParserError):
        numerical_failures += 1

    boundary_failures = 0
    try:
        frontend = json.loads(
            (root / "scientific_frontend_summary.json").read_text(encoding="utf-8")
        )
        utility = pd.read_csv(root / "synthetic_utility_dimensions.csv")
        boundary_failures += int(frontend.get("synthetic_data_only") is not True)
        boundary_failures += int(frontend.get("causal_interpretation_allowed") is not False)
        boundary_failures += int(frontend.get("clinical_validation_status") != "NOT YET VALIDATED")
        governed = utility.loc[utility.dimension.eq("governed_real_data_evaluation")]
        boundary_failures += int(governed.empty or not governed.status.eq("BLOCKED").all())
        impossible = utility.loc[
            utility.metric.eq("mutually_exclusive_or_post_censor_conflicts"), "value"
        ]
        boundary_failures += int(impossible.empty or float(impossible.iloc[0]) != 0.0)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, pd.errors.ParserError):
        boundary_failures += 1

    return [
        _result(
            "science.package_manifest",
            "scientific_evidence",
            manifest_failures,
            manifest_detail,
            str(manifest_path),
        ),
        _result(
            "science.chart_metadata",
            "scientific_evidence",
            metadata_failures,
            "all chart-ready scientific tables contain required interpretation metadata"
            if not metadata_failures
            else "; ".join(metadata_details[:8]),
            str(root),
        ),
        _result(
            "science.numerical_reconciliation",
            "scientific_evidence",
            numerical_failures,
            "risk sets, probability ranges, monotonic CIFs, and probability mass reconcile",
            str(root),
        ),
        _result(
            "science.claim_and_state_boundaries",
            "governance",
            boundary_failures,
            "synthetic/non-causal labels, impossible-state gate, and BLOCKED real-data hooks pass",
            str(root),
        ),
    ]


def validate_simulation_package(
    simulation_dir: str | Path,
    source: AnalyticalDataset,
    contract: dict[str, Any],
) -> list[CheckResult]:
    """Validate multi-seed manifests, minimum runs, metadata, and uncertainty labels."""
    root = Path(simulation_dir).resolve()
    manifest_path = root / "simulation_manifest.json"
    if not manifest_path.is_file():
        return [
            _result(
                "simulation.package_manifest",
                "simulation_evidence",
                1,
                "simulation manifest is missing",
                str(manifest_path),
            )
        ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_manifest = contract["artifact_schemas"]["simulation_manifest.json"]["required_fields"]
    manifest_failures = sum(field not in manifest for field in required_manifest)
    manifest_failures += int(manifest.get("release") != source.dataset_version)
    manifest_failures += int(manifest.get("synthetic_data_only") is not True)
    manifest_failures += int(manifest.get("formal_clinical_or_market_claim") is not False)
    manifest_failures += int(manifest.get("source_tracked_clean") is not True)
    expected_commit = source.release_manifest.get("git", {}).get("git_commit")
    if expected_commit:
        manifest_failures += int(manifest.get("source_commit") != expected_commit)
    manifest_failures += sum(
        int(int(manifest.get("completed_seeds", {}).get(scenario, 0)) < 100)
        for scenario in ("low", "base", "high")
    )
    try:
        verify_simulation_manifest(root)
    except (OSError, KeyError, TypeError, ValueError) as error:
        manifest_failures += 1
        manifest_detail = f"sealed simulation verification failed: {error}"
    else:
        manifest_detail = "parent/child hashes, source identity, and seed minimums pass"

    required_columns = set(
        contract["artifact_schemas"]["simulation_chart_ready_csv"]["required_columns"]
    )
    metadata_failures, metadata_details = _chart_metadata_failures(
        root, SIMULATION_CHART_FILES, required_columns
    )
    label_failures = 0
    try:
        labels = {
            "within_scenario_variability.csv": "WITHIN_SCENARIO_SIMULATION_INTERVAL_95",
            "monte_carlo_error.csv": "MONTE_CARLO_STANDARD_ERROR",
            "scenario_envelope.csv": "SCENARIO_ASSUMPTION_ENVELOPE_NOT_CONFIDENCE_INTERVAL",
            "sensitivity_drivers.csv": "SCENARIO_SENSITIVITY_DRIVER",
        }
        for filename, expected in labels.items():
            actual = set(pd.read_csv(root / filename).uncertainty_type.astype(str))
            label_failures += int(actual != {expected})
        label_failures += int(len(set(labels.values())) != len(labels))
    except (OSError, KeyError, pd.errors.ParserError):
        label_failures += 1
    return [
        _result(
            "simulation.package_manifest",
            "simulation_evidence",
            manifest_failures,
            manifest_detail,
            str(manifest_path),
        ),
        _result(
            "simulation.chart_metadata",
            "simulation_evidence",
            metadata_failures,
            "all chart-ready simulation tables contain required interpretation metadata"
            if not metadata_failures
            else "; ".join(metadata_details[:8]),
            str(root),
        ),
        _result(
            "simulation.uncertainty_labels",
            "simulation_evidence",
            label_failures,
            "regeneration, Monte Carlo, scenario-envelope, and driver labels remain separate",
            str(root),
        ),
    ]


def validate_predictive_package(
    predictive_dir: str | Path,
    source: AnalyticalDataset,
    contract: dict[str, Any],
) -> list[CheckResult]:
    """Validate predictive evidence, nesting, dispositions, cards, and non-use controls."""
    root = Path(predictive_dir).resolve()
    manifest_path = root / "predictive_evidence_manifest.json"
    if not manifest_path.is_file():
        return [
            _result(
                "prediction.package_manifest",
                "predictive_evidence",
                1,
                "predictive evidence manifest is missing",
                str(manifest_path),
            )
        ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = contract["artifact_schemas"]["predictive_evidence_manifest.json"]["required_fields"]
    manifest_failures = sum(field not in manifest for field in required)
    manifest_failures += int(manifest.get("release") != source.dataset_version)
    manifest_failures += int(manifest.get("synthetic_data_only") is not True)
    manifest_failures += int(manifest.get("external_validation") is not False)
    manifest_failures += int(manifest.get("clinical_validation") is not False)
    manifest_failures += int(manifest.get("deployable") is not False)
    manifest_failures += int(manifest.get("patient_level_predictions_included") is not False)
    manifest_failures += int(
        manifest.get("random_row_split_used_as_principal_evidence") is not False
    )
    manifest_failures += int(manifest.get("decision_curve_generated") is not False)
    manifest_failures += int(manifest.get("analysis_worktree_clean") is not True)
    expected_commit = source.release_manifest.get("git", {}).get("git_commit")
    if expected_commit:
        manifest_failures += int(manifest.get("source_commit") != expected_commit)
        manifest_failures += int(manifest.get("analysis_commit") != expected_commit)
    component_hashes = manifest.get("configuration_component_hashes")
    expected_components = {
        "model_target_contracts_snapshot.yaml",
        "model_evaluation_snapshot.yaml",
        "model_governance_snapshot.yaml",
        "model_aliases_snapshot.yaml",
    }
    if not isinstance(component_hashes, dict):
        manifest_failures += 1
    else:
        manifest_failures += len(expected_components ^ set(component_hashes))
        for filename in expected_components & set(component_hashes):
            path = root / filename
            manifest_failures += int(not path.is_file())
            if path.is_file():
                manifest_failures += int(component_hashes[filename] != sha256(path))
    forbidden_exports = {
        "patient_predictions.csv",
        "patient_scores.csv",
        "predictions.csv",
        "scores.csv",
    }
    actual_names = {path.name.lower() for path in root.rglob("*") if path.is_file()}
    manifest_failures += len(actual_names & forbidden_exports)
    manifest_failures += len(list(root.rglob("*.parquet")))
    try:
        verify_predictive_evidence_manifest(root)
    except (OSError, KeyError, TypeError, ValueError) as error:
        manifest_failures += 1
        manifest_detail = f"sealed predictive package verification failed: {error}"
    else:
        manifest_detail = "manifest, immutable marker, release identity and artifact hashes pass"

    required_columns = set(
        contract["artifact_schemas"]["predictive_chart_ready_csv"]["required_columns"]
    )
    metadata_failures, metadata_details = _chart_metadata_failures(
        root, PREDICTIVE_CHART_FILES, required_columns
    )
    for filename in PREDICTIVE_CHART_FILES:
        path = root / filename
        if path.is_file():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                header = lines[0].split(",")
                frame = pd.read_csv(path)
            except (IndexError, OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
                metadata_failures += 1
                metadata_details.append(f"{filename}: {error}")
            else:
                if len(header) != len(set(header)):
                    metadata_failures += 1
                    metadata_details.append(f"{filename}: duplicate columns")
                if frame.empty or set(frame.configuration_hash.astype(str)) != {
                    str(manifest.get("configuration_hash"))
                }:
                    metadata_failures += 1
                    metadata_details.append(f"{filename}: predictive configuration hash mismatch")

    population_failures = 0
    validation_failures = 0
    leakage_failures = 0
    boundary_failures = 0
    try:
        derivation = pd.read_csv(root / "model_population_derivation.csv")
        dispositions = pd.read_csv(root / "model_disposition.csv")
        model_ids = set(dispositions.model_id.astype(str))
        population_failures += int(len(model_ids) != 4)
        population_failures += int(not derivation.reconciliation_difference.eq(0).all())
        population_failures += int(
            not derivation.entered_n.eq(derivation.excluded_n + derivation.retained_n).all()
        )
        for model_id, group in derivation.sort_values("step_order").groupby("model_id"):
            disposition = dispositions.loc[dispositions.model_id.eq(model_id)]
            population_failures += int(disposition.empty)
            if not disposition.empty:
                population_failures += int(
                    int(group.retained_n.iloc[-1]) != int(disposition.analysis_population_n.iloc[0])
                )
    except (OSError, KeyError, TypeError, ValueError, pd.errors.ParserError):
        population_failures += 1

    try:
        metrics = pd.read_csv(root / "validation_metrics.csv")
        folds = pd.read_csv(root / "validation_fold_registry.csv")
        prior = pd.read_csv(root / "prior_claim_reproduction.csv")
        designs = {"ROLLING_TEMPORAL", "FINAL_TEMPORAL_HOLDOUT", "LEAVE_ONE_MARKET_OUT"}
        validation_failures += int("RANDOM" in " ".join(metrics.evaluation_design.astype(str)))
        for model_id in model_ids:
            current = metrics.loc[metrics.model_id.eq(model_id)]
            validation_failures += len(designs - set(current.evaluation_design.astype(str)))
            final = current.loc[
                current.evaluation_design.eq("FINAL_TEMPORAL_HOLDOUT")
                & current.status.eq("EVALUATED")
            ]
            validation_failures += int(
                set(final.model.astype(str))
                != {
                    "regularized_logistic_nested_calibration",
                    "training_prevalence_comparator",
                }
            )
            primary = final.loc[final.model.eq("regularized_logistic_nested_calibration")]
            validation_failures += int(len(primary) != 1)
            if len(primary) == 1:
                required_numeric = (
                    "roc_auc",
                    "pr_auc",
                    "brier_score",
                    "calibration_intercept",
                    "calibration_slope",
                    "roc_auc_ci_lower",
                    "roc_auc_ci_upper",
                    "pr_auc_ci_lower",
                    "pr_auc_ci_upper",
                )
                validation_failures += int(primary[list(required_numeric)].isna().any(axis=None))
            comparator = final.loc[final.model.eq("training_prevalence_comparator")]
            if len(comparator) == 1:
                validation_failures += int(
                    abs(
                        float(comparator.pr_auc.iloc[0])
                        - float(comparator.event_prevalence.iloc[0])
                    )
                    > 1e-10
                )
        validation_failures += int(
            not metrics.threshold_metrics_status.dropna()
            .astype(str)
            .str.startswith("NOT REPORTED")
            .all()
        )
        validation_failures += int(prior.exact_reproduction_claimed.astype(bool).any())
        temporal = folds.loc[
            folds.evaluation_design.isin(["ROLLING_TEMPORAL", "FINAL_TEMPORAL_HOLDOUT"])
        ]
        validation_failures += int(
            not pd.to_datetime(temporal.outer_train_max_time)
            .lt(pd.to_datetime(temporal.validation_min_time))
            .all()
        )
    except (OSError, KeyError, TypeError, ValueError, pd.errors.ParserError):
        validation_failures += 1

    try:
        leakage = pd.read_csv(root / "leakage_audit.csv")
        folds = pd.read_csv(root / "validation_fold_registry.csv")
        leakage_failures += int(not leakage.status.dropna().eq("PASS").all())
        leakage_failures += int(
            pd.to_numeric(leakage.failure_count, errors="coerce").fillna(0).sum()
        )
        leakage_failures += int(
            not folds.preprocessor_fitted_on_validation.astype(str).str.lower().eq("false").all()
        )
        leakage_failures += int(
            not folds.imputer_fitted_on_validation.astype(str).str.lower().eq("false").all()
        )
        leakage_failures += int(
            not folds.calibration_fit_scope.astype(str)
            .str.contains("inner temporal|identity fallback", regex=True)
            .all()
        )
        audited_targets = leakage.target.dropna().astype(str).unique()
        leakage_failures += int(len(audited_targets) != 4)
        for target in audited_targets:
            checks = set(leakage.loc[leakage.target.eq(target), "check"].dropna().astype(str))
            leakage_failures += int("outcome_not_after_declared_horizon" not in checks)
    except (OSError, KeyError, TypeError, ValueError, pd.errors.ParserError):
        leakage_failures += 1

    try:
        dca = json.loads((root / "decision_curve_status.json").read_text(encoding="utf-8"))
        dispositions = pd.read_csv(root / "model_disposition.csv")
        subgroups = pd.read_csv(root / "subgroup_metrics.csv")
        robustness = pd.read_csv(root / "robustness_metrics.csv")
        expected_robustness = {
            "ALTERNATIVE_INITIATION_WINDOW",
            "ALTERNATIVE_PERSISTENCE_GAP",
            "ADDED_PREDICTOR_MISSINGNESS",
            "FEATURE_REMOVAL",
            "SIMPLIFIED_MODEL",
            "PREVALENCE_SHIFT",
            "TEMPORAL_SHIFT",
            "MARKET_HOLDOUT",
        }
        boundary_failures += int(dca.get("statement") != DECISION_CURVE_BLOCK)
        boundary_failures += int(dca.get("decision_curve_generated") is not False)
        boundary_failures += sum(
            item.get("statement") != DECISION_CURVE_BLOCK for item in dca.get("models", [])
        )
        boundary_failures += int(not set(dispositions.disposition).issubset(DISPOSITIONS))
        boundary_failures += int(
            dispositions.disposition.isin(
                ["CANDIDATE FOR EXTERNAL VALIDATION", "APPROVED FOR A SPECIFIED USE"]
            ).any()
        )
        boundary_failures += int(
            dispositions.promotion_to_operational_alias_allowed.astype(bool).any()
        )
        boundary_failures += int(subgroups.ranking_allowed.astype(bool).any())
        boundary_failures += len(expected_robustness - set(robustness.robustness_type))
        prevalence_shift = robustness.loc[
            robustness.robustness_type.eq("PREVALENCE_SHIFT") & robustness.status.eq("EVALUATED")
        ]
        boundary_failures += int(prevalence_shift.empty)
        if not prevalence_shift.empty:
            rounding_tolerance = 1 / prevalence_shift.validation_n.astype(float)
            boundary_failures += int(
                prevalence_shift.event_prevalence.sub(prevalence_shift.requested_event_prevalence)
                .abs()
                .gt(rounding_tolerance + 1e-12)
                .any()
            )
            boundary_failures += int(
                not prevalence_shift.resampling_method.eq(
                    "OUTCOME_STRATIFIED_WITH_REPLACEMENT_NO_REFIT"
                ).all()
            )
        governance = load_model_governance(root / "model_governance_snapshot.yaml")
        disposition_map = dict(zip(dispositions.model_id, dispositions.disposition, strict=True))
        validate_model_alias_configuration(
            root / "model_aliases_snapshot.yaml", disposition_map, governance
        )
        card_index = json.loads((root / "model_cards/index.json").read_text(encoding="utf-8"))
        boundary_failures += int(len(card_index) != 4)
        for card in card_index:
            payload = json.loads(
                (root / "model_cards" / str(card["json"])).read_text(encoding="utf-8")
            )
            model_id = str(card["model_id"])
            boundary_failures += int(payload.get("release") != source.dataset_version)
            boundary_failures += int(payload.get("source_commit") != expected_commit)
            boundary_failures += int(payload.get("deployable") is not False)
            boundary_failures += int(
                payload.get("disposition", {}).get("disposition") != disposition_map.get(model_id)
            )
    except (
        OSError,
        KeyError,
        PermissionError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        pd.errors.ParserError,
    ):
        boundary_failures += 1

    return [
        _result(
            "prediction.package_manifest",
            "predictive_evidence",
            manifest_failures,
            manifest_detail,
            str(manifest_path),
        ),
        _result(
            "prediction.chart_metadata",
            "predictive_evidence",
            metadata_failures,
            "all predictive aggregate tables have unique columns and interpretation metadata"
            if not metadata_failures
            else "; ".join(metadata_details[:8]),
            str(root),
        ),
        _result(
            "prediction.population_reconciliation",
            "predictive_evidence",
            population_failures,
            "every model population attrition row and final analysis n reconcile",
            str(root / "model_population_derivation.csv"),
        ),
        _result(
            "prediction.validation_design",
            "predictive_evidence",
            validation_failures,
            (
                "temporal, untouched holdout, market, comparator, uncertainty and "
                "calibration evidence pass"
            ),
            str(root / "validation_metrics.csv"),
        ),
        _result(
            "prediction.leakage_and_nesting",
            "leakage",
            leakage_failures,
            (
                "all feature, patient, time, market, preprocessing, imputation and "
                "calibration gates pass"
            ),
            str(root / "leakage_audit.csv"),
        ),
        _result(
            "prediction.responsible_ai_boundaries",
            "governance",
            boundary_failures,
            (
                "DCA is blocked; subgroup ranking, approval, deployability and alias "
                "promotion are prohibited"
            ),
            str(root),
        ),
    ]


def validate_presentation_package(
    presentation_dir: str | Path,
    source: AnalyticalDataset,
    contract: dict[str, Any],
) -> list[CheckResult]:
    """Validate release identity, KPI parity, hashes, guardrails and HTML smoke markers."""
    root = Path(presentation_dir).resolve()
    manifest_path = root / "presentation_manifest.json"
    if not manifest_path.is_file():
        return [
            _result(
                "presentation.manifest",
                "presentation",
                1,
                "presentation manifest is missing",
                str(manifest_path),
            )
        ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = contract["artifact_schemas"]["presentation_manifest.json"]["required_fields"]
    missing = [field for field in required if field not in manifest]
    provenance_required = [
        manifest.get("dataset_version"),
        manifest.get("generated_at"),
        manifest.get("source_git", {}).get("git_commit"),
        manifest.get("configuration_hash"),
        manifest.get("code_version"),
        manifest.get("active_analytical_definition"),
    ]
    identity_failures = len(missing) + sum(value in (None, "", {}) for value in provenance_required)
    identity_failures += int(manifest.get("dataset_version") != source.dataset_version)
    identity_failures += int(
        manifest.get("source_release_decision") not in ACCEPTED_RELEASE_DECISIONS
    )
    identity_failures += int(manifest.get("consistency_gate") != "PASSED")
    identity_failures += int(manifest.get("patient_level_data_included") is not False)
    predictive_presentation = manifest.get("predictive_evidence", {})
    if predictive_presentation.get("available"):
        identity_failures += int(
            predictive_presentation.get("patient_level_predictions_included") is not False
        )
        identity_failures += int(predictive_presentation.get("deployable_models") != 0)

    hash_failures = 0
    for name, spec in manifest.get("output_files", {}).items():
        path = root / name
        if not path.is_file() or path.stat().st_size != int(spec.get("bytes", -1)):
            hash_failures += 1
        elif sha256(path) != spec.get("sha256"):
            hash_failures += 1

    kpi_path = root / "presentation_kpis.csv"
    journey = pd.read_parquet(source.analytical_dir / "patient_journey.parquet")
    expected = eligible_cohort_funnel_counts(journey)
    kpi_failures = 0
    if not kpi_path.is_file():
        kpi_failures = 1
    else:
        frame = pd.read_csv(kpi_path).set_index("kpi")["value"]
        comparisons = {
            "total_patients": len(journey),
            "markets": int(journey.market_code.nunique()),
            "eligible": expected["eligible"],
            "initiated_90d_among_eligible": expected["initiated_90d"],
            "treatment_gap_90d_among_eligible": expected["treatment_gap_90d"],
            "initiation_censored_90d_among_eligible": expected[
                "initiation_censored_not_evaluable_90d"
            ],
            "evaluable_12m_among_eligible_initiated_90d": expected["evaluable_12m"],
            "persistent_12m_among_eligible_initiated_90d": expected["persistent_12m"],
            "censored_12m_among_eligible_initiated_90d": expected["censored_12m"],
        }
        for name, value in comparisons.items():
            kpi_failures += int(name not in frame.index or int(frame.get(name, -1)) != value)
            kpi_failures += int(int(manifest.get("headline_kpis", {}).get(name, -1)) != value)

    html_failures = 0
    frontend_names = ["cohort_dashboard.html", "executive_story.html"]
    if manifest.get("scientific_evidence", {}).get("available"):
        frontend_names.append("scientific_story.html")
    if predictive_presentation.get("available"):
        frontend_names.append("model_story.html")
    for name in frontend_names:
        path = root / name
        if not path.is_file():
            html_failures += 1
            continue
        text = path.read_text(encoding="utf-8")
        markers = [
            "<!doctype html>",
            '<html lang="en">',
            "<main",
            source.dataset_version,
            "SYNTHETIC",
        ]
        html_failures += sum(marker.lower() not in text.lower() for marker in markers)
        if name == "executive_story.html":
            html_failures += int('href="#main-content"' not in text)
            html_failures += int(":focus-visible" not in text)
            html_failures += int('role="dialog"' not in text)
        if name == "scientific_story.html":
            html_failures += int("scienceData" not in text)
            html_failures += int("Three different uncertainty questions" not in text)
            html_failures += int('role="dialog"' not in text)
        if name == "model_story.html":
            html_failures += int("modelEvidenceData" not in text)
            html_failures += int("0 deployable models" not in text)
            html_failures += int('role="dialog"' not in text)

    patient_export_failures = len(list(root.rglob("*.parquet")))
    return [
        _result(
            "presentation.identity_and_provenance",
            "presentation",
            identity_failures,
            (
                "presentation records one release, source commit, config hash, code "
                "version and definitions"
            ),
            str(manifest_path),
        ),
        _result(
            "presentation.output_hashes",
            "presentation",
            hash_failures,
            "every declared presentation artifact exists and matches its SHA-256",
            str(manifest_path),
        ),
        _result(
            "presentation.headline_kpis",
            "release_consistency",
            kpi_failures,
            "headline KPIs reconcile across source mart, CSV and presentation manifest",
            str(kpi_path),
        ),
        _result(
            "presentation.frontend_smoke",
            "frontend",
            html_failures,
            "both generated HTML files expose semantic, release and synthetic-data markers",
            str(root),
        ),
        _result(
            "presentation.aggregate_only",
            "privacy_boundary",
            patient_export_failures,
            "stakeholder package contains no patient-level Parquet export",
            str(root),
        ),
    ]


def validate_eda_manifest(eda_dir: str | Path, source: AnalyticalDataset) -> CheckResult:
    """Require all current EDA outputs to be mapped to the selected release."""
    root = Path(eda_dir).resolve()
    manifest_path = root / "eda_artifact_manifest.json"
    if not manifest_path.is_file():
        return _result(
            "eda.artifact_provenance",
            "release_consistency",
            1,
            "EDA artifact manifest is missing",
            str(manifest_path),
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    provenance = payload.get("provenance", {})
    failures = int(provenance.get("dataset_version") != source.dataset_version)
    failures += int(not provenance.get("source_commit"))
    failures += int(not provenance.get("configuration_hash"))
    failures += int(payload.get("code_version") != __version__)
    for relative, spec in payload.get("artifacts", {}).items():
        path = root / relative
        failures += int(not path.is_file())
        if path.is_file():
            failures += int(path.stat().st_size != int(spec.get("bytes", -1)))
            failures += int(sha256(path) != spec.get("sha256"))
    return _result(
        "eda.artifact_provenance",
        "release_consistency",
        failures,
        "all EDA outputs map by hash to the selected release and active definitions",
        str(manifest_path),
    )


def run_industry_checks(
    project_root: str | Path,
    *,
    dataset_dir: str | Path | None = None,
    presentation_dir: str | Path | None = None,
    eda_dir: str | Path | None = None,
    scientific_dir: str | Path | None = None,
    simulation_dir: str | Path | None = None,
    predictive_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    allow_missing_release: bool = False,
) -> dict[str, Any]:
    """Run source and optional artifact gates and persist one JSON report."""
    root = Path(project_root).resolve()
    contract_path = root / CONTRACT_RELATIVE_PATH
    contract = load_contract(contract_path)
    checks = validate_contract_structure(contract, str(CONTRACT_RELATIVE_PATH))
    checks.extend(
        [
            validate_markdown_links(root),
            validate_frontend_source(root),
            validate_scientific_frontend_source(root),
            validate_predictive_frontend_source(root),
        ]
    )
    checks.extend(validate_scientific_source_specs(root))
    checks.extend(validate_predictive_source_specs(root))

    source: AnalyticalDataset | None = None
    if allow_missing_release and dataset_dir is None:
        checks.append(
            _skip(
                "release.available",
                "release_consistency",
                "release-dependent checks intentionally deferred in source-only mode",
                "data/releases",
            )
        )
    else:
        try:
            source = resolve_analytical_dataset(
                root,
                TABLES,
                dataset_dir,
                require_certified=not allow_missing_release,
            )
        except (FileNotFoundError, ValueError) as error:
            checks.append(
                _result(
                    "release.available",
                    "release_consistency",
                    1,
                    str(error),
                    str(dataset_dir or root / "data/releases"),
                )
            )

    if source is not None:
        checks.extend(validate_dataset_contract(source.analytical_dir, contract))
        checks.extend(validate_release_provenance(source))
        expected_presentation = (
            Path(presentation_dir).resolve()
            if presentation_dir is not None
            else root / "outputs/presentation" / source.dataset_version
        )
        if expected_presentation.is_dir():
            checks.extend(validate_presentation_package(expected_presentation, source, contract))
        elif allow_missing_release:
            checks.append(
                _skip(
                    "presentation.available",
                    "presentation",
                    "presentation-dependent checks deferred",
                    str(expected_presentation),
                )
            )
        else:
            checks.append(
                _result(
                    "presentation.available",
                    "presentation",
                    1,
                    "presentation package for selected release is missing",
                    str(expected_presentation),
                )
            )
        if eda_dir is not None:
            checks.append(validate_eda_manifest(eda_dir, source))
        expected_scientific = (
            Path(scientific_dir).resolve()
            if scientific_dir is not None
            else root / "outputs/scientific" / source.dataset_version
        )
        if expected_scientific.is_dir():
            checks.extend(validate_scientific_package(expected_scientific, source, contract))
        elif allow_missing_release:
            checks.append(
                _skip(
                    "science.package_available",
                    "scientific_evidence",
                    "scientific package-dependent checks deferred",
                    str(expected_scientific),
                )
            )
        else:
            checks.append(
                _result(
                    "science.package_available",
                    "scientific_evidence",
                    1,
                    "scientific package for selected release is missing",
                    str(expected_scientific),
                )
            )
        expected_simulation = (
            Path(simulation_dir).resolve()
            if simulation_dir is not None
            else root / "outputs/simulations" / source.dataset_version
        )
        if expected_simulation.is_dir():
            checks.extend(validate_simulation_package(expected_simulation, source, contract))
        elif allow_missing_release:
            checks.append(
                _skip(
                    "simulation.package_available",
                    "simulation_evidence",
                    "simulation package-dependent checks deferred",
                    str(expected_simulation),
                )
            )
        else:
            checks.append(
                _result(
                    "simulation.package_available",
                    "simulation_evidence",
                    1,
                    "simulation package for selected release is missing",
                    str(expected_simulation),
                )
            )
        expected_predictive = (
            Path(predictive_dir).resolve()
            if predictive_dir is not None
            else root / "outputs/predictive" / source.dataset_version
        )
        if expected_predictive.is_dir():
            checks.extend(validate_predictive_package(expected_predictive, source, contract))
        elif allow_missing_release:
            checks.append(
                _skip(
                    "prediction.package_available",
                    "predictive_evidence",
                    "predictive package-dependent checks deferred",
                    str(expected_predictive),
                )
            )
        else:
            checks.append(
                _result(
                    "prediction.package_available",
                    "predictive_evidence",
                    1,
                    "predictive package for selected release is missing",
                    str(expected_predictive),
                )
            )
    failed = [check for check in checks if check.status == FAIL]
    skipped = [check for check in checks if check.status == SKIPPED]
    payload = {
        "baseline_version": __version__,
        "generated_at": datetime.now(UTC).isoformat(),
        "disclaimer": DISCLAIMER,
        "scope": "internal synthetic-data engineering and analytical contract",
        "formal_compliance_claim": False,
        "overall_status": PASS if not failed else FAIL,
        "summary": {
            "checks": len(checks),
            "passed": sum(check.status == PASS for check in checks),
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "selected_dataset": source.dataset_version if source is not None else None,
        "checks": [asdict(check) for check in checks],
    }
    destination = (
        Path(output_path).resolve()
        if output_path is not None
        else root / "outputs/industry_readiness/industry_check_report.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["report_path"] = str(destination)
    return payload
