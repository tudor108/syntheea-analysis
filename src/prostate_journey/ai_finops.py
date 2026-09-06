"""Versioned AI pricing, atomic reservations, rate limits, and safe audit telemetry."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

MICRO_USD = Decimal("1000000")


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_per_million_usd: Decimal = Field(ge=0)
    cached_input_per_million_usd: Decimal = Field(ge=0)
    cache_write_per_million_usd: Decimal = Field(ge=0)
    output_per_million_usd: Decimal = Field(ge=0)


class ToolPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    per_call_usd: Decimal = Field(default=Decimal("0"), ge=0)
    per_session_usd: Decimal = Field(default=Decimal("0"), ge=0)
    storage_per_gb_day_usd: Decimal = Field(default=Decimal("0"), ge=0)


class RequestProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    max_input_tokens: int = Field(gt=0, le=272_000)
    max_output_tokens: int = Field(gt=0, le=10_000)
    max_retrieved_chunks: int = Field(ge=0, le=20)
    max_file_search_calls: int = Field(ge=0, le=10)
    max_deterministic_tool_calls: int = Field(ge=0, le=20)
    max_model_iterations: int = Field(ge=1, le=2)
    max_request_cost_usd: Decimal = Field(gt=0, le=Decimal("2.00"))


class InteractiveBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning_usd: Decimal = Field(gt=0)
    specialist_soft_stop_usd: Decimal = Field(gt=0)
    hard_stop_usd: Decimal = Field(gt=0, le=Decimal("2.00"))


class HardBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard_stop_usd: Decimal = Field(gt=0)


class WarningBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning_usd: Decimal = Field(gt=0)
    hard_stop_usd: Decimal = Field(gt=0, le=Decimal("2.00"))


class MonthlyAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning_usd: Decimal = Field(gt=0)
    critical_usd: Decimal = Field(gt=0)
    provider_limit_required_for_production: bool = True


class BudgetConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interactive_session: InteractiveBudget
    specialist_run: HardBudget
    authenticated_user_daily: HardBudget
    live_eval_run: WarningBudget
    monthly_project_alert: MonthlyAlert


class LiveEvalSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    luna_evidence_questions: int = Field(ge=1, le=100)
    terra_planning_scenarios: int = Field(ge=1, le=20)
    max_file_search_calls: int = Field(ge=0, le=100)
    hard_stop_usd: Decimal = Field(gt=0, le=Decimal("2.00"))


class SecurityLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_request_bytes: int = Field(ge=1024, le=1_000_000)
    session_ttl_seconds: int = Field(ge=60, le=86_400)
    rate_limit_requests: int = Field(ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(ge=1, le=3600)
    max_index_artifact_bytes: int = Field(ge=1024, le=20_000_000)
    max_sandbox_disk_bytes: int = Field(ge=10_000, le=20_000_000)
    audit_log_max_field_characters: int = Field(ge=32, le=1000)
    retry_max_attempts: int = Field(ge=1, le=2)
    retry_initial_backoff_seconds: float = Field(ge=0, le=2)


class AICostControls(BaseModel):
    """Single source of truth for AI prices, budgets, and bounded request profiles."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["AI-FINOPS-v1.0"]
    effective_date: str
    currency: Literal["USD"]
    source_reference_note: str
    safety_margin_multiplier: Decimal = Field(ge=Decimal("1.0"), le=Decimal("2.0"))
    models: dict[str, ModelPrice]
    tools: dict[str, ToolPrice]
    request_profiles: dict[str, RequestProfile]
    budgets: BudgetConfiguration
    live_eval_suite: LiveEvalSuite
    security_limits: SecurityLimits

    @model_validator(mode="after")
    def _cross_validate(self) -> AICostControls:
        if (
            self.budgets.interactive_session.warning_usd
            >= self.budgets.interactive_session.hard_stop_usd
        ):
            raise ValueError("session warning must be below the hard stop")
        if (
            self.budgets.interactive_session.specialist_soft_stop_usd
            >= self.budgets.interactive_session.hard_stop_usd
        ):
            raise ValueError("specialist soft stop must be below the session hard stop")
        if self.live_eval_suite.hard_stop_usd != self.budgets.live_eval_run.hard_stop_usd:
            raise ValueError("live evaluation hard limits must agree")
        for name, profile in self.request_profiles.items():
            if profile.model_id not in self.models:
                raise ValueError(f"unknown model in request profile: {name}")
            estimate = CostCalculator(self).estimate_maximum(name)
            if estimate.total_cost_usd > profile.max_request_cost_usd:
                raise ValueError(f"request profile ceiling is below worst-case estimate: {name}")
        suite_maximum = (
            self.estimate_profile("live_evidence") * self.live_eval_suite.luna_evidence_questions
            + self.estimate_profile("live_specialist_planning")
            * self.live_eval_suite.terra_planning_scenarios
        )
        if suite_maximum >= self.live_eval_suite.hard_stop_usd:
            raise ValueError("configured live evaluation worst case must remain below $2")
        return self

    def estimate_profile(self, profile_name: str) -> Decimal:
        profile = self.request_profiles[profile_name]
        price = self.models[profile.model_id]
        token_cost = (
            Decimal(profile.max_input_tokens) * price.input_per_million_usd
            + Decimal(profile.max_output_tokens) * price.output_per_million_usd
        ) / MICRO_USD
        tool_cost = Decimal(profile.max_file_search_calls) * self.tools["file_search"].per_call_usd
        return (
            token_cost * profile.max_model_iterations + tool_cost
        ) * self.safety_margin_multiplier


class CostBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str
    model_id: str
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    file_search_calls: int
    deterministic_tool_calls: int
    model_iterations: int
    model_cost_usd: Decimal
    tool_cost_usd: Decimal
    safety_margin_usd: Decimal
    total_cost_usd: Decimal
    pricing_effective_date: str


class CostCalculator:
    def __init__(self, controls: AICostControls) -> None:
        self.controls = controls

    def estimate_maximum(self, profile_name: str) -> CostBreakdown:
        profile = self.controls.request_profiles[profile_name]
        return self._calculate(
            profile_name,
            input_tokens=profile.max_input_tokens,
            cached_input_tokens=0,
            cache_write_tokens=0,
            output_tokens=profile.max_output_tokens,
            file_search_calls=profile.max_file_search_calls,
            deterministic_tool_calls=profile.max_deterministic_tool_calls,
            model_iterations=profile.max_model_iterations,
            apply_margin=True,
        )

    def actual(
        self,
        profile_name: str,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        cache_write_tokens: int,
        output_tokens: int,
        file_search_calls: int,
        deterministic_tool_calls: int,
        model_iterations: int = 1,
    ) -> CostBreakdown:
        profile = self.controls.request_profiles[profile_name]
        if input_tokens > profile.max_input_tokens or output_tokens > profile.max_output_tokens:
            raise ValueError("actual token usage exceeded the reserved request profile")
        if file_search_calls > profile.max_file_search_calls:
            raise ValueError("actual File Search usage exceeded the reserved request profile")
        if deterministic_tool_calls > profile.max_deterministic_tool_calls:
            raise ValueError("deterministic tool usage exceeded the request profile")
        if model_iterations > profile.max_model_iterations:
            raise ValueError("model iterations exceeded the request profile")
        return self._calculate(
            profile_name,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_write_tokens=cache_write_tokens,
            output_tokens=output_tokens,
            file_search_calls=file_search_calls,
            deterministic_tool_calls=deterministic_tool_calls,
            model_iterations=model_iterations,
            apply_margin=False,
        )

    def _calculate(
        self,
        profile_name: str,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        cache_write_tokens: int,
        output_tokens: int,
        file_search_calls: int,
        deterministic_tool_calls: int,
        model_iterations: int,
        apply_margin: bool,
    ) -> CostBreakdown:
        profile = self.controls.request_profiles[profile_name]
        price = self.controls.models[profile.model_id]
        uncached = max(0, input_tokens - cached_input_tokens - cache_write_tokens)
        model_cost = (
            Decimal(uncached) * price.input_per_million_usd
            + Decimal(cached_input_tokens) * price.cached_input_per_million_usd
            + Decimal(cache_write_tokens) * price.cache_write_per_million_usd
            + Decimal(output_tokens) * price.output_per_million_usd
        ) / MICRO_USD
        model_cost *= model_iterations
        tool_cost = Decimal(file_search_calls) * self.controls.tools["file_search"].per_call_usd
        base = model_cost + tool_cost
        margin = (
            base * (self.controls.safety_margin_multiplier - Decimal("1"))
            if apply_margin
            else Decimal("0")
        )
        total = base + margin
        return CostBreakdown(
            profile=profile_name,
            model_id=profile.model_id,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_write_tokens=cache_write_tokens,
            output_tokens=output_tokens,
            file_search_calls=file_search_calls,
            deterministic_tool_calls=deterministic_tool_calls,
            model_iterations=model_iterations,
            model_cost_usd=model_cost.quantize(Decimal("0.00000001")),
            tool_cost_usd=tool_cost.quantize(Decimal("0.00000001")),
            safety_margin_usd=margin.quantize(Decimal("0.00000001")),
            total_cost_usd=total.quantize(Decimal("0.00000001")),
            pricing_effective_date=self.controls.effective_date,
        )

    @staticmethod
    def conservative_token_count(value: str) -> int:
        """Upper-bound tokens by UTF-8 bytes plus a fixed structured-message allowance."""
        return len(value.encode("utf-8")) + 512

    def validate_input(self, profile_name: str, value: str) -> int:
        estimate = self.conservative_token_count(value)
        if estimate > self.controls.request_profiles[profile_name].max_input_tokens:
            raise ValueError("request input exceeds its configured worst-case token limit")
        return estimate


