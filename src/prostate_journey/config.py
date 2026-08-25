"""Typed configuration loading and deterministic overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ScenarioConfig(BaseModel):
    """Validated scenario configuration while allowing documented extensions."""

    model_config = ConfigDict(extra="allow")
    disclaimer: str
    random_seed: int = 42
    target_cohort_size: int = Field(10000, gt=0)
    minimum_age: int = 50
    maximum_age: int = 90
    scenario_version: str = "demo-v1.0"
    observation_end_date: str = "2025-12-31"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge a small profile override into the base scenario."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path, **overrides: Any) -> dict[str, Any]:
    """Load YAML plus referenced market/clinical rules and apply CLI overrides."""
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if data.get("base_config_file"):
        base_path = source.parent / data["base_config_file"]
        base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
        data = _deep_merge(base, data)
    for file_key, payload_key in (
        ("market_config_file", "market_configuration"),
        ("clinical_rules_file", "clinical_rule_configuration"),
    ):
        if data.get(file_key):
            referenced = source.parent / data[file_key]
            data[payload_key] = yaml.safe_load(referenced.read_text(encoding="utf-8"))
    data.update({key: value for key, value in overrides.items() if value is not None})
    validated = ScenarioConfig.model_validate(data)
    return {**data, **validated.model_dump()}
