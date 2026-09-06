"""Build a sealed, aggregate-only synthetic prediction-model evidence package."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from . import DISCLAIMER, __version__
from .dataset_resolver import AnalyticalDataset
from .model_governance import (
    derive_model_disposition,
    load_model_governance,
    load_model_target_contracts,
    validate_model_alias_configuration,
)
from .predictive_modeling import (
    build_model_datasets,
    build_subgroup_metrics,
    compare_with_prior_reported_claims,
    run_robustness_framework,
    run_validation_framework,
)

DECISION_CURVE_BLOCK = (
    "DECISION CURVE NOT INTERPRETABLE — OPERATIONAL ACTION AND THRESHOLD TRADE-OFF NOT DEFINED."
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _git_value(project_root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=project_root, text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def verify_analysis_source_identity(project_root: str | Path, release_source_commit: str) -> str:
    """Require predictive evidence to run from the exact clean release source commit."""
    project = Path(project_root).resolve()
    analysis_commit = _git_value(project, "rev-parse", "HEAD")
    if not analysis_commit:
        raise ValueError("Predictive evidence requires an identifiable Git source commit")
    if release_source_commit != analysis_commit:
        raise ValueError("Predictive analysis commit does not match selected release source commit")
    worktree_status = _git_value(project, "status", "--porcelain", "--untracked-files=all")
    if worktree_status is None:
        raise ValueError("Predictive evidence could not verify Git worktree cleanliness")
    if worktree_status:
        raise ValueError(
            "Predictive evidence requires a clean worktree; commit or remove all tracked and "
            "untracked source changes before generating candidate evidence"
        )
    return analysis_commit


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    return value


def load_model_evaluation_config(path: str | Path) -> dict[str, Any]:
    """Load and validate the leakage-safe validation design."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Model evaluation configuration must be a mapping")
    required = {
        "version",
        "status",
        "synthetic_data_only",
        "principal_validation",
        "random_row_split_allowed_as_principal_evidence",
        "features",
        "validation",
        "subgroups",
        "robustness",
        "disposition_policy",
        "prior_reported_claims",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"Model evaluation configuration is missing {missing}")
    if payload["principal_validation"] != "repeated_rolling_temporal":
        raise ValueError("Repeated rolling temporal validation must remain principal")
    if payload["random_row_split_allowed_as_principal_evidence"] is not False:
        raise ValueError("Random row splitting cannot be principal evidence")
    validation = payload["validation"]
    if int(validation["rolling_repeats"]) < 2:
        raise ValueError("Rolling temporal validation must be repeated")
    if int(validation["rolling_origins_per_repeat"]) < 2:
        raise ValueError("Multiple rolling origins are required")
    if not 0 < float(validation["final_temporal_holdout_fraction"]) < 0.5:
        raise ValueError("Final temporal holdout fraction must be in (0, 0.5)")
    if validation["feature_selection"] != "none":
        raise ValueError("Any future feature selection requires a nested implementation")
    return payload