class BudgetExceededError(RuntimeError):
    pass


class DuplicateRequestError(RuntimeError):
    pass


class SessionExpiredError(RuntimeError):
    pass


class Reservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: str
    session_id: str
    idempotency_key: str
    profile: str
    reserved_cost_usd: Decimal
    status: str


def _micros(value: Decimal) -> int:
    return int((value * MICRO_USD).to_integral_value(rounding=ROUND_CEILING))


def _dollars(value: int) -> Decimal:
    return (Decimal(value) / MICRO_USD).quantize(Decimal("0.000001"))


class AtomicBudgetLedger:
    """SQLite-backed reservation ledger with BEGIN IMMEDIATE overspend protection."""

    def __init__(self, path: Path, controls: AICostControls) -> None:
        self.path = path
        self.controls = controls
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(path), timeout=30, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    hard_limit_micros INTEGER NOT NULL,
                    spent_micros INTEGER NOT NULL DEFAULT 0,
                    reserved_micros INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    reserved_micros INTEGER NOT NULL,
                    actual_micros INTEGER,
                    status TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    file_search_calls INTEGER NOT NULL DEFAULT 0,
                    deterministic_tool_calls INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    live_eval_id TEXT,
                    specialist_run_id TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS live_evals (
                    live_eval_id TEXT PRIMARY KEY,
                    hard_limit_micros INTEGER NOT NULL,
                    spent_micros INTEGER NOT NULL DEFAULT 0,
                    reserved_micros INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS specialist_runs (
                    specialist_run_id TEXT PRIMARY KEY,
                    hard_limit_micros INTEGER NOT NULL,
                    spent_micros INTEGER NOT NULL DEFAULT 0,
                    reserved_micros INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS user_daily (
                    user_day TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    spent_micros INTEGER NOT NULL DEFAULT 0,
                    reserved_micros INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_day, user_id)
                );
                """
            )

    def create_session(self, session_id: str, *, user_id: str | None = None) -> None:
        now = time.time()
        budget = self.controls.budgets.interactive_session.hard_stop_usd
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, 0, 0, 'ACTIVE')",
                (
                    session_id,
                    user_id,
                    now,
                    now + self.controls.security_limits.session_ttl_seconds,
                    _micros(budget),
                ),
            )

    def expire_session(self, session_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE sessions SET status='EXPIRED' WHERE session_id=?", (session_id,)
            )

    def create_live_eval(self, live_eval_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO live_evals VALUES (?, ?, 0, 0, 'ACTIVE', ?)",
                (
                    live_eval_id,
                    _micros(self.controls.budgets.live_eval_run.hard_stop_usd),
                    time.time(),
                ),
            )

    def reserve(
        self,
        session_id: str,
        *,
        idempotency_key: str,
        profile: str,
        estimated: CostBreakdown,
        live_eval_id: str | None = None,
        specialist_run_id: str | None = None,
    ) -> Reservation:
        requested = _micros(estimated.total_cost_usd)
        profile_limit = _micros(self.controls.request_profiles[profile].max_request_cost_usd)
        if requested > profile_limit:
            raise BudgetExceededError("request estimate exceeds its per-request budget")
        now = time.time()
        today = datetime.now(UTC).date().isoformat()
        with self._transaction() as connection:
            duplicate = connection.execute(
                "SELECT status FROM reservations WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if duplicate is not None:
                raise DuplicateRequestError("duplicate idempotency key was rejected")
            session = connection.execute(
                "SELECT * FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if session is None or session["status"] != "ACTIVE" or session["expires_at"] <= now:
                if session is not None:
                    connection.execute(
                        "UPDATE sessions SET status='EXPIRED' WHERE session_id=?", (session_id,)
                    )
                raise SessionExpiredError("unknown or expired session")
            if (
                session["spent_micros"] + session["reserved_micros"] + requested
                > session["hard_limit_micros"]
            ):
                raise BudgetExceededError("session hard budget would be exceeded")
            user_id = session["user_id"]
            if user_id:
                connection.execute(
                    "INSERT OR IGNORE INTO user_daily VALUES (?, ?, 0, 0)", (today, user_id)
                )
                daily = connection.execute(
                    "SELECT * FROM user_daily WHERE user_day=? AND user_id=?", (today, user_id)
                ).fetchone()
                daily_limit = _micros(self.controls.budgets.authenticated_user_daily.hard_stop_usd)
                if daily["spent_micros"] + daily["reserved_micros"] + requested > daily_limit:
                    raise BudgetExceededError("authenticated user daily budget would be exceeded")
                connection.execute(
                    """UPDATE user_daily SET reserved_micros=reserved_micros+?
                    WHERE user_day=? AND user_id=?""",
                    (requested, today, user_id),
                )
            if live_eval_id:
                evaluation = connection.execute(
                    "SELECT * FROM live_evals WHERE live_eval_id=?", (live_eval_id,)
                ).fetchone()
                if evaluation is None or evaluation["status"] != "ACTIVE":
                    raise BudgetExceededError("live evaluation budget is unavailable")
                if (
                    evaluation["spent_micros"] + evaluation["reserved_micros"] + requested
                    >= evaluation["hard_limit_micros"]
                ):
                    raise BudgetExceededError("live evaluation must stop below its hard budget")
                connection.execute(
                    "UPDATE live_evals SET reserved_micros=reserved_micros+? WHERE live_eval_id=?",
                    (requested, live_eval_id),
                )
            if specialist_run_id:
                connection.execute(
                    "INSERT OR IGNORE INTO specialist_runs VALUES (?, ?, 0, 0)",
                    (
                        specialist_run_id,
                        _micros(self.controls.budgets.specialist_run.hard_stop_usd),
                    ),
                )
                run = connection.execute(
                    "SELECT * FROM specialist_runs WHERE specialist_run_id=?",
                    (specialist_run_id,),
                ).fetchone()
                if (
                    run["spent_micros"] + run["reserved_micros"] + requested
                    > run["hard_limit_micros"]
                ):
                    raise BudgetExceededError("specialist-run budget would be exceeded")
                connection.execute(
                    """UPDATE specialist_runs SET reserved_micros=reserved_micros+?
                    WHERE specialist_run_id=?""",
                    (requested, specialist_run_id),
                )
            reservation_id = str(uuid.uuid4())
            connection.execute(
                "UPDATE sessions SET reserved_micros=reserved_micros+? WHERE session_id=?",
                (requested, session_id),
            )
            connection.execute(
                """INSERT INTO reservations (
                    reservation_id,idempotency_key,session_id,profile,model_id,reserved_micros,
                    actual_micros,status,created_at,updated_at,live_eval_id,specialist_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'RESERVED', ?, ?, ?, ?)""",
                (
                    reservation_id,
                    idempotency_key,
                    session_id,
                    profile,
                    estimated.model_id,
                    requested,
                    now,
                    now,
                    live_eval_id,
                    specialist_run_id,
                ),
            )
        return Reservation(
            reservation_id=reservation_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            profile=profile,
            reserved_cost_usd=_dollars(requested),
            status="RESERVED",
        )

    def reconcile(
        self,
        reservation_id: str,
        *,
        actual: CostBreakdown | None,
        latency_ms: int,
        failure: bool = False,
    ) -> Decimal:
        """Release unused funds; unknown partial failures conservatively consume the reservation."""
        today = datetime.now(UTC).date().isoformat()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM reservations WHERE reservation_id=?", (reservation_id,)
            ).fetchone()
            if row is None or row["status"] != "RESERVED":
                raise DuplicateRequestError("reservation is unknown or already reconciled")
            actual_micros = (
                row["reserved_micros"] if actual is None else _micros(actual.total_cost_usd)
            )
            status = (
                "FAILED_CONSERVATIVE"
                if failure and actual is None
                else ("FAILED" if failure else "COMPLETED")
            )
            connection.execute(
                """UPDATE sessions SET reserved_micros=reserved_micros-?,
                    spent_micros=spent_micros+? WHERE session_id=?""",
                (row["reserved_micros"], actual_micros, row["session_id"]),
            )
            user = connection.execute(
                "SELECT user_id FROM sessions WHERE session_id=?", (row["session_id"],)
            ).fetchone()
            if user and user["user_id"]:
                connection.execute(
                    """UPDATE user_daily SET reserved_micros=reserved_micros-?,
                        spent_micros=spent_micros+? WHERE user_day=? AND user_id=?""",
                    (row["reserved_micros"], actual_micros, today, user["user_id"]),
                )
            for table, key_name, key in (
                ("live_evals", "live_eval_id", row["live_eval_id"]),
                ("specialist_runs", "specialist_run_id", row["specialist_run_id"]),
            ):
                if key:
                    connection.execute(
                        f"""UPDATE {table} SET reserved_micros=reserved_micros-?,
                        spent_micros=spent_micros+? WHERE {key_name}=?""",
                        (row["reserved_micros"], actual_micros, key),
                    )
            usage = actual or CostBreakdown(
                profile=row["profile"],
                model_id=row["model_id"],
                input_tokens=0,
                cached_input_tokens=0,
                cache_write_tokens=0,
                output_tokens=0,
                file_search_calls=0,
                deterministic_tool_calls=0,
                model_iterations=0,
                model_cost_usd=Decimal("0"),
                tool_cost_usd=Decimal("0"),
                safety_margin_usd=Decimal("0"),
                total_cost_usd=_dollars(actual_micros),
                pricing_effective_date=self.controls.effective_date,
            )
            connection.execute(
                """UPDATE reservations SET actual_micros=?,status=?,input_tokens=?,
                    cached_input_tokens=?,cache_write_tokens=?,output_tokens=?,file_search_calls=?,
                    deterministic_tool_calls=?,latency_ms=?,updated_at=? WHERE reservation_id=?""",
                (
                    actual_micros,
                    status,
                    usage.input_tokens,
                    usage.cached_input_tokens,
                    usage.cache_write_tokens,
                    usage.output_tokens,
                    usage.file_search_calls,
                    usage.deterministic_tool_calls,
                    latency_ms,
                    time.time(),
                    reservation_id,
                ),
            )
        return _dollars(actual_micros)

    def session_snapshot(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None or row["status"] != "ACTIVE" or row["expires_at"] <= time.time():
                if row is not None and row["status"] == "ACTIVE":
                    self._connection.execute(
                        "UPDATE sessions SET status='EXPIRED' WHERE session_id=?",
                        (session_id,),
                    )
                raise SessionExpiredError("unknown or expired session")
            spent = _dollars(row["spent_micros"])
            reserved = _dollars(row["reserved_micros"])
            hard = _dollars(row["hard_limit_micros"])
            warning = self.controls.budgets.interactive_session.warning_usd
            soft = self.controls.budgets.interactive_session.specialist_soft_stop_usd
            return {
                "session_id": session_id,
                "status": row["status"],
                "cost_used_usd": float(spent),
                "reserved_usd": float(reserved),
                "remaining_budget_usd": float(max(Decimal("0"), hard - spent - reserved)),
                "hard_stop_usd": float(hard),
                "warning_usd": float(warning),
                "specialist_soft_stop_usd": float(soft),
                "warning_active": spent + reserved >= warning,
                "specialist_soft_stop_active": spent + reserved >= soft,
                "expires_at_epoch": row["expires_at"],
            }

    def dashboard(self, session_id: str) -> dict[str, Any]:
        snapshot = self.session_snapshot(session_id)
        with self._lock:
            rows = self._connection.execute(
                """SELECT profile,model_id,status,actual_micros,reserved_micros,input_tokens,
                    cached_input_tokens,cache_write_tokens,output_tokens,file_search_calls,
                    deterministic_tool_calls,latency_ms,created_at
                    FROM reservations WHERE session_id=? ORDER BY created_at DESC LIMIT 50""",
                (session_id,),
            ).fetchall()
        totals: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "requests": 0,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "cache_write_tokens": 0,
                "output_tokens": 0,
                "file_search_calls": 0,
                "deterministic_tool_calls": 0,
            }
        )
        events: list[dict[str, Any]] = []
        for row in rows:
            key = str(row["model_id"])
            item = totals[key]
            item["requests"] += 1
            item["cost_usd"] = round(
                item["cost_usd"] + float(_dollars(row["actual_micros"] or 0)), 8
            )
            for field in (
                "input_tokens",
                "cached_input_tokens",
                "cache_write_tokens",
                "output_tokens",
                "file_search_calls",
                "deterministic_tool_calls",
            ):
                item[field] += int(row[field] or 0)
            events.append(
                {
                    "profile": row["profile"],
                    "model_id": row["model_id"],
                    "status": row["status"],
                    "actual_cost_usd": float(_dollars(row["actual_micros"] or 0)),
                    "reserved_cost_usd": float(_dollars(row["reserved_micros"])),
                    "latency_ms": row["latency_ms"],
                    "created_at": datetime.fromtimestamp(row["created_at"], UTC).isoformat(),
                }
            )
        return {
            "session": snapshot,
            "by_model": dict(totals),
            "recent_requests": events,
            "pricing_effective_date": self.controls.effective_date,
            "monthly_project_alert": self.controls.budgets.monthly_project_alert.model_dump(
                mode="json"
            ),
            "local_compute_tracked_separately": True,
        }

    def live_eval_snapshot(self, live_eval_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM live_evals WHERE live_eval_id=?", (live_eval_id,)
            ).fetchone()
            if row is None:
                raise KeyError("unknown live evaluation")
            return {
                "live_eval_id": live_eval_id,
                "spent_usd": float(_dollars(row["spent_micros"])),
                "reserved_usd": float(_dollars(row["reserved_micros"])),
                "hard_stop_usd": float(_dollars(row["hard_limit_micros"])),
                "below_hard_stop": row["spent_micros"] + row["reserved_micros"]
                < row["hard_limit_micros"],
            }

    class _Transaction:
        def __init__(self, ledger: AtomicBudgetLedger) -> None:
            self.ledger = ledger

        def __enter__(self) -> sqlite3.Connection:
            self.ledger._lock.acquire()
            self.ledger._connection.execute("BEGIN IMMEDIATE")
            return self.ledger._connection

        def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
            try:
                self.ledger._connection.execute("ROLLBACK" if exc_type else "COMMIT")
            finally:
                self.ledger._lock.release()

    def _transaction(self) -> AtomicBudgetLedger._Transaction:
        return self._Transaction(self)


class SlidingWindowRateLimiter:
    def __init__(self, *, requests: int, window_seconds: int) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            values = self._events[key]
            while values and values[0] <= now - self.window_seconds:
                values.popleft()
            if len(values) >= self.requests:
                return False
            values.append(now)
            return True


SECRET_PATTERN = re.compile(
    r"(?i)(sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._~-]{12,}|"
    r"(?:api[_ -]?key|secret|token)\s*[:=]\s*\S+)"
)


def redact_sensitive(value: str, *, limit: int = 160) -> str:
    return SECRET_PATTERN.sub("[REDACTED]", value)[:limit]


class SafeAuditLog:
    def __init__(self, path: Path, *, max_field_characters: int = 160) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_field_characters = max_field_characters
        self._lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> None:
        permitted = {
            "request_id",
            "run_id",
            "session_id_hash",
            "release_id",
            "profile",
            "model_id",
            "status",
            "error_category",
            "reserved_cost_usd",
            "actual_cost_usd",
            "latency_ms",
            "input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "output_tokens",
            "file_search_calls",
            "deterministic_tool_calls",
            "local_compute_ms",
        }
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": redact_sensitive(event, limit=self.max_field_characters),
        }
        for key, value in fields.items():
            if key not in permitted or value is None:
                continue
            payload[key] = (
                redact_sensitive(str(value), limit=self.max_field_characters)
                if isinstance(value, str)
                else value
            )
        serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")

    @staticmethod
    def session_hash(session_id: str) -> str:
        return hashlib.sha256(session_id.encode()).hexdigest()[:16]


def load_cost_controls(path: Path) -> AICostControls:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AI cost controls must be one YAML mapping")
    return AICostControls.model_validate(payload)
