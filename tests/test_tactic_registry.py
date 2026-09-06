from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from prostate_journey.executive_dashboard import build_executive_payload
from prostate_journey.tactic_registry import (
    TACTIC_CATEGORIES,
    TacticRegistry,
    load_tactic_registry,
    validate_tactic_source_paths,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "configs" / "tactic_registry.yaml"


def test_canonical_tactic_registry_is_complete_unique_and_source_valid() -> None:
    registry = load_tactic_registry(REGISTRY_PATH)

    assert registry.synthetic_only is True
    assert len(registry.tactics) == 10
    assert len({tactic.tactic_id for tactic in registry.tactics}) == 10
    assert {tag for tactic in registry.tactics for tag in tactic.tags} == TACTIC_CATEGORIES
    validate_tactic_source_paths(registry, ROOT)
    for tactic in registry.tactics:
        assert tactic.numerator_definition
        assert tactic.denominator_definition
        assert tactic.evidence_files
        assert tactic.required_real_data_fields
        assert tactic.prohibited_interpretations


def test_tactic_registry_schema_rejects_duplicate_ids_and_unsafe_paths() -> None:
    registry = load_tactic_registry(REGISTRY_PATH)
    duplicate = registry.model_dump(mode="json")
    duplicate["tactics"][1]["tactic_id"] = duplicate["tactics"][0]["tactic_id"]
    with pytest.raises(ValidationError, match="Tactic IDs must be unique"):
        TacticRegistry.model_validate(duplicate)

    unsafe = registry.model_dump(mode="json")
    unsafe["tactics"][0]["evidence_files"] = ["../patient.parquet"]
    with pytest.raises(ValidationError, match="unsafe artifact path"):
        TacticRegistry.model_validate(unsafe)


def test_frontend_payload_consumes_registry_and_reconciles_denominators(generated_tables) -> None:
    registry = load_tactic_registry(REGISTRY_PATH)
    payload = build_executive_payload(generated_tables, registry=registry)
    overall = payload["segments"]["ALL"]

    assert payload["synthetic_only"] is True
    assert [item["tactic_id"] for item in payload["tactics"]] == [
        tactic.tactic_id for tactic in registry.tactics
    ]
    for window in overall["initiation_windows"]:
        assert window["value"] + window["gap"] + window["censored"] == overall["eligible"]
        assert window["value"] + window["gap"] == window["evaluable"]
    for persistence in overall["persistence_sensitivity"]:
        assert persistence["evaluable"] + persistence["censored"] <= persistence["at_risk"]


def test_frontend_assets_encode_accessible_deterministic_controls() -> None:
    javascript = (ROOT / "src" / "prostate_journey" / "frontend" / "analytics.js").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "src" / "prostate_journey" / "frontend" / "analytics.css").read_text(
        encoding="utf-8"
    )

    assert "DENOMINATOR CHANGED" in javascript
    assert "SYNTHETIC SCENARIO" in javascript
    assert "presentationSteps" in javascript
    assert "downloadPng" in javascript
    assert "patient" not in " ".join(
        part for part in javascript.split('href = "') if part.endswith(".parquet")
    )
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 760px)" in css