def verify_predictive_eda_inputs(
    eda_dir: str | Path,
    source: AnalyticalDataset,
) -> dict[str, str]:
    """Require target-derivation inputs to match and hash to the selected certified release."""
    root = Path(eda_dir).resolve()
    cohort_manifest_path = root / "cohort_run_manifest.json"
    longitudinal_manifest_path = root / "longitudinal_run_manifest.json"
    flags_path = root / "cohort_patient_flags.parquet"
    persistence_path = root / "persistence_event_data.parquet"
    required = (
        cohort_manifest_path,
        longitudinal_manifest_path,
        flags_path,
        persistence_path,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Predictive EDA inputs are missing: {missing}")
    cohort = json.loads(cohort_manifest_path.read_text(encoding="utf-8"))
    longitudinal = json.loads(longitudinal_manifest_path.read_text(encoding="utf-8"))
    if cohort.get("dataset_selection", {}).get("dataset_version") != source.dataset_version:
        raise ValueError("Cohort model input does not match the selected release")
    if Path(cohort.get("analytical_data_dir", "")).resolve() != source.analytical_dir:
        raise ValueError("Cohort model input analytical directory does not match the release")
    cohort_hash = cohort.get("output_file_hashes", {}).get(flags_path.name, {}).get("sha256")
    if cohort_hash != _sha256(flags_path):
        raise ValueError("Cohort model input hash does not match its manifest")
    longitudinal_outputs = longitudinal.get("outputs", {})
    persistence_hash = next(
        (
            value
            for name, value in longitudinal_outputs.items()
            if Path(name).name == persistence_path.name
        ),
        None,
    )
    if persistence_hash != _sha256(persistence_path):
        raise ValueError("Persistence model input hash does not match its manifest")
    release_fragment = str(source.analytical_dir).lower()
    longitudinal_inputs = " ".join(map(str, longitudinal.get("inputs", {}).keys())).lower()
    if release_fragment not in longitudinal_inputs:
        raise ValueError("Persistence model input does not point to the selected release")
    return {
        str(flags_path): _sha256(flags_path),
        str(persistence_path): _sha256(persistence_path),
        str(cohort_manifest_path): _sha256(cohort_manifest_path),
        str(longitudinal_manifest_path): _sha256(longitudinal_manifest_path),
    }


def verify_predictive_evidence_manifest(output_dir: str | Path) -> None:
    """Verify the sealed predictive manifest and every declared aggregate artifact."""
    root = Path(output_dir).resolve()
    manifest_path = root / "predictive_evidence_manifest.json"
    marker_path = root / "IMMUTABLE_PREDICTIVE_EVIDENCE"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if _sha256(manifest_path) != marker_path.read_text(encoding="utf-8").strip():
        raise ValueError(f"Predictive evidence manifest changed after sealing: {root}")
    declared = manifest.get("artifacts")
    if not isinstance(declared, dict) or not declared:
        raise ValueError("Predictive evidence manifest contains no artifact inventory")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path not in {manifest_path, marker_path}
        and path.name != ".predictive-in-progress"
    }
    if actual != set(declared):
        raise ValueError(f"Predictive artifact inventory changed after sealing: {root}")
    for relative, evidence in declared.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(f"Predictive artifact path escapes package: {relative}") from error
        if _sha256(path) != evidence["sha256"] or path.stat().st_size != int(evidence["bytes"]):
            raise ValueError(f"Predictive artifact changed after sealing: {path}")


def _attach_metadata(
    frame: pd.DataFrame,
    contracts: Mapping[str, Any],
    *,
    release: str,
    source_commit: str,
    configuration_hash: str,
) -> pd.DataFrame:
    result = frame.copy()
    metadata_columns = (
        "population_definition",
        "prediction_time",
        "prediction_horizon_days",
        "release",
        "source_commit",
        "configuration_hash",
        "synthetic_data_only",
        "external_validation",
        "deployable",
        "limitation",
    )
    model_lookup = {str(model["model_id"]): model for model in contracts["models"]}
    target_lookup = {str(model["target_name"]): model for model in contracts["models"]}

    def contract_for(row: pd.Series) -> Mapping[str, Any] | None:
        model_id = str(row.get("model_id", ""))
        target = str(row.get("target", ""))
        return model_lookup.get(model_id) or target_lookup.get(target)

    metadata = [
        {
            "population_definition": (
                str(contract["model_development_population"])
                if contract
                else "aggregate model evidence"
            ),
            "prediction_time": str(contract["prediction_time"])
            if contract
            else "analysis-specific",
            "prediction_horizon_days": (
                int(contract["prediction_horizon_days"]) if contract else None
            ),
            "release": release,
            "source_commit": source_commit,
            "configuration_hash": configuration_hash,
            "synthetic_data_only": True,
            "external_validation": False,
            "deployable": False,
            "limitation": (
                "Synthetic internal validation only; not clinical or external validation, "
                "transportability, real-world utility, or evidence of patient benefit."
            ),
        }
        for _, row in result.iterrows()
        for contract in [contract_for(row)]
    ]
    metadata_frame = pd.DataFrame(metadata, columns=metadata_columns)
    result = result.drop(
        columns=[column for column in metadata_columns if column in result.columns]
    )
    return pd.concat([result.reset_index(drop=True), metadata_frame], axis=1)


