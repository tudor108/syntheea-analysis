from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from typer.testing import CliRunner

from prostate_journey.app_config import (
    assert_mutable_output_path,
    load_application_settings,
)
from prostate_journey.application import create_application_server
from prostate_journey.cli import app
from prostate_journey.dataset_resolver import (
    CERTIFIED_DECISION,
    resolve_analytical_dataset,
)
from prostate_journey.pipeline import TABLES
from prostate_journey.release_integrity import (
    resolve_application_artifacts,
    sha256_file,
    verify_release_integrity,
)

ROOT = Path(__file__).resolve().parents[1]


def _file_entry(path: Path) -> dict[str, int | str]:
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _write_certified_release(project: Path, release_id: str = "synthetic-test-release") -> Path:
    release = project / "data" / "releases" / release_id
    analytical = release / "analytical_dataset"
    qa = release / "qa_evidence"
    archives = release / "archives"
    analytical.mkdir(parents=True)
    qa.mkdir()
    archives.mkdir()
    for table in TABLES:
        (analytical / f"{table}.parquet").write_bytes(f"synthetic-{table}".encode())
    (qa / "qa-summary.json").write_text('{"status":"PASS"}', encoding="utf-8")
    analytical_archive = archives / f"{release_id}-analytical.zip"
    qa_archive = archives / f"{release_id}-qa-evidence.zip"
    analytical_archive.write_bytes(b"synthetic analytical archive")
    qa_archive.write_bytes(b"synthetic qa archive")
    manifest = {
        "dataset_version": release_id,
        "created_at": "2026-09-05T00:00:00+00:00",
        "decision": CERTIFIED_DECISION,
        "synthetic_data_only": True,
        "immutable": True,
        "analytical_dataset_directory": "analytical_dataset",
        "qa_evidence_directory": "qa_evidence",
        "archives": {
            "analytical": {
                "path": analytical_archive.relative_to(release).as_posix(),
                **_file_entry(analytical_archive),
            },
            "qa_evidence": {
                "path": qa_archive.relative_to(release).as_posix(),
                **_file_entry(qa_archive),
            },
        },
        "git": {"git_commit": "a" * 40},
    }
    manifest_path = release / "release_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (release / "IMMUTABLE_RELEASE").write_text(
        f"dataset_version={release_id}\n"
        f"release_manifest_sha256={sha256_file(manifest_path)}\n"
        "sealed_at=2026-09-05T00:00:00+00:00\n",
        encoding="utf-8",
    )
    checksum_path = release / "CHECKSUMS.sha256"
    files = sorted(path for path in release.rglob("*") if path.is_file())
    checksum_path.write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(release).as_posix()}\n"
            for path in files
            if path != checksum_path
        ),
        encoding="utf-8",
    )
    return release


