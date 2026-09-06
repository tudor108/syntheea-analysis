from __future__ import annotations

import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from prostate_journey.ai_client import AIProviderClient, ProviderRequestError
from prostate_journey.ai_evaluation import run_live_evaluation, run_offline_evaluation
from prostate_journey.ai_finops import (
    AtomicBudgetLedger,
    BudgetExceededError,
    CostCalculator,
    DuplicateRequestError,
    SessionExpiredError,
    SlidingWindowRateLimiter,
    load_cost_controls,
    redact_sensitive,
)
from prostate_journey.ai_studio_config import AIStudioSettings, load_ai_studio_settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def calculator() -> CostCalculator:
    return CostCalculator(load_cost_controls(ROOT / "configs/ai_cost_controls.yaml"))


def test_central_pricing_and_live_worst_case_are_below_hard_stop(
    calculator: CostCalculator,
) -> None:
    controls = calculator.controls
    assert controls.effective_date == "2026-09-05"
    assert controls.request_profiles["evidence"].model_id == "gpt-5.6-luna"
    assert controls.request_profiles["specialist_planning"].model_id == "gpt-5.6-terra"
    maximum = (
        calculator.estimate_maximum("live_evidence").total_cost_usd
        * controls.live_eval_suite.luna_evidence_questions
        + calculator.estimate_maximum("live_specialist_planning").total_cost_usd
        * controls.live_eval_suite.terra_planning_scenarios
    )
    assert maximum < Decimal("2.00")
    assert controls.budgets.interactive_session.hard_stop_usd == Decimal("2.00")


def test_cost_calculator_separates_cached_tokens_tools_and_margin(
    calculator: CostCalculator,
) -> None:
    actual = calculator.actual(
        "evidence",
        input_tokens=1000,
        cached_input_tokens=600,
        cache_write_tokens=100,
        output_tokens=200,
        file_search_calls=1,
        deterministic_tool_calls=3,
    )
    assert actual.tool_cost_usd == Decimal("0.00250000")
    assert actual.safety_margin_usd == 0
    assert actual.total_cost_usd == actual.model_cost_usd + actual.tool_cost_usd
    assert calculator.estimate_maximum("evidence").safety_margin_usd > 0


