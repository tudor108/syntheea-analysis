from __future__ import annotations

import hashlib
import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pytest
from pydantic import ValidationError

from prostate_journey.ai_artifact_catalog import build_artifact_catalogue
from prostate_journey.ai_demo import build_ai_demo_package
from prostate_journey.ai_evidence_tools import EvidenceTools
from prostate_journey.ai_openai import AIUnavailableError, ModelUsage
from prostate_journey.ai_studio import create_ai_studio_server
from prostate_journey.ai_studio_config import AIStudioSettings, load_ai_studio_settings
from prostate_journey.specialist_contracts import (
    AnalysisSpec,
    ExpertLens,
    RequestMode,
)
from prostate_journey.specialist_openai import PlanningResult
from prostate_journey.specialist_orchestrator import SpecialistOrchestrator
from prostate_journey.specialist_sandbox import SandboxError, run_isolated_worker
from prostate_journey.specialist_tools import SpecialistAnalysisTools

ROOT = Path(__file__).resolve().parents[1]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_static_demo_fallback_is_release_bound_and_provider_free() -> None:
    settings = load_ai_studio_settings(ROOT, environ={})
    target = (
        ROOT / "outputs" / "experiments" / "ai_studio" / ("test_demo_fallback_" + uuid.uuid4().hex)
    ).resolve()
    try:
        result = build_ai_demo_package(
            ROOT,
            settings,
            output_dir=target,
            confirm_run=False,
        )
        assert result["slides"] == 10
        assert result["provider_cost_usd"] == 0
        assert result["certified_release_unchanged"] is True
        assert (target / "index.html").is_file()
        assert len(list(target.glob("step-*.svg"))) == 10
        assert "INTERACTIVE SYNTHETIC ANALYSIS" in (target / "step-01.svg").read_text(
            encoding="utf-8"
        )
    finally:
        assert target.is_relative_to((ROOT / "outputs" / "experiments").resolve())
        shutil.rmtree(target, ignore_errors=True)


class _NoProvider:
    configured = False

    @staticmethod
    def _vector_store_id() -> None:
        return None

    @staticmethod
    def search_file_store(_question: str) -> list[object]:
        return []

    @staticmethod
    def generate(*_args: object, **_kwargs: object) -> None:
        raise AIUnavailableError("Provider intentionally disabled in tests.")


class _FakePlanner:
    configured = True

    def route_request(self, *_args: Any, **_kwargs: Any) -> PlanningResult:
        return PlanningResult(
            payload={
                "mode": "modify_existing_tactic",
                "tactic_id": "initiation_landmarks",
                "expert_lens": "rwe_epidemiology",
                "parameter_updates": {"initiation_window_days": 60, "market": "US"},
                "requires_deep_methodology": False,
                "rationale": "The request changes a registered initiation landmark.",
            },
            usage=ModelUsage(input_tokens=100, output_tokens=30, estimated_cost_usd=0.0001),
            response_id="resp_test_router",
        )

    def plan_specialist_analysis(
        self,
        _question: str,
        _spec: AnalysisSpec,
        *,
        budget_confirmed: bool,
        **_kwargs: Any,
    ) -> PlanningResult:
        assert budget_confirmed is True
        return PlanningResult(
            payload={
                "proposed_method": "Governed descriptive comparison over existing aggregate rows.",
                "why_registered_tactics_are_insufficient": (
                    "The user explicitly requested a proposed method contract."
                ),
                "estimand": "Scenario-specific aggregate 90-day initiation proportion.",
                "assumptions": ["Configured scenarios remain synthetic and non-comparative."],
                "validation_checks": ["Keep every market denominator separate."],
                "implementation_steps": ["Use the declarative aggregate sandbox."],
                "limitations": ["No real-world or causal interpretation."],
                "sme_review_requirements": ["Independent RWE method review."],
            },
            usage=ModelUsage(input_tokens=400, output_tokens=200, estimated_cost_usd=0.0032),
            response_id="resp_test_terra",
        )

    def summarize_results(
        self,
        _spec: AnalysisSpec,
        _rows: list[Any],
        **_kwargs: Any,
    ) -> PlanningResult:
        return PlanningResult(
            payload={
                "observations": ["The synthetic aggregate rows passed governed QA."],
                "method_note": "Existing deterministic calculations produced the result.",
                "limitations": ["Human review remains required."],
            },
            usage=ModelUsage(input_tokens=200, output_tokens=60, estimated_cost_usd=0.0002),
            response_id="resp_test_summary",
        )


