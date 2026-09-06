from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_container_is_non_root_read_only_and_has_health_contract() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["analytics-app"]
    assert "FROM python:3.11.9-slim-bookworm" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "/health" in dockerfile
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert all(volume.get("read_only") is True for volume in service["volumes"])
    assert "/ready" in " ".join(service["healthcheck"]["test"])


def test_container_context_excludes_secrets_and_generated_evidence() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
    assert "data" in ignored
    assert "outputs" in ignored
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in dockerfile
    assert "OPENAI_API_KEY" not in compose
    assert "aws " not in dockerfile.lower()
    assert "aws " not in compose.lower()
