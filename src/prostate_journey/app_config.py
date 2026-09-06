"""Typed, secret-safe configuration for the local presentation application."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class OutputNamespaces(BaseModel):
    """Non-overlapping local output namespaces with explicit trust levels."""

    model_config = ConfigDict(extra="forbid")

    working_analytical: Path = Path("data/gold")
    working_reports: Path = Path("data/reports")
    certified_releases: Path = Path("data/releases")
    qa_evidence: Path = Path("outputs/industry_readiness")
    presentations: Path = Path("outputs/presentation")
    temporary: Path = Path(".test-work/runtime")
    experiments: Path = Path("outputs/experiments")


class ApplicationSettings(BaseModel):
    """Runtime contract for the aggregate-only application service."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_version: Literal["1.0"] = "1.0"
    service_name: str = "prostate-journey-analytics"
    environment: str = "local"
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=0, le=65535)
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    presentation_entrypoint: str = "executive_story.html"
    verify_release_hashes: bool = True
    readiness_cache_seconds: float = Field(default=30.0, ge=0, le=300)
    shutdown_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    paths: OutputNamespaces = Field(default_factory=OutputNamespaces)
    presentation_dir: Path | None = None
    project_root: Path = Path(".")
    openai_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @field_validator("service_name", "environment", "host", "log_level")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("configuration value cannot be blank")
        return value.strip()

    @field_validator("presentation_entrypoint")
    @classmethod
    def _safe_entrypoint(cls, value: str) -> str:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
            raise ValueError("presentation_entrypoint must be one safe relative filename")
        if candidate.suffix.lower() != ".html":
            raise ValueError("presentation_entrypoint must be an HTML file")
        return candidate.as_posix()


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true/false, yes/no, on/off, or 1/0")


def _resolve(root: Path, value: Path) -> Path:
    return (value if value.is_absolute() else root / value).resolve()


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_output_boundaries(settings: ApplicationSettings) -> None:
    """Fail when mutable, certified, presentation, and experiment paths overlap."""
    paths = settings.paths
    named = {
        "working_analytical": paths.working_analytical,
        "working_reports": paths.working_reports,
        "certified_releases": paths.certified_releases,
        "qa_evidence": paths.qa_evidence,
        "presentations": paths.presentations,
        "temporary": paths.temporary,
        "experiments": paths.experiments,
    }
    items = list(named.items())
    for index, (left_name, left_path) in enumerate(items):
        for right_name, right_path in items[index + 1 :]:
            if _is_within(left_path, right_path) or _is_within(right_path, left_path):
                raise ValueError(
                    f"Output namespaces overlap: {left_name}={left_path} and "
                    f"{right_name}={right_path}"
                )
    if settings.presentation_dir is not None and not _is_within(
        settings.presentation_dir, paths.presentations
    ):
        raise ValueError(
            "PROSTATE_JOURNEY_PRESENTATION_DIR must be inside the presentation namespace"
        )


def assert_mutable_output_path(
    settings: ApplicationSettings,
    candidate: str | Path,
    *,
    label: str,
) -> Path:
    """Reject a mutable output target that could touch a certified release."""
    output = _resolve(settings.project_root, Path(candidate))
    certified = settings.paths.certified_releases
    if _is_within(output, certified) or _is_within(certified, output):
        raise ValueError(f"{label} cannot overlap the certified release namespace: {output}")
    for parent in (output, *output.parents):
        if (parent / "IMMUTABLE_RELEASE").is_file():
            raise ValueError(f"{label} cannot write below an immutable release: {output}")
    return output


def load_application_settings(
    project_root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ApplicationSettings:
    """Load base YAML, one environment profile, environment variables, and CLI overrides."""
    root = Path(project_root).resolve()
    environment = dict(os.environ if environ is None else environ)
    selected_value: str | Path = (
        config_path
        if config_path is not None
        else environment.get("PROSTATE_JOURNEY_APP_CONFIG", str(root / "configs/application.yaml"))
    )
    selected_config = Path(selected_value)
    if not selected_config.is_absolute():
        selected_config = root / selected_config
    if not selected_config.is_file():
        raise FileNotFoundError(f"Application configuration is missing: {selected_config}")
    payload = yaml.safe_load(selected_config.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Application configuration must be a mapping: {selected_config}")

    profile_name = environment.get(
        "PROSTATE_JOURNEY_ENVIRONMENT", str(payload.get("environment", "local"))
    )
    profile_value = environment.get(
        "PROSTATE_JOURNEY_ENVIRONMENT_CONFIG",
        str(root / "configs" / "environments" / f"{profile_name}.yaml"),
    )
    profile_path = Path(profile_value)
    if not profile_path.is_absolute():
        profile_path = root / profile_path
    if profile_path.is_file():
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        if not isinstance(profile, dict):
            raise ValueError(f"Environment configuration must be a mapping: {profile_path}")
        payload = _deep_merge(payload, profile)

    scalar_environment_map = {
        "PROSTATE_JOURNEY_ENVIRONMENT": "environment",
        "PROSTATE_JOURNEY_HOST": "host",
        "PROSTATE_JOURNEY_PORT": "port",
        "PROSTATE_JOURNEY_LOG_LEVEL": "log_level",
        "PROSTATE_JOURNEY_LOG_FORMAT": "log_format",
        "PROSTATE_JOURNEY_PRESENTATION_DIR": "presentation_dir",
        "PROSTATE_JOURNEY_READINESS_CACHE_SECONDS": "readiness_cache_seconds",
    }
    for variable, field in scalar_environment_map.items():
        if variable in environment:
            payload[field] = environment[variable]
    if "PROSTATE_JOURNEY_VERIFY_RELEASE_HASHES" in environment:
        payload["verify_release_hashes"] = _parse_bool(
            "PROSTATE_JOURNEY_VERIFY_RELEASE_HASHES",
            environment["PROSTATE_JOURNEY_VERIFY_RELEASE_HASHES"],
        )
    path_environment_map = {
        "PROSTATE_JOURNEY_WORKING_DATA_ROOT": "working_analytical",
        "PROSTATE_JOURNEY_WORKING_REPORT_ROOT": "working_reports",
        "PROSTATE_JOURNEY_RELEASE_ROOT": "certified_releases",
        "PROSTATE_JOURNEY_QA_ROOT": "qa_evidence",
        "PROSTATE_JOURNEY_PRESENTATION_ROOT": "presentations",
        "PROSTATE_JOURNEY_TEMP_ROOT": "temporary",
        "PROSTATE_JOURNEY_EXPERIMENT_ROOT": "experiments",
    }
    path_payload = dict(payload.get("paths", {}))
    for variable, field in path_environment_map.items():
        if variable in environment:
            path_payload[field] = environment[variable]
    payload["paths"] = path_payload
    payload["openai_api_key"] = environment.get("OPENAI_API_KEY") or None
    payload["project_root"] = root
    if overrides:
        explicit = {key: value for key, value in overrides.items() if value is not None}
        payload = _deep_merge(payload, explicit)

    settings = ApplicationSettings.model_validate(payload)
    resolved_paths = OutputNamespaces(
        **{name: _resolve(root, value) for name, value in settings.paths.model_dump().items()}
    )
    presentation_dir = (
        _resolve(root, settings.presentation_dir) if settings.presentation_dir is not None else None
    )
    resolved = settings.model_copy(
        update={
            "project_root": root,
            "paths": resolved_paths,
            "presentation_dir": presentation_dir,
        }
    )
    validate_output_boundaries(resolved)
    return resolved
