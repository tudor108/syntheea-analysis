"""Independent, read-only AI Analysis Studio HTTP service."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import posixpath
import secrets
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import PurePosixPath
from types import FrameType
from typing import Any, Literal
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .ai_artifact_catalog import (
    ArtifactCatalogue,
    build_artifact_catalogue,
)
from .ai_client import AIProviderClient, provider_failure_category
from .ai_evidence_tools import EvidenceTools, guard_question
from .ai_finops import (
    AtomicBudgetLedger,
    BudgetExceededError,
    CostBreakdown,
    CostCalculator,
    DuplicateRequestError,
    Reservation,
    SafeAuditLog,
    SessionExpiredError,
    SlidingWindowRateLimiter,
    load_cost_controls,
    redact_sensitive,
)
from .ai_openai import (
    AIUnavailableError,
    EvidenceAnswer,
    GatewayResult,
    ModelUsage,
    OpenAIEvidenceGateway,
    blocked_answer,
)
from .ai_studio_config import AIStudioSettings
from .specialist_contracts import ExpertLens
from .specialist_openai import SpecialistPlanningGateway
from .specialist_orchestrator import SpecialistOrchestrator
from .specialist_tools import SpecialistAnalysisTools

LOGGER = logging.getLogger(__name__)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    question: str
    market: str = "ALL"
    tactic_id: str | None = None
    source_filter: Literal["ALL", "AGGREGATE", "METHODOLOGY", "GOVERNANCE"] = "ALL"
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()), pattern=r"^[a-f0-9-]{36}$"
    )

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question cannot be blank")
        return normalized

    @field_validator("market")
    @classmethod
    def _market(cls, value: str) -> str:
        normalized = value.upper()
        if normalized != "ALL" and (
            len(normalized) != 2 or not normalized.isascii() or not normalized.isalpha()
        ):
            raise ValueError("market must be ALL or a two-letter configured scenario")
        return normalized


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class SpecialistPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    question: str = Field(min_length=10, max_length=2400)
    expert_lens: ExpertLens
    tactic_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    specialist_mode: bool = False
    use_model_router: bool = True
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()), pattern=r"^[a-f0-9-]{36}$"
    )


class SpecialistPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    request_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    accept_estimated_cost: bool


class SpecialistExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    request_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    confirmation_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation: str
    use_model_summary: bool = False


class RunComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    left_run_id: str = Field(pattern=r"^iar_[a-f0-9]{20}$")
    right_run_id: str = Field(pattern=r"^iar_[a-f0-9]{20}$")


class ReviewSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    run_id: str = Field(pattern=r"^iar_[a-f0-9]{20}$")
    reviewer_note: str = Field(default="", max_length=1000)


@dataclass
class ConversationSession:
    session_id: str
    csrf_token: str
    user_id: str | None = None
    title: str = "New evidence conversation"
    turns: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""

    def add_turn(
        self,
        question: str,
        answer: EvidenceAnswer,
        *,
        memory_turns: int,
        summary_limit: int,
    ) -> None:
        if self.title == "New evidence conversation":
            words = question.split()
            self.title = " ".join(words[:7])[:80]
        self.turns.append(
            {
                "question": question[:600],
                "answer": answer.direct_answer[:900],
                "status": answer.evidence_status,
            }
        )
        while len(self.turns) > memory_turns:
            old = self.turns.pop(0)
            addition = f"Q: {old['question']} A-status: {old['status']} A: {old['answer'][:300]}\n"
            self.summary = (self.summary + addition)[-summary_limit:]


class SessionStore:
    def __init__(self, ledger: AtomicBudgetLedger) -> None:
        self.ledger = ledger
        self.sessions: dict[str, ConversationSession] = {}
        self.lock = threading.Lock()

    def create(self, *, user_id: str | None = None) -> ConversationSession:
        with self.lock:
            session = ConversationSession(
                str(uuid.uuid4()), secrets.token_urlsafe(32), user_id=user_id
            )
            self.ledger.create_session(session.session_id, user_id=user_id)
            self.sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> ConversationSession:
        with self.lock:
            try:
                session = self.sessions[session_id]
            except KeyError as error:
                raise KeyError("unknown or expired session") from error
        self.ledger.session_snapshot(session_id)
        return session

    def reset(self, session_id: str) -> ConversationSession:
        with self.lock:
            if session_id not in self.sessions:
                raise KeyError("unknown or expired session")
            prior = self.sessions.pop(session_id)
            self.ledger.expire_session(session_id)
        return self.create(user_id=prior.user_id)

    def public(self, session: ConversationSession) -> dict[str, Any]:
        return {
            **self.ledger.session_snapshot(session.session_id),
            "title": session.title,
            "turn_count": len(session.turns),
            "csrf_token": session.csrf_token,
        }


class AIStudioRuntime:
    """Verified catalogue, deterministic tools, optional OpenAI, and bounded sessions."""

    def __init__(
        self,
        settings: AIStudioSettings,
        *,
        catalogue: ArtifactCatalogue | None = None,
        tools: EvidenceTools | None = None,
        gateway: Any | None = None,
    ) -> None:
        self.settings = settings
        self.started = time.monotonic()
        self.run_id = str(uuid.uuid4())
        root = settings.project_root.resolve()
        controls_path = settings.cost_controls_path
        controls_path = (
            controls_path if controls_path.is_absolute() else (root / controls_path).resolve()
        )
        self.cost_controls = load_cost_controls(controls_path)
        if (
            settings.specialist_max_disk_bytes
            > self.cost_controls.security_limits.max_sandbox_disk_bytes
        ):
            raise ValueError("specialist disk quota exceeds the central security limit")
        self.calculator = CostCalculator(self.cost_controls)
        ledger_path = settings.budget_ledger_path
        ledger_path = ledger_path if ledger_path.is_absolute() else (root / ledger_path).resolve()
        audit_path = settings.audit_log_path
        audit_path = audit_path if audit_path.is_absolute() else (root / audit_path).resolve()
        self.ledger = AtomicBudgetLedger(ledger_path, self.cost_controls)
        self.audit = SafeAuditLog(
            audit_path,
            max_field_characters=self.cost_controls.security_limits.audit_log_max_field_characters,
        )
        self.rate_limiter = SlidingWindowRateLimiter(
            requests=self.cost_controls.security_limits.rate_limit_requests,
            window_seconds=self.cost_controls.security_limits.rate_limit_window_seconds,
        )
        self.provider = AIProviderClient(
            settings,
            retry_initial_backoff_seconds=(
                self.cost_controls.security_limits.retry_initial_backoff_seconds
            ),
            maximum_attempts=self.cost_controls.security_limits.retry_max_attempts,
        )
        if catalogue is None:
            # Resolve the currently selected certified package on every startup;
            # never trust a stale local catalogue as the active release selector.
            catalogue = build_artifact_catalogue(settings.project_root, settings)
        self.catalogue = catalogue
        self.tools = tools or EvidenceTools(settings.project_root, catalogue)
        self.gateway = gateway or OpenAIEvidenceGateway(
            settings,
            catalogue,
            provider=self.provider,
            calculator=self.calculator,
        )
        self.sessions = SessionStore(self.ledger)
        self.specialist_tools: SpecialistAnalysisTools | None = None
        self.specialist: SpecialistOrchestrator | None = None
        analysis_registry = settings.analysis_registry_path
        lens_registry = settings.expert_lenses_path
        analysis_registry = (
            analysis_registry
            if analysis_registry.is_absolute()
            else (root / analysis_registry).resolve()
        )
        lens_registry = (
            lens_registry if lens_registry.is_absolute() else (root / lens_registry).resolve()
        )
        run_root = settings.interactive_runs_directory
        run_root = run_root if run_root.is_absolute() else (root / run_root).resolve()
        if analysis_registry.is_file() and lens_registry.is_file():
            specialist_settings = settings.model_copy(
                update={
                    "analysis_registry_path": analysis_registry,
                    "expert_lenses_path": lens_registry,
                    "interactive_runs_directory": run_root,
                    "cost_controls_path": controls_path,
                }
            )
            self.specialist_tools = SpecialistAnalysisTools(specialist_settings, self.tools)
            self.specialist = SpecialistOrchestrator(
                specialist_settings,
                self.specialist_tools,
                planner=SpecialistPlanningGateway(
                    specialist_settings,
                    provider=self.provider,
                    calculator=self.calculator,
                ),
            )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": self.settings.service_name,
            "run_id": self.run_id,
            "uptime_seconds": round(time.monotonic() - self.started, 3),
            "synthetic_only": True,
            "analytics_dependency": False,
            "budget_ledger": "ready",
        }

    def ready(self) -> dict[str, Any]:
        vector_ready = (
            bool(self.gateway._vector_store_id())
            if hasattr(self.gateway, "_vector_store_id")
            else False
        )
        return {
            "status": "ready",
            "feature_enabled": self.settings.enabled,
            "service": self.settings.service_name,
            "release_id": self.catalogue.release_id,
            "catalogue_status": "verified",
            "catalogued_artifacts": len(self.catalogue.artifacts),
            "indexable_artifacts": sum(item.indexable for item in self.catalogue.artifacts),
            "openai_configured": bool(getattr(self.gateway, "configured", False)),
            "vector_search_configured": vector_ready,
            "model": self.settings.model,
            "mode": "ASK THE EVIDENCE — READ ONLY",
            "specialist_analysis_enabled": self.specialist is not None,
            "cost_controls": {
                "schema_version": self.cost_controls.schema_version,
                "pricing_effective_date": self.cost_controls.effective_date,
                "session_warning_usd": float(
                    self.cost_controls.budgets.interactive_session.warning_usd
                ),
                "specialist_soft_stop_usd": float(
                    self.cost_controls.budgets.interactive_session.specialist_soft_stop_usd
                ),
                "session_hard_stop_usd": float(
                    self.cost_controls.budgets.interactive_session.hard_stop_usd
                ),
                "live_eval_hard_stop_usd": float(
                    self.cost_controls.budgets.live_eval_run.hard_stop_usd
                ),
            },
            "synthetic_only": True,
        }

    def context(self) -> dict[str, Any]:
        return {
            **self.ready(),
            "markets": ["ALL", *self.tools.dashboard_data.get("markets", [])],
            "analytics_url": self.settings.analytics_url,
            "tool_contracts": self.tools.tool_contracts(),
            "prohibited_use": (
                "No clinical decisions, treatment recommendations, patient action, "
                "market ranking, causal claims, commercial conclusions, real population "
                "estimates, or production AI."
            ),
            "specialist": self.specialist.context() if self.specialist else None,
        }

    def require_specialist(self) -> tuple[SpecialistOrchestrator, SpecialistAnalysisTools]:
        if self.specialist is None or self.specialist_tools is None:
            raise ValueError("Specialist Analysis configuration is unavailable.")
        return self.specialist, self.specialist_tools

    def session_public(self, session: ConversationSession) -> dict[str, Any]:
        return self.sessions.public(session)

    def _reserve(
        self,
        session: ConversationSession,
        *,
        profile: str,
        idempotency_key: str,
        live_eval_id: str | None = None,
        specialist_run_id: str | None = None,
    ) -> Reservation:
        estimate = self.calculator.estimate_maximum(profile)
        reservation = self.ledger.reserve(
            session.session_id,
            idempotency_key=idempotency_key,
            profile=profile,
            estimated=estimate,
            live_eval_id=live_eval_id,
            specialist_run_id=specialist_run_id,
        )
        self.audit.write(
            "budget_reserved",
            request_id=idempotency_key,
            session_id_hash=self.audit.session_hash(session.session_id),
            release_id=self.catalogue.release_id,
            profile=profile,
            model_id=estimate.model_id,
            status="RESERVED",
            reserved_cost_usd=float(reservation.reserved_cost_usd),
        )
        return reservation

    def _usage_cost(
        self,
        profile: str,
        usage: ModelUsage,
        *,
        file_search_calls: int,
        deterministic_tool_calls: int,
    ) -> CostBreakdown:
        iterations = usage.model_iterations if usage.input_tokens or usage.output_tokens else 0
        return self.calculator.actual(
            profile,
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            output_tokens=usage.output_tokens,
            file_search_calls=file_search_calls,
            deterministic_tool_calls=deterministic_tool_calls,
            model_iterations=iterations,
        )

    def _reconcile(
        self,
        reservation: Reservation,
        *,
        actual: CostBreakdown | None,
        started: float,
        failure: bool = False,
        error_category: str | None = None,
    ) -> float:
        latency_ms = int((time.monotonic() - started) * 1000)
        charged = self.ledger.reconcile(
            reservation.reservation_id,
            actual=actual,
            latency_ms=latency_ms,
            failure=failure,
        )
        self.audit.write(
            "budget_reconciled",
            request_id=reservation.idempotency_key,
            session_id_hash=self.audit.session_hash(reservation.session_id),
            release_id=self.catalogue.release_id,
            profile=reservation.profile,
            model_id=actual.model_id if actual else None,
            status="FAILED_CONSERVATIVE" if failure and actual is None else "COMPLETED",
            error_category=error_category,
            actual_cost_usd=float(charged),
            latency_ms=latency_ms,
            input_tokens=actual.input_tokens if actual else 0,
            cached_input_tokens=actual.cached_input_tokens if actual else 0,
            cache_write_tokens=actual.cache_write_tokens if actual else 0,
            output_tokens=actual.output_tokens if actual else 0,
            file_search_calls=actual.file_search_calls if actual else 0,
            deterministic_tool_calls=actual.deterministic_tool_calls if actual else 0,
        )
        return float(charged)

    def preview_specialist(self, request: SpecialistPreviewRequest) -> dict[str, Any]:
        specialist, _ = self.require_specialist()
        session = self.sessions.get(request.session_id)
        snapshot = self.ledger.session_snapshot(session.session_id)
        if snapshot["specialist_soft_stop_active"]:
            raise BudgetExceededError(
                "new specialist work is disabled at the session soft-stop threshold"
            )
        request_id = str(uuid.uuid4())
        reservation: Reservation | None = None
        started = time.monotonic()
        use_model = request.use_model_router and specialist.planner.configured
        if use_model:
            reservation = self._reserve(
                session,
                profile="specialist_router",
                idempotency_key=f"preview:{request.idempotency_key}",
                specialist_run_id=request_id,
            )
        try:
            preview = specialist.prepare_preview(
                request.question,
                selected_lens=request.expert_lens,
                tactic_id=request.tactic_id,
                parameters=request.parameters,
                remaining_budget_usd=float(snapshot["remaining_budget_usd"]),
                specialist_mode=request.specialist_mode,
                use_model_router=use_model,
                request_id=request_id,
            )
        except Exception as error:
            if reservation:
                self._reconcile(
                    reservation,
                    actual=None,
                    started=started,
                    failure=True,
                    error_category=provider_failure_category(error),
                )
            raise
        if reservation:
            usages = specialist.provider_usages(request_id)
            if usages:
                self._reconcile(
                    reservation,
                    actual=self._usage_cost(
                        "specialist_router",
                        usages[-1][1],
                        file_search_calls=0,
                        deterministic_tool_calls=2,
                    ),
                    started=started,
                )
            else:
                self._reconcile(reservation, actual=None, started=started, failure=True)
        return {
            "preview": preview.model_dump(mode="json"),
            "session": self.session_public(session),
        }

    def plan_specialist(self, request: SpecialistPlanRequest) -> dict[str, Any]:
        specialist, _ = self.require_specialist()
        session = self.sessions.get(request.session_id)
        snapshot = self.ledger.session_snapshot(session.session_id)
        reservation = self._reserve(
            session,
            profile="specialist_planning",
            idempotency_key=f"plan:{request.request_id}",
            specialist_run_id=request.request_id,
        )
        started = time.monotonic()
        usages_before = len(specialist.provider_usages(request.request_id))
        try:
            preview, _ = specialist.plan_specialist(
                request.request_id,
                budget_confirmed=request.accept_estimated_cost,
                remaining_budget_usd=float(snapshot["remaining_budget_usd"]),
            )
        except Exception as error:
            self._reconcile(
                reservation,
                actual=None,
                started=started,
                failure=True,
                error_category=provider_failure_category(error),
            )
            raise
        usages = specialist.provider_usages(request.request_id)[usages_before:]
        if usages:
            profile_name, usage = usages[-1]
            self._reconcile(
                reservation,
                actual=self._usage_cost(
                    profile_name,
                    usage,
                    file_search_calls=0,
                    deterministic_tool_calls=6,
                ),
                started=started,
            )
        else:
            self._reconcile(reservation, actual=None, started=started, failure=True)
        return {
            "preview": preview.model_dump(mode="json"),
            "session": self.session_public(session),
        }

    def execute_specialist(self, request: SpecialistExecuteRequest) -> dict[str, Any]:
        specialist, _ = self.require_specialist()
        session = self.sessions.get(request.session_id)
        reserve_summary = request.use_model_summary and specialist.planner.configured
        reservation = (
            self._reserve(
                session,
                profile="specialist_summary",
                idempotency_key=f"summary:{request.request_id}",
                specialist_run_id=request.request_id,
            )
            if reserve_summary
            else None
        )
        started = time.monotonic()
        usages_before = len(specialist.provider_usages(request.request_id))
        try:
            run = specialist.execute(
                request.request_id,
                confirmation_token=request.confirmation_token,
                confirmation_text=request.confirmation,
                use_model_summary=request.use_model_summary,
            )
        except (KeyError, ValueError):
            if reservation:
                self._reconcile(
                    reservation,
                    actual=self.calculator.actual(
                        "specialist_summary",
                        input_tokens=0,
                        cached_input_tokens=0,
                        cache_write_tokens=0,
                        output_tokens=0,
                        file_search_calls=0,
                        deterministic_tool_calls=1,
                        model_iterations=0,
                    ),
                    started=started,
                    failure=True,
                    error_category="validation_failure",
                )
            raise
        except Exception as error:
            if reservation:
                self._reconcile(
                    reservation,
                    actual=None,
                    started=started,
                    failure=True,
                    error_category=provider_failure_category(error),
                )
            raise
        if reservation:
            usages = specialist.provider_usages(request.request_id)[usages_before:]
            if usages:
                profile_name, usage = usages[-1]
                self._reconcile(
                    reservation,
                    actual=self._usage_cost(
                        profile_name,
                        usage,
                        file_search_calls=0,
                        deterministic_tool_calls=2,
                    ),
                    started=started,
                )
            elif run.qa.status == "PASS":
                # A QA-passed run attempts the optional provider summary. If that call
                # fails before metered usage is returned, keep the full reservation.
                self._reconcile(
                    reservation,
                    actual=None,
                    started=started,
                    failure=True,
                    error_category="provider_summary_unavailable",
                )
            else:
                self._reconcile(
                    reservation,
                    actual=self.calculator.actual(
                        "specialist_summary",
                        input_tokens=0,
                        cached_input_tokens=0,
                        cache_write_tokens=0,
                        output_tokens=0,
                        file_search_calls=0,
                        deterministic_tool_calls=1,
                        model_iterations=0,
                    ),
                    started=started,
                    failure=True,
                    error_category="qa_failure",
                )
        self.audit.write(
            "specialist_local_compute",
            request_id=request.request_id,
            session_id_hash=self.audit.session_hash(session.session_id),
            release_id=self.catalogue.release_id,
            status=run.qa.status,
            local_compute_ms=int((time.monotonic() - started) * 1000),
        )
        return {
            "run": run.model_dump(mode="json"),
            "session": self.session_public(session),
        }

    def ask(
        self,
        request: AskRequest,
        *,
        profile_name: str = "evidence",
        live_eval_id: str | None = None,
    ) -> GatewayResult:
        if len(request.question) > self.settings.max_question_characters:
            raise ValueError("question exceeds configured character limit")
        session = self.sessions.get(request.session_id)
        category = guard_question(request.question)
        if category:
            answer = blocked_answer(
                self.catalogue.release_id,
                request.question,
                category,
                market=request.market,
            )
            session.add_turn(
                request.question,
                answer,
                memory_turns=self.settings.memory_turns,
                summary_limit=self.settings.summary_character_limit,
            )
            return GatewayResult(answer=answer, usage=ModelUsage())

        question = request.question
        if request.tactic_id:
            self.tools.get_tactic_card(request.tactic_id)
            question = f"{question}\nRelevant tactic_id: {request.tactic_id}"
        profile = self.cost_controls.request_profiles[profile_name]
        packet = self.tools.build_grounding(
            question,
            market=request.market,
            top_k=profile.max_retrieved_chunks,
        )
        allowed_types: set[str] | None = None
        if request.source_filter != "ALL":
            allowed_types = {
                "AGGREGATE": {"aggregate_table"},
                "METHODOLOGY": {"methodology", "model_card"},
                "GOVERNANCE": {
                    "governance_configuration",
                    "manifest",
                    "qa",
                    "tactic_registry",
                },
            }[request.source_filter]
            filtered_results = [
                item
                for item in self.tools.search_certified_artifacts(question, top_k=10)
                if item.artifact_type in allowed_types
            ][: profile.max_retrieved_chunks]
            metrics = packet.metrics if request.source_filter == "AGGREGATE" else []
            tactics = packet.tactics if request.source_filter == "METHODOLOGY" else []
            packet = packet.model_copy(
                update={
                    "metrics": metrics,
                    "tactics": tactics,
                    "narrative_results": filtered_results,
                    "evidence_sufficient": bool(metrics or tactics or filtered_results),
                    "allowed_numbers": (
                        packet.allowed_numbers if request.source_filter == "AGGREGATE" else []
                    ),
                }
            )
        reservation = self._reserve(
            session,
            profile=profile_name,
            idempotency_key=f"evidence:{request.idempotency_key}",
            live_eval_id=live_eval_id,
        )
        started = time.monotonic()
        file_search_calls = 0
        try:
            vector_configured = bool(
                self.gateway._vector_store_id()
                if hasattr(self.gateway, "_vector_store_id")
                else False
            )
            if vector_configured:
                file_search_calls = 1
            remote = self.gateway.search_file_store(question)
            if allowed_types is not None:
                remote = [item for item in remote if item.artifact_type in allowed_types]
            if remote:
                remote_ids = {item.artifact_id for item in remote}
                merged = [
                    *remote,
                    *(
                        item
                        for item in packet.narrative_results
                        if item.artifact_id not in remote_ids
                    ),
                ]
                packet = packet.model_copy(
                    update={"narrative_results": merged[: self.settings.retrieval_top_k]}
                )
            result = self.gateway.generate(
                packet,
                market=request.market,
                recent_turns=session.turns,
                conversation_summary=session.summary,
                idempotency_key=f"evidence:{request.idempotency_key}",
                profile_name=profile_name,
            )
        except Exception as error:
            self._reconcile(
                reservation,
                actual=None,
                started=started,
                failure=True,
                error_category=provider_failure_category(error),
            )
            raise
        actual = self._usage_cost(
            profile_name,
            result.usage,
            file_search_calls=file_search_calls,
            deterministic_tool_calls=3,
        )
        result.usage.estimated_cost_usd = self._reconcile(
            reservation,
            actual=actual,
            started=started,
        )
        session.add_turn(
            request.question,
            result.answer,
            memory_turns=self.settings.memory_turns,
            summary_limit=self.settings.summary_character_limit,
        )
        return result


class AIStudioRequestHandler(BaseHTTPRequestHandler):
    """Serve the isolated frontend and a small same-origin JSON/SSE API."""

    server_version = "ProstateJourneyAIStudio/1.0"
    sys_version = ""
    runtime: AIStudioRuntime

    def _request_id(self) -> str:
        value = getattr(self, "_correlation_id", None)
        if value is None:
            value = str(uuid.uuid4())
            self._correlation_id = value
        return value

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in self.runtime.settings.allowed_origins

    def _authenticate(self) -> str | None:
        if self.runtime.settings.authentication_mode == "local":
            return None
        configured = self.runtime.settings.access_token
        header = self.headers.get("Authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        expected = configured.get_secret_value() if configured else ""
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise PermissionError("authentication required")
        return hashlib.sha256(supplied.encode()).hexdigest()[:24]

    def _enforce_request_boundary(self) -> str | None:
        if not self._origin_allowed():
            raise PermissionError("origin is not allowed")
        user_id = self._authenticate()
        client = user_id or self.client_address[0]
        if not self.runtime.rate_limiter.allow(client):
            raise RuntimeError("rate limit exceeded")
        return user_id

    def _require_csrf(self, session_id: str) -> ConversationSession:
        session = self.runtime.sessions.get(session_id)
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
            raise PermissionError("CSRF validation failed")
        return session

    def _normalized_path(self) -> str | None:
        raw = unquote(urlsplit(self.path).path)
        normalized = posixpath.normpath(raw).lstrip("/")
        candidate = PurePosixPath(normalized)
        if normalized in {"", "."}:
            return ""
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        return candidate.as_posix()

    def _write_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _write_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid content length") from error
        maximum = self.runtime.cost_controls.security_limits.max_request_bytes
        if length > maximum:
            # Drain at most one bounded body so ordinary clients receive the
            # explicit rejection without permitting unbounded allocation.
            self.rfile.read(maximum + 1)
            self.close_connection = True
            raise ValueError("request body size is invalid")
        if length <= 0:
            raise ValueError("request body size is invalid")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise ValueError("request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("request body must be one JSON object")
        return payload

    def _write_asset(self, filename: str, content_type: str) -> None:
        body = files("prostate_journey").joinpath("frontend", filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self._normalized_path()
        if path is None:
            self._write_json(HTTPStatus.BAD_REQUEST, {"status": "invalid_path"})
            return
        if path in {"", "ai_studio.html"}:
            self._write_asset("ai_studio.html", "text/html; charset=utf-8")
            return
        if path == "assets/ai_studio.css":
            self._write_asset("ai_studio.css", "text/css; charset=utf-8")
            return
        if path == "assets/ai_studio.js":
            self._write_asset("ai_studio.js", "text/javascript; charset=utf-8")
            return
        try:
            self._enforce_request_boundary()
        except PermissionError:
            self._write_json(HTTPStatus.UNAUTHORIZED, {"status": "unauthorized"})
            return
        except RuntimeError:
            self._write_json(HTTPStatus.TOO_MANY_REQUESTS, {"status": "rate_limited"})
            return
        if path == "health":
            self._write_json(HTTPStatus.OK, self.runtime.health())
            return
        if path == "ready":
            self._write_json(HTTPStatus.OK, self.runtime.ready())
            return
        if path == "api/context":
            self._write_json(HTTPStatus.OK, self.runtime.context())
            return
        if path == "api/cost":
            query = parse_qs(urlsplit(self.path).query)
            session_id = str(query.get("session_id", [""])[0])
            try:
                self.runtime.sessions.get(session_id)
                self._write_json(
                    HTTPStatus.OK,
                    self.runtime.ledger.dashboard(session_id),
                )
            except (KeyError, SessionExpiredError):
                self._write_json(HTTPStatus.GONE, {"status": "session_expired"})
            return
        if path == "api/tactics":
            tactics = (
                self.runtime.specialist_tools.list_tactics()
                if self.runtime.specialist_tools
                else self.runtime.tools.list_available_tactics()
            )
            self._write_json(
                HTTPStatus.OK,
                {"tactics": tactics},
            )
            return
        if path == "api/specialist/context":
            specialist, _ = self.runtime.require_specialist()
            self._write_json(HTTPStatus.OK, specialist.context())
            return
        if path == "api/specialist/runs":
            _, tools = self.runtime.require_specialist()
            self._write_json(HTTPStatus.OK, {"runs": tools.list_runs()})
            return
        if path and path.startswith("api/specialist/tactics/"):
            tactic_id = path.removeprefix("api/specialist/tactics/")
            _, tools = self.runtime.require_specialist()
            self._write_json(HTTPStatus.OK, tools.get_tactic_contract(tactic_id))
            return
        if path and path.startswith("api/specialist/runs/"):
            suffix = path.removeprefix("api/specialist/runs/")
            _, tools = self.runtime.require_specialist()
            try:
                if suffix.endswith("/export"):
                    run_id = suffix.removesuffix("/export")
                    export = tools.export_interactive_result(run_id)
                    self._write_bytes(
                        HTTPStatus.OK,
                        export.read_bytes(),
                        "text/csv; charset=utf-8",
                    )
                    return
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "manifest": tools.get_run_manifest(suffix).model_dump(mode="json"),
                        "results": [
                            item.model_dump(mode="json") for item in tools.get_run_results(suffix)
                        ],
                    },
                )
            except KeyError:
                self._write_json(
                    HTTPStatus.NOT_FOUND,
                    {"status": "not_found", "message": "The interactive run was not found."},
                )
            except ValueError as error:
                status = "run_expired" if "no longer available" in str(error) else "invalid_request"
                self._write_json(
                    HTTPStatus.GONE if status == "run_expired" else HTTPStatus.BAD_REQUEST,
                    {"status": status, "message": redact_sensitive(str(error), limit=200)},
                )
                return
            return
        if path.startswith("api/artifacts/"):
            artifact_id = path.removeprefix("api/artifacts/")
            try:
                payload = self.runtime.tools.get_artifact_section(artifact_id)
            except (KeyError, ValueError):
                self._write_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})
                return
            self._write_json(HTTPStatus.OK, payload)
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._write_json(HTTPStatus.FORBIDDEN, {"status": "origin_rejected"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-CSRF-Token, X-Request-ID",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = self._normalized_path()
        try:
            user_id = self._enforce_request_boundary()
            payload = self._read_json()
            if path == "api/session":
                session = self.runtime.sessions.create(user_id=user_id)
                self._write_json(
                    HTTPStatus.CREATED,
                    self.runtime.session_public(session),
                )
                return
            session_id = str(payload.get("session_id", ""))
            self._require_csrf(session_id)
            if path == "api/reset":
                session = self.runtime.sessions.reset(session_id)
                self._write_json(
                    HTTPStatus.OK,
                    self.runtime.session_public(session),
                )
                return
            if path == "api/specialist/preview":
                preview_request = SpecialistPreviewRequest.model_validate(payload)
                self._write_json(
                    HTTPStatus.OK,
                    self.runtime.preview_specialist(preview_request),
                )
                return
            if path == "api/specialist/plan":
                plan_request = SpecialistPlanRequest.model_validate(payload)
                self._write_json(HTTPStatus.OK, self.runtime.plan_specialist(plan_request))
                return
            if path == "api/specialist/execute":
                execute_request = SpecialistExecuteRequest.model_validate(payload)
                self._write_json(
                    HTTPStatus.CREATED,
                    self.runtime.execute_specialist(execute_request),
                )
                return
            if path == "api/specialist/compare":
                comparison_request = RunComparisonRequest.model_validate(payload)
                _, tools = self.runtime.require_specialist()
                comparison = tools.compare_runs(
                    comparison_request.left_run_id,
                    comparison_request.right_run_id,
                )
                self._write_json(HTTPStatus.OK, comparison.model_dump(mode="json"))
                return
            if path == "api/specialist/submit":
                submission_request = ReviewSubmissionRequest.model_validate(payload)
                _, tools = self.runtime.require_specialist()
                submission = tools.submit_run_for_review(
                    submission_request.run_id,
                    submission_request.reviewer_note,
                )
                self._write_json(HTTPStatus.CREATED, submission.model_dump(mode="json"))
                return
            if path and path.startswith("api/tools/"):
                tool_name = path.removeprefix("api/tools/")
                tool_request = ToolRequest.model_validate(payload)
                result = self.runtime.tools.dispatch(tool_name, tool_request.arguments)
                serialized = (
                    [item.model_dump(mode="json") for item in result]
                    if isinstance(result, list) and result and isinstance(result[0], BaseModel)
                    else (
                        result.model_dump(mode="json") if isinstance(result, BaseModel) else result
                    )
                )
                self._write_json(HTTPStatus.OK, {"result": serialized})
                return
            if path == "api/chat":
                ask_request = AskRequest.model_validate(payload)
                result = self.runtime.ask(ask_request)
                self._stream_chat(ask_request, result)
                return
        except PermissionError:
            self._write_json(HTTPStatus.FORBIDDEN, {"status": "forbidden"})
            return
        except DuplicateRequestError:
            self._write_json(
                HTTPStatus.CONFLICT,
                {"status": "duplicate_request", "message": "This request was already used."},
            )
            return
        except BudgetExceededError as error:
            self._write_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {
                    "status": "budget_exhausted",
                    "message": redact_sensitive(str(error)),
                },
            )
            return
        except SessionExpiredError:
            self._write_json(
                HTTPStatus.GONE,
                {"status": "session_expired", "message": "The session has expired."},
            )
            return
        except AIUnavailableError as error:
            self._write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "status": "provider_unavailable",
                    "message": redact_sensitive(str(error), limit=300),
                    "analytics_unaffected": True,
                },
            )
            return
        except RuntimeError as error:
            if str(error) == "rate limit exceeded":
                self._write_json(HTTPStatus.TOO_MANY_REQUESTS, {"status": "rate_limited"})
                return
            raise
        except (ValidationError, ValueError, KeyError) as error:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "status": "invalid_request",
                    "message": redact_sensitive(str(error), limit=300),
                },
            )
            return
        except Exception:
            LOGGER.exception(
                "ai_studio_request_failed",
                extra={"request_id": self._request_id()},
            )
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "status": "internal_error",
                    "message": "The request failed safely; no fallback evidence was loaded.",
                    "analytics_unaffected": True,
                },
            )
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

    def _sse(self, event: str, payload: dict[str, Any]) -> None:
        body = (
            f"event: {event}\n"
            f"data: {json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}\n\n"
        ).encode()
        self.wfile.write(body)
        self.wfile.flush()

    def _stream_chat(self, request: AskRequest, result: GatewayResult) -> None:
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self._sse("status", {"message": "Searching the active certified evidence catalogue…"})
        self._sse("status", {"message": "Validating citations and denominators…"})
        for section, values in (
            ("direct_answer", [result.answer.direct_answer]),
            ("certified_evidence", result.answer.certified_evidence),
            ("explanation", result.answer.explanation),
            ("limitation", result.answer.limitation),
        ):
            for value in values:
                for start in range(0, len(value), 180):
                    self._sse(
                        "chunk",
                        {"section": section, "text": value[start : start + 180]},
                    )
        session = self.runtime.sessions.get(request.session_id)
        self._sse(
            "answer",
            {
                "answer": result.answer.model_dump(mode="json"),
                "usage": result.usage.model_dump(mode="json"),
                "session": self.runtime.session_public(session),
            },
        )

    def end_headers(self) -> None:
        self.send_header("X-Request-ID", self._request_id())
        origin = self.headers.get("Origin")
        if origin and origin in self.runtime.settings.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info(
            "ai_studio_http_request",
            extra={
                "run_id": self.runtime.run_id,
                "release_id": self.runtime.catalogue.release_id,
                "operation": "ai_studio_http",
                "status": str(args[1]) if len(args) > 1 else "UNKNOWN",
                "duration_ms": None,
                "error_category": None,
            },
        )


def create_ai_studio_server(
    settings: AIStudioSettings,
    *,
    catalogue: ArtifactCatalogue | None = None,
    tools: EvidenceTools | None = None,
    gateway: Any | None = None,
) -> tuple[ThreadingHTTPServer, AIStudioRuntime]:
    if not settings.enabled:
        raise RuntimeError("AI Analysis Studio is disabled by AI_ANALYSIS_STUDIO_ENABLED")
    runtime = AIStudioRuntime(
        settings,
        catalogue=catalogue,
        tools=tools,
        gateway=gateway,
    )
    handler = type(
        "ConfiguredAIStudioRequestHandler",
        (AIStudioRequestHandler,),
        {"runtime": runtime},
    )
    server = ThreadingHTTPServer((settings.host, settings.port), handler)
    server.daemon_threads = True
    return server, runtime


def serve_ai_studio(settings: AIStudioSettings) -> None:
    """Run only the optional AI service; deterministic Analytics remains separate."""
    server, runtime = create_ai_studio_server(settings)
    stop_requested = threading.Event()

    def request_shutdown(_signum: int, _frame: FrameType | None) -> None:
        if not stop_requested.is_set():
            stop_requested.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_shutdown)
    LOGGER.info(
        "ai_studio_started",
        extra={
            "run_id": runtime.run_id,
            "release_id": runtime.catalogue.release_id,
            "operation": "ai_studio_serve",
            "status": "STARTED",
            "duration_ms": 0,
            "error_category": None,
        },
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
