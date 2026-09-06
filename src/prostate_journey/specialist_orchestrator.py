"""Single controlled orchestrator for Explore Tactics and Specialist Analysis."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import yaml

from .ai_evidence_tools import guard_question
from .ai_openai import AIUnavailableError, ModelUsage
from .ai_studio_config import AIStudioSettings
from .specialist_contracts import (
    AnalysisPreview,
    AnalysisSpec,
    AnalysisState,
    EvidenceBadge,
    ExpertLens,
    InteractiveRun,
    LensDefinition,
    PopulationPreview,
    PopulationSlice,
    RequestClassification,
    RequestMode,
    WorkflowEvent,
)
from .specialist_openai import SpecialistPlanningGateway
from .specialist_tools import PROHIBITED_USE, SpecialistAnalysisTools

STATE_ORDER = [
    AnalysisState.UNDERSTAND,
    AnalysisState.RETRIEVE,
    AnalysisState.SELECT_EXPERT_LENS,
    AnalysisState.CREATE_ANALYSIS_SPEC,
    AnalysisState.VALIDATE,
    AnalysisState.ESTIMATE_COST,
    AnalysisState.PREVIEW_PARAMETER_DIFF,
    AnalysisState.PREVIEW_DENOMINATOR,
    AnalysisState.USER_CONFIRMATION,
    AnalysisState.EXECUTE,
    AnalysisState.QA,
    AnalysisState.INTERPRET,
    AnalysisState.EXPORT_OR_SUBMIT,
]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _spec_hash(spec: AnalysisSpec) -> str:
    payload = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class PendingAnalysis:
    question: str
    preview: AnalysisPreview
    provider_cost_usd: float
    provider_usages: list[tuple[str, ModelUsage]]
    executed: bool = False


class SpecialistOrchestrator:
    """Enforce the fixed state machine and explicit confirmation boundary."""

    def __init__(
        self,
        settings: AIStudioSettings,
        tools: SpecialistAnalysisTools,
        *,
        planner: SpecialistPlanningGateway | None = None,
    ) -> None:
        self.settings = settings
        self.tools = tools
        self.planner = planner or SpecialistPlanningGateway(settings)
        self._confirmation_secret = secrets.token_bytes(32)
        self._execution_lock = threading.Lock()
        self.pending: dict[str, PendingAnalysis] = {}
        payload = yaml.safe_load(settings.expert_lenses_path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("orchestrator") != "ONE_CONTROLLED_ORCHESTRATOR"
        ):
            raise ValueError("expert lens registry must declare one controlled orchestrator")
        self.lenses = [LensDefinition.model_validate(item) for item in payload.get("lenses", [])]
        if {item.lens_id for item in self.lenses} != set(ExpertLens):
            raise ValueError("expert lens registry must define all seven governed lenses")

    def context(self) -> dict[str, Any]:
        return {
            "orchestrator": "ONE CONTROLLED ORCHESTRATOR",
            "lenses": [item.model_dump(mode="json") for item in self.lenses],
            "state_machine": [item.value for item in STATE_ORDER],
            "router_model": self.settings.model,
            "specialist_model": self.settings.specialist_model,
            "specialist_reasoning_effort": self.settings.specialist_reasoning_effort,
            "tools": self.tools.tool_contracts(),
            "run_root": self.tools.run_root.relative_to(self.settings.project_root).as_posix(),
            "custom_analysis": "PROPOSED UNVERIFIED ANALYSIS",
            "prohibited_use": PROHIBITED_USE,
        }

    def classify(
        self,
        question: str,
        *,
        selected_lens: ExpertLens,
        tactic_id: str | None,
        use_model: bool,
        idempotency_key: str | None = None,
    ) -> tuple[RequestClassification, ModelUsage]:
        deterministic = self._deterministic_classification(
            question,
            selected_lens=selected_lens,
            tactic_id=tactic_id,
        )
        if deterministic.mode == RequestMode.PROHIBITED_REQUEST:
            return deterministic, ModelUsage()
        if not use_model or not self.planner.configured:
            return deterministic, ModelUsage()
        try:
            candidates = (
                [self.tools.get_tactic_contract(tactic_id)["tactic"]]
                if tactic_id
                else [item for item in self.tools.recommend_tactics(question)[:3]]
            )
            allowed_tactics = [
                {
                    "tactic_id": item["tactic_id"],
                    "title": item["title"],
                    "question": item["question"],
                }
                for item in candidates
            ]
            allowed_parameters = (
                self.tools.get_allowed_parameters(tactic_id)["executable_parameters"]
                if tactic_id
                else {"market": ["ALL", *self.tools.evidence.dashboard_data.get("markets", [])]}
            )
            routed = self.planner.route_request(
                question,
                allowed_tactics=allowed_tactics,
                allowed_parameters=allowed_parameters,
                selected_lens=selected_lens,
                idempotency_key=idempotency_key,
            )
            payload = dict(routed.payload)
            payload["expert_lens"] = selected_lens.value
            payload["routing_source"] = self.settings.model
            model_route = RequestClassification.model_validate(payload)
            known = set(self.tools.evidence.tactics)
            if model_route.tactic_id is not None and model_route.tactic_id not in known:
                return deterministic, routed.usage
            if tactic_id is not None:
                model_route = model_route.model_copy(update={"tactic_id": tactic_id})
            return model_route, routed.usage
        except (AIUnavailableError, ValueError):
            return deterministic, ModelUsage()

    def _deterministic_classification(
        self,
        question: str,
        *,
        selected_lens: ExpertLens,
        tactic_id: str | None,
    ) -> RequestClassification:
        folded = question.casefold()
        prohibited = guard_question(question) or any(
            phrase in folded
            for phrase in (
                "rank markets",
                "best market",
                "worst market",
                "bayer performance",
                "real patients",
                "production recommendation",
            )
        )
        inferred = tactic_id or self._infer_tactic(folded)
        parameters = self._extract_parameters(question, inferred)
        if prohibited:
            mode = RequestMode.PROHIBITED_REQUEST
        elif "run this analysis" in folded or "execute approved" in folded:
            mode = RequestMode.EXECUTE_APPROVED_ANALYSIS
        elif any(word in folded for word in ("compare", "comparison", "versus", " vs ")):
            mode = RequestMode.COMPARE_EXISTING_RESULTS
        elif any(
            phrase in folded
            for phrase in ("new analysis", "custom analysis", "new method", "propose")
        ):
            mode = RequestMode.PROPOSE_NEW_ANALYSIS
        elif inferred and (
            parameters or any(word in folded for word in ("change", "modify", "rerun", "run"))
        ):
            mode = RequestMode.MODIFY_EXISTING_TACTIC
        elif inferred and any(
            word in folded for word in ("explain", "method", "denominator", "why")
        ):
            mode = RequestMode.EXPLAIN_TACTIC
        elif any(word in folded for word in ("recommend", "which tactic", "choose tactic")):
            mode = RequestMode.RECOMMEND_TACTIC
        elif any(word in folded for word in ("artifact", "evidence", "release", "source")):
            mode = RequestMode.ARTIFACT_QUESTION
        elif inferred:
            mode = RequestMode.MODIFY_EXISTING_TACTIC
        else:
            mode = RequestMode.INSUFFICIENT_EVIDENCE
        return RequestClassification(
            mode=mode,
            tactic_id=inferred,
            expert_lens=selected_lens,
            parameter_updates=parameters,
            requires_deep_methodology=mode == RequestMode.PROPOSE_NEW_ANALYSIS,
            rationale=(
                "Deterministic allow-list routing based on the explicit request and "
                "registered tactics."
            ),
            routing_source="deterministic",
        )

    def _infer_tactic(self, text: str) -> str | None:
        aliases = [
            ("persistence_sensitivity", ("persistence", "persistent", "permissible gap")),
            ("initiation_landmarks", ("initiation", "initiated", "treatment start")),
            ("censoring_evaluability", ("censor", "evaluable", "evaluability")),
            ("time_to_initiation", ("time to initiation", "time-to-initiation")),
            ("referral_pathway", ("referral",)),
            ("segmented_treatment_gap", ("care setting", "market scenario", "segment")),
            ("missingness_profile", ("missingness", "missing data", "null")),
            ("model_disposition", ("model", "predictive", "auc", "calibration")),
            ("evidence_governance", ("governance", "lineage", "provenance")),
            ("cohort_definition", ("cohort", "attrition", "eligible")),
        ]
        for tactic, words in aliases:
            if any(word in text for word in words):
                return tactic
        return None

    def _extract_parameters(self, question: str, tactic_id: str | None) -> dict[str, Any]:
        folded = question.casefold()
        values: dict[str, Any] = {}
        market_codes = [str(item) for item in self.tools.evidence.dashboard_data.get("markets", [])]
        selected = [code for code in market_codes if re.search(rf"\b{code.casefold()}\b", folded)]
        if "all markets" in folded or "all scenarios" in folded:
            values["markets"] = market_codes
        elif len(selected) > 1:
            values["markets"] = selected
        elif selected:
            values["market"] = selected[0]
        days = [int(value) for value in re.findall(r"\b(30|60|90)[ -]?(?:day|days|d)\b", folded)]
        if tactic_id == "persistence_sensitivity" and days:
            values["persistence_gap_days"] = days[-1]
        elif (
            tactic_id in {"initiation_landmarks", "time_to_initiation", "segmented_treatment_gap"}
            and days
        ):
            values["initiation_window_days"] = days[-1]
        if "care setting" in folded:
            values["segment"] = "care_setting"
            settings = self.tools.evidence.dashboard_data["segments"]["ALL"].get("settings", [])
            for item in settings:
                slug = re.sub(r"[^a-z0-9]+", "_", str(item["label"]).casefold()).strip("_")
                if str(item["label"]).casefold() in folded or slug.replace("_", " ") in folded:
                    values["care_setting"] = slug
        elif "by market" in folded or "market scenario" in folded:
            values["segment"] = "market"
        return values

    def prepare_preview(
        self,
        question: str,
        *,
        selected_lens: ExpertLens,
        tactic_id: str | None,
        parameters: dict[str, Any],
        remaining_budget_usd: float,
        specialist_mode: bool,
        use_model_router: bool = True,
        request_id: str | None = None,
    ) -> AnalysisPreview:
        normalized = question.strip()
        if len(normalized) < 10:
            raise ValueError("analysis request must contain at least 10 characters")
        request_id = request_id or str(uuid.uuid4())
        classification, usage = self.classify(
            normalized,
            selected_lens=selected_lens,
            tactic_id=tactic_id,
            use_model=use_model_router,
            idempotency_key=f"route:{request_id}",
        )
        if classification.mode == RequestMode.PROHIBITED_REQUEST:
            raise ValueError(PROHIBITED_USE)
        selected_tactic = tactic_id or classification.tactic_id
        if specialist_mode and classification.mode in {
            RequestMode.PROPOSE_NEW_ANALYSIS,
            RequestMode.INSUFFICIENT_EVIDENCE,
        }:
            selected_tactic = None
            classification = classification.model_copy(
                update={
                    "mode": RequestMode.PROPOSE_NEW_ANALYSIS,
                    "tactic_id": None,
                    "requires_deep_methodology": True,
                }
            )
        elif selected_tactic is None:
            recommendations = self.tools.recommend_tactics(normalized)
            if recommendations:
                selected_tactic = str(recommendations[0]["tactic_id"])
                classification = classification.model_copy(
                    update={
                        "mode": RequestMode.MODIFY_EXISTING_TACTIC,
                        "tactic_id": selected_tactic,
                        "requires_deep_methodology": False,
                    }
                )
            else:
                raise ValueError(
                    "No registered tactic supports this request; use Specialist Analysis "
                    "to propose a method."
                )
        merged_parameters = {**classification.parameter_updates, **parameters}
        spec = self.tools.build_spec(
            request_id,
            normalized,
            selected_lens,
            selected_tactic,
            merged_parameters,
        )
        validation = self.tools.validate_analysis_spec(spec)
        requires_plan = spec.new_proposal
        cost = self.tools.estimate_analysis_cost(
            spec,
            remaining_budget_usd=max(0.0, remaining_budget_usd - usage.estimated_cost_usd),
            specialist_plan_required=requires_plan,
        )
        diff = self.tools.parameter_diff(spec)
        try:
            population = self.tools.preview_population(spec)
        except (KeyError, StopIteration, TypeError, ValueError):
            population = PopulationPreview(
                denominator_changed=False,
                previous_denominator=None,
                current_denominator=0,
                reason="A denominator preview is unavailable because the specification is invalid.",
                slices=[
                    PopulationSlice(
                        market=spec.markets[0],
                        population=spec.target_population,
                        numerator=0,
                        denominator=0,
                        excluded=0,
                        censored=0,
                        time_zero=spec.index_date_time_zero,
                        evaluability="Validation must pass before execution.",
                    )
                ],
            )
        token = None
        if validation.valid and cost.within_budget and not requires_plan:
            token = self._token(spec)
        workflow = self._preview_workflow(
            selected_lens,
            validation.valid,
            cost.within_budget,
            requires_plan,
        )
        badges = [
            EvidenceBadge.PROPOSED_METHOD if spec.new_proposal else EvidenceBadge.INTERACTIVE_RERUN,
            EvidenceBadge.REQUIRES_SME_REVIEW,
        ]
        preview = AnalysisPreview(
            request_id=request_id,
            classification=classification,
            spec=spec,
            validation=validation,
            cost_estimate=cost,
            parameter_diff=diff,
            population_preview=population,
            workflow=workflow,
            confirmation_token=token,
            requires_specialist_plan=requires_plan,
            badges=badges,
            warning=(
                "PROPOSED UNVERIFIED ANALYSIS. Confirm the displayed Terra planning "
                "ceiling before method planning."
                if requires_plan
                else "INTERACTIVE RE-RUN. This cannot overwrite or certify the parent release."
            ),
        )
        self.pending[request_id] = PendingAnalysis(
            question=normalized,
            preview=preview,
            provider_cost_usd=usage.estimated_cost_usd,
            provider_usages=([("specialist_router", usage)] if usage.input_tokens else []),
        )
        return preview

    def plan_specialist(
        self,
        request_id: str,
        *,
        budget_confirmed: bool,
        remaining_budget_usd: float,
    ) -> tuple[AnalysisPreview, float]:
        pending = self._pending(request_id)
        if not pending.preview.requires_specialist_plan:
            raise ValueError("this request does not require Terra specialist planning")
        ceiling = pending.preview.cost_estimate.maximum_planning_cost_usd
        if not budget_confirmed or remaining_budget_usd < ceiling:
            raise ValueError("specialist planning cost ceiling was not explicitly accepted")
        result = self.planner.plan_specialist_analysis(
            pending.question,
            pending.preview.spec,
            budget_confirmed=True,
            idempotency_key=f"plan:{request_id}",
        )
        plan = result.payload
        spec = pending.preview.spec.model_copy(
            update={
                "assumptions": list(
                    dict.fromkeys([*pending.preview.spec.assumptions, *plan["assumptions"]])
                ),
                "validation_checks": list(
                    dict.fromkeys(
                        [*pending.preview.spec.validation_checks, *plan["validation_checks"]]
                    )
                ),
                "sme_review_requirements": list(
                    dict.fromkeys(
                        [
                            *pending.preview.spec.sme_review_requirements,
                            *plan["sme_review_requirements"],
                        ]
                    )
                ),
                "parameters": {**pending.preview.spec.parameters, "approved_specialist_plan": plan},
            }
        )
        validation = self.tools.validate_analysis_spec(spec)
        token = self._token(spec) if validation.valid else None
        preview = pending.preview.model_copy(
            update={
                "spec": spec,
                "validation": validation,
                "confirmation_token": token,
                "requires_specialist_plan": False,
                "workflow": self._preview_workflow(
                    spec.expert_lens,
                    validation.valid,
                    True,
                    False,
                ),
                "warning": (
                    "PROPOSED UNVERIFIED ANALYSIS. Terra planned methodology; only the "
                    "constrained declarative sandbox can execute."
                ),
            }
        )
        pending.preview = preview
        pending.provider_cost_usd += result.usage.estimated_cost_usd
        pending.provider_usages.append(("specialist_planning", result.usage))
        return preview, result.usage.estimated_cost_usd

    def execute(
        self,
        request_id: str,
        *,
        confirmation_token: str,
        confirmation_text: str,
        use_model_summary: bool = True,
    ) -> InteractiveRun:
        pending = self._pending(request_id)
        preview = pending.preview
        with self._execution_lock:
            if pending.executed:
                raise ValueError("analysis confirmation token has already been used")
            if confirmation_text != "RUN THIS ANALYSIS":
                raise ValueError("explicit RUN THIS ANALYSIS confirmation is required")
            if preview.requires_specialist_plan or not preview.validation.valid:
                raise ValueError("analysis is not ready for execution")
            expected = self._token(preview.spec)
            if not hmac.compare_digest(confirmation_token, expected):
                raise ValueError(
                    "confirmation token does not match the validated analysis specification"
                )
            if preview.confirmation_token != confirmation_token:
                raise ValueError("analysis parameters changed after preview")
            pending.executed = True
        workflow = [
            *[
                event.model_copy(update={"status": "COMPLETE"})
                if event.state == AnalysisState.USER_CONFIRMATION
                else event
                for event in preview.workflow
            ],
            WorkflowEvent(
                state=AnalysisState.EXECUTE,
                occurred_at=_now(),
                status="COMPLETE",
                detail="Explicit confirmation accepted; isolated aggregate execution started.",
            ),
        ]
        if preview.spec.new_proposal:
            run = self.tools.run_sandbox_analysis(
                preview.spec,
                user_request=pending.question,
                parameter_diff=preview.parameter_diff,
                workflow=workflow,
                actual_provider_cost_usd=pending.provider_cost_usd,
            )
        else:
            run = self.tools.run_registered_analysis(
                preview.spec,
                user_request=pending.question,
                parameter_diff=preview.parameter_diff,
                workflow=workflow,
                actual_provider_cost_usd=pending.provider_cost_usd,
            )
        if run.qa.status != "PASS" or not use_model_summary or not self.planner.configured:
            return run
        try:
            summary = self.planner.summarize_results(
                run.spec,
                run.results,
                idempotency_key=f"summary:{request_id}",
            )
        except (AIUnavailableError, ValueError):
            return run
        pending.provider_cost_usd += summary.usage.estimated_cost_usd
        pending.provider_usages.append(("specialist_summary", summary.usage))
        return self.tools.finalize_model_summary(
            run,
            summary.payload,
            total_provider_cost_usd=pending.provider_cost_usd,
        )

    def provider_cost(self, request_id: str) -> float:
        return self._pending(request_id).provider_cost_usd

    def provider_usages(self, request_id: str) -> list[tuple[str, ModelUsage]]:
        return list(self._pending(request_id).provider_usages)

    def _pending(self, request_id: str) -> PendingAnalysis:
        try:
            return self.pending[request_id]
        except KeyError as error:
            raise KeyError("unknown or expired specialist request") from error

    def _token(self, spec: AnalysisSpec) -> str:
        return hmac.new(
            self._confirmation_secret, _spec_hash(spec).encode("ascii"), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _preview_workflow(
        lens: ExpertLens,
        valid: bool,
        within_budget: bool,
        requires_plan: bool,
    ) -> list[WorkflowEvent]:
        details = {
            AnalysisState.UNDERSTAND: "Request classified into exactly one governed mode.",
            AnalysisState.RETRIEVE: (
                "Canonical tactic and release-scoped aggregate contracts retrieved."
            ),
            AnalysisState.SELECT_EXPERT_LENS: f"Selected expert lens: {lens.value}.",
            AnalysisState.CREATE_ANALYSIS_SPEC: (
                "Strict AnalysisSpec created with explicit denominator, time zero, "
                "outcome, and event hierarchy."
            ),
            AnalysisState.VALIDATE: "Specification validation completed.",
            AnalysisState.ESTIMATE_COST: "Runtime and provider ceiling estimated before execution.",
            AnalysisState.PREVIEW_PARAMETER_DIFF: (
                "Exact certified-to-proposed parameter diff generated."
            ),
            AnalysisState.PREVIEW_DENOMINATOR: (
                "Population, exclusions, evaluability, censoring, and denominator "
                "preview generated."
            ),
            AnalysisState.USER_CONFIRMATION: (
                "Confirm Terra method-planning ceiling first."
                if requires_plan
                else "Waiting for the exact RUN THIS ANALYSIS action."
            ),
        }
        events: list[WorkflowEvent] = []
        for state in STATE_ORDER[:9]:
            status: Literal["COMPLETE", "WAITING", "FAILED"] = "COMPLETE"
            if state == AnalysisState.VALIDATE and not valid:
                status = "FAILED"
            elif state == AnalysisState.ESTIMATE_COST and not within_budget:
                status = "FAILED"
            elif state == AnalysisState.USER_CONFIRMATION:
                status = "WAITING" if valid and within_budget else "FAILED"
            events.append(
                WorkflowEvent(
                    state=state,
                    occurred_at=_now(),
                    status=status,
                    detail=details[state],
                )
            )
        return events
