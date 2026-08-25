import json
import subprocess
import zipfile
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from prostate_journey.release_packager import (
    ReleasePackagingError,
    assert_final_scorecard,
    assert_new_empty_release_dir,
    assert_release_scores,
    copy_versioned_context,
    create_separate_release_archives,
    package_certified_release,
    reload_and_verify_exported_artifacts,
    run_release_tests,
    sha256_file,
    write_component_hash_manifests,
    write_final_release_files,
)


def _write_table_contract(gold: Path, table: str, frame: pd.DataFrame) -> None:
    frame.to_csv(gold / f"{table}.csv", index=False, date_format="%Y-%m-%d")
    frame.to_parquet(gold / f"{table}.parquet", index=False)


def test_new_release_directory_is_never_reused(tmp_path):
    release = tmp_path / "release-v1"
    created = assert_new_empty_release_dir(release)
    assert created == release.resolve()
    assert (created / ".release-in-progress").is_file()
    with pytest.raises(ReleasePackagingError, match="cannot be reused"):
        assert_new_empty_release_dir(release)


def test_export_parity_reloads_csv_parquet_and_duckdb(tmp_path):
    gold = tmp_path / "gold"
    gold.mkdir()
    patient = pd.DataFrame(
        {
            "patient_id": ["P-001", "P-002"],
            "postal_code_prefix": ["00123", "90210"],
            "index_date": pd.to_datetime(["2024-01-01", "2024-02-02"]),
            "eligible": [True, False],
            "score": [1.25, 2.5],
        }
    )
    outcome = pd.DataFrame({"outcome_id": ["O-1", "O-2"], "patient_id": ["P-001", "P-002"]})
    _write_table_contract(gold, "patient", patient)
    _write_table_contract(gold, "outcome", outcome)
    database = gold / "prostate_journey.duckdb"
    connection = duckdb.connect(str(database))
    try:
        connection.register("patient_frame", patient)
        connection.register("outcome_frame", outcome)
        connection.execute("CREATE TABLE patient AS SELECT * FROM patient_frame")
        connection.execute("CREATE TABLE outcome AS SELECT * FROM outcome_frame")
    finally:
        connection.close()

    tables, evidence = reload_and_verify_exported_artifacts(gold, ["patient", "outcome"])
    assert len(tables["patient"]) == 2
    assert evidence["verified_table_count"] == 2
    assert evidence["tables"]["outcome"]["duckdb_rows"] == 2

    corrupted = pd.read_csv(gold / "patient.csv", dtype="string")
    corrupted.loc[0, "score"] = "99"
    corrupted.to_csv(gold / "patient.csv", index=False)
    with pytest.raises(ReleasePackagingError, match="content mismatch"):
        reload_and_verify_exported_artifacts(gold, ["patient", "outcome"])