def _fmt(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "not evaluable"
    return f"{number:.{digits}f}" if math.isfinite(number) else "not evaluable"


def _count(value: Any) -> int:
    return int(float(str(value)))


def _model_card_document(
    contract: Mapping[str, Any],
    disposition: Mapping[str, Any],
    derivation: pd.DataFrame,
    metrics: pd.DataFrame,
    subgroup: pd.DataFrame,
    prior: pd.DataFrame,
    evaluation_config: Mapping[str, Any],
    *,
    release: str,
    source_commit: str,
) -> str:
    target = str(contract["target_name"])
    final_rows = metrics.loc[
        metrics.target.eq(target)
        & metrics.evaluation_design.eq("FINAL_TEMPORAL_HOLDOUT")
        & metrics.status.eq("EVALUATED")
    ]
    primary = final_rows.loc[final_rows.model.eq("regularized_logistic_nested_calibration")]
    comparator = final_rows.loc[final_rows.model.eq("training_prevalence_comparator")]
    primary_row = primary.iloc[0] if not primary.empty else None
    comparator_row = comparator.iloc[0] if not comparator.empty else None
    rolling = metrics.loc[
        metrics.target.eq(target)
        & metrics.model.eq("regularized_logistic_nested_calibration")
        & metrics.evaluation_design.eq("ROLLING_TEMPORAL")
        & metrics.status.eq("EVALUATED")
    ]
    lomo = metrics.loc[
        metrics.target.eq(target)
        & metrics.model.eq("regularized_logistic_nested_calibration")
        & metrics.evaluation_design.eq("LEAVE_ONE_MARKET_OUT")
        & metrics.status.eq("EVALUATED")
    ]
    subgroup_rows = subgroup.loc[subgroup.target.eq(target)]
    insufficient = int(subgroup_rows.support_status.str.startswith("INSUFFICIENT").sum())
    subgroup_lines = [
        "| Dimension | Group | n | Events | Missing | ROC AUC (95% CI) | PR AUC (95% CI) | "
        "Calibration intercept / slope | Support |",
        "|---|---|---:|---:|---:|---|---|---|---|",
    ]
    for row in subgroup_rows.sort_values(
        ["subgroup_dimension", "subgroup_value"], kind="stable"
    ).itertuples(index=False):
        dimension = str(row.subgroup_dimension).replace("|", "\\|")
        value = str(row.subgroup_value).replace("|", "\\|")
        support = str(row.support_status).replace("|", "\\|")
        subgroup_lines.append(
            f"| {dimension} | {value} | {_count(row.n)} | {_count(row.event_n)} | "
            f"{100 * float(str(row.predictor_missingness_rate)):.1f}% | "
            f"{_fmt(row.roc_auc)} ({_fmt(row.roc_auc_ci_lower)}–{_fmt(row.roc_auc_ci_upper)}) | "
            f"{_fmt(row.pr_auc)} ({_fmt(row.pr_auc_ci_lower)}–{_fmt(row.pr_auc_ci_upper)}) | "
            f"{_fmt(row.calibration_intercept)} / {_fmt(row.calibration_slope)} | {support} |"
        )
    if len(subgroup_lines) == 2:
        subgroup_lines.append(
            "| — | No evaluable final-holdout subgroup rows | 0 | 0 | — | — | — | — | INSUFFICIENT SUPPORT — DO NOT RANK |"
        )
    prior_row = prior.loc[prior.target.eq(target)]
    prior_text = (
        f"Prior ROC AUC {_fmt(prior_row.iloc[0].prior_roc_auc)} versus current "
        f"{_fmt(prior_row.iloc[0].current_roc_auc)}; difference "
        f"{_fmt(prior_row.iloc[0].roc_auc_difference)}. This is not claimed as exact replication."
        if not prior_row.empty
        else "No prior comparison is evaluable."
    )
    derivation_lines = [
        f"| {_count(row.step_order)} | {row.derivation_step} | {_count(row.entered_n)} | "
        f"{_count(row.excluded_n)} | {_count(row.retained_n)} |"
        for row in derivation.itertuples(index=False)
    ]
    performance = (
        f"- Final untouched holdout: n={int(primary_row.validation_n):,}, events="
        f"{int(primary_row.validation_event_n):,} ({100 * float(primary_row.event_prevalence):.1f}%).\n"
        f"- Training period: {primary_row.train_period_start} to "
        f"{primary_row.train_period_end}; validation period: "
        f"{primary_row.validation_period_start} to {primary_row.validation_period_end}.\n"
        f"- ROC AUC {_fmt(primary_row.roc_auc)} "
        f"({_fmt(primary_row.roc_auc_ci_lower)}–{_fmt(primary_row.roc_auc_ci_upper)}); "
        f"PR AUC {_fmt(primary_row.pr_auc)} "
        f"({_fmt(primary_row.pr_auc_ci_lower)}–{_fmt(primary_row.pr_auc_ci_upper)}); "
        f"Brier {_fmt(primary_row.brier_score)}.\n"
        f"- Calibration intercept {_fmt(primary_row.calibration_intercept)}; slope "
        f"{_fmt(primary_row.calibration_slope)}."
        if primary_row is not None
        else "- Final untouched holdout was not evaluable."
    )
    comparator_text = (
        f"Training-prevalence comparator: ROC AUC {_fmt(comparator_row.roc_auc)}, "
        f"PR AUC {_fmt(comparator_row.pr_auc)}, Brier {_fmt(comparator_row.brier_score)}."
        if comparator_row is not None
        else "Training-prevalence comparator was not evaluable."
    )
    rolling_text = (
        f"{len(rolling)} evaluable repeated rolling folds; ROC AUC range "
        f"{_fmt(rolling.roc_auc.min())}–{_fmt(rolling.roc_auc.max())}."
        if not rolling.empty
        else "No rolling fold met minimum support."
    )
    lomo_text = (
        f"{len(lomo)} evaluable development-period market holdouts; results are not ranked."
        if not lomo.empty
        else "No market holdout met minimum support."
    )
    prohibited = "\n".join(f"- {item}" for item in contract["prohibited_uses"])
    selection_warning = (
        f"\n- Selection/applicability warning: {contract['retrospective_selection_warning']}"
        if contract.get("retrospective_selection_warning")
        else ""
    )
    return f"""# Model card — {contract["model_id"]} v{contract["model_version"]}

> **{DISCLAIMER}** Synthetic temporal and market validation is not external validation, clinical
> validation, transportability, real-world utility, or evidence of patient benefit.

## Identity, source and disposition

- Release: `{release}`
- Source commit: `{source_commit}`
- Data source: certified generated synthetic analytical release; no real patient or Bayer data
- Target: `{target}`
- Reviewer status: `{contract["reviewer_status"]}`
- Current generated disposition: **{disposition["disposition"]}**
- Disposition reason: {disposition["reason"]}
- Operational deployment permitted: **NO**

## Intended research use

{contract["intended_research_use"]}

Prediction time is `{contract["prediction_time"]}` and the horizon is
{contract["prediction_horizon_days"]} days. {contract["predictor_availability_cutoff"]}

## Population derivation

- Target population: {contract["target_population"]}
- Model-development population: {contract["model_development_population"]}{selection_warning}

| Step | Rule | Entered | Excluded | Retained |
|---:|---|---:|---:|---:|
{chr(10).join(derivation_lines)}

Every row reconciles as entered = excluded + retained. The final count equals the model population.

## Outcome, events and censoring

- Outcome: {contract["outcome_definition"]}
- Event handling: {contract["event_handling"]}
- Censoring handling: {contract["censoring_handling"]}
- Simple comparator: {contract["simple_comparator"]}

## Validation and performance

{performance}

{comparator_text}

- {rolling_text}
- {lomo_text}
- Flexible Gaussian-kernel calibration curves and patient-level percentile bootstrap intervals are
  provided as aggregate evidence.
- Preprocessing, median imputation, categorical levels, the regularized model, and Platt calibration
  are refit inside each fold. Feature selection is `{evaluation_config["validation"]["feature_selection"]}`.
- Sensitivity, specificity and confusion matrices are not reported because no operational threshold
  is prespecified.

Historical comparison: {prior_text}

## Subgroups and missing data

The final holdout reports n, events, prevalence, predictor missingness, discrimination, calibration,
and uncertainty for configured groups. {insufficient} of {len(subgroup_rows)} rows are explicitly
marked insufficient support. Groups and markets must not be ranked.

{chr(10).join(subgroup_lines)}

Numeric missing values use medians fitted only on the inner model-fit subset. Categorical missingness
is explicit and unseen validation levels map to a reserved level. Missingness stress tests are
reported separately and do not establish MAR.

## Decision utility

**{DECISION_CURVE_BLOCK}**

Proposed workflow: {contract["plausible_decision_or_workflow"]}

- False-positive harm: {contract["false_positive_harm"]}
- False-negative harm: {contract["false_negative_harm"]}
- Human oversight: {contract["required_human_oversight"]}

## Prohibited uses

{prohibited}

## Limitations and next evidence

This is a regularized logistic research baseline on generated data. Weak or negative findings are
retained. No SHAP or local explanation is generated for rejected models, and no feature output may be
interpreted as causal or clinically meaningful. Any external-validation discussion requires an
approved target/workflow, governed real data, preregistered analysis, independent temporal and
geographic evaluation, calibration and subgroup uncertainty, privacy/security review, and named
clinical/statistics/model-risk/data-owner approval.
"""


def _build_dispositions(
    datasets: Mapping[str, pd.DataFrame],
    contracts: Mapping[str, Any],
    validation_metrics: pd.DataFrame,
    leakage_audit: pd.DataFrame,
    evaluation_config: Mapping[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    policy = evaluation_config["disposition_policy"]
    for contract in contracts["models"]:
        model_id = str(contract["model_id"])
        target = str(contract["target_name"])
        frame = datasets[target]
        final = validation_metrics.loc[
            validation_metrics.model_id.eq(model_id)
            & validation_metrics.model.eq("regularized_logistic_nested_calibration")
            & validation_metrics.evaluation_design.eq("FINAL_TEMPORAL_HOLDOUT")
            & validation_metrics.status.eq("EVALUATED")
        ]
        if final.empty:
            final_n = final_events = 0
            final_roc = None
        else:
            row = final.iloc[0]
            final_n = int(row.validation_n)
            final_events = int(row.validation_event_n)
            final_roc = float(row.roc_auc) if pd.notna(row.roc_auc) else None
        leakage_failures = int(
            leakage_audit.loc[
                leakage_audit.target.eq(target) & leakage_audit.status.eq("FAIL"),
                "failure_count",
            ].sum()
        )
        disposition, reason = derive_model_disposition(
            analysis_event_n=int(frame.target.sum()),
            final_holdout_n=final_n,
            final_holdout_event_n=final_events,
            final_holdout_roc_auc=final_roc,
            leakage_failure_count=leakage_failures,
            policy=policy,
        )
        rows.append(
            {
                "model_id": model_id,
                "model_version": contract["model_version"],
                "target": target,
                "analysis_population_n": len(frame),
                "analysis_event_n": int(frame.target.sum()),
                "final_holdout_n": final_n,
                "final_holdout_event_n": final_events,
                "final_holdout_roc_auc": final_roc,
                "disposition": disposition,
                "reason": reason,
                "automatic_policy_status": policy["status"],
                "promotion_to_external_validation_alias_allowed": False,
                "promotion_to_operational_alias_allowed": False,
                "reviewer_status": contract["reviewer_status"],
            }
        )
    return pd.DataFrame(rows)


def _decision_curve_artifact(contracts: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for contract in contracts["models"]:
        interpretable = (
            bool(contract["operational_action_defined"])
            and bool(contract["plausible_threshold_range"])
            and bool(contract["approved_comparison_strategies"])
        )
        if interpretable:
            raise RuntimeError(
                "A model contract now defines decision-curve inputs; add the approved analysis "
                "before generating evidence"
            )
        rows.append(
            {
                "model_id": contract["model_id"],
                "status": "BLOCKED",
                "statement": DECISION_CURVE_BLOCK,
                "operational_action_defined": contract["operational_action_defined"],
                "threshold_range_defined": bool(contract["plausible_threshold_range"]),
                "approved_comparison_strategies": contract["approved_comparison_strategies"],
            }
        )
    return {
        "synthetic_data_only": True,
        "decision_curve_generated": False,
        "status": "BLOCKED",
        "statement": DECISION_CURVE_BLOCK,
        "models": rows,
    }


def build_predictive_evidence_package(
    *,
    project_root: str | Path,
    tables: Mapping[str, pd.DataFrame],
    flags: pd.DataFrame,
    persistence: pd.DataFrame,
    output_dir: str | Path,
    release: str,
    release_source_commit: str,
    model_contract_path: str | Path,
    evaluation_config_path: str | Path,
    governance_path: str | Path,
    alias_config_path: str | Path,
    input_hashes: Mapping[str, str] | None = None,
) -> Path:
    """Generate, document, and seal aggregate predictive research evidence."""
    project = Path(project_root).resolve()
    output = Path(output_dir).resolve()
    analysis_commit = verify_analysis_source_identity(project, release_source_commit)
    try:
        output.mkdir(parents=True)
    except FileExistsError as error:
        raise FileExistsError(f"Predictive evidence output already exists: {output}") from error
    in_progress = output / ".predictive-in-progress"
    in_progress.write_text(_utc_now(), encoding="utf-8")

    contracts = load_model_target_contracts(model_contract_path)
    evaluation_config = load_model_evaluation_config(evaluation_config_path)
    governance = load_model_governance(governance_path)
    alias_configuration = yaml.safe_load(Path(alias_config_path).read_text(encoding="utf-8"))
    if not isinstance(alias_configuration, dict):
        raise ValueError("Model alias configuration must be a mapping")
    configuration_components = {
        "model_target_contracts": contracts,
        "model_evaluation": evaluation_config,
        "model_governance": governance,
        "model_aliases": alias_configuration,
    }
    configuration_hash = _payload_hash(configuration_components)
    snapshots = {
        "model_target_contracts_snapshot.yaml": Path(model_contract_path),
        "model_evaluation_snapshot.yaml": Path(evaluation_config_path),
        "model_governance_snapshot.yaml": Path(governance_path),
        "model_aliases_snapshot.yaml": Path(alias_config_path),
    }
    for filename, source in snapshots.items():
        shutil.copy2(source, output / filename)

    datasets, derivation = build_model_datasets(
        flags,
        persistence,
        tables,
        evaluation_config,
    )
    metrics, calibration, leakage, folds, final_scores = run_validation_framework(
        datasets,
        contracts,
        evaluation_config,
    )
    subgroup = build_subgroup_metrics(final_scores, contracts, evaluation_config)
    robustness = run_robustness_framework(
        base_datasets=datasets,
        flags=flags,
        persistence=persistence,
        tables=tables,
        contracts=contracts,
        evaluation_config=evaluation_config,
        validation_metrics=metrics,
        final_scores=final_scores,
    )
    prior = compare_with_prior_reported_claims(metrics, evaluation_config)
    dispositions = _build_dispositions(
        datasets,
        contracts,
        metrics,
        leakage,
        evaluation_config,
    )
    disposition_map = dict(zip(dispositions.model_id, dispositions.disposition, strict=True))
    validate_model_alias_configuration(alias_config_path, disposition_map, governance)
    decision_curve = _decision_curve_artifact(contracts)

    csv_outputs = {
        "model_population_derivation.csv": derivation,
        "validation_metrics.csv": metrics,
        "flexible_calibration_curves.csv": calibration,
        "leakage_audit.csv": leakage,
        "validation_fold_registry.csv": folds,
        "subgroup_metrics.csv": subgroup,
        "robustness_metrics.csv": robustness,
        "prior_claim_reproduction.csv": prior,
        "model_disposition.csv": dispositions,
    }
    for filename, frame in csv_outputs.items():
        enriched = _attach_metadata(
            frame,
            contracts,
            release=release,
            source_commit=release_source_commit,
            configuration_hash=configuration_hash,
        )
        enriched.to_csv(output / filename, index=False)
        csv_outputs[filename] = enriched

    (output / "decision_curve_status.json").write_text(
        json.dumps(_json_safe(decision_curve), indent=2, allow_nan=False), encoding="utf-8"
    )
    (output / "decision_curve_status.md").write_text(
        "# Decision-curve status\n\n"
        f"> **{DISCLAIMER}**\n\n"
        f"**{DECISION_CURVE_BLOCK}**\n\n"
        "No current model contract contains an approved human action, threshold range, or "
        "comparison strategy. Net benefit is therefore not calculated.\n",
        encoding="utf-8",
    )

    cards_dir = output / "model_cards"
    cards_dir.mkdir()
    card_index: list[dict[str, Any]] = []
    disposition_by_model = dispositions.set_index("model_id")
    for contract in contracts["models"]:
        model_id = str(contract["model_id"])
        target = str(contract["target_name"])
        disposition = {
            str(key): value for key, value in disposition_by_model.loc[model_id].to_dict().items()
        }
        document = _model_card_document(
            contract,
            disposition,
            derivation.loc[derivation.model_id.eq(model_id)],
            metrics,
            subgroup,
            prior,
            evaluation_config,
            release=release,
            source_commit=release_source_commit,
        )
        markdown_path = cards_dir / f"{model_id}.md"
        json_path = cards_dir / f"{model_id}.json"
        markdown_path.write_text(document, encoding="utf-8")
        card_payload = _json_safe(
            {
                "model_contract": contract,
                "release": release,
                "source_commit": release_source_commit,
                "population_derivation": derivation.loc[derivation.model_id.eq(model_id)].to_dict(
                    orient="records"
                ),
                "final_temporal_metrics": metrics.loc[
                    metrics.model_id.eq(model_id)
                    & metrics.evaluation_design.eq("FINAL_TEMPORAL_HOLDOUT")
                ].to_dict(orient="records"),
                "subgroup_findings": subgroup.loc[subgroup.model_id.eq(model_id)].to_dict(
                    orient="records"
                ),
                "disposition": disposition,
                "decision_curve": DECISION_CURVE_BLOCK,
                "shap_or_local_explanations_generated": False,
                "deployable": False,
            }
        )
        json_path.write_text(json.dumps(card_payload, indent=2, allow_nan=False), encoding="utf-8")
        card_index.append(
            {
                "model_id": model_id,
                "target": target,
                "disposition": disposition["disposition"],
                "markdown": markdown_path.name,
                "json": json_path.name,
            }
        )
    (cards_dir / "index.json").write_text(
        json.dumps(card_index, indent=2, allow_nan=False), encoding="utf-8"
    )

    final_metrics = metrics.loc[
        metrics.model.eq("regularized_logistic_nested_calibration")
        & metrics.evaluation_design.eq("FINAL_TEMPORAL_HOLDOUT")
    ]
    frontend = _json_safe(
        {
            "synthetic_data_only": True,
            "disclaimer": DISCLAIMER,
            "release": release,
            "source_commit": release_source_commit,
            "configuration_hash": configuration_hash,
            "external_validation": False,
            "deployable_models": 0,
            "models": dispositions.merge(
                final_metrics[
                    [
                        "model_id",
                        "event_prevalence",
                        "validation_n",
                        "validation_event_n",
                        "roc_auc",
                        "roc_auc_ci_lower",
                        "roc_auc_ci_upper",
                        "pr_auc",
                        "pr_auc_ci_lower",
                        "pr_auc_ci_upper",
                        "brier_score",
                        "calibration_intercept",
                        "calibration_slope",
                    ]
                ],
                on="model_id",
                how="left",
                validate="one_to_one",
            ).to_dict(orient="records"),
            "prior_comparison": prior.to_dict(orient="records"),
            "population_derivation": derivation.to_dict(orient="records"),
            "rolling_temporal": metrics.loc[
                metrics.evaluation_design.eq("ROLLING_TEMPORAL")
                & metrics.model.eq("regularized_logistic_nested_calibration")
            ].to_dict(orient="records"),
            "market_holdout": metrics.loc[
                metrics.evaluation_design.eq("LEAVE_ONE_MARKET_OUT")
                & metrics.model.eq("regularized_logistic_nested_calibration")
            ].to_dict(orient="records"),
            "subgroups": subgroup.to_dict(orient="records"),
            "decision_curve": decision_curve,
            "threshold_metrics_reported": False,
            "shap_generated": False,
        }
    )
    (output / "predictive_frontend_summary.json").write_text(
        json.dumps(frontend, indent=2, allow_nan=False), encoding="utf-8"
    )

    report_lines: Sequence[str] = (
        "# Predictive research evaluation implementation report",
        "",
        f"> **{DISCLAIMER}**",
        "",
        f"- Release: `{release}`",
        f"- Source commit: `{release_source_commit}`",
        f"- Evaluation configuration: `{evaluation_config['version']}`",
        f"- Models evaluated: {len(contracts['models'])}",
        f"- Rolling temporal folds: {int(metrics.evaluation_design.eq('ROLLING_TEMPORAL').sum() / 2)}",
        f"- Leave-one-market-out folds: {int(metrics.evaluation_design.eq('LEAVE_ONE_MARKET_OUT').sum() / 2)}",
        "- One final temporal holdout per target remained outside rolling and market-holdout evidence.",
        "- No random row split, decision curve, operational threshold, SHAP, deployment alias, or causal claim.",
        "",
        "## Dispositions",
        "",
        *(
            f"- `{row.model_id}`: **{row.disposition}** — {row.reason}"
            for row in dispositions.itertuples(index=False)
        ),
        "",
        "All decisions are synthetic engineering dispositions and require independent review.",
    )
    (output / "PREDICTIVE_EVALUATION_REPORT.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )

    manifest_path = output / "predictive_evidence_manifest.json"
    artifacts = {
        path.relative_to(output).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(output.rglob("*"))
        if path.is_file() and path not in {manifest_path, in_progress}
    }
    manifest = {
        "manifest_version": "1.0",
        "package_type": "synthetic predictive research evaluation",
        "generated_at": _utc_now(),
        "release": release,
        "source_commit": release_source_commit,
        "analysis_commit": analysis_commit,
        "analysis_worktree_clean": True,
        "code_version": __version__,
        "configuration_hash": configuration_hash,
        "configuration_component_hashes": {
            filename: _sha256(source) for filename, source in snapshots.items()
        },
        "model_contract_version": contracts["contract_version"],
        "governance_version": governance["version"],
        "input_hashes": dict(input_hashes or {}),
        "synthetic_data_only": True,
        "external_validation": False,
        "clinical_validation": False,
        "deployable": False,
        "patient_level_predictions_included": False,
        "random_row_split_used_as_principal_evidence": False,
        "decision_curve_generated": False,
        "artifacts": artifacts,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "IMMUTABLE_PREDICTIVE_EVIDENCE").write_text(_sha256(manifest_path), encoding="utf-8")
    in_progress.unlink()
    verify_predictive_evidence_manifest(output)
    return output
