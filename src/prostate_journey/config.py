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


def load_config(path: str | Path, **overrides: Any) -> dict[str, Any]:
    """Load YAML, validate core fields, and apply non-null CLI overrides."""
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    data.update({key: value for key, value in overrides.items() if value is not None})
    validated = ScenarioConfig.model_validate(data)
    return {**data, **validated.model_dump()}