def test_release_tests_write_json_markdown_and_junit_and_fail_closed(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    qa = tmp_path / "qa"

    def passing_runner(command, **_kwargs):
        junit_argument = next((value for value in command if value.startswith("--junitxml=")), None)
        if junit_argument:
            junit = Path(junit_argument.split("=", 1)[1])
            junit.parent.mkdir(parents=True, exist_ok=True)
            junit.write_text(
                '<testsuite name="tests" tests="3" failures="0" errors="0" '
                'skipped="0" time="0.2"/>',
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    report = run_release_tests(project, qa, python_executable="python", runner=passing_runner)
    assert report["passed"] is True
    assert report["junit"]["tests"] == 3
    assert {"test_report.json", "test_report.md", "test_report.xml"} <= {
        path.name for path in qa.iterdir()
    }

    def failing_runner(command, **kwargs):
        completed = passing_runner(command, **kwargs)
        if "ruff" in command:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="lint failure")
        return completed

    with pytest.raises(ReleasePackagingError, match="Ruff or pytest failed"):
        run_release_tests(project, tmp_path / "failed-qa", runner=failing_runner)
    failed_payload = json.loads(
        (tmp_path / "failed-qa" / "test_report.json").read_text(encoding="utf-8")
    )
    assert failed_payload["passed"] is False


def test_scores_reject_partial_or_non_100_release(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "data_quality_summary.json").write_text(
        json.dumps({"critical_failures": 0, "rules": []}), encoding="utf-8"
    )
    (reports / "readiness_audit.json").write_text(
        json.dumps(
            {
                "overall_readiness_score": 100,
                "maximum_score": 100,
                "failed_requirements": [],
                "partial_requirements": [9],
                "p0_p1_failures": [],
            }
        ),
        encoding="utf-8",
    )
    (reports / "adversarial_audit.json").write_text(
        json.dumps(
            {
                "independent_audit_score": 100,
                "maximum_score": 100,
                "p0_blockers_remaining": 0,
                "p1_issues_remaining": 0,
                "ready_for_bayer_diagnostic": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReleasePackagingError, match="non-passing requirements"):
        assert_release_scores(reports)


def test_final_scorecard_requires_all_11_dimensions_to_be_perfect(tmp_path):
    scorecard = tmp_path / "final_scorecard.csv"
    frame = pd.DataFrame(
        {
            "dimension": [f"dimension-{index}" for index in range(11)],
            "score_0_100": [100] * 11,
            "status": ["PASS"] * 11,
            "remaining_deficiency": ["NONE"] * 11,
        }
    )
    frame.to_csv(scorecard, index=False)
    summary = assert_final_scorecard(scorecard)
    assert summary["overall_score"] == 100
    assert summary["dimensions"] == 11

    frame.loc[7, "remaining_deficiency"] = "missing evidence"
    frame.to_csv(scorecard, index=False)
    with pytest.raises(ReleasePackagingError, match="not uniformly"):
        assert_final_scorecard(scorecard)


def test_manifests_separate_archives_and_final_checksums(tmp_path):
    project = tmp_path / "project"
    for directory in ("src", "tests", "scripts", "configs", "docs"):
        (project / directory).mkdir(parents=True)
        (project / directory / "evidence.txt").write_text(directory, encoding="utf-8")
    for filename in ("pyproject.toml", "requirements.txt", "README.md", "Makefile"):
        (project / filename).write_text(filename, encoding="utf-8")
    for filename in (
        "ER_SCHEMA.md",
        "DATA_DICTIONARY.md",
        "COHORT_ANALYSIS.md",
        "SYNTHETIC_ASSUMPTIONS.md",
    ):
        (project / "docs" / filename).write_text(filename, encoding="utf-8")
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "patients.csv").write_text("Id\nP-1\n", encoding="utf-8")

    release = assert_new_empty_release_dir(tmp_path / "release")
    analytical = release / "analytical_dataset"
    qa = release / "qa_evidence"
    analytical.mkdir()
    qa.mkdir()
    (analytical / "patient.parquet").write_bytes(b"synthetic-parquet")
    (qa / "audit.json").write_text('{"score": 100}', encoding="utf-8")
    copy_versioned_context(project, qa, analytical_dir=analytical)
    assert (analytical / "docs" / "ER_SCHEMA.md").is_file()
    assert (analytical / "README.md").is_file()
    manifests = write_component_hash_manifests(project, inputs, release, qa)
    assert all(manifest["file_count"] > 0 for manifest in manifests.values())

    archives = create_separate_release_archives(release, "diagnostic-v2.1")
    assert archives["analytical"]["sha256"] == sha256_file(release / archives["analytical"]["path"])
    with zipfile.ZipFile(release / archives["qa_evidence"]["path"]) as archive:
        assert any(name.startswith("qa_evidence/") for name in archive.namelist())

    test_report = {
        "passed": True,
        "junit": {"tests": 3, "failures": 0, "errors": 0},
        "commands": {
            "ruff": {"exit_code": 0, "duration_seconds": 0.1},
            "pytest": {"exit_code": 0, "duration_seconds": 0.2},
        },
    }
    bad_archives = {name: dict(value) for name, value in archives.items()}
    bad_archives["analytical"]["sha256"] = "0" * 64
    with pytest.raises(ReleasePackagingError, match="archive SHA-256 mismatch"):
        write_final_release_files(
            release,
            dataset_version="diagnostic-v2.1",
            git_info={"git_commit": "abc", "git_branch": "dev", "source_clean": True},
            run_metadata={"random_seed": 42},
            gate_summary={
                "overall_readiness_score": 100,
                "p0_blockers": 0,
                "p1_issues": 0,
                "hard_failures": 0,
            },
            parity_evidence={"verified_table_count": 19},
            test_report=test_report,
            archive_hashes=bad_archives,
        )
    manifest = write_final_release_files(
        release,
        dataset_version="diagnostic-v2.1",
        git_info={"git_commit": "abc", "git_branch": "dev", "source_clean": True},
        run_metadata={"random_seed": 42},
        gate_summary={
            "overall_readiness_score": 100,
            "p0_blockers": 0,
            "p1_issues": 0,
            "hard_failures": 0,
        },
        parity_evidence={"verified_table_count": 19},
        test_report=test_report,
        archive_hashes=archives,
    )
    assert manifest["decision"] == "CERTIFIED — READY FOR BAYER ANALYSIS"
    assert not (release / ".release-in-progress").exists()
    persisted_manifest = json.loads((release / "release_manifest.json").read_text(encoding="utf-8"))
    assert persisted_manifest == manifest
    assert (release / "IMMUTABLE_RELEASE").exists()
    assert (release / "RELEASE_DECISION.md").exists()
    assert (release / "release_manifest.json").exists()
    checksums = (release / "CHECKSUMS.sha256").read_text(encoding="utf-8")
    assert "archives/diagnostic-v2.1-analytical.zip" in checksums


def test_package_orchestration_passes_reconciliation_into_evidence(tmp_path, monkeypatch):
    from prostate_journey import pipeline

    monkeypatch.setattr(pipeline, "TABLES", ("patient", "outcome"))
    project = tmp_path / "project"
    for directory in ("src", "tests", "scripts", "configs", "docs"):
        (project / directory).mkdir(parents=True)
        (project / directory / "tracked.txt").write_text(directory, encoding="utf-8")
    for filename in ("pyproject.toml", "requirements.txt", "README.md", "Makefile"):
        (project / filename).write_text(filename, encoding="utf-8")
    for filename in (
        "ER_SCHEMA.md",
        "DATA_DICTIONARY.md",
        "COHORT_ANALYSIS.md",
        "SYNTHETIC_ASSUMPTIONS.md",
    ):
        (project / "docs" / filename).write_text(filename, encoding="utf-8")

    gold = tmp_path / "staging-gold"
    reports = tmp_path / "staging-reports"
    inputs = tmp_path / "input"
    gold.mkdir()
    reports.mkdir()
    inputs.mkdir()
    (inputs / "input.csv").write_text("id\nP-1\n", encoding="utf-8")
    patient = pd.DataFrame({"patient_id": ["P-1"]})
    outcome = pd.DataFrame({"outcome_id": ["O-1"], "patient_id": ["P-1"]})
    _write_table_contract(gold, "patient", patient)
    _write_table_contract(gold, "outcome", outcome)
    connection = duckdb.connect(str(gold / "prostate_journey.duckdb"))
    try:
        connection.register("patient_frame", patient)
        connection.register("outcome_frame", outcome)
        connection.execute("CREATE TABLE patient AS SELECT * FROM patient_frame")
        connection.execute("CREATE TABLE outcome AS SELECT * FROM outcome_frame")
    finally:
        connection.close()

    config = {
        "generator_version": "2.1.0",
        "scenario_version": "diagnostic-v2.1-release",
        "random_seed": 42,
        "market_configuration": {"version": "market-v1"},
        "clinical_rule_configuration": {"version": "clinical-v1"},
    }
    metadata = {
        "git_commit": "abc123",
        "git_branch": "dev",
        "git_tracked_source_clean": True,
        "generator_version": config["generator_version"],
        "scenario_version": config["scenario_version"],
        "market_configuration_version": "market-v1",
        "clinical_rules_version": "clinical-v1",
        "random_seed": 42,
        "generation_started_at": "2026-08-25T10:00:00+00:00",
        "generation_completed_at": "2026-08-25T10:01:00+00:00",
        "output_file_hashes": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in gold.iterdir()
            if path.is_file()
        },
    }
    (reports / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (reports / "data_quality_summary.json").write_text(
        json.dumps({"critical_failures": 0, "rules": []}), encoding="utf-8"
    )
    (reports / "readiness_audit.json").write_text(
        json.dumps(
            {
                "overall_readiness_score": 100,
                "maximum_score": 100,
                "failed_requirements": [],
                "partial_requirements": [],
                "p0_p1_failures": [],
            }
        ),
        encoding="utf-8",
    )
    (reports / "adversarial_audit.json").write_text(
        json.dumps(
            {
                "independent_audit_score": 100,
                "maximum_score": 100,
                "p0_blockers_remaining": 0,
                "p1_issues_remaining": 0,
                "ready_for_bayer_diagnostic": True,
            }
        ),
        encoding="utf-8",
    )

    def git_runner(command, **_kwargs):
        arguments = command[1:]
        stdout = (
            "abc123\n"
            if arguments == ["rev-parse", "HEAD"]
            else "dev\n"
            if arguments == ["branch", "--show-current"]
            else ""
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def reconciliation_callback(tables, config, report_dir):
        assert set(tables) == {"patient", "outcome"}
        assert config["random_seed"] == 42
        assert Path(report_dir).name == "reports"
        return {"status": "PASS", "total_mismatches": 0, "hard_failures": []}

    def evidence_callback(tables, config, analytical_dir, qa_dir, reconciliation_summary):
        assert set(tables) == {"patient", "outcome"}
        assert config["generator_version"] == "2.1.0"
        assert Path(analytical_dir).name == "analytical_dataset"
        assert reconciliation_summary["status"] == "PASS"
        scorecard = Path(qa_dir) / "final_scorecard.csv"
        pd.DataFrame(
            {
                "dimension": [f"dimension-{index}" for index in range(11)],
                "score_0_100": [100] * 11,
                "status": ["PASS"] * 11,
                "remaining_deficiency": ["NONE"] * 11,
            }
        ).to_csv(scorecard, index=False)
        return {"final_scorecard_csv": scorecard}

    def test_runner(command, **_kwargs):
        junit_argument = next((value for value in command if value.startswith("--junitxml=")), None)
        if junit_argument:
            Path(junit_argument.split("=", 1)[1]).write_text(
                '<testsuite name="tests" tests="1" failures="0" errors="0"/>',
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    release = tmp_path / "immutable-release"
    manifest = package_certified_release(
        project_root=project,
        staging_gold_dir=gold,
        staging_report_dir=reports,
        input_dir=inputs,
        release_dir=release,
        dataset_version="diagnostic-v2.1",
        config=config,
        expected_git_commit="abc123",
        reconcile_callback=reconciliation_callback,
        evidence_callback=evidence_callback,
        test_runner=test_runner,
        git_runner=git_runner,
    )
    assert manifest["decision"] == "CERTIFIED — READY FOR BAYER ANALYSIS"
    assert manifest["gate_summary"]["final_scorecard"]["dimensions"] == 11
    assert (release / "analytical_dataset" / "docs" / "ER_SCHEMA.md").is_file()
    assert (release / "qa_evidence" / "test_report.xml").is_file()