def _write_presentation(project: Path, release: Path) -> Path:
    release_id = release.name
    presentation = project / "outputs" / "presentation" / release_id
    assets = presentation / "assets"
    assets.mkdir(parents=True)
    index = presentation / "executive_story.html"
    script = assets / "app.js"
    index.write_text(
        "<!doctype html><html><body>SYNTHETIC TEST PRESENTATION"
        '<script src="assets/app.js"></script></body></html>',
        encoding="utf-8",
    )
    script.write_text("document.body.dataset.ready = 'true';", encoding="utf-8")
    output_files = {
        path.relative_to(presentation).as_posix(): _file_entry(path) for path in (index, script)
    }
    manifest = {
        "package_type": "aggregate stakeholder presentation",
        "generated_at": "2026-09-05T00:01:00+00:00",
        "dataset_version": release_id,
        "analytical_dataset_directory": str(release / "analytical_dataset"),
        "release_directory": str(release),
        "source_release_decision": CERTIFIED_DECISION,
        "patient_level_data_included": False,
        "analysis_git": {"tracked_source_clean": True},
        "output_files": output_files,
    }
    (presentation / "presentation_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return presentation


def _settings(project: Path, **overrides: object):
    return load_application_settings(
        project,
        environ={"PROSTATE_JOURNEY_ENVIRONMENT_CONFIG": str(project / "missing-profile.yaml")},
        config_path=ROOT / "configs" / "application.yaml",
        overrides={"port": 0, "readiness_cache_seconds": 0, **overrides},
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_typed_configuration_keeps_optional_openai_secret_out_of_serialization(
    tmp_path: Path,
) -> None:
    settings = load_application_settings(
        tmp_path,
        environ={
            "PROSTATE_JOURNEY_ENVIRONMENT_CONFIG": str(tmp_path / "missing.yaml"),
            "OPENAI_API_KEY": "optional-test-secret",
        },
        config_path=ROOT / "configs" / "application.yaml",
    )
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "optional-test-secret"
    assert "optional-test-secret" not in repr(settings)
    assert "openai_api_key" not in settings.model_dump()
    settings_without_secret = _settings(tmp_path)
    assert settings_without_secret.openai_api_key is None


def test_mutable_outputs_and_experiments_cannot_cross_trust_boundaries(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    safe = assert_mutable_output_path(settings, tmp_path / "data" / "gold", label="test")
    assert safe == (tmp_path / "data" / "gold").resolve()
    with pytest.raises(ValueError, match="certified release namespace"):
        assert_mutable_output_path(
            settings,
            tmp_path / "data" / "releases" / "release-1" / "analytical_dataset",
            label="test",
        )
    with pytest.raises(ValueError, match="presentation namespace"):
        _settings(
            tmp_path,
            presentation_dir=tmp_path / "outputs" / "experiments" / "untrusted",
        )


def test_resolver_never_silently_falls_back_to_working_gold(tmp_path: Path) -> None:
    gold = tmp_path / "data" / "gold"
    gold.mkdir(parents=True)
    for table in TABLES:
        (gold / f"{table}.parquet").write_bytes(b"working")
    with pytest.raises(FileNotFoundError, match="No complete certified analytical release"):
        resolve_analytical_dataset(tmp_path, TABLES)
    selected = resolve_analytical_dataset(tmp_path, TABLES, allow_gold_fallback=True)
    assert selected.dataset_version == "working-gold"


def test_application_serves_only_verified_aggregate_files_without_aws_or_openai(
    tmp_path: Path,
) -> None:
    release = _write_certified_release(tmp_path)
    presentation = _write_presentation(tmp_path, release)
    before_release = _tree_hashes(release)
    before_presentation = _tree_hashes(presentation)
    settings = _settings(tmp_path)
    server, state = create_application_server(settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            health = json.loads(response.read())
            assert response.status == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        with urlopen(f"http://127.0.0.1:{port}/ready", timeout=5) as response:
            readiness = json.loads(response.read())
        with urlopen(f"http://127.0.0.1:{port}/executive_story.html", timeout=5) as response:
            frontend = response.read().decode()
        assert health["status"] == "ok"
        assert readiness["status"] == "ready"
        assert readiness["openai_required"] is False
        assert readiness["release_id"] == release.name
        assert "SYNTHETIC TEST PRESENTATION" in frontend
        assert "optional-test-secret" not in frontend
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{port}/presentation_manifest.json", timeout=5)
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert state.artifacts is not None
    assert _tree_hashes(release) == before_release
    assert _tree_hashes(presentation) == before_presentation


def test_release_mutation_fails_closed_for_manifest_and_readiness(tmp_path: Path) -> None:
    release = _write_certified_release(tmp_path)
    _write_presentation(tmp_path, release)
    settings = _settings(tmp_path)
    artifacts = resolve_application_artifacts(settings)
    assert artifacts.release.dataset_version == release.name
    patient = release / "analytical_dataset" / "patient.parquet"
    patient.write_bytes(patient.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_release_integrity(release)
    server, state = create_application_server(settings)
    try:
        assert state.artifacts is None
        assert state.error_category == "ValueError"
        assert state.readiness_payload()["status"] == "not_ready"
    finally:
        server.server_close()


def test_verified_presentation_can_relocate_across_os_mounts(tmp_path: Path) -> None:
    release = _write_certified_release(tmp_path)
    presentation = _write_presentation(tmp_path, release)
    manifest_path = presentation / "presentation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release_directory"] = f"C:\\historical\\workspace\\{release.name}"
    manifest["analytical_dataset_directory"] = (
        f"C:\\historical\\workspace\\{release.name}\\analytical_dataset"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    artifacts = resolve_application_artifacts(_settings(tmp_path))
    assert artifacts.release.release_dir == release.resolve()
    assert any("safely relocated" in item for item in artifacts.presentation.warnings)


def test_application_cli_contract_is_available() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "health and readiness" in result.stdout
    result = runner.invoke(app, ["application-check", "--help"])
    assert result.exit_code == 0
    assert "aggregate presentation readiness" in result.stdout


def test_runtime_modules_contain_no_aws_client_or_command() -> None:
    runtime_files = [
        ROOT / "src" / "prostate_journey" / "app_config.py",
        ROOT / "src" / "prostate_journey" / "application.py",
        ROOT / "src" / "prostate_journey" / "release_integrity.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in runtime_files)
    assert "boto3" not in text
    assert "botocore" not in text
    assert "aws cli" not in text
    assert "subprocess" not in text
