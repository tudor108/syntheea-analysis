"""Machine-enforced responsible-AI disposition and deployment-alias controls."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

DISPOSITIONS = {
    "REJECTED",
    "RESEARCH ONLY",
    "CANDIDATE FOR EXTERNAL VALIDATION",
    "APPROVED FOR A SPECIFIED USE",
}

MODEL_CONTRACT_REQUIRED_FIELDS = {
    "model_id",
    "model_version",
    "analysis_registry_id",
    "target_name",
    "intended_research_use",
    "prohibited_uses",
    "target_population",
    "model_development_population",
    "prediction_time",
    "prediction_horizon_days",
    "outcome_definition",
    "predictor_availability_cutoff",
    "event_handling",
    "censoring_handling",
    "denominator_derivation",
    "simple_comparator",
    "plausible_decision_or_workflow",
    "operational_action_defined",
    "plausible_threshold_range",
    "approved_comparison_strategies",
    "false_positive_harm",
    "false_negative_harm",
    "required_human_oversight",
    "current_disposition",
    "reviewer_status",
}


def _load_yaml_mapping(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return payload


def load_model_target_contracts(path: str | Path) -> dict[str, Any]:
    """Load complete target contracts and reject unsupported approval claims."""
    payload = _load_yaml_mapping(path)
    models = payload.get("models")
    if not isinstance(models, list) or len(models) != 4:
        raise ValueError("Exactly four current predictive model contracts are required")
    if set(map(str, payload.get("allowed_dispositions", []))) != DISPOSITIONS:
        raise ValueError("Model contract disposition vocabulary is incomplete")
    identifiers: list[str] = []
    targets: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("Every model contract must be a mapping")
        missing = sorted(MODEL_CONTRACT_REQUIRED_FIELDS - set(model))
        if missing:
            raise ValueError(f"Model contract {model.get('model_id')} is missing {missing}")
        disposition = str(model["current_disposition"])
        if disposition not in DISPOSITIONS:
            raise ValueError(f"Unknown model disposition: {disposition}")
        if disposition == "APPROVED FOR A SPECIFIED USE" and not model.get("approval_evidence"):
            raise ValueError("APPROVED FOR A SPECIFIED USE requires actual approval evidence")
        if model["reviewer_status"] != "NOT YET VALIDATED" and not model.get("review_evidence"):
            raise ValueError("A reviewed model contract requires review evidence")
        if bool(model["operational_action_defined"]):
            if (
                not model["plausible_threshold_range"]
                or not model["approved_comparison_strategies"]
            ):
                raise ValueError(
                    f"Model {model['model_id']} defines an action without thresholds/strategies"
                )
        identifiers.append(str(model["model_id"]))
        targets.append(str(model["target_name"]))
    if len(identifiers) != len(set(identifiers)) or len(targets) != len(set(targets)):
        raise ValueError("Model IDs and target names must be unique")
    return payload


def load_model_governance(path: str | Path) -> dict[str, Any]:
    """Load and validate minimum responsible-AI governance controls."""
    payload = _load_yaml_mapping(path)
    if set(map(str, payload.get("disposition_states", []))) != DISPOSITIONS:
        raise ValueError("Responsible-AI disposition vocabulary is incomplete")
    required = {
        "intended_use_statement",
        "prohibited_use_statement",
        "human_oversight_requirements",
        "model_harm_register",
        "model_disposition_workflow",
        "stop_use_conditions",
        "misuse_scenarios",
        "drift_monitoring_specification",
        "incident_and_rollback_procedure",
        "external_validation_requirements",
        "promotion_policy",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"Model governance specification is missing {missing}")
    aliases = payload["promotion_policy"].get("aliases", {})
    if set(aliases.get("operational", [])) != {"APPROVED FOR A SPECIFIED USE"}:
        raise ValueError("Operational aliases must accept only APPROVED FOR A SPECIFIED USE")
    return payload


def derive_model_disposition(
    *,
    analysis_event_n: int,
    final_holdout_n: int,
    final_holdout_event_n: int,
    final_holdout_roc_auc: float | None,
    leakage_failure_count: int,
    policy: Mapping[str, Any],
) -> tuple[str, str]:
    """Apply the conservative automatic disposition ceiling to one model."""
    non_events = final_holdout_n - final_holdout_event_n
    failures: list[str] = []
    if leakage_failure_count:
        failures.append(f"{leakage_failure_count} leakage/split gate failure(s)")
    if analysis_event_n < int(policy["minimum_analysis_events"]):
        failures.append("analysis event count below the engineering minimum")
    if final_holdout_event_n < int(policy["minimum_final_holdout_events"]):
        failures.append("final holdout event count below the engineering minimum")
    if non_events < int(policy["minimum_final_holdout_non_events"]):
        failures.append("final holdout non-event count below the engineering minimum")
    if final_holdout_roc_auc is None:
        failures.append("final holdout ROC AUC is not evaluable")
    elif final_holdout_roc_auc < float(policy["reject_below_roc_auc"]):
        failures.append(
            "final holdout ROC AUC is below the prespecified engineering continuation boundary"
        )
    if failures:
        return "REJECTED", "; ".join(failures)
    ceiling = str(policy["maximum_automatic_disposition"])
    if ceiling != "RESEARCH ONLY":
        raise ValueError("Automatic disposition may not exceed RESEARCH ONLY in this project")
    return (
        "RESEARCH ONLY",
        "evaluable synthetic research signal; external, clinical, workflow, and approval "
        "evidence absent",
    )


def assert_alias_promotion_allowed(
    *,
    model_id: str,
    disposition: str,
    alias: str,
    governance: Mapping[str, Any],
    approval_evidence: Mapping[str, Any] | None = None,
) -> None:
    """Block rejected/research models from external-validation or operational aliases."""
    if disposition not in DISPOSITIONS:
        raise ValueError(f"Unknown disposition for {model_id}: {disposition}")
    allowed = governance["promotion_policy"]["aliases"].get(alias)
    if allowed is None:
        raise ValueError(f"Unknown deployment alias: {alias}")
    if disposition not in set(map(str, allowed)):
        raise PermissionError(
            f"Model {model_id} with disposition {disposition} cannot be promoted to {alias}"
        )
    if disposition == "APPROVED FOR A SPECIFIED USE" and not approval_evidence:
        raise PermissionError(
            f"Model {model_id} requires approval evidence before any approved-use alias"
        )


def validate_model_alias_configuration(
    alias_path: str | Path,
    dispositions: Mapping[str, str],
    governance: Mapping[str, Any],
) -> None:
    """Validate every configured alias against generated model dispositions."""
    aliases = _load_yaml_mapping(alias_path)
    assignments = aliases.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("Model alias assignments must be a list")
    seen: set[tuple[str, str]] = set()
    for assignment in assignments:
        model_id = str(assignment["model_id"])
        alias = str(assignment["alias"])
        if model_id not in dispositions:
            raise ValueError(f"Alias references an unknown model: {model_id}")
        key = (model_id, alias)
        if key in seen:
            raise ValueError(f"Duplicate model alias assignment: {key}")
        seen.add(key)
        assert_alias_promotion_allowed(
            model_id=model_id,
            disposition=dispositions[model_id],
            alias=alias,
            governance=governance,
            approval_evidence=assignment.get("approval_evidence"),
        )
