import json
from pathlib import Path

import pandas as pd
import pytest

from prostate_journey.dataset_resolver import (
    CERTIFIED_DECISION,
    resolve_analytical_dataset,
)
from prostate_journey.executive_dashboard import build_executive_payload
from prostate_journey.frontend_validation import validate_frontend_package
from prostate_journey.pipeline import TABLES
from prostate_journey.presentation import (
    PREDICTIVE_PRESENTATION_FILES,
    build_presentation_package,
)


def _write_release(
    project_root: Path,
    tables: dict[str, pd.DataFrame],
    name: str,
    created_at: str,
    decision: str = CERTIFIED_DECISION,
) -> Path:
    release = project_root / "data" / "releases" / name
    analytical = release / "analytical_dataset"
    analytical.mkdir(parents=True)
    for table in TABLES:
        tables[table].to_parquet(analytical / f"{table}.parquet", index=False)
    manifest = {
        "dataset_version": name,
        "created_at": created_at,
        "decision": decision,
        "analytical_dataset_directory": "analytical_dataset",
        "git": {"git_commit": "abc123", "git_branch": "dev", "source_clean": True},
        "run_metadata": {
            "config_snapshot_sha256": "f" * 64,
            "generator_version": "2.2.0",
            "scenario_version": "test-v2.2",
            "clinical_rules_version": "CLINICAL-RULES-v2.2",
            "market_configuration_version": "MARKET-PROFILE-v1.0",
        },
    }
    (release / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return analytical


def test_resolver_selects_newest_complete_certified_release(tmp_path, generated_tables):
    old = _write_release(tmp_path, generated_tables, "release-old", "2026-01-01T00:00:00Z")
    newest = _write_release(tmp_path, generated_tables, "release-new", "2026-02-01T00:00:00Z")
    _write_release(
        tmp_path,
        generated_tables,
        "release-uncertified",
        "2026-03-01T00:00:00Z",
        decision="NOT CERTIFIED",
    )

    selected = resolve_analytical_dataset(tmp_path, TABLES)

    assert selected.analytical_dir == newest.resolve()
    assert selected.analytical_dir != old.resolve()
    assert selected.dataset_version == "release-new"
    assert selected.selection_method == "newest complete certified release"


def test_presentation_package_is_provenance_locked_and_aggregate_only(tmp_path, generated_tables):
    analytical = _write_release(
        tmp_path, generated_tables, "release-certified", "2026-02-01T00:00:00Z"
    )
    before_release = {
        path.relative_to(analytical.parent).as_posix(): path.read_bytes()
        for path in analytical.parent.rglob("*")
        if path.is_file()
    }

    output = build_presentation_package(tmp_path, output_root=tmp_path / "presentation")

    manifest = json.loads((output / "presentation_manifest.json").read_text(encoding="utf-8"))
    kpis = pd.read_csv(output / "presentation_kpis.csv").set_index("kpi")["value"]
    dashboard = (output / "cohort_dashboard.html").read_text(encoding="utf-8")
    executive = (output / "executive_story.html").read_text(encoding="utf-8")
    assert manifest["dataset_version"] == "release-certified"
    assert manifest["analytical_dataset_directory"] == str(analytical.resolve())
    assert manifest["consistency_gate"] == "PASSED"
    assert manifest["patient_level_data_included"] is False
    assert manifest["configuration_hash"] == "f" * 64
    assert manifest["code_version"] == "2.2.0"
    assert set(manifest["artifact_provenance"]) == set(manifest["output_files"])
    assert "release-certified" in dashboard
    assert f"{int(kpis['eligible']):,}" in dashboard
    assert f"{int(kpis['initiated_90d_among_eligible']):,}" in dashboard
    assert "Patient Journey Explorer" in executive
    assert "dashboardData" in executive
    assert "Open every analytical tactic" in executive
    assert "Tactic Library v2" in executive
    assert "Denominator Inspector" in executive
    assert "Evidence &amp; Provenance" in executive
    assert "Presentation Mode" in executive
    assert "SYNTHETIC SCENARIO — NOT REAL PATIENT" in executive
    assert "release-certified" in executive
    assert 'href="#main-content"' in executive
    assert ":focus-visible" in (output / "assets" / "analytics.css").read_text(encoding="utf-8")
    assert "350 synthetic patients" in executive
    assert f'"eligible":{int(kpis["eligible"])}' in executive
    assert manifest["tactic_registry"]["tactic_count"] == 10
    assert manifest["exports"]["patient_level_export"] is False
    assert (output / "tactic_registry.json").is_file()
    assert (output / "accessible_report.html").is_file()
    assert (output / "aggregate_export.csv").is_file()
    assert (output / "evidence_manifest.json").is_file()
    assert (output / "demo_fallback.html").is_file()
    assert len(list((output / "fallback").glob("*.svg"))) == 4
    assert validate_frontend_package(output) == []
    aggregate_export = pd.read_csv(output / "aggregate_export.csv")
    assert {
        "numerator",
        "denominator",
        "population",
        "time_window",
        "release_id",
        "source_commit",
        "active_filters",
        "generated_time",
        "prohibited_use",
        "synthetic_only",
    }.issubset(aggregate_export.columns)
    assert set(aggregate_export.release_id) == {"release-certified"}
    evidence_manifest = json.loads((output / "evidence_manifest.json").read_text(encoding="utf-8"))
    assert evidence_manifest["patient_level_data_included"] is False
    assert evidence_manifest["release_id"] == "release-certified"
    assert "tactic_registry.json" in evidence_manifest["artifacts"]
    assert evidence_manifest["primary_metric"]["numerator"] == int(
        kpis["initiated_90d_among_eligible"]
    )
    assert evidence_manifest["primary_metric"]["denominator"] == int(kpis["eligible"])
    assert evidence_manifest["primary_metric"]["method"]
    fallback = (output / "fallback" / "01-executive-overview.svg").read_text(encoding="utf-8")
    assert "source: abc123" in fallback
    assert f"{int(kpis['initiated_90d_among_eligible']):,}/{int(kpis['eligible']):,}" in fallback
    assert "Method:" in fallback
    assert "generated:" in fallback
    assert {
        path.relative_to(analytical.parent).as_posix(): path.read_bytes()
        for path in analytical.parent.rglob("*")
        if path.is_file()
    } == before_release
    assert not list(output.glob("*.parquet"))


def test_presentation_requires_certified_release(tmp_path):
    with pytest.raises(FileNotFoundError, match="No complete certified analytical release"):
        build_presentation_package(tmp_path)


def test_executive_payload_reconciles_market_aggregates(generated_tables):
    payload = build_executive_payload(generated_tables)
    market_segments = [payload["segments"][market] for market in payload["markets"]]

    assert len(payload["markets"]) == 7
    assert len(payload["tactics"]) == 10
    assert {tactic["tactic_id"] for tactic in payload["tactics"]} == {
        "cohort_definition",
        "initiation_landmarks",
        "censoring_evaluability",
        "persistence_sensitivity",
        "time_to_initiation",
        "referral_pathway",
        "segmented_treatment_gap",
        "missingness_profile",
        "model_disposition",
        "evidence_governance",
    }
    assert (
        sum(segment["total"] for segment in market_segments) == payload["segments"]["ALL"]["total"]
    )
    assert (
        sum(segment["eligible"] for segment in market_segments)
        == payload["segments"]["ALL"]["eligible"]
    )
    assert generated_tables["patient_journey"].patient_id.iloc[0] not in json.dumps(payload)


def test_presentation_integrates_release_matched_predictive_evidence(
    tmp_path, generated_tables, monkeypatch
):
    analytical = _write_release(
        tmp_path, generated_tables, "release-with-models", "2026-04-01T00:00:00Z"
    )
    predictive = tmp_path / "predictive"
    predictive.mkdir()
    for filename in PREDICTIVE_PRESENTATION_FILES:
        path = predictive / filename
        if path.suffix == ".json":
            path.write_text("{}", encoding="utf-8")
        else:
            path.write_text("aggregate evidence\n", encoding="utf-8")
    (predictive / "predictive_evidence_manifest.json").write_text(
        json.dumps(
            {
                "release": "release-with-models",
                "source_commit": "abc123",
                "analysis_commit": "abc123",
                "analysis_worktree_clean": True,
                "configuration_hash": "f" * 64,
                "configuration_component_hashes": {
                    "model_target_contracts_snapshot.yaml": "f" * 64,
                    "model_evaluation_snapshot.yaml": "f" * 64,
                    "model_governance_snapshot.yaml": "f" * 64,
                    "model_aliases_snapshot.yaml": "f" * 64,
                },
                "patient_level_predictions_included": False,
                "deployable": False,
            }
        ),
        encoding="utf-8",
    )
    cards = predictive / "model_cards"
    cards.mkdir()
    (cards / "one.md").write_text("aggregate model card", encoding="utf-8")
    (cards / "one.json").write_text("{}", encoding="utf-8")
    (cards / "index.json").write_text(
        json.dumps(
            [
                {
                    "model_id": "one",
                    "markdown": "one.md",
                    "json": "one.json",
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "prostate_journey.presentation.verify_predictive_evidence_manifest",
        lambda _path: None,
    )

    def write_stub(_source, output_dir, provenance):
        path = Path(output_dir) / "model_story.html"
        path.write_text(
            '<!doctype html><html lang="en"><main>SYNTHETIC release-with-models '
            "Model Evidence Lab modelEvidenceData 0 deployable models</main></html>",
            encoding="utf-8",
        )
        return path

    monkeypatch.setattr("prostate_journey.presentation.write_predictive_dashboard", write_stub)
    output = build_presentation_package(
        tmp_path,
        dataset_dir=analytical,
        output_root=tmp_path / "presentation-models",
        scientific_dir=tmp_path / "no-science",
        simulation_dir=tmp_path / "no-simulation",
        predictive_dir=predictive,
    )
    manifest = json.loads((output / "presentation_manifest.json").read_text(encoding="utf-8"))
    executive = (output / "executive_story.html").read_text(encoding="utf-8")
    assert manifest["predictive_evidence"]["available"] is True
    assert manifest["predictive_evidence"]["deployable_models"] == 0
    assert manifest["predictive_evidence"]["analysis_worktree_clean"] is True
    assert manifest["predictive_evidence"]["patient_level_predictions_included"] is False
    assert "model_cards/one.md" in manifest["output_files"]
    assert 'href="model_story.html">Model evidence' in executive
    assert (output / "model_story.html").is_file()
