"""Strict contracts for governed interactive and specialist analysis."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RequestMode(StrEnum):
    ARTIFACT_QUESTION = "artifact_question"
    EXPLAIN_TACTIC = "explain_tactic"
    RECOMMEND_TACTIC = "recommend_tactic"
    MODIFY_EXISTING_TACTIC = "modify_existing_tactic"
    COMPARE_EXISTING_RESULTS = "compare_existing_results"
    PROPOSE_NEW_ANALYSIS = "propose_new_analysis"
    EXECUTE_APPROVED_ANALYSIS = "execute_approved_analysis"
    PROHIBITED_REQUEST = "prohibited_request"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ExpertLens(StrEnum):
    RWE_EPIDEMIOLOGY = "rwe_epidemiology"
    BIOSTATISTICS = "biostatistics"
    ONCOLOGY_DEFINITION_REVIEW = "oncology_definition_review"
    MISSING_DATA_ANALYSIS = "missing_data_analysis"
    PREDICTIVE_MODELLING = "predictive_modelling"
    DATA_QUALITY = "data_quality"
    MARKET_SCENARIO_ANALYSIS = "market_scenario_analysis"


class AnalysisState(StrEnum):
    UNDERSTAND = "UNDERSTAND"
    RETRIEVE = "RETRIEVE"
    SELECT_EXPERT_LENS = "SELECT EXPERT LENS"
    CREATE_ANALYSIS_SPEC = "CREATE ANALYSIS SPEC"
    VALIDATE = "VALIDATE"
    ESTIMATE_COST = "ESTIMATE COST"
    PREVIEW_PARAMETER_DIFF = "PREVIEW PARAMETER DIFF"
    PREVIEW_DENOMINATOR = "PREVIEW DENOMINATOR"
    USER_CONFIRMATION = "USER CONFIRMATION"
    EXECUTE = "EXECUTE"
    QA = "QA"
    INTERPRET = "INTERPRET"
    EXPORT_OR_SUBMIT = "EXPORT OR SUBMIT FOR REVIEW"


class EvidenceBadge(StrEnum):
    CERTIFIED_EVIDENCE = "CERTIFIED EVIDENCE"
    INTERACTIVE_RERUN = "INTERACTIVE RE-RUN"
    PROPOSED_METHOD = "PROPOSED METHOD"
    FAILED_VALIDATION = "FAILED VALIDATION"
    REQUIRES_SME_REVIEW = "REQUIRES SME REVIEW"
    SUBMITTED_FOR_REVIEW = "SUBMITTED FOR REVIEW"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LensDefinition(StrictModel):
    lens_id: ExpertLens
    title: str = Field(min_length=3)
    purpose: str = Field(min_length=10)
    required_checks: list[str] = Field(min_length=1)


class RequestClassification(StrictModel):
    mode: RequestMode
    tactic_id: str | None
    expert_lens: ExpertLens
    parameter_updates: dict[str, Any]
    requires_deep_methodology: bool
    rationale: str = Field(min_length=3)
    routing_source: Literal["gpt-5.6-luna", "deterministic"]


class AnalysisSpec(StrictModel):
    """Complete immutable contract required before an interactive run."""

    request_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    parent_release_id: str = Field(min_length=3)
    analysis_name: str = Field(min_length=5, max_length=160)
    existing_tactic_id: str | None
    new_proposal: bool
    expert_lens: ExpertLens
    research_question: str = Field(min_length=10)
    analysis_type: str = Field(min_length=3)
    target_population: str = Field(min_length=5)
    eligibility_criteria: list[str] = Field(min_length=1)
    exclusion_criteria: list[str] = Field(min_length=1)
    numerator_definition: str = Field(min_length=3)
    denominator_definition: str = Field(min_length=3)
    index_date_time_zero: str = Field(min_length=3)
    outcome_definition: str = Field(min_length=3)
    observation_window: str = Field(min_length=3)
    competing_events: list[str]
    censoring_events: list[str]
    markets: list[str] = Field(min_length=1)
    subgroups: list[str]
    initiation_window_days: int | None
    persistence_gap_days: int | None
    scenario: str = Field(min_length=3)
    seeds: list[int] = Field(min_length=1)
    missingness_strategy: str = Field(min_length=3)
    analytical_method: str = Field(min_length=5)
    assumptions: list[str] = Field(min_length=1)
    parameters: dict[str, Any]
    expected_outputs: list[str] = Field(min_length=1)
    validation_checks: list[str] = Field(min_length=1)
    required_source_fields: list[str] = Field(min_length=1)
    prohibited_interpretations: list[str] = Field(min_length=1)
    sme_review_requirements: list[str] = Field(min_length=1)

    @field_validator("markets")
    @classmethod
    def _markets_are_explicit(cls, values: list[str]) -> list[str]:
        normalized = [value.upper().strip() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("markets cannot contain duplicates")
        if "ALL" in normalized and len(normalized) > 1:
            raise ValueError("ALL cannot be combined with individual markets")
        if any(not re.fullmatch(r"ALL|[A-Z]{2}", value) for value in normalized):
            raise ValueError("markets must contain ALL or two-letter configured codes")
        return normalized

    @field_validator("initiation_window_days")
    @classmethod
    def _initiation_window(cls, value: int | None) -> int | None:
        if value is not None and value not in {30, 60, 90}:
            raise ValueError("initiation_window_days must be 30, 60, or 90")
        return value

    @field_validator("persistence_gap_days")
    @classmethod
    def _persistence_gap(cls, value: int | None) -> int | None:
        if value is not None and value not in {30, 60, 90}:
            raise ValueError("persistence_gap_days must be 30, 60, or 90")
        return value

    @field_validator("seeds")
    @classmethod
    def _seeds(cls, values: list[int]) -> list[int]:
        if any(value < 0 for value in values):
            raise ValueError("seeds cannot be negative")
        if len(values) != len(set(values)):
            raise ValueError("seeds cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def _one_analysis_origin(self) -> AnalysisSpec:
        if self.new_proposal == (self.existing_tactic_id is not None):
            raise ValueError("select exactly one existing tactic or new proposal")
        return self


class ValidationCheck(StrictModel):
    check_id: str
    status: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    detail: str


class SpecValidation(StrictModel):
    valid: bool
    checks: list[ValidationCheck] = Field(min_length=1)
    errors: list[str]
    warnings: list[str]


class ParameterDiffItem(StrictModel):
    parameter: str
    certified_value: Any
    proposed_value: Any
    changed: bool
    impact: str


class PopulationSlice(StrictModel):
    market: str
    population: str
    numerator: int
    denominator: int
    excluded: int
    censored: int
    time_zero: str
    evaluability: str


class PopulationPreview(StrictModel):
    denominator_changed: bool
    previous_denominator: int | None
    current_denominator: int
    reason: str
    slices: list[PopulationSlice] = Field(min_length=1)


class CostEstimate(StrictModel):
    execution_engine: Literal["deterministic_local_python", "isolated_declarative_sandbox"]
    planning_model: str | None
    maximum_planning_cost_usd: float
    maximum_summary_cost_usd: float
    maximum_total_provider_cost_usd: float
    deterministic_execution_cost_usd: float = Field(default=0.0, ge=0.0, le=0.0)
    expected_runtime_seconds: int = Field(ge=0)
    maximum_runtime_seconds: int = Field(ge=1)
    within_budget: bool
    assumptions: list[str] = Field(min_length=1)


class WorkflowEvent(StrictModel):
    state: AnalysisState
    occurred_at: str
    status: Literal["COMPLETE", "WAITING", "FAILED"]
    detail: str


class AnalysisPreview(StrictModel):
    request_id: str
    classification: RequestClassification
    spec: AnalysisSpec
    validation: SpecValidation
    cost_estimate: CostEstimate
    parameter_diff: list[ParameterDiffItem]
    population_preview: PopulationPreview
    workflow: list[WorkflowEvent]
    confirmation_token: str | None
    requires_specialist_plan: bool
    badges: list[EvidenceBadge]
    warning: str


class ResultRow(StrictModel):
    market: str
    subgroup: str
    metric_id: str
    label: str
    numerator: int
    denominator: int
    rate: float | None
    unit: str
    population: str
    time_window: str
    method: str
    parent_release_id: str


class QAReport(StrictModel):
    status: Literal["PASS", "FAIL"]
    checks: list[ValidationCheck] = Field(min_length=1)
    population_count: int
    numerator_total: int
    denominator_total: int
    duplicate_rows: int
    missing_values: int


class InteractiveRunManifest(StrictModel):
    schema_version: Literal["INTERACTIVE-ANALYSIS-RUN-v1.0"] = "INTERACTIVE-ANALYSIS-RUN-v1.0"
    run_id: str = Field(pattern=r"^iar_[a-f0-9]{20}$")
    request_id: str
    parent_release_id: str
    status: Literal["COMPLETED", "ANALYSIS FAILED VALIDATION"]
    badges: list[EvidenceBadge]
    user_request: str
    expert_lens: ExpertLens
    tactic_id: str | None
    analysis_spec_sha256: str
    config_diff: list[ParameterDiffItem]
    config_sha256: str
    code_identity: str
    input_snapshot_sha256: str
    input_artifacts: list[str]
    output_files: list[str]
    qa_status: Literal["PASS", "FAIL"]
    estimated_cost_usd: float
    actual_provider_cost_usd: float
    started_at: str
    completed_at: str
    workflow: list[WorkflowEvent]
    limitations: list[str]
    synthetic_only: Literal[True] = True
    prohibited_use: str


class InteractiveRun(StrictModel):
    manifest: InteractiveRunManifest
    spec: AnalysisSpec
    results: list[ResultRow]
    qa: QAReport
    interpretation: list[str]
    run_directory: str


class RunComparison(StrictModel):
    left_run_id: str
    right_run_id: str
    parent_release_id: str
    compatible: bool
    differences: list[dict[str, Any]]
    warning: str


class ReviewSubmission(StrictModel):
    run_id: str
    status: Literal["SUBMITTED FOR REVIEW"] = "SUBMITTED FOR REVIEW"
    submitted_at: str
    human_reviewer: Literal["TO BE ASSIGNED"] = "TO BE ASSIGNED"
    reviewer_note: str
    certification_changed: Literal[False] = False
    next_required_action: str