@pytest.fixture(scope="module")
def specialist_runtime() -> tuple[
    AIStudioSettings,
    EvidenceTools,
    SpecialistAnalysisTools,
    SpecialistOrchestrator,
]:
    settings = load_ai_studio_settings(ROOT, environ={})
    catalogue = build_artifact_catalogue(ROOT, settings)
    evidence = EvidenceTools(ROOT, catalogue)
    test_root = (
        ROOT / "outputs" / "experiments" / "ai_studio" / ("test_specialist_" + uuid.uuid4().hex)
    ).resolve()
    assert test_root.is_relative_to((ROOT / "outputs" / "experiments").resolve())
    configured = settings.model_copy(
        update={
            "interactive_runs_directory": test_root,
            "openai_api_key": None,
        }
    )
    tools = SpecialistAnalysisTools(configured, evidence)
    orchestrator = SpecialistOrchestrator(configured, tools)
    yield configured, evidence, tools, orchestrator
    assert test_root.is_relative_to((ROOT / "outputs" / "experiments").resolve())
    shutil.rmtree(test_root, ignore_errors=True)


def _preview(
    orchestrator: SpecialistOrchestrator,
    *,
    tactic_id: str = "initiation_landmarks",
    question: str = "Re-run initiation at 60 days for US and DE with explicit denominators.",
) -> Any:
    return orchestrator.prepare_preview(
        question,
        selected_lens=ExpertLens.RWE_EPIDEMIOLOGY,
        tactic_id=tactic_id,
        parameters={},
        remaining_budget_usd=2.0,
        specialist_mode=True,
        use_model_router=False,
    )


def test_exact_tool_surface_and_seven_expert_lenses(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    _, _, tools, orchestrator = specialist_runtime
    expected = {
        "list_tactics",
        "get_tactic_contract",
        "recommend_tactics",
        "get_allowed_parameters",
        "validate_analysis_spec",
        "estimate_analysis_cost",
        "preview_population",
        "preview_denominator",
        "run_registered_analysis",
        "run_sandbox_analysis",
        "get_run_status",
        "get_run_manifest",
        "get_run_results",
        "compare_runs",
        "export_interactive_result",
        "submit_run_for_review",
    }
    assert {item["name"] for item in tools.tool_contracts()} == expected
    assert {item.lens_id for item in orchestrator.lenses} == set(ExpertLens)
    assert len(tools.list_tactics()) == 10


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Explain the initiation denominator and method.", RequestMode.EXPLAIN_TACTIC),
        ("Recommend which tactic fits a missing-data question.", RequestMode.RECOMMEND_TACTIC),
        ("Re-run persistence with a 90-day gap.", RequestMode.MODIFY_EXISTING_TACTIC),
        ("Compare two existing interactive results.", RequestMode.COMPARE_EXISTING_RESULTS),
        ("Propose a new analysis for this synthetic question.", RequestMode.PROPOSE_NEW_ANALYSIS),
        ("RUN THIS ANALYSIS after approval.", RequestMode.EXECUTE_APPROVED_ANALYSIS),
        ("Recommend treatment for this patient.", RequestMode.PROHIBITED_REQUEST),
        ("Tell me something unrelated right now.", RequestMode.INSUFFICIENT_EVIDENCE),
        ("Show the certified release evidence source.", RequestMode.ARTIFACT_QUESTION),
    ],
)
def test_request_router_uses_exactly_one_mode(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
    question: str,
    expected: RequestMode,
) -> None:
    _, _, _, orchestrator = specialist_runtime
    classification, _ = orchestrator.classify(
        question,
        selected_lens=ExpertLens.BIOSTATISTICS,
        tactic_id=None,
        use_model=False,
    )
    assert classification.mode is expected
    assert isinstance(classification.mode, RequestMode)