def test_atomic_parallel_reservations_cannot_overspend(
    tmp_path: Path, calculator: CostCalculator
) -> None:
    ledger = AtomicBudgetLedger(tmp_path / "ledger.sqlite3", calculator.controls)
    session_id = str(uuid.uuid4())
    ledger.create_session(session_id)
    estimate = calculator.estimate_maximum("specialist_planning")
    for index in range(3):
        ledger.reserve(
            session_id,
            idempotency_key=f"seed-{index}",
            profile="specialist_planning",
            estimated=estimate,
        )
    outcomes: list[str] = []
    barrier = threading.Barrier(3)

    def reserve(index: int) -> None:
        barrier.wait()
        try:
            ledger.reserve(
                session_id,
                idempotency_key=f"race-{index}",
                profile="specialist_planning",
                estimated=estimate,
            )
            outcomes.append("reserved")
        except BudgetExceededError:
            outcomes.append("blocked")

    threads = [threading.Thread(target=reserve, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=3)
    assert sorted(outcomes) == ["blocked", "reserved"]
    snapshot = ledger.session_snapshot(session_id)
    assert snapshot["reserved_usd"] < snapshot["hard_stop_usd"]


def test_reconciliation_releases_unused_reservation_and_duplicate_is_rejected(
    tmp_path: Path, calculator: CostCalculator
) -> None:
    ledger = AtomicBudgetLedger(tmp_path / "ledger.sqlite3", calculator.controls)
    session_id = str(uuid.uuid4())
    ledger.create_session(session_id)
    maximum = calculator.estimate_maximum("evidence")
    reservation = ledger.reserve(
        session_id,
        idempotency_key="one-request",
        profile="evidence",
        estimated=maximum,
    )
    with pytest.raises(DuplicateRequestError):
        ledger.reserve(
            session_id,
            idempotency_key="one-request",
            profile="evidence",
            estimated=maximum,
        )
    actual = calculator.actual(
        "evidence",
        input_tokens=300,
        cached_input_tokens=0,
        cache_write_tokens=0,
        output_tokens=80,
        file_search_calls=0,
        deterministic_tool_calls=2,
    )
    charged = ledger.reconcile(reservation.reservation_id, actual=actual, latency_ms=12)
    snapshot = ledger.session_snapshot(session_id)
    assert charged == actual.total_cost_usd
    assert snapshot["reserved_usd"] == 0
    assert snapshot["cost_used_usd"] == float(charged)


def test_live_eval_reservation_stops_strictly_before_two_dollars(
    tmp_path: Path, calculator: CostCalculator
) -> None:
    ledger = AtomicBudgetLedger(tmp_path / "ledger.sqlite3", calculator.controls)
    session_id = str(uuid.uuid4())
    evaluation_id = str(uuid.uuid4())
    ledger.create_session(session_id)
    ledger.create_live_eval(evaluation_id)
    estimate = calculator.estimate_maximum("specialist_planning").model_copy(
        update={"total_cost_usd": Decimal("0.40")}
    )
    for index in range(4):
        ledger.reserve(
            session_id,
            idempotency_key=f"live-{index}",
            profile="specialist_planning",
            estimated=estimate,
            live_eval_id=evaluation_id,
        )
    with pytest.raises(BudgetExceededError, match="below"):
        ledger.reserve(
            session_id,
            idempotency_key="live-blocked",
            profile="specialist_planning",
            estimated=estimate,
            live_eval_id=evaluation_id,
        )
    snapshot = ledger.live_eval_snapshot(evaluation_id)
    assert snapshot["below_hard_stop"] is True


def test_session_expiry_is_fail_closed(tmp_path: Path, calculator: CostCalculator) -> None:
    ledger = AtomicBudgetLedger(tmp_path / "ledger.sqlite3", calculator.controls)
    session_id = str(uuid.uuid4())
    ledger.create_session(session_id)
    ledger._connection.execute(
        "UPDATE sessions SET expires_at=? WHERE session_id=?", (time.time() - 1, session_id)
    )
    with pytest.raises(SessionExpiredError):
        ledger.session_snapshot(session_id)


def test_rate_limiter_is_bounded() -> None:
    limiter = SlidingWindowRateLimiter(requests=2, window_seconds=60)
    assert limiter.allow("client") is True
    assert limiter.allow("client") is True
    assert limiter.allow("client") is False


class _ProviderError(Exception):
    def __init__(self, status_code: int, code: str = "") -> None:
        super().__init__("provider detail with " + "s" + "k-secret-value-that-must-not-leak")
        self.status_code = status_code
        self.body = {"error": {"code": code}}


class _Responses:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    def create(self, **_kwargs: object) -> object:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(id="response")


def _raw_client(responses: _Responses) -> object:
    return SimpleNamespace(responses=responses)


def test_retry_only_for_transient_errors_and_never_for_quota() -> None:
    settings = AIStudioSettings(
        project_root=ROOT,
        cost_controls_path=ROOT / "configs/ai_cost_controls.yaml",
    )
    transient = _Responses([_ProviderError(500)])
    sleeps: list[float] = []
    client = AIProviderClient(
        settings,
        raw_client=_raw_client(transient),
        sleep=sleeps.append,
    )
    client.create_response(idempotency_key="retry", max_attempts=2, model="test")
    assert transient.calls == 2
    assert sleeps == [0.25]

    quota = _Responses([_ProviderError(429, "insufficient_quota")])
    no_retry = AIProviderClient(settings, raw_client=_raw_client(quota), sleep=sleeps.append)
    with pytest.raises(ProviderRequestError, match="budget_or_quota_exhausted") as caught:
        no_retry.create_response(idempotency_key="quota", max_attempts=2, model="test")
    assert quota.calls == 1
    assert ("s" + "k-secret") not in str(caught.value)


def test_secret_redaction_covers_keys_and_bearer_tokens() -> None:
    value = "api_key=" + "s" + "k-example-secret-value-123456 bearer abcdefghijklmnopqrstuvwxyz"
    redacted = redact_sensitive(value)
    assert "example-secret" not in redacted
    assert "abcdefghijklmnopqrstuvwxyz" not in redacted
    assert redacted.count("[REDACTED]") == 2


def test_offline_suite_is_large_and_makes_no_provider_calls() -> None:
    settings = load_ai_studio_settings(ROOT, environ={})
    # Keep mutable paths in the governed namespace required by the configuration loader.
    experiment = ROOT / "outputs" / "experiments" / "ai_studio" / f"test_eval_{uuid.uuid4().hex}"
    settings = settings.model_copy(
        update={
            "catalogue_path": experiment / "catalogue.json",
            "budget_ledger_path": experiment / "ledger.sqlite3",
            "audit_log_path": experiment / "audit.jsonl",
            "index_staging_directory": experiment / "index",
            "interactive_runs_directory": experiment / "runs",
        }
    )
    report = run_offline_evaluation(settings)
    assert report["status"] == "PASS"
    assert len(report["cases"]) > 100
    assert report["provider_requests"] == 0
    assert report["cost"]["actual_metered_usd"] == 0


def test_live_suite_without_a_key_writes_not_run_report() -> None:
    settings = load_ai_studio_settings(ROOT, environ={})
    experiment = ROOT / "outputs" / "experiments" / "ai_studio" / f"test_live_{uuid.uuid4().hex}"
    settings = settings.model_copy(
        update={
            "catalogue_path": experiment / "catalogue.json",
            "budget_ledger_path": experiment / "ledger.sqlite3",
            "audit_log_path": experiment / "audit.jsonl",
            "index_staging_directory": experiment / "index",
            "interactive_runs_directory": experiment / "runs",
            "openai_api_key": None,
            "vector_store_id": None,
        }
    )
    report = run_live_evaluation(settings)
    assert report["status"] == "NOT_RUN"
    assert report["provider_requests"] == 0
    assert report["cost"]["actual_metered_usd"] == 0
    assert report["cost"]["below_hard_stop"] is True
    assert all((ROOT / path).is_file() for path in report["report_paths"])
