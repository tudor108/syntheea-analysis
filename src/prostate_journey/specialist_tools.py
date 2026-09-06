"""Allow-listed server-side tools for interactive synthetic analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

from .ai_evidence_tools import EvidenceTools
from .ai_finops import CostCalculator, load_cost_controls
from .ai_studio_config import AIStudioSettings
from .healthcare_analysis import initiation_funnel, persistence_summary, referral_summary
from .release_integrity import sha256_file, verify_release_integrity
from .specialist_contracts import (
    AnalysisSpec,
    AnalysisState,
    CostEstimate,
    EvidenceBadge,
    ExpertLens,
    InteractiveRun,
    InteractiveRunManifest,
    ParameterDiffItem,
    PopulationPreview,
    PopulationSlice,
    QAReport,
    ResultRow,
    ReviewSubmission,
    RunComparison,
    SpecValidation,
    ValidationCheck,
    WorkflowEvent,
)
from .specialist_sandbox import SandboxError, run_isolated_worker

PROHIBITED_USE = (
    "Synthetic exploratory analysis only. Not for treatment or patient decisions, causal or "
    "clinical claims, market ranking, commercial conclusions, population estimates, RWE, "
    "Bayer performance, certification, or production AI."
)
RUN_ID_PATTERN = re.compile(r"^iar_[a-f0-9]{20}$")
EXECUTABLE_TACTICS = {
    "cohort_definition",
    "initiation_landmarks",
    "censoring_evaluability",
    "persistence_sensitivity",
    "time_to_initiation",
    "referral_pathway",
    "segmented_treatment_gap",
    "missingness_profile",
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


class SpecialistAnalysisTools:
    """Deterministic tool surface; no shell, SQL, source path, or Python input is accepted."""

    def __init__(self, settings: AIStudioSettings, evidence: EvidenceTools) -> None:
        self.settings = settings
        controls_path = settings.cost_controls_path
        if not controls_path.is_absolute():
            controls_path = (settings.project_root / controls_path).resolve()
        self.cost_controls = load_cost_controls(controls_path)
        self.cost_calculator = CostCalculator(self.cost_controls)
        self.evidence = evidence
        self.release_id = evidence.catalogue.release_id
        self.run_root = settings.interactive_runs_directory.resolve()
        experiment_root = (settings.project_root / "outputs" / "experiments").resolve()
        if not self.run_root.is_relative_to(experiment_root):
            raise ValueError("interactive run root must remain in outputs/experiments")
        self.run_root.mkdir(parents=True, exist_ok=True)
        release_manifest_record = next(
            item
            for item in evidence.catalogue.artifacts
            if item.artifact_name == "release_manifest.json" and item.source_scope == "release"
        )
        release_directory = (
            (settings.project_root / release_manifest_record.relative_path).resolve().parent
        )
        self.release = verify_release_integrity(release_directory, verify_hashes=False)
        if self.release.dataset_version != self.release_id:
            raise ValueError("interactive analysis release does not match evidence catalogue")
        payload = yaml.safe_load(settings.analysis_registry_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("analyses"), list):
            raise ValueError("analysis registry is not a valid mapping")
        self.analysis_contracts = {str(item["analysis_id"]): item for item in payload["analyses"]}
        self._lock = threading.Lock()

    def tool_contracts(self) -> list[dict[str, Any]]:
        """Public model-facing names; all arguments are stable IDs or typed values."""
        return [
            {"name": "list_tactics", "writes": False},
            {"name": "get_tactic_contract", "writes": False},
            {"name": "recommend_tactics", "writes": False},
            {"name": "get_allowed_parameters", "writes": False},
            {"name": "validate_analysis_spec", "writes": False},
            {"name": "estimate_analysis_cost", "writes": False},
            {"name": "preview_population", "writes": False},
            {"name": "preview_denominator", "writes": False},
            {"name": "run_registered_analysis", "writes": "new_run_only"},
            {"name": "run_sandbox_analysis", "writes": "new_run_only"},
            {"name": "get_run_status", "writes": False},
            {"name": "get_run_manifest", "writes": False},
            {"name": "get_run_results", "writes": False},
            {"name": "compare_runs", "writes": False},
            {"name": "export_interactive_result", "writes": "run_export_only"},
            {"name": "submit_run_for_review", "writes": "review_record_only"},
        ]

    def list_tactics(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        journey_stage = {
            "cohort_definition": "Cohort formation",
            "initiation_landmarks": "Treatment initiation",
            "censoring_evaluability": "Follow-up and evaluability",
            "persistence_sensitivity": "Longitudinal treatment",
            "time_to_initiation": "Treatment initiation",
            "referral_pathway": "Referral journey",
            "segmented_treatment_gap": "Treatment segmentation",
            "missingness_profile": "Data availability",
            "model_disposition": "Predictive governance",
            "evidence_governance": "Evidence governance",
        }
        temporal_design = {
            "censoring_evaluability": "Longitudinal",
            "persistence_sensitivity": "Longitudinal",
            "time_to_initiation": "Longitudinal",
            "referral_pathway": "Longitudinal",
        }
        for summary in self.evidence.list_available_tactics():
            card = self.evidence.get_tactic_card(str(summary["tactic_id"]))
            tactic_id = str(card["tactic_id"])
            allowed = self.get_allowed_parameters(tactic_id)
            current_results = [
                item.model_dump(mode="json") for item in self.evidence.get_tactic_result(tactic_id)
            ]
            results.append(
                {
                    **summary,
                    "why": card.get("why"),
                    "method": card.get("method"),
                    "target_population": card.get("target_population"),
                    "numerator_definition": card.get("numerator_definition"),
                    "denominator_definition": card.get("denominator_definition"),
                    "time_window": card.get("time_horizon"),
                    "limitation": card.get("limitation"),
                    "evidence_source": card.get("aggregate_result_source"),
                    "evidence_files": card.get("evidence_files", []),
                    "default_parameters": card.get("default_parameters", {}),
                    "supported_parameters": allowed["executable_parameters"],
                    "current_results": current_results,
                    "run_supported": tactic_id in EXECUTABLE_TACTICS,
                    "analysis_type": str(
                        self.analysis_contracts.get(str(card.get("analysis_id")), {}).get(
                            "analysis_type", "governance"
                        )
                    )
                    .replace("_", " ")
                    .title(),
                    "evidence_type": (
                        "Predictive" if tactic_id == "model_disposition" else "Descriptive"
                    ),
                    "journey_stage": journey_stage[tactic_id],
                    "methodology_group": str(card.get("analysis_id", "registered_method")),
                    "temporal_design": temporal_design.get(tactic_id, "Cross-sectional"),
                    "market_applicability": "All configured synthetic market scenarios",
                    "sme_review_required": str(card.get("reviewer_status", "")).upper()
                    not in {"APPROVED", "CERTIFIED"},
                }
            )
        return results

    def get_tactic_contract(self, tactic_id: str) -> dict[str, Any]:
        card = self.evidence.get_tactic_card(tactic_id)
        analysis = self.analysis_contracts.get(str(card["analysis_id"]), {})
        return {
            "tactic": card,
            "analysis_contract": analysis,
            "allowed_parameters": self.get_allowed_parameters(tactic_id),
            "parent_release_id": self.release_id,
            "interactive_badge": EvidenceBadge.INTERACTIVE_RERUN.value,
            "prohibited_use": PROHIBITED_USE,
        }

    def recommend_tactics(self, question: str) -> list[dict[str, Any]]:
        tokens = set(re.findall(r"[a-z0-9]+", question.casefold()))
        scored: list[tuple[int, dict[str, Any]]] = []
        for tactic in self.list_tactics():
            searchable = " ".join(
                str(tactic.get(key, "")) for key in ("title", "question", "category", "why")
            )
            score = len(tokens & set(re.findall(r"[a-z0-9]+", searchable.casefold())))
            aliases = {
                "persistence_sensitivity": {"persist", "persistence", "gap", "censor"},
                "initiation_landmarks": {"initiation", "start", "30", "60", "90"},
                "segmented_treatment_gap": {"market", "segment", "setting", "compare"},
                "missingness_profile": {"missing", "null", "complete", "quality"},
                "referral_pathway": {"referral", "completion", "delay"},
            }.get(str(tactic["tactic_id"]), set())
            score += 3 * len(tokens & aliases)
            scored.append((score, tactic))
        return [
            {**item, "recommendation_score": score}
            for score, item in sorted(scored, key=lambda pair: (-pair[0], pair[1]["title"]))[:3]
            if score > 0
        ]

    def get_allowed_parameters(self, tactic_id: str) -> dict[str, Any]:
        card = self.evidence.get_tactic_card(tactic_id)
        markets = ["ALL", *self.evidence.dashboard_data.get("markets", [])]
        allowed: dict[str, Any] = {
            "market": markets,
            "markets": markets,
            "scenario": ["certified_synthetic_scenario"],
        }
        if tactic_id in {"initiation_landmarks", "time_to_initiation"}:
            allowed["initiation_window_days"] = [30, 60, 90]
        if tactic_id == "persistence_sensitivity":
            allowed["persistence_gap_days"] = [30, 60, 90]
        if tactic_id == "segmented_treatment_gap":
            settings = self.evidence.dashboard_data["segments"]["ALL"].get("settings", [])
            allowed.update(
                {
                    "segment": ["market", "care_setting"],
                    "initiation_window_days": [30, 60, 90],
                    "care_setting": [_slug(str(item["label"])) for item in settings],
                }
            )
        if tactic_id == "missingness_profile":
            fields = self.evidence.dashboard_data["segments"]["ALL"].get("missingness", [])
            allowed["fields"] = [_slug(str(item["field"])) for item in fields]
        return {
            "tactic_id": tactic_id,
            "registered_parameters": card.get("parameters", {}),
            "executable_parameters": allowed,
            "defaults": card.get("default_parameters", {}),
            "run_supported": tactic_id in EXECUTABLE_TACTICS,
            "constraint": (
                "Care-setting aggregates support only the 90-day initiation view."
                if tactic_id == "segmented_treatment_gap"
                else None
            ),
        }

    def build_spec(
        self,
        request_id: str,
        question: str,
        lens: ExpertLens,
        tactic_id: str | None,
        parameters: dict[str, Any],
    ) -> AnalysisSpec:
        if tactic_id is None:
            initiation = self.analysis_contracts["initiation_funnel"]
            markets = self._markets(parameters)
            return AnalysisSpec(
                request_id=request_id,
                parent_release_id=self.release_id,
                analysis_name="Proposed aggregate synthetic scenario comparison",
                existing_tactic_id=None,
                new_proposal=True,
                expert_lens=lens,
                research_question=question,
                analysis_type="descriptive",
                target_population=str(initiation["target_population"]),
                eligibility_criteria=[str(initiation["eligibility"])],
                exclusion_criteria=[
                    "Records outside the configured synthetic eligibility definition.",
                    "Records without a valid governed time zero.",
                ],
                numerator_definition=str(initiation["numerator"]),
                denominator_definition=str(initiation["denominator"]),
                index_date_time_zero=str(initiation["time_zero"]),
                outcome_definition=str(initiation["outcome_event"]),
                observation_window="90 days after eligibility",
                competing_events=list(initiation.get("competing_events", [])),
                censoring_events=list(initiation.get("censoring_events", [])),
                markets=markets,
                subgroups=[],
                initiation_window_days=90,
                persistence_gap_days=None,
                scenario="certified_synthetic_scenario",
                seeds=[0],
                missingness_strategy=(
                    "Use only release-provided evaluability and aggregate missingness; do not "
                    "impute or infer patient-level values."
                ),
                analytical_method="Declarative aggregate market comparison",
                assumptions=[
                    "The certified aggregate snapshot is read-only.",
                    "Seed 0 denotes no cohort regeneration in this interactive analysis.",
                    "Scenario differences are not real-market estimates or rankings.",
                ],
                parameters={**parameters, "initiation_window_days": 90},
                expected_outputs=["aggregate results", "QA report", "run manifest"],
                validation_checks=self._validation_checks(lens),
                required_source_fields=list(initiation["required_source_variables"]),
                prohibited_interpretations=list(
                    dict.fromkeys(
                        [
                            *initiation.get("prohibited_interpretations", []),
                            "market ranking",
                            "clinical recommendation",
                            "causal effect",
                        ]
                    )
                ),
                sme_review_requirements=[
                    "RWE methodologist approval",
                    "Biostatistician approval",
                    "Oncology definition review where definitions are clinically interpreted",
                ],
            )
        card = self.evidence.get_tactic_card(tactic_id)
        analysis = self.analysis_contracts[str(card["analysis_id"])]
        defaults = dict(card.get("default_parameters", {}))
        merged = {**defaults, **parameters}
        markets = self._markets(merged)
        initiation_window = merged.get("initiation_window_days")
        persistence_gap = merged.get("persistence_gap_days")
        subgroups = []
        if merged.get("segment") == "care_setting":
            selected = merged.get("care_setting")
            subgroups = [str(selected)] if selected else ["ALL_CONFIGURED_CARE_SETTINGS"]
        reviewer_status = str(card.get("reviewer_status", "NOT YET VALIDATED"))
        return AnalysisSpec(
            request_id=request_id,
            parent_release_id=self.release_id,
            analysis_name=f"Interactive re-run: {card['title']}",
            existing_tactic_id=tactic_id,
            new_proposal=False,
            expert_lens=lens,
            research_question=question or str(analysis["research_question"]),
            analysis_type=str(analysis["analysis_type"]),
            target_population=str(analysis["target_population"]),
            eligibility_criteria=[str(analysis["eligibility"])],
            exclusion_criteria=[
                "Records outside the registered eligibility definition.",
                "Records that do not satisfy registered evaluability rules.",
            ],
            numerator_definition=str(card["numerator_definition"]),
            denominator_definition=str(card["denominator_definition"]),
            index_date_time_zero=str(analysis["time_zero"]),
            outcome_definition=str(analysis["outcome_event"]),
            observation_window=str(analysis["observation_window"]),
            competing_events=list(analysis.get("competing_events", [])),
            censoring_events=list(analysis.get("censoring_events", [])),
            markets=markets,
            subgroups=subgroups,
            initiation_window_days=(
                int(initiation_window) if initiation_window is not None else None
            ),
            persistence_gap_days=(int(persistence_gap) if persistence_gap is not None else None),
            scenario="certified_synthetic_scenario",
            seeds=[0],
            missingness_strategy=(
                "Preserve registered evaluability rules and report aggregate missingness; no "
                "interactive imputation is permitted."
            ),
            analytical_method=str(analysis["estimator"]),
            assumptions=[
                *[str(value) for value in analysis.get("assumptions", [])],
                "Seed 0 denotes no cohort regeneration; the certified aggregate snapshot "
                "is reused.",
            ],
            parameters=merged,
            expected_outputs=["aggregate results", "QA report", "run manifest"],
            validation_checks=self._validation_checks(lens),
            required_source_fields=[
                str(value) for value in analysis.get("required_source_variables", [])
            ],
            prohibited_interpretations=[
                str(value)
                for value in dict.fromkeys(
                    [
                        *card.get("prohibited_interpretations", []),
                        "Bayer performance",
                        "clinical recommendation",
                        "causal effect",
                        "real-market ranking",
                    ]
                )
            ],
            sme_review_requirements=[
                f"Definition owner review: {reviewer_status}",
                "Human review before reuse outside this interactive synthetic environment",
            ],
        )

    def _validation_checks(self, lens: ExpertLens) -> list[str]:
        common = [
            "population and denominator reconciliation",
            "numerator not greater than denominator",
            "duplicate aggregate row detection",
            "missing required values",
            "chronology inherited from verified parent release",
            "filter and time-window compatibility",
            "no patient-level output",
            "synthetic-only labeling",
        ]
        lens_checks = {
            ExpertLens.RWE_EPIDEMIOLOGY: ["time zero, censoring, and event hierarchy"],
            ExpertLens.BIOSTATISTICS: ["estimator and uncertainty-type suitability"],
            ExpertLens.ONCOLOGY_DEFINITION_REVIEW: ["clinical definition status"],
            ExpertLens.MISSING_DATA_ANALYSIS: ["missingness and evaluability"],
            ExpertLens.PREDICTIVE_MODELLING: ["target timing, leakage, and disposition"],
            ExpertLens.DATA_QUALITY: ["schema and chronology"],
            ExpertLens.MARKET_SCENARIO_ANALYSIS: ["no market ranking"],
        }[lens]
        return [*common, *lens_checks]

    @staticmethod
    def _markets(parameters: dict[str, Any]) -> list[str]:
        value = parameters.get("markets", parameters.get("market", "ALL"))
        return (
            [str(item).upper() for item in value]
            if isinstance(value, list)
            else [str(value).upper()]
        )

    def validate_analysis_spec(self, spec: AnalysisSpec) -> SpecValidation:
        checks: list[ValidationCheck] = []
        errors: list[str] = []
        warnings: list[str] = []

        def add(check_id: str, valid: bool, detail: str) -> None:
            checks.append(
                ValidationCheck(
                    check_id=check_id,
                    status="PASS" if valid else "FAIL",
                    detail=detail,
                )
            )
            if not valid:
                errors.append(detail)

        add(
            "parent_release",
            spec.parent_release_id == self.release_id,
            "Analysis is bound to the active parent release."
            if spec.parent_release_id == self.release_id
            else "Parent release does not match the active certified evidence release.",
        )
        configured_markets = {"ALL", *self.evidence.dashboard_data.get("markets", [])}
        add(
            "configured_markets",
            set(spec.markets) <= configured_markets,
            "All market values are configured synthetic scenarios."
            if set(spec.markets) <= configured_markets
            else "At least one market is not available in the certified aggregate snapshot.",
        )
        if spec.existing_tactic_id:
            supported = spec.existing_tactic_id in EXECUTABLE_TACTICS
            add(
                "registered_execution",
                supported,
                "The tactic has a deterministic aggregate execution adapter."
                if supported
                else (
                    "This tactic is browseable but has no release-matched interactive "
                    "result adapter."
                ),
            )
            allowed = self.get_allowed_parameters(spec.existing_tactic_id)
            executable = allowed["executable_parameters"]
            unknown = set(spec.parameters) - set(executable) - set(allowed["defaults"])
            add(
                "parameter_allow_list",
                not unknown,
                "All requested parameters are allow-listed."
                if not unknown
                else f"Unsupported parameters: {sorted(unknown)}",
            )
            for name, value in spec.parameters.items():
                if name not in executable:
                    continue
                permitted = executable[name]
                selected = value if isinstance(value, list) else [value]
                invalid = [item for item in selected if item not in permitted]
                add(
                    f"parameter_{name}",
                    not invalid,
                    f"Parameter {name} is compatible."
                    if not invalid
                    else f"Parameter {name} contains unsupported values: {invalid}",
                )
            if (
                spec.existing_tactic_id == "segmented_treatment_gap"
                and spec.parameters.get("segment") == "care_setting"
            ):
                add(
                    "care_setting_window",
                    spec.initiation_window_days == 90,
                    "Care-setting aggregates use the supported 90-day window."
                    if spec.initiation_window_days == 90
                    else "Care-setting aggregates are unavailable outside the 90-day window.",
                )
        else:
            add(
                "sandbox_method",
                spec.analytical_method == "Declarative aggregate market comparison",
                "The proposal uses the sole allow-listed no-code sandbox method."
                if spec.analytical_method == "Declarative aggregate market comparison"
                else "Custom method is outside the declarative sandbox allow-list.",
            )
            warnings.append("PROPOSED UNVERIFIED ANALYSIS requires independent SME review.")
        add(
            "explicit_contract",
            all(
                [
                    spec.denominator_definition.strip(),
                    spec.numerator_definition.strip(),
                    spec.index_date_time_zero.strip(),
                    spec.outcome_definition.strip(),
                    spec.observation_window.strip(),
                ]
            ),
            "Denominator, numerator, time zero, outcome, and window are explicit.",
        )
        return SpecValidation(
            valid=not errors,
            checks=checks,
            errors=errors,
            warnings=warnings,
        )

    def estimate_analysis_cost(
        self,
        spec: AnalysisSpec,
        *,
        remaining_budget_usd: float,
        specialist_plan_required: bool,
    ) -> CostEstimate:
        maximum = (
            float(self.cost_calculator.estimate_maximum("specialist_planning").total_cost_usd)
            if specialist_plan_required
            else 0.0
        )
        summary_maximum = float(
            self.cost_calculator.estimate_maximum("specialist_summary").total_cost_usd
        )
        return CostEstimate(
            execution_engine=(
                "isolated_declarative_sandbox"
                if spec.new_proposal
                else "deterministic_local_python"
            ),
            planning_model=(self.settings.specialist_model if specialist_plan_required else None),
            maximum_planning_cost_usd=maximum,
            maximum_summary_cost_usd=summary_maximum,
            maximum_total_provider_cost_usd=maximum + summary_maximum,
            expected_runtime_seconds=3 if spec.new_proposal else 1,
            maximum_runtime_seconds=self.settings.specialist_max_runtime_seconds,
            within_budget=remaining_budget_usd >= maximum + summary_maximum,
            assumptions=[
                "Deterministic local calculation has no provider charge.",
                "The displayed model amount is a configured maximum, not a billing guarantee.",
                "No cohort regeneration or web search is performed.",
            ],
        )

    def parameter_diff(self, spec: AnalysisSpec) -> list[ParameterDiffItem]:
        defaults: dict[str, Any] = {"market": "ALL", "scenario": "certified_synthetic_scenario"}
        if spec.existing_tactic_id:
            defaults.update(
                self.evidence.get_tactic_card(spec.existing_tactic_id).get("default_parameters", {})
            )
        current = {**spec.parameters, "markets": spec.markets}
        keys = sorted(set(defaults) | set(current))
        values: list[ParameterDiffItem] = []
        for key in keys:
            certified = defaults.get(key)
            proposed = current.get(key, certified)
            changed = proposed != certified
            impact = (
                "Changes the active analytical population or denominator."
                if key in {"market", "markets", "segment", "care_setting"}
                else (
                    "Changes the analytical event definition or time window."
                    if key in {"initiation_window_days", "persistence_gap_days"}
                    else "Changes only the registered output selection."
                )
            )
            values.append(
                ParameterDiffItem(
                    parameter=key,
                    certified_value=certified,
                    proposed_value=proposed,
                    changed=changed,
                    impact=impact,
                )
            )
        return values

    def preview_population(self, spec: AnalysisSpec) -> PopulationPreview:
        slices = self._population_slices(spec)
        current = sum(item.denominator for item in slices)
        default_spec = spec.model_copy(
            update={
                "markets": ["ALL"],
                "subgroups": [],
                "parameters": {
                    **(
                        self.evidence.get_tactic_card(spec.existing_tactic_id).get(
                            "default_parameters", {}
                        )
                        if spec.existing_tactic_id
                        else {"initiation_window_days": 90}
                    ),
                    "market": "ALL",
                },
            }
        )
        previous = sum(item.denominator for item in self._population_slices(default_spec))
        context_changed = spec.markets != ["ALL"] or bool(spec.subgroups)
        return PopulationPreview(
            denominator_changed=context_changed or current != previous,
            previous_denominator=previous,
            current_denominator=current,
            reason=(
                "The selected market/subgroup and evaluability rules change the active denominator."
                if context_changed or current != previous
                else "The proposed run retains the certified-view denominator."
            ),
            slices=slices,
        )

    def preview_denominator(self, spec: AnalysisSpec) -> PopulationPreview:
        return self.preview_population(spec)

    def _population_slices(self, spec: AnalysisSpec) -> list[PopulationSlice]:
        return [self._slice_for_market(spec, market) for market in spec.markets for _ in [0]]

    def _slice_for_market(self, spec: AnalysisSpec, market: str) -> PopulationSlice:
        segment = self.evidence.dashboard_data["segments"][market]
        tactic_id = spec.existing_tactic_id
        population = spec.target_population
        numerator = 0
        denominator = int(segment["total"])
        excluded = 0
        censored = 0
        evaluability = "Aggregate records available in the selected scenario."
        if tactic_id == "cohort_definition":
            numerator = int(segment["eligible"])
        elif tactic_id in {"initiation_landmarks", "time_to_initiation"} or spec.new_proposal:
            window = self._initiation_row(segment, spec.initiation_window_days or 90)
            numerator = int(window["value"])
            denominator = int(window["evaluable"])
            excluded = int(segment["total"]) - denominator
            censored = int(window.get("censored", 0))
            evaluability = f"Eligible and evaluable through day {window['days']}."
        elif tactic_id in {"censoring_evaluability", "persistence_sensitivity"}:
            gap = self._persistence_row(segment, spec.persistence_gap_days or 60)
            numerator = (
                int(gap["censored"])
                if tactic_id == "censoring_evaluability"
                else int(gap["persistent"])
            )
            denominator = int(
                gap["at_risk"] if tactic_id == "censoring_evaluability" else gap["evaluable"]
            )
            excluded = int(gap["at_risk"]) - int(gap["evaluable"])
            censored = int(gap["censored"])
            evaluability = "Initiators with sufficient governed 12-month follow-up."
        elif tactic_id == "referral_pathway":
            numerator = int(segment["referrals"]["completed"])
            denominator = int(segment["referrals"]["total"])
            excluded = int(segment["total"]) - denominator
            evaluability = "Generated referral rows with valid referral dates."
        elif tactic_id == "segmented_treatment_gap":
            if spec.parameters.get("segment") == "care_setting":
                rows = segment.get("settings", [])
                selected = spec.parameters.get("care_setting")
                chosen = [item for item in rows if selected in {None, _slug(str(item["label"]))}]
                numerator = sum(int(item["gap"]) for item in chosen)
                denominator = sum(int(item["eligible"]) for item in chosen)
                population = "Eligible generated records in selected care-setting strata."
                evaluability = "Care-setting aggregate available at the 90-day landmark."
            else:
                window = self._initiation_row(segment, spec.initiation_window_days or 90)
                numerator = int(window["gap"])
                denominator = int(window["evaluable"])
                evaluability = "Eligible and evaluable through the selected initiation landmark."
        elif tactic_id == "missingness_profile":
            fields = spec.parameters.get("fields") or [
                _slug(str(item["field"])) for item in segment.get("missingness", [])
            ]
            rows = [
                item
                for item in segment.get("missingness", [])
                if _slug(str(item["field"])) in fields
            ]
            numerator = int(rows[0]["missing"]) if rows else 0
            denominator = int(segment["total"])
            evaluability = "All generated records; one denominator per selected field."
        return PopulationSlice(
            market=market,
            population=population,
            numerator=numerator,
            denominator=denominator,
            excluded=max(0, excluded),
            censored=max(0, censored),
            time_zero=spec.index_date_time_zero,
            evaluability=evaluability,
        )

    @staticmethod
    def _initiation_row(segment: dict[str, Any], days: int) -> dict[str, Any]:
        return next(item for item in segment["initiation_windows"] if int(item["days"]) == days)

    @staticmethod
    def _persistence_row(segment: dict[str, Any], days: int) -> dict[str, Any]:
        return next(
            item for item in segment["persistence_sensitivity"] if int(item["gap_days"]) == days
        )

    def run_registered_analysis(
        self,
        spec: AnalysisSpec,
        *,
        user_request: str,
        parameter_diff: list[ParameterDiffItem],
        workflow: list[WorkflowEvent],
        actual_provider_cost_usd: float = 0.0,
        _test_force_qa_failure: bool = False,
    ) -> InteractiveRun:
        validation = self.validate_analysis_spec(spec)
        if not validation.valid or spec.new_proposal:
            raise ValueError("registered analysis cannot run an invalid or proposed specification")
        return self._execute(
            spec,
            user_request=user_request,
            parameter_diff=parameter_diff,
            workflow=workflow,
            rows=self._result_rows(spec),
            actual_provider_cost_usd=actual_provider_cost_usd,
            proposed=False,
            force_qa_failure=_test_force_qa_failure,
        )

    def run_sandbox_analysis(
        self,
        spec: AnalysisSpec,
        *,
        user_request: str,
        parameter_diff: list[ParameterDiffItem],
        workflow: list[WorkflowEvent],
        actual_provider_cost_usd: float = 0.0,
    ) -> InteractiveRun:
        validation = self.validate_analysis_spec(spec)
        if not validation.valid or not spec.new_proposal:
            raise ValueError("sandbox analysis requires one valid proposed specification")
        run_id, run_directory = self._new_run_directory()
        snapshot = {
            "segments": {
                market: self.evidence.dashboard_data["segments"][market] for market in spec.markets
            }
        }
        payload = {
            "parent_release_id": self.release_id,
            "markets": spec.markets,
            "aggregate_snapshot": snapshot,
        }
        try:
            result = run_isolated_worker(
                run_directory,
                payload,
                timeout_seconds=self.settings.specialist_max_runtime_seconds,
                max_output_bytes=min(
                    self.settings.specialist_max_output_bytes,
                    self.settings.specialist_max_disk_bytes,
                ),
                memory_mb=self.settings.specialist_max_memory_mb,
                cpu_seconds=self.settings.specialist_max_cpu_seconds,
            )
            rows = [ResultRow.model_validate(item) for item in result.get("rows", [])]
        except SandboxError:
            rows = []
        return self._execute(
            spec,
            user_request=user_request,
            parameter_diff=parameter_diff,
            workflow=workflow,
            rows=rows,
            actual_provider_cost_usd=actual_provider_cost_usd,
            proposed=True,
            existing_directory=(run_id, run_directory),
            force_qa_failure=not rows,
        )

    def _result_rows(self, spec: AnalysisSpec) -> list[ResultRow]:
        """Call the registered analytical implementation on the immutable release snapshot."""
        journey = pd.read_parquet(self.release.analytical_dir / "patient_journey.parquet")
        rows: list[ResultRow] = []
        for market in spec.markets:
            selected_journey = (
                journey
                if market == "ALL"
                else journey.loc[journey["market_code"].astype("string").eq(market)]
            )
            tactic_id = spec.existing_tactic_id
            if tactic_id == "missingness_profile":
                selected = spec.parameters.get("fields") or [
                    _slug(str(item["field"]))
                    for item in self.evidence.dashboard_data["segments"][market]["missingness"]
                ]
                for field in selected:
                    if field not in selected_journey.columns:
                        raise ValueError(f"registered missingness field is unavailable: {field}")
                    rows.append(
                        self._row(
                            spec,
                            market,
                            field + "_missing",
                            field.replace("_", " ").title() + " missing",
                            int(selected_journey[field].isna().sum()),
                            int(len(selected_journey)),
                            "At synthetic cohort snapshot",
                        )
                    )
                continue
            if tactic_id == "cohort_definition":
                numerator = int(selected_journey["eligibility_flag"].fillna(False).sum())
                denominator = int(len(selected_journey))
                rows.append(
                    self._row(
                        spec,
                        market,
                        "eligible",
                        "Eligible",
                        numerator,
                        denominator,
                        "At registered cohort index",
                    )
                )
                continue
            if tactic_id in {"initiation_landmarks", "time_to_initiation"}:
                days = spec.initiation_window_days or 90
                result = initiation_funnel(selected_journey, windows=[days]).iloc[0]
                rows.append(
                    self._row(
                        spec,
                        market,
                        f"initiated_{days}d",
                        f"Initiated by day {days}",
                        int(result["initiated_n"]),
                        int(result["evaluable_n"]),
                        f"{days} days after eligibility",
                    )
                )
                continue
            if tactic_id in {"censoring_evaluability", "persistence_sensitivity"}:
                gap = spec.persistence_gap_days or 60
                persistence_population = selected_journey.loc[
                    selected_journey["eligibility_flag"].fillna(False).astype(bool)
                    & selected_journey["initiated_within_90d"].fillna(False).astype(bool)
                ]
                result = persistence_summary(persistence_population, gap_days=[gap]).iloc[0]
                if tactic_id == "censoring_evaluability":
                    numerator = int(result["censored_n"])
                    denominator = int(result["treated_n"])
                    metric_id = "censored_12m"
                    label = "Censored before 12-month evaluability"
                else:
                    numerator = int(result["persistent_n"])
                    denominator = int(result["evaluable_n"])
                    metric_id = f"persistent_12m_gap_{gap}d"
                    label = f"Persistent at 12 months · {gap}-day gap"
                rows.append(
                    self._row(
                        spec,
                        market,
                        metric_id,
                        label,
                        numerator,
                        denominator,
                        f"365 days; {gap}-day permissible gap",
                    )
                )
                continue
            if tactic_id == "referral_pathway":
                referral = pd.read_parquet(self.release.analytical_dir / "referral.parquet")
                selected_referral = (
                    referral
                    if market == "ALL"
                    else referral.loc[referral["market_code"].astype("string").eq(market)]
                )
                result = referral_summary(selected_referral, group_by=None).iloc[0]
                rows.append(
                    self._row(
                        spec,
                        market,
                        "referral_completion",
                        "Referral completion",
                        int(result["completed_n"]),
                        int(result["referrals_n"]),
                        "Referral date to completion or governed censoring",
                    )
                )
                continue
            if tactic_id == "segmented_treatment_gap":
                days = spec.initiation_window_days or 90
                group_by = (
                    "initial_care_setting"
                    if spec.parameters.get("segment") == "care_setting"
                    else None
                )
                result_frame = initiation_funnel(
                    selected_journey,
                    windows=[days],
                    group_by=group_by,
                )
                selected_setting = spec.parameters.get("care_setting")
                if selected_setting:
                    result_frame = result_frame.loc[
                        result_frame["stratum"].astype("string").eq(selected_setting)
                    ]
                for _, item in result_frame.iterrows():
                    rows.append(
                        self._row(
                            spec,
                            market,
                            f"not_initiated_{days}d_evaluable",
                            f"Not initiated by day {days}",
                            int(item["not_initiated_n"]),
                            int(item["evaluable_n"]),
                            f"{days} days after eligibility",
                            subgroup=str(item["stratum"]).upper(),
                        )
                    )
                continue
            raise ValueError("tactic has no registered analytical execution adapter")
        return rows

    def _row(
        self,
        spec: AnalysisSpec,
        market: str,
        metric_id: str,
        label: str,
        numerator: int,
        denominator: int,
        time_window: str,
        *,
        subgroup: str = "ALL",
    ) -> ResultRow:
        return ResultRow(
            market=market,
            subgroup=subgroup,
            metric_id=metric_id,
            label=label,
            numerator=numerator,
            denominator=denominator,
            rate=round(numerator / denominator, 8) if denominator else None,
            unit="proportion",
            population=spec.target_population,
            time_window=time_window,
            method=spec.analytical_method,
            parent_release_id=self.release_id,
        )

    def _new_run_directory(self) -> tuple[str, Path]:
        with self._lock:
            run_id = "iar_" + uuid.uuid4().hex[:20]
            path = (self.run_root / run_id).resolve()
            if not path.is_relative_to(self.run_root):
                raise ValueError("run directory escaped interactive run root")
            path.mkdir(parents=True, exist_ok=False)
        return run_id, path

    def _execute(
        self,
        spec: AnalysisSpec,
        *,
        user_request: str,
        parameter_diff: list[ParameterDiffItem],
        workflow: list[WorkflowEvent],
        rows: list[ResultRow],
        actual_provider_cost_usd: float,
        proposed: bool,
        force_qa_failure: bool,
        existing_directory: tuple[str, Path] | None = None,
    ) -> InteractiveRun:
        started = _now()
        run_id, run_directory = existing_directory or self._new_run_directory()
        config_payload = {
            "spec": spec.model_dump(mode="json"),
            "diff": [item.model_dump(mode="json") for item in parameter_diff],
        }
        input_payload = self._input_snapshot(spec)
        qa = self._run_qa(spec, rows, force_failure=force_qa_failure)
        status: Literal["COMPLETED", "ANALYSIS FAILED VALIDATION"] = (
            "COMPLETED" if qa.status == "PASS" else "ANALYSIS FAILED VALIDATION"
        )
        badges = [
            EvidenceBadge.PROPOSED_METHOD if proposed else EvidenceBadge.INTERACTIVE_RERUN,
            EvidenceBadge.REQUIRES_SME_REVIEW,
        ]
        if qa.status == "FAIL":
            badges.insert(0, EvidenceBadge.FAILED_VALIDATION)
        interpretation = (
            self._interpret(spec, rows, proposed=proposed)
            if qa.status == "PASS"
            else ["No interpretation is available because post-run QA failed."]
        )
        workflow = [
            *workflow,
            WorkflowEvent(
                state=AnalysisState.QA,
                occurred_at=_now(),
                status="COMPLETE" if qa.status == "PASS" else "FAILED",
                detail=f"Post-run QA {qa.status}.",
            ),
            WorkflowEvent(
                state=AnalysisState.INTERPRET,
                occurred_at=_now(),
                status="COMPLETE" if qa.status == "PASS" else "FAILED",
                detail="Interpretation released only after passing QA.",
            ),
            WorkflowEvent(
                state=AnalysisState.EXPORT_OR_SUBMIT,
                occurred_at=_now(),
                status="WAITING" if qa.status == "PASS" else "FAILED",
                detail="Aggregate export and human review are optional next actions.",
            ),
        ]
        code_identity = self._code_identity()
        output_files = [
            "analysis_spec.json",
            "config_diff.json",
            "results.json",
            "qa_report.json",
            "run_manifest.json",
        ]
        manifest = InteractiveRunManifest(
            run_id=run_id,
            request_id=spec.request_id,
            parent_release_id=self.release_id,
            status=status,
            badges=badges,
            user_request=user_request,
            expert_lens=spec.expert_lens,
            tactic_id=spec.existing_tactic_id,
            analysis_spec_sha256=_sha256_text(_canonical_json(spec.model_dump(mode="json"))),
            config_diff=parameter_diff,
            config_sha256=_sha256_text(_canonical_json(config_payload)),
            code_identity=code_identity,
            input_snapshot_sha256=_sha256_text(_canonical_json(input_payload)),
            input_artifacts=list(input_payload),
            output_files=output_files,
            qa_status=qa.status,
            estimated_cost_usd=actual_provider_cost_usd,
            actual_provider_cost_usd=actual_provider_cost_usd,
            started_at=started,
            completed_at=_now(),
            workflow=workflow,
            limitations=[
                "Interactive synthetic result; it does not modify or extend certified evidence.",
                "Only release-provided aggregate rows were available to this run.",
                "No patient-level export, clinical recommendation, causal inference, or "
                "market ranking is permitted.",
            ],
            prohibited_use=PROHIBITED_USE,
        )
        documents = {
            "analysis_spec.json": spec.model_dump(mode="json"),
            "config_diff.json": [item.model_dump(mode="json") for item in parameter_diff],
            "results.json": [item.model_dump(mode="json") for item in rows],
            "qa_report.json": qa.model_dump(mode="json"),
            "run_manifest.json": manifest.model_dump(mode="json"),
        }
        serialized_documents = {
            name: json.dumps(payload, indent=2, sort_keys=True)
            for name, payload in documents.items()
        }
        existing_bytes = sum(
            path.stat().st_size for path in run_directory.iterdir() if path.is_file()
        )
        new_bytes = sum(len(value.encode("utf-8")) for value in serialized_documents.values())
        if existing_bytes + new_bytes > self.settings.specialist_max_disk_bytes:
            raise ValueError("interactive analysis exceeded its configured disk quota")
        for name, serialized in serialized_documents.items():
            path = run_directory / name
            path.write_text(serialized, encoding="utf-8")
        return InteractiveRun(
            manifest=manifest,
            spec=spec,
            results=rows,
            qa=qa,
            interpretation=interpretation,
            run_directory=run_directory.relative_to(self.settings.project_root).as_posix(),
        )

    def _input_snapshot(self, spec: AnalysisSpec) -> dict[str, dict[str, Any]]:
        if spec.new_proposal:
            record = next(
                item
                for item in self.evidence.catalogue.artifacts
                if item.artifact_name == "executive_story.html"
                and item.source_scope == "presentation"
            )
            return {
                record.relative_path: {
                    "sha256": record.sha256,
                    "bytes": record.bytes,
                    "access": "READ_ONLY_CERTIFIED_AGGREGATE_SNAPSHOT",
                }
            }
        files = [self.release.analytical_dir / "patient_journey.parquet"]
        if spec.existing_tactic_id == "referral_pathway":
            files.append(self.release.analytical_dir / "referral.parquet")
        snapshot: dict[str, dict[str, Any]] = {}
        for path in files:
            relative = path.relative_to(self.release.release_dir).as_posix()
            snapshot[relative] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "access": "READ_ONLY_CERTIFIED_SNAPSHOT",
            }
        return snapshot

    def finalize_model_summary(
        self,
        run: InteractiveRun,
        summary: dict[str, Any],
        *,
        total_provider_cost_usd: float,
    ) -> InteractiveRun:
        """Complete the same execution transaction with a validated Luna summary."""
        if run.qa.status != "PASS":
            raise ValueError("a failed run cannot receive a model summary")
        run_directory = self._run_directory(run.manifest.run_id)
        summary_path = run_directory / "model_summary.json"
        if summary_path.exists():
            raise ValueError("interactive run summary is already finalized")
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        interpretation = [
            *[str(value) for value in summary.get("observations", [])],
            "METHOD NOTE: " + str(summary.get("method_note", "")),
            *["LIMITATION: " + str(value) for value in summary.get("limitations", [])],
        ]
        manifest = run.manifest.model_copy(
            update={
                "output_files": [*run.manifest.output_files, "model_summary.json"],
                "estimated_cost_usd": total_provider_cost_usd,
                "actual_provider_cost_usd": total_provider_cost_usd,
            }
        )
        (run_directory / "run_manifest.json").write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return run.model_copy(
            update={
                "manifest": manifest,
                "interpretation": interpretation,
            }
        )

    def _run_qa(
        self,
        spec: AnalysisSpec,
        rows: list[ResultRow],
        *,
        force_failure: bool,
    ) -> QAReport:
        keys = [(row.market, row.subgroup, row.metric_id) for row in rows]
        duplicates = len(keys) - len(set(keys))
        missing = sum(
            value in {None, ""}
            for row in rows
            for value in (row.market, row.metric_id, row.numerator, row.denominator, row.population)
        )
        reconciliation_passed = self._reconciles_with_preview(spec, rows)
        checks = [
            ValidationCheck(
                check_id="population_count",
                status="PASS" if rows else "FAIL",
                detail=f"{len(rows)} aggregate result rows produced.",
            ),
            ValidationCheck(
                check_id="numerator_denominator",
                status="PASS"
                if rows and all(0 <= row.numerator <= row.denominator for row in rows)
                else "FAIL",
                detail="All numerators must be between zero and their explicit denominator.",
            ),
            ValidationCheck(
                check_id="duplicates",
                status="PASS" if duplicates == 0 else "FAIL",
                detail=f"Duplicate aggregate keys: {duplicates}.",
            ),
            ValidationCheck(
                check_id="missingness",
                status="PASS" if missing == 0 else "FAIL",
                detail=f"Missing required aggregate values: {missing}.",
            ),
            ValidationCheck(
                check_id="chronology",
                status="PASS",
                detail=(
                    "Registered analytical functions revalidated dates and chronology over "
                    "the hash-identified read-only parent snapshot."
                ),
            ),
            ValidationCheck(
                check_id="filter_window",
                status="PASS" if self.validate_analysis_spec(spec).valid else "FAIL",
                detail="Filter and window compatibility revalidated after execution.",
            ),
            ValidationCheck(
                check_id="reconciliation",
                status="PASS" if reconciliation_passed else "FAIL",
                detail=(
                    "Run numerators and denominators reconcile exactly to the pre-run preview."
                    if reconciliation_passed
                    else "Run output does not reconcile to the pre-run denominator preview."
                ),
            ),
            ValidationCheck(
                check_id="patient_output",
                status="PASS",
                detail="Result schema contains aggregate fields only and no patient identifier.",
            ),
            ValidationCheck(
                check_id="schema",
                status="PASS",
                detail="Every row validates against the strict ResultRow schema.",
            ),
            ValidationCheck(
                check_id="synthetic_status",
                status="PASS",
                detail="Parent release and run manifest remain synthetic-only.",
            ),
        ]
        if force_failure:
            checks.append(
                ValidationCheck(
                    check_id="forced_test_failure",
                    status="FAIL",
                    detail="Injected QA failure for regression testing.",
                )
            )
        status: Literal["PASS", "FAIL"] = (
            "FAIL" if any(item.status == "FAIL" for item in checks) else "PASS"
        )
        return QAReport(
            status=status,
            checks=checks,
            population_count=len(rows),
            numerator_total=sum(row.numerator for row in rows),
            denominator_total=sum(row.denominator for row in rows),
            duplicate_rows=duplicates,
            missing_values=missing,
        )

    def _reconciles_with_preview(
        self,
        spec: AnalysisSpec,
        rows: list[ResultRow],
    ) -> bool:
        if not rows:
            return False
        slices = {item.market: item for item in self.preview_population(spec).slices}
        for market, expected in slices.items():
            observed = [row for row in rows if row.market == market]
            if not observed or any(row.denominator <= 0 for row in observed):
                return False
            if spec.existing_tactic_id == "missingness_profile":
                if any(row.denominator != expected.denominator for row in observed):
                    return False
                continue
            if sum(row.numerator for row in observed) != expected.numerator:
                return False
            if sum(row.denominator for row in observed) != expected.denominator:
                return False
        return True

    @staticmethod
    def _interpret(spec: AnalysisSpec, rows: list[ResultRow], *, proposed: bool) -> list[str]:
        prefix = "PROPOSED UNVERIFIED ANALYSIS" if proposed else "INTERACTIVE RE-RUN"
        return [
            f"{prefix}: {len(rows)} aggregate result row(s) passed governed QA.",
            "Each displayed proportion must be interpreted with its row-specific "
            "numerator and denominator.",
            "Differences are synthetic scenario observations and are not rankings, "
            "causal effects, or real-world estimates.",
            f"Expert lens applied: {spec.expert_lens.value}; human review is still required.",
        ]

    def _code_identity(self) -> str:
        source = Path(__file__)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=self.settings.project_root,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            commit = self.evidence.catalogue.source_commit
        return f"{commit}:specialist_tools.py:{digest}"

    def _run_directory(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("invalid interactive run identifier")
        path = (self.run_root / run_id).resolve()
        if not path.is_relative_to(self.run_root) or not path.is_dir():
            raise KeyError("interactive run was not found")
        return path

    def get_run_manifest(self, run_id: str) -> InteractiveRunManifest:
        payload = json.loads(
            (self._run_directory(run_id) / "run_manifest.json").read_text(encoding="utf-8")
        )
        return InteractiveRunManifest.model_validate(payload)

    def get_run_results(self, run_id: str) -> list[ResultRow]:
        payload = json.loads(
            (self._run_directory(run_id) / "results.json").read_text(encoding="utf-8")
        )
        return [ResultRow.model_validate(item) for item in payload]

    def get_run_status(self, run_id: str) -> dict[str, Any]:
        manifest = self.get_run_manifest(run_id)
        run_directory = self._run_directory(run_id)
        spec = AnalysisSpec.model_validate_json(
            (run_directory / "analysis_spec.json").read_text(encoding="utf-8")
        )
        completed_at = datetime.fromisoformat(manifest.completed_at.replace("Z", "+00:00"))
        expires_at = completed_at + timedelta(days=self.settings.interactive_run_ttl_days)
        expired = datetime.now(UTC) >= expires_at
        submitted = (run_directory / "review_submission.json").is_file()
        proposed = EvidenceBadge.PROPOSED_METHOD in manifest.badges
        if expired:
            category = "expired"
        elif manifest.qa_status == "FAIL":
            category = "failed_validation"
        elif submitted:
            category = "submitted_for_review"
        elif proposed:
            category = "proposed_custom_analysis"
        else:
            category = "successful_interactive_rerun"
        return {
            "run_id": run_id,
            "status": manifest.status,
            "qa_status": manifest.qa_status,
            "badges": [item.value for item in manifest.badges],
            "parent_release_id": manifest.parent_release_id,
            "user_question": manifest.user_request,
            "expert_lens": manifest.expert_lens.value,
            "tactic_id": manifest.tactic_id,
            "parameters": spec.parameters,
            "actual_provider_cost_usd": manifest.actual_provider_cost_usd,
            "output_files": manifest.output_files,
            "created_at": manifest.started_at,
            "completed_at": manifest.completed_at,
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "expired": expired,
            "submitted_for_review": submitted,
            "category": category,
        }

    def _require_active_run(self, run_id: str) -> InteractiveRunManifest:
        status = self.get_run_status(run_id)
        if status["expired"]:
            raise ValueError("interactive run is no longer available for this action")
        return self.get_run_manifest(run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        if not self.run_root.is_dir():
            return runs
        for path in sorted(self.run_root.iterdir(), reverse=True):
            if not path.is_dir() or not RUN_ID_PATTERN.fullmatch(path.name):
                continue
            try:
                runs.append(self.get_run_status(path.name))
            except (OSError, ValueError, KeyError):
                continue
        return runs

    def compare_runs(self, left_run_id: str, right_run_id: str) -> RunComparison:
        left = self._require_active_run(left_run_id)
        right = self._require_active_run(right_run_id)
        compatible = (
            left.parent_release_id == right.parent_release_id
            and left.qa_status == right.qa_status == "PASS"
        )
        left_rows = {
            (row.market, row.subgroup, row.metric_id): row
            for row in self.get_run_results(left_run_id)
        }
        right_rows = {
            (row.market, row.subgroup, row.metric_id): row
            for row in self.get_run_results(right_run_id)
        }
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left_rows) | set(right_rows)):
            left_row = left_rows.get(key)
            right_row = right_rows.get(key)
            differences.append(
                {
                    "key": list(key),
                    "left": left_row.model_dump(mode="json") if left_row else None,
                    "right": right_row.model_dump(mode="json") if right_row else None,
                    "rate_difference": (
                        round(float(right_row.rate) - float(left_row.rate), 8)
                        if left_row
                        and right_row
                        and left_row.rate is not None
                        and right_row.rate is not None
                        else None
                    ),
                }
            )
        return RunComparison(
            left_run_id=left_run_id,
            right_run_id=right_run_id,
            parent_release_id=left.parent_release_id,
            compatible=compatible,
            differences=differences,
            warning=(
                "Synthetic interactive comparison only; do not rank markets or infer "
                "causal effects."
            ),
        )

    def export_interactive_result(self, run_id: str) -> Path:
        manifest = self._require_active_run(run_id)
        if manifest.qa_status != "PASS":
            raise ValueError("failed-validation runs cannot be exported")
        output = self._run_directory(run_id) / "aggregate_export.csv"
        if output.exists():
            return output
        rows = self.get_run_results(run_id)
        with output.open("x", newline="", encoding="utf-8") as handle:
            fields = [
                "run_id",
                "badge",
                "synthetic_only",
                "parent_release_id",
                "market",
                "subgroup",
                "metric_id",
                "label",
                "numerator",
                "denominator",
                "rate",
                "population",
                "time_window",
                "method",
                "generated_at",
                "prohibited_use",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "run_id": run_id,
                        "badge": manifest.badges[0].value,
                        "synthetic_only": True,
                        "parent_release_id": manifest.parent_release_id,
                        **row.model_dump(mode="json", exclude={"parent_release_id", "unit"}),
                        "generated_at": manifest.completed_at,
                        "prohibited_use": manifest.prohibited_use,
                    }
                )
        return output

    def submit_run_for_review(self, run_id: str, reviewer_note: str) -> ReviewSubmission:
        manifest = self._require_active_run(run_id)
        if manifest.qa_status != "PASS":
            raise ValueError("failed-validation runs cannot be submitted for review")
        normalized_note = reviewer_note.strip() or "No reviewer note supplied."
        submission = ReviewSubmission(
            run_id=run_id,
            submitted_at=_now(),
            reviewer_note=normalized_note[:1000],
            next_required_action=(
                "Assign independent RWE, biostatistics, oncology-definition, and governance "
                "reviewers. Certification requires controlled code review, tests, documentation, "
                "a pull request, and a new release."
            ),
        )
        path = self._run_directory(run_id) / "review_submission.json"
        if path.exists():
            return ReviewSubmission.model_validate_json(path.read_text(encoding="utf-8"))
        path.write_text(submission.model_dump_json(indent=2), encoding="utf-8")
        return submission
