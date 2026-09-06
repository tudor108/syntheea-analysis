"""Typed, server-side-only configuration for the optional AI Analysis Studio."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class AIStudioSettings(BaseModel):
    """Configuration isolated from the deterministic Analytics application."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_version: Literal["1.0"] = "1.0"
    enabled: bool = True
    provider_enabled: bool = True
    service_name: str = "prostate-journey-ai-studio"
    environment: str = "local"
    host: str = "127.0.0.1"
    port: int = Field(default=8090, ge=0, le=65535)
    model: str = "gpt-5.6-luna"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    output_verbosity: Literal["low", "medium", "high"] = "low"
    max_output_tokens: int = Field(default=900, ge=256, le=2500)
    retrieval_top_k: int = Field(default=4, ge=1, le=6)
    memory_turns: int = Field(default=4, ge=0, le=10)
    summary_character_limit: int = Field(default=1600, ge=256, le=8000)
    max_question_characters: int = Field(default=2400, ge=100, le=10000)
    request_timeout_seconds: float = Field(default=90, gt=0, le=300)
    vector_sync_timeout_seconds: float = Field(default=180, gt=0, le=900)
    cost_controls_path: Path = Path("configs/ai_cost_controls.yaml")
    budget_ledger_path: Path = Path("outputs/experiments/ai_studio/budget_ledger.sqlite3")
    audit_log_path: Path = Path("outputs/experiments/ai_studio/audit.jsonl")
    catalogue_path: Path = Path("outputs/experiments/ai_studio/artifact_catalogue.json")
    vector_store_state_path: Path = Path("outputs/experiments/ai_studio/vector_store_state.json")
    index_staging_directory: Path = Path("outputs/experiments/ai_studio/index_payload")
    analytics_url: str = "http://127.0.0.1:8080/"
    specialist_model: str = "gpt-5.6-terra"
    specialist_reasoning_effort: Literal["medium"] = "medium"
    specialist_max_output_tokens: int = Field(default=2500, ge=512, le=2500)
    specialist_max_runtime_seconds: int = Field(default=20, ge=1, le=120)
    specialist_max_cpu_seconds: int = Field(default=15, ge=1, le=120)
    specialist_max_memory_mb: int = Field(default=256, ge=64, le=2048)
    specialist_max_output_bytes: int = Field(default=1_000_000, ge=10_000, le=10_000_000)
    specialist_max_disk_bytes: int = Field(default=2_000_000, ge=10_000, le=20_000_000)
    interactive_runs_directory: Path = Path("outputs/experiments/ai_studio/interactive_runs")
    interactive_run_ttl_days: int = Field(default=7, ge=1, le=90)
    expert_lenses_path: Path = Path("configs/expert_lenses.yaml")
    analysis_registry_path: Path = Path("contracts/analysis_registry.yaml")
    authentication_mode: Literal["local", "bearer"] = "local"
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:8090", "http://localhost:8090"]
    )
    project_root: Path = Path(".")
    openai_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    vector_store_id: SecretStr | None = Field(default=None, exclude=True, repr=False)
    access_token: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("service_name", "environment", "host", "model", "specialist_model")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("AI Studio configuration values cannot be blank")
        return value.strip()

    @field_validator("analytics_url")
    @classmethod
    def _safe_analytics_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("local analytics_url must use localhost or 127.0.0.1")
        return normalized if normalized.endswith("/") else f"{normalized}/"

    @model_validator(mode="after")
    def _secure_binding(self) -> AIStudioSettings:
        loopback = self.host in {"127.0.0.1", "localhost", "::1"}
        if (not loopback or self.environment != "local") and (
            self.authentication_mode != "bearer" or self.access_token is None
        ):
            raise ValueError("non-local AI Studio requires bearer authentication")
        if self.authentication_mode == "bearer" and self.access_token is None:
            raise ValueError("bearer authentication requires AI_STUDIO_ACCESS_TOKEN")
        return self


