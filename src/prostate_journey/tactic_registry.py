"""Typed canonical metadata registry for deterministic analytical tactics."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TACTIC_CATEGORIES = {
    "Cohort",
    "Longitudinal",
    "Treatment",
    "Referral",
    "Missingness",
    "Data Quality",
    "Predictive",
    "Governance",
}
DEFAULT_TACTIC_REGISTRY = Path(__file__).resolve().parents[2] / "configs" / "tactic_registry.yaml"


class TacticDefinition(BaseModel):
    """One versioned tactic contract; results remain external aggregate evidence."""

    model_config = ConfigDict(extra="forbid")

    tactic_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    version: str
    title: str = Field(min_length=5)
    category: str
    tags: list[str] = Field(min_length=1)
    question: str = Field(min_length=10)
    why: str = Field(min_length=10)
    analysis_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    target_population: str
    numerator_definition: str
    denominator_definition: str
    numerator_key: str
    denominator_key: str
    index_date: str
    time_horizon: str
    method: str
    parameters: dict[str, Any]
    default_parameters: dict[str, Any]
    aggregate_result_source: str
    methodology_source: str
    limitation_source: str
    evidence_files: list[str] = Field(min_length=1)
    release_compatibility: str
    reviewer_status: str
    synthetic_only: Literal[True]
    interpretation: str
    limitation: str
    required_real_data_fields: list[str] = Field(min_length=1)
    prohibited_interpretations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> TacticDefinition:
        if not re.fullmatch(r"\d+\.\d+\.\d+", self.version):
            raise ValueError(f"Tactic {self.tactic_id} version must be semantic")
        if self.category not in TACTIC_CATEGORIES:
            raise ValueError(f"Unknown tactic category: {self.category}")
        unknown_tags = set(self.tags) - TACTIC_CATEGORIES
        if unknown_tags:
            raise ValueError(f"Unknown tactic tags: {sorted(unknown_tags)}")
        for value in (
            self.aggregate_result_source,
            self.methodology_source,
            self.limitation_source,
            *self.evidence_files,
        ):
            _validate_relative_path(value, self.tactic_id)
        return self


class TacticRegistry(BaseModel):
    """Top-level registry contract shared by the frontend and future Evidence Copilot."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["TACTIC-REGISTRY-v2.0"]
    registry_status: Literal["ENGINEERING DEFINITION"]
    synthetic_only: Literal[True]
    default_release_policy: Literal["ONE_EXPLICIT_CERTIFIED_RELEASE"]
    prohibited_interpretations: list[str] = Field(min_length=1)
    tactics: list[TacticDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_tactics(self) -> TacticRegistry:
        identifiers = [tactic.tactic_id for tactic in self.tactics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Tactic IDs must be unique")
        if len(self.tactics) != 10:
            raise ValueError("The governed Tactic Library v2 must contain exactly ten tactics")
        covered = {tag for tactic in self.tactics for tag in tactic.tags}
        missing_categories = sorted(TACTIC_CATEGORIES - covered)
        if missing_categories:
            raise ValueError(f"Tactic filters have no registered content: {missing_categories}")
        return self


def _validate_relative_path(value: str, tactic_id: str) -> None:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not value.strip():
        raise ValueError(f"Tactic {tactic_id} contains an unsafe artifact path: {value}")


def load_tactic_registry(path: str | Path) -> TacticRegistry:
    """Read and validate the canonical tactic registry."""
    registry_path = Path(path)
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a tactic-registry mapping: {registry_path}")
    return TacticRegistry.model_validate(payload)


def validate_tactic_source_paths(registry: TacticRegistry, project_root: str | Path) -> None:
    """Require every repository methodology/limitation source to resolve locally."""
    root = Path(project_root).resolve()
    missing: list[str] = []
    for tactic in registry.tactics:
        for source in (tactic.methodology_source, tactic.limitation_source):
            path = (root / source).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                missing.append(f"{tactic.tactic_id}:{source}")
    if missing:
        raise FileNotFoundError(f"Tactic source files are missing: {sorted(missing)}")


def registry_json(registry: TacticRegistry) -> str:
    """Return a deterministic, portable registry snapshot for presentation packages."""
    return json.dumps(registry.model_dump(mode="json"), indent=2, sort_keys=True)