def test_luna_route_is_validated_and_user_lens_remains_authoritative(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    settings, _, tools, _ = specialist_runtime
    orchestrator = SpecialistOrchestrator(settings, tools, planner=_FakePlanner())
    route, usage = orchestrator.classify(
        "Change initiation to 60 days for US.",
        selected_lens=ExpertLens.BIOSTATISTICS,
        tactic_id="initiation_landmarks",
        use_model=True,
    )
    assert route.routing_source == "gpt-5.6-luna"
    assert route.expert_lens is ExpertLens.BIOSTATISTICS
    assert route.parameter_updates["initiation_window_days"] == 60
    assert usage.estimated_cost_usd == 0.0001


def test_parameter_extraction_validation_diff_and_denominator_preview(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    _, _, _, orchestrator = specialist_runtime
    preview = _preview(orchestrator)
    assert preview.validation.valid is True
    assert preview.spec.markets == ["DE", "US"]
    assert preview.spec.initiation_window_days == 60
    assert preview.population_preview.denominator_changed is True
    assert preview.population_preview.current_denominator == 1060
    assert {item.market for item in preview.population_preview.slices} == {"DE", "US"}
    assert any(
        item.parameter == "initiation_window_days" and item.changed
        for item in preview.parameter_diff
    )
    assert preview.confirmation_token


@pytest.mark.parametrize(
    ("tactic_id", "question"),
    [
        ("cohort_definition", "Re-run cohort definition for US with explicit denominator."),
        ("initiation_landmarks", "Re-run initiation at 30 days for US."),
        ("censoring_evaluability", "Re-run censoring evaluability for US."),
        ("persistence_sensitivity", "Re-run persistence with a 90-day gap for US."),
        ("time_to_initiation", "Re-run time-to-initiation at 60 days for US."),
        ("referral_pathway", "Re-run referral completion for US."),
        (
            "segmented_treatment_gap",
            "Re-run care setting segmentation for academic oncology at 90 days for US.",
        ),
        ("missingness_profile", "Re-run the registered missingness profile for US."),
    ],
)
def test_every_registered_execution_adapter_passes_post_run_qa(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
    tactic_id: str,
    question: str,
) -> None:
    _, _, _, orchestrator = specialist_runtime
    preview = _preview(orchestrator, tactic_id=tactic_id, question=question)
    assert preview.validation.valid is True
    run = orchestrator.execute(
        preview.request_id,
        confirmation_token=preview.confirmation_token or "",
        confirmation_text="RUN THIS ANALYSIS",
    )
    assert run.qa.status == "PASS"
    assert run.results


def test_incomplete_unknown_and_incompatible_specs_are_rejected(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    _, _, tools, orchestrator = specialist_runtime
    preview = _preview(orchestrator)
    incomplete = preview.spec.model_dump(mode="json")
    incomplete["denominator_definition"] = ""
    with pytest.raises(ValidationError):
        AnalysisSpec.model_validate(incomplete)
    unknown = preview.spec.model_copy(
        update={"parameters": {**preview.spec.parameters, "unrestricted_sql": "SELECT *"}}
    )
    validation = tools.validate_analysis_spec(unknown)
    assert validation.valid is False
    assert any("Unsupported parameters" in value for value in validation.errors)
    care = tools.build_spec(
        str(uuid.uuid4()),
        "Re-run care setting segmentation at 60 days with explicit denominator.",
        ExpertLens.DATA_QUALITY,
        "segmented_treatment_gap",
        {"market": "ALL", "segment": "care_setting", "initiation_window_days": 60},
    )
    assert tools.validate_analysis_spec(care).valid is False


def test_explicit_confirmation_prevents_tampering_and_replay(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    _, _, _, orchestrator = specialist_runtime
    preview = _preview(orchestrator, question="Re-run initiation at 30 days for US.")
    with pytest.raises(ValueError, match="explicit"):
        orchestrator.execute(
            preview.request_id,
            confirmation_token=preview.confirmation_token or "",
            confirmation_text="yes",
        )
    with pytest.raises(ValueError, match="token"):
        orchestrator.execute(
            preview.request_id,
            confirmation_token="0" * 64,
            confirmation_text="RUN THIS ANALYSIS",
        )
    run = orchestrator.execute(
        preview.request_id,
        confirmation_token=preview.confirmation_token or "",
        confirmation_text="RUN THIS ANALYSIS",
    )
    assert run.qa.status == "PASS"
    with pytest.raises(ValueError, match="already"):
        orchestrator.execute(
            preview.request_id,
            confirmation_token=preview.confirmation_token or "",
            confirmation_text="RUN THIS ANALYSIS",
        )


def test_registered_run_isolated_manifest_export_comparison_and_review(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    settings, _, tools, orchestrator = specialist_runtime
    checksum = ROOT / "data" / "releases" / tools.release_id / "CHECKSUMS.sha256"
    release_manifest = ROOT / "data" / "releases" / tools.release_id / "release_manifest.json"
    dashboard = ROOT / "outputs" / "presentation" / tools.release_id / "executive_story.html"
    before = [_digest(path) for path in (checksum, release_manifest, dashboard)]
    first_preview = _preview(orchestrator, question="Re-run initiation at 30 days for US.")
    first = orchestrator.execute(
        first_preview.request_id,
        confirmation_token=first_preview.confirmation_token or "",
        confirmation_text="RUN THIS ANALYSIS",
    )
    second_preview = _preview(orchestrator, question="Re-run initiation at 90 days for US.")
    second = orchestrator.execute(
        second_preview.request_id,
        confirmation_token=second_preview.confirmation_token or "",
        confirmation_text="RUN THIS ANALYSIS",
    )
    assert before == [_digest(path) for path in (checksum, release_manifest, dashboard)]
    run_dir = (settings.project_root / first.run_directory).resolve()
    assert run_dir.is_relative_to(settings.interactive_runs_directory)
    assert set(first.manifest.output_files) <= {item.name for item in run_dir.iterdir()}
    assert first.manifest.parent_release_id == tools.release_id
    assert first.manifest.config_sha256 and first.manifest.input_snapshot_sha256
    assert first.manifest.qa_status == "PASS"
    exported = tools.export_interactive_result(first.manifest.run_id)
    text = exported.read_text(encoding="utf-8")
    assert "numerator,denominator" in text
    assert "patient_id" not in text
    comparison = tools.compare_runs(first.manifest.run_id, second.manifest.run_id)
    assert comparison.compatible is True
    assert comparison.differences
    submission = tools.submit_run_for_review(first.manifest.run_id, "Independent review")
    assert submission.certification_changed is False
    assert submission.status == "SUBMITTED FOR REVIEW"
    assert all("CERTIFIED" not in badge.value for badge in first.manifest.badges)


def test_failed_qa_suppresses_interpretation_export_and_review(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    _, _, tools, orchestrator = specialist_runtime
    preview = _preview(orchestrator, question="Re-run initiation at 60 days for CA.")
    run = tools.run_registered_analysis(
        preview.spec,
        user_request="Regression test only",
        parameter_diff=preview.parameter_diff,
        workflow=preview.workflow,
        _test_force_qa_failure=True,
    )
    assert run.manifest.status == "ANALYSIS FAILED VALIDATION"
    assert run.interpretation == ["No interpretation is available because post-run QA failed."]
    with pytest.raises(ValueError, match="cannot be exported"):
        tools.export_interactive_result(run.manifest.run_id)
    with pytest.raises(ValueError, match="cannot be submitted"):
        tools.submit_run_for_review(run.manifest.run_id, "Should fail")


def test_declarative_sandbox_denies_network_enforces_timeout_and_runs_proposal(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    settings, _, tools, _ = specialist_runtime
    controls = settings.interactive_runs_directory / ("sandbox_controls_" + uuid.uuid4().hex)
    network = run_isolated_worker(
        controls / "network",
        {},
        action="network-probe",
        timeout_seconds=3,
    )
    assert network == {"status": "blocked", "network": "denied"}
    with pytest.raises(SandboxError, match="duration"):
        run_isolated_worker(
            controls / "timeout",
            {"delay_seconds": 3},
            action="delay",
            timeout_seconds=1,
        )
    orchestrator = SpecialistOrchestrator(settings, tools, planner=_FakePlanner())
    preview = orchestrator.prepare_preview(
        "Propose a new analysis comparing configured synthetic scenario aggregates.",
        selected_lens=ExpertLens.MARKET_SCENARIO_ANALYSIS,
        tactic_id=None,
        parameters={"markets": ["US", "DE"]},
        remaining_budget_usd=2.0,
        specialist_mode=True,
        use_model_router=False,
    )
    assert preview.requires_specialist_plan is True
    assert preview.confirmation_token is None
    planned, cost = orchestrator.plan_specialist(
        preview.request_id,
        budget_confirmed=True,
        remaining_budget_usd=2.0,
    )
    assert cost == 0.0032
    assert planned.confirmation_token
    run = orchestrator.execute(
        planned.request_id,
        confirmation_token=planned.confirmation_token or "",
        confirmation_text="RUN THIS ANALYSIS",
    )
    assert run.qa.status == "PASS"
    assert run.spec.new_proposal is True
    assert "PROPOSED METHOD" in {badge.value for badge in run.manifest.badges}
    assert all(row.parent_release_id == tools.release_id for row in run.results)
    assert "model_summary.json" in run.manifest.output_files
    assert run.manifest.actual_provider_cost_usd == pytest.approx(0.0034)


def test_specialist_http_preview_and_execution_are_separate_actions(
    specialist_runtime: tuple[
        AIStudioSettings,
        EvidenceTools,
        SpecialistAnalysisTools,
        SpecialistOrchestrator,
    ],
) -> None:
    settings, evidence, _, _ = specialist_runtime
    server_settings = settings.model_copy(update={"port": 0})
    server, _ = create_ai_studio_server(
        server_settings,
        catalogue=evidence.catalogue,
        tools=evidence,
        gateway=_NoProvider(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        session_request = Request(
            f"http://{host}:{port}/api/session",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(session_request, timeout=3) as response:
            session = json.loads(response.read())
        before_count = len(list(settings.interactive_runs_directory.glob("iar_*")))
        preview_body = json.dumps(
            {
                "session_id": session["session_id"],
                "question": "Re-run initiation at 60 days for US with explicit denominator.",
                "expert_lens": "rwe_epidemiology",
                "tactic_id": "initiation_landmarks",
                "parameters": {},
                "specialist_mode": True,
                "use_model_router": False,
            }
        ).encode()
        preview_request = Request(
            f"http://{host}:{port}/api/specialist/preview",
            data=preview_body,
            headers={
                "Content-Type": "application/json",
                "X-CSRF-Token": session["csrf_token"],
            },
            method="POST",
        )
        with urlopen(preview_request, timeout=5) as response:
            preview = json.loads(response.read())["preview"]
        assert preview["validation"]["valid"] is True
        assert len(list(settings.interactive_runs_directory.glob("iar_*"))) == before_count
        execute_body = json.dumps(
            {
                "session_id": session["session_id"],
                "request_id": preview["request_id"],
                "confirmation_token": preview["confirmation_token"],
                "confirmation": "RUN THIS ANALYSIS",
            }
        ).encode()
        execute_request = Request(
            f"http://{host}:{port}/api/specialist/execute",
            data=execute_body,
            headers={
                "Content-Type": "application/json",
                "X-CSRF-Token": session["csrf_token"],
            },
            method="POST",
        )
        with urlopen(execute_request, timeout=5) as response:
            run = json.loads(response.read())["run"]
        assert run["qa"]["status"] == "PASS"
        assert run["manifest"]["status"] == "COMPLETED"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