def _read_local_secret_file(path: Path) -> dict[str, str]:
    """Read only recognized local environment keys without logging their values."""
    if not path.is_file():
        return {}
    allowed = {
        "OPENAI_API_KEY",
        "OPENAI_VECTOR_STORE_ID",
        "AI_STUDIO_MODEL",
        "AI_STUDIO_HOST",
        "AI_STUDIO_PORT",
        "AI_STUDIO_ACCESS_TOKEN",
        "AI_ANALYSIS_STUDIO_ENABLED",
        "AI_STUDIO_PROVIDER_ENABLED",
        "AI_STUDIO_INTERACTIVE_RUN_TTL_DAYS",
    }
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() in allowed:
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def _within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def load_ai_studio_settings(
    project_root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> AIStudioSettings:
    """Load config and local secrets while keeping secrets out of serialized settings."""
    root = Path(project_root).resolve()
    if environ is None:
        environment = dict(os.environ)
        for name, value in _read_local_secret_file(root / ".env").items():
            environment.setdefault(name, value)
    else:
        environment = dict(environ)

    selected = Path(config_path or root / "configs" / "ai_studio.yaml")
    if not selected.is_absolute():
        selected = root / selected
    payload = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"AI Studio configuration must be a mapping: {selected}")

    environment_map = {
        "AI_ANALYSIS_STUDIO_ENABLED": "enabled",
        "AI_STUDIO_PROVIDER_ENABLED": "provider_enabled",
        "AI_STUDIO_ENVIRONMENT": "environment",
        "AI_STUDIO_HOST": "host",
        "AI_STUDIO_PORT": "port",
        "AI_STUDIO_MODEL": "model",
        "AI_STUDIO_REASONING_EFFORT": "reasoning_effort",
        "AI_STUDIO_OUTPUT_VERBOSITY": "output_verbosity",
        "AI_STUDIO_MAX_OUTPUT_TOKENS": "max_output_tokens",
        "AI_STUDIO_RETRIEVAL_TOP_K": "retrieval_top_k",
        "AI_STUDIO_ANALYTICS_URL": "analytics_url",
        "AI_STUDIO_CATALOGUE_PATH": "catalogue_path",
        "AI_STUDIO_VECTOR_STATE_PATH": "vector_store_state_path",
        "AI_STUDIO_INDEX_STAGING_DIRECTORY": "index_staging_directory",
        "AI_STUDIO_SPECIALIST_MODEL": "specialist_model",
        "AI_STUDIO_INTERACTIVE_RUNS_DIRECTORY": "interactive_runs_directory",
        "AI_STUDIO_INTERACTIVE_RUN_TTL_DAYS": "interactive_run_ttl_days",
        "AI_STUDIO_COST_CONTROLS_PATH": "cost_controls_path",
        "AI_STUDIO_BUDGET_LEDGER_PATH": "budget_ledger_path",
        "AI_STUDIO_AUDIT_LOG_PATH": "audit_log_path",
        "AI_STUDIO_AUTHENTICATION_MODE": "authentication_mode",
    }
    for variable, field_name in environment_map.items():
        if variable in environment:
            payload[field_name] = environment[variable]
    payload["openai_api_key"] = environment.get("OPENAI_API_KEY") or None
    payload["vector_store_id"] = environment.get("OPENAI_VECTOR_STORE_ID") or None
    payload["access_token"] = environment.get("AI_STUDIO_ACCESS_TOKEN") or None
    payload["project_root"] = root
    if overrides:
        payload.update({key: value for key, value in overrides.items() if value is not None})

    settings = AIStudioSettings.model_validate(payload)
    resolved = settings.model_copy(
        update={
            "project_root": root,
            "catalogue_path": _resolve(root, settings.catalogue_path),
            "cost_controls_path": _resolve(root, settings.cost_controls_path),
            "budget_ledger_path": _resolve(root, settings.budget_ledger_path),
            "audit_log_path": _resolve(root, settings.audit_log_path),
            "vector_store_state_path": _resolve(root, settings.vector_store_state_path),
            "index_staging_directory": _resolve(root, settings.index_staging_directory),
            "interactive_runs_directory": _resolve(root, settings.interactive_runs_directory),
            "expert_lenses_path": _resolve(root, settings.expert_lenses_path),
            "analysis_registry_path": _resolve(root, settings.analysis_registry_path),
        }
    )
    experiment_root = (root / "outputs" / "experiments").resolve()
    for label, path in {
        "catalogue_path": resolved.catalogue_path,
        "budget_ledger_path": resolved.budget_ledger_path,
        "audit_log_path": resolved.audit_log_path,
        "vector_store_state_path": resolved.vector_store_state_path,
        "index_staging_directory": resolved.index_staging_directory,
        "interactive_runs_directory": resolved.interactive_runs_directory,
    }.items():
        if not _within(path, experiment_root):
            raise ValueError(f"{label} must remain inside outputs/experiments: {path}")
    for label, path in {
        "expert_lenses_path": resolved.expert_lenses_path,
        "analysis_registry_path": resolved.analysis_registry_path,
        "cost_controls_path": resolved.cost_controls_path,
    }.items():
        if not _within(path, root):
            raise ValueError(f"{label} must remain inside the project root: {path}")
    return resolved
