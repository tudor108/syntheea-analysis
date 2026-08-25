from pathlib import Path

import pytest

from prostate_journey.release_packager import ReleasePackagingError
from prostate_journey.release_runner import create_fresh_certified_release


def test_fresh_runner_uses_new_stage_and_pins_generation_commit(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    input_dir = project / "data" / "raw"
    input_dir.mkdir(parents=True)
    release = project / "data" / "releases" / "release-v2.1"
    observed = {}

    monkeypatch.setattr(
        "prostate_journey.release_runner.assert_clean_source",
        lambda *_args, **_kwargs: {
            "git_commit": "abc123",
            "git_branch": "dev",
            "source_clean": True,
        },
    )

    def create_stage(path):
        resolved = Path(path).resolve()
        resolved.mkdir(parents=True)
        return resolved

    monkeypatch.setattr(
        "prostate_journey.release_runner.assert_new_empty_release_dir", create_stage
    )

    def fake_run_all(root, config, raw, gold, reports):
        observed["generation"] = (root, config, raw, gold, reports)
        gold.mkdir()
        reports.mkdir()
        return {}

    monkeypatch.setattr("prostate_journey.release_runner.run_all", fake_run_all)

    def fake_package(**kwargs):
        observed["package"] = kwargs
        kwargs["release_dir"].mkdir(parents=True)
        return {"decision": "CERTIFIED — READY FOR BAYER ANALYSIS"}

    monkeypatch.setattr("prostate_journey.release_runner.package_certified_release", fake_package)

    result = create_fresh_certified_release(
        project_root=project,
        config={"scenario_version": "diagnostic-v2.1-release"},
        input_dir=input_dir,
        release_dir=release,
        dataset_version="BAYER_SYNTHETIC_v2.1.0",
    )

    assert observed["package"]["expected_git_commit"] == "abc123"
    assert observed["package"]["staging_gold_dir"].parent.name == "release-v2.1"
    assert result["release_directory"] == str(release.resolve())
    assert Path(result["fresh_staging_directory"]).is_dir()


def test_fresh_runner_rejects_existing_release_before_generation(tmp_path, monkeypatch):
    release = tmp_path / "existing"
    release.mkdir()
    monkeypatch.setattr(
        "prostate_journey.release_runner.assert_clean_source",
        lambda *_args, **_kwargs: {"git_commit": "abc123"},
    )

    with pytest.raises(ReleasePackagingError, match="cannot be reused"):
        create_fresh_certified_release(
            project_root=tmp_path,
            config={},
            input_dir=tmp_path / "raw",
            release_dir=release,
            dataset_version="v1",
        )
