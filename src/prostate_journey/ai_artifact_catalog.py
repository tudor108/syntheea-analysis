"""Release-isolated allow-list for Ask the Evidence retrieval."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ai_finops import load_cost_controls
from .ai_studio_config import AIStudioSettings
from .app_config import load_application_settings
from .release_integrity import (
    ApplicationArtifacts,
    resolve_application_artifacts,
    sha256_file,
)

PRESENTATION_INDEX_FILES = {
    "accessible_report.html",
    "aggregate_export.csv",
    "cohort_kpis.csv",
    "cohort_summary.md",
    "evidence_manifest.json",
    "healthcare_analysis_report.md",
    "healthcare_initiation_funnel.csv",
    "healthcare_missingness_by_market.csv",
    "healthcare_persistence_summary.csv",
    "healthcare_referral_summary.csv",
    "presentation_kpis.csv",
    "tactic_registry.json",
}
PRESENTATION_TOOL_ONLY_FILES = {"executive_story.html"}
RELEASE_REFERENCE_FILES = {
    "release_manifest.json",
    "RELEASE_DECISION.md",
    "qa_evidence/assumptions_register.csv",
    "qa_evidence/final_scorecard.md",
    "qa_evidence/synthetic_realism_report.md",
    "qa_evidence/uncertainty_confidence.csv",
    "qa_evidence/docs/ARCHITECTURE.md",
    "qa_evidence/docs/COHORT_ANALYSIS.md",
    "qa_evidence/docs/DATA_DICTIONARY.md",
    "qa_evidence/docs/RUNBOOK.md",
    "qa_evidence/docs/SYNTHETIC_ASSUMPTIONS.md",
    "qa_evidence/reports/adversarial_audit.md",
    "qa_evidence/reports/data_quality_report.md",
    "qa_evidence/reports/data_quality_summary.json",
    "qa_evidence/reports/release_reconciliation.json",
    "qa_evidence/reports/readiness_audit.md",
    "qa_evidence/test_report.md",
}
CURRENT_CONTROL_FILES = {
    "configs/ai_cost_controls.yaml",
    "configs/ai_evaluation.yaml",
    "configs/expert_lenses.yaml",
    "configs/event_hierarchy.yaml",
    "configs/model_aliases.yaml",
    "configs/tactic_registry.yaml",
    "contracts/analysis_registry.yaml",
    "contracts/model_governance.yaml",
    "contracts/model_target_contracts.yaml",
    "docs/AI_ANALYSIS_STUDIO_HANDOFF.md",
    "docs/AI_ANALYSIS_STUDIO_RUNBOOK.md",
    "docs/AI_ANALYSIS_STUDIO_THREAT_MODEL.md",
    "docs/AI_EVALUATION_REPORT.md",
    "docs/AI_FINOPS_SECURITY_EVALUATION_RUNBOOK.md",
    "docs/CLAIM_EVIDENCE_REGISTER.md",
    "docs/DEPLOYMENT_CONTRACT.md",
    "docs/LOCAL_RUNBOOK.md",
    "docs/PREDICTIVE_METHODS_V2.2.md",
    "docs/RELEASE_AND_CHANGE_CONTROL.md",
    "docs/SCIENTIFIC_METHODS_V2.2.md",
    "docs/STAGE4_EXIT_CRITERIA.md",
}
FORBIDDEN_PARTS = {
    ".env",
    "analytical_dataset",
    "archives",
    "data/gold",
    "data/raw",
    "logs",
    "temporary",
}
FORBIDDEN_SUFFIXES = {".duckdb", ".parquet", ".py", ".pyc", ".zip"}


class ArtifactRecord(BaseModel):
    """Metadata contract for one approved read-only evidence artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_name: str
    artifact_type: str
    release_id: str
    source_commit: str
    analysis_id: str | None = None
    tactic_id: str | None = None
    tactic_ids: list[str] = Field(default_factory=list)
    market: str | None = None
    scenario: str | None = None
    certification_status: str
    synthetic_only: Literal[True] = True
    generated_at: str
    confidentiality: str
    permitted_use: str
    source_scope: Literal["presentation", "release", "current_control"]
    relative_path: str
    sha256: str
    bytes: int = Field(ge=0)
    mime_type: str
    indexable: bool

    @field_validator("artifact_id")
    @classmethod
    def _stable_id(cls, value: str) -> str:
        if not value.startswith("artifact_") or not value.removeprefix("artifact_").isalnum():
            raise ValueError("artifact_id must be a stable artifact_ identifier")
        return value

    @field_validator("relative_path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("artifact path must be relative and traversal-free")
        normalized = candidate.as_posix()
        folded = normalized.casefold()
        if any(part in folded for part in FORBIDDEN_PARTS):
            raise ValueError(f"forbidden artifact path: {normalized}")
        if candidate.suffix.casefold() in FORBIDDEN_SUFFIXES:
            raise ValueError(f"forbidden artifact type: {normalized}")
        return normalized


class ArtifactCatalogue(BaseModel):
    """One active release and its allow-listed evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["AI-ARTIFACT-CATALOGUE-v1.0"] = "AI-ARTIFACT-CATALOGUE-v1.0"
    release_id: str
    source_commit: str
    generated_at: str
    synthetic_only: Literal[True] = True
    patient_level_data_included: Literal[False] = False
    active_release_count: Literal[1] = 1
    artifacts: list[ArtifactRecord]

    @model_validator(mode="after")
    def _one_release_unique_ids(self) -> ArtifactCatalogue:
        if not self.artifacts:
            raise ValueError("artifact catalogue cannot be empty")
        if any(item.release_id != self.release_id for item in self.artifacts):
            raise ValueError("artifact catalogue mixes release identifiers")
        identifiers = [item.artifact_id for item in self.artifacts]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("artifact identifiers must be unique")
        paths = [item.relative_path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("artifact paths must be unique")
        return self


def _current_commit(root: Path) -> str:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "UNAVAILABLE"
    return value or "UNAVAILABLE"


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"artifact path escapes project root: {relative}") from error
    return path


def _artifact_type(path: Path) -> str:
    name = path.name.casefold()
    if name == "tactic_registry.json":
        return "tactic_registry"
    if "manifest" in name:
        return "manifest"
    if "model_card" in path.as_posix().casefold():
        return "model_card"
    if "method" in name or "method" in path.as_posix().casefold():
        return "methodology"
    if "quality" in name or "audit" in name or "scorecard" in name:
        return "qa"
    if path.suffix.casefold() == ".csv":
        return "aggregate_table"
    if path.suffix.casefold() in {".yaml", ".yml"}:
        return "governance_configuration"
    return "narrative"


def _tactic_mappings(presentation: Path) -> dict[str, tuple[list[str], list[str]]]:
    path = presentation / "tactic_registry.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mappings: dict[str, tuple[list[str], list[str]]] = {}
    for tactic in payload.get("tactics", []):
        if not isinstance(tactic, dict):
            continue
        tactic_id = str(tactic.get("tactic_id", ""))
        analysis_id = str(tactic.get("analysis_id", ""))
        evidence_files = tactic.get("evidence_files", [])
        aggregate_source = tactic.get("aggregate_result_source")
        candidates = [
            *(str(item) for item in evidence_files if isinstance(item, str)),
            *([str(aggregate_source)] if aggregate_source else []),
        ]
        for candidate in candidates:
            name = Path(candidate).name
            tactic_ids, analysis_ids = mappings.setdefault(name, ([], []))
            if tactic_id and tactic_id not in tactic_ids:
                tactic_ids.append(tactic_id)
            if analysis_id and analysis_id not in analysis_ids:
                analysis_ids.append(analysis_id)
    return mappings


def _record(
    root: Path,
    path: Path,
    *,
    release_id: str,
    source_commit: str,
    generated_at: str,
    source_scope: Literal["presentation", "release", "current_control"],
    certification_status: str,
    indexable: bool,
    mappings: dict[str, tuple[list[str], list[str]]],
    scenario: str | None,
) -> ArtifactRecord:
    relative = path.resolve().relative_to(root).as_posix()
    digest = sha256_file(path)
    tactic_ids, analysis_ids = mappings.get(path.name, ([], []))
    stable = hashlib.sha256(f"{release_id}|{source_scope}|{relative}".encode()).hexdigest()[:24]
    mime_type = mimetypes.guess_type(path.name)[0] or "text/plain"
    return ArtifactRecord(
        artifact_id=f"artifact_{stable}",
        artifact_name=path.name,
        artifact_type=_artifact_type(path),
        release_id=release_id,
        source_commit=source_commit,
        analysis_id=analysis_ids[0] if len(analysis_ids) == 1 else None,
        tactic_id=tactic_ids[0] if len(tactic_ids) == 1 else None,
        tactic_ids=tactic_ids,
        scenario=scenario,
        certification_status=certification_status,
        generated_at=generated_at,
        confidentiality="INTERNAL SYNTHETIC",
        permitted_use=(
            "Grounded aggregate synthetic evidence Q&A only."
            if source_scope != "current_control"
            else "Methodology and governance context only; not a certified numerical result."
        ),
        source_scope=source_scope,
        relative_path=relative,
        sha256=digest,
        bytes=path.stat().st_size,
        mime_type=mime_type,
        indexable=indexable,
    )


def _presentation_records(
    root: Path,
    artifacts: ApplicationArtifacts,
    mappings: dict[str, tuple[list[str], list[str]]],
) -> list[ArtifactRecord]:
    presentation = artifacts.presentation.presentation_dir
    evidence_path = presentation / "evidence_manifest.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if (
        evidence.get("release_id") != artifacts.release.dataset_version
        or evidence.get("synthetic_only") is not True
        or evidence.get("patient_level_data_included") is not False
    ):
        raise ValueError("presentation evidence manifest violates release or synthetic boundary")
    declared = evidence.get("artifacts", {})
    if not isinstance(declared, dict):
        raise ValueError("presentation evidence artifact inventory is invalid")
    records: list[ArtifactRecord] = []
    approved = PRESENTATION_INDEX_FILES | PRESENTATION_TOOL_ONLY_FILES
    for relative in sorted(approved):
        path = presentation / relative
        if not path.is_file():
            continue
        if relative != "evidence_manifest.json":
            item = declared.get(relative)
            if not isinstance(item, dict) or item.get("sha256") != sha256_file(path):
                raise ValueError(f"presentation evidence is not manifest verified: {relative}")
        records.append(
            _record(
                root,
                path,
                release_id=artifacts.release.dataset_version,
                source_commit=str(evidence.get("source_commit", "UNAVAILABLE")),
                generated_at=str(evidence.get("generated_time", "")),
                source_scope="presentation",
                certification_status="RELEASE-MATCHED AGGREGATE PRESENTATION EVIDENCE",
                indexable=relative in PRESENTATION_INDEX_FILES,
                mappings=mappings,
                scenario=str(evidence.get("active_analytical_definition", {}).get("scenario", "")),
            )
        )
    model_dir = presentation / "model_cards"
    if model_dir.is_dir():
        for path in sorted(model_dir.iterdir()):
            relative = path.relative_to(presentation).as_posix()
            if (
                path.is_file()
                and path.suffix.casefold() in {".md", ".json"}
                and relative in declared
                and declared[relative].get("sha256") == sha256_file(path)
            ):
                records.append(
                    _record(
                        root,
                        path,
                        release_id=artifacts.release.dataset_version,
                        source_commit=str(evidence.get("source_commit", "UNAVAILABLE")),
                        generated_at=str(evidence.get("generated_time", "")),
                        source_scope="presentation",
                        certification_status="VERIFIED RELEASE-MATCHED MODEL EVIDENCE",
                        indexable=True,
                        mappings=mappings,
                        scenario=None,
                    )
                )
    return records


def build_artifact_catalogue(
    project_root: str | Path,
    settings: AIStudioSettings,
) -> ArtifactCatalogue:
    """Build a fail-closed catalogue without reading patient-level directories."""
    root = Path(project_root).resolve()
    app_settings = load_application_settings(root)
    artifacts = resolve_application_artifacts(app_settings)
    release_id = artifacts.release.dataset_version
    release_manifest = artifacts.release.manifest
    source_commit = str(release_manifest.get("git", {}).get("git_commit", "UNAVAILABLE"))
    generated_at = datetime.now(UTC).isoformat()
    mappings = _tactic_mappings(artifacts.presentation.presentation_dir)
    records = _presentation_records(root, artifacts, mappings)

    release_created = str(release_manifest.get("created_at", generated_at))
    for relative in sorted(RELEASE_REFERENCE_FILES):
        path = artifacts.release.release_dir / relative
        if path.is_file():
            records.append(
                _record(
                    root,
                    path,
                    release_id=release_id,
                    source_commit=source_commit,
                    generated_at=release_created,
                    source_scope="release",
                    certification_status="IMMUTABLE CERTIFIED RELEASE REFERENCE",
                    indexable=True,
                    mappings=mappings,
                    scenario=None,
                )
            )

    current_commit = _current_commit(root)
    for relative in sorted(CURRENT_CONTROL_FILES):
        path = _safe_path(root, relative)
        if path.is_file():
            records.append(
                _record(
                    root,
                    path,
                    release_id=release_id,
                    source_commit=current_commit,
                    generated_at=generated_at,
                    source_scope="current_control",
                    certification_status="CONTROLLED CURRENT REFERENCE — NOT RELEASE CERTIFIED",
                    indexable=True,
                    mappings=mappings,
                    scenario=None,
                )
            )

    catalogue = ArtifactCatalogue(
        release_id=release_id,
        source_commit=source_commit,
        generated_at=generated_at,
        artifacts=records,
    )
    controls_path = settings.cost_controls_path
    if not controls_path.is_absolute():
        controls_path = (root / controls_path).resolve()
    maximum = load_cost_controls(controls_path).security_limits.max_index_artifact_bytes
    oversized = [
        item.relative_path
        for item in catalogue.artifacts
        if item.indexable and item.bytes > maximum
    ]
    if oversized:
        raise ValueError(f"indexable artifacts exceed the configured file limit: {oversized}")
    settings.catalogue_path.parent.mkdir(parents=True, exist_ok=True)
    settings.catalogue_path.write_text(
        json.dumps(catalogue.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return catalogue


def load_artifact_catalogue(path: str | Path) -> ArtifactCatalogue:
    """Load and validate the catalogue schema."""
    return ArtifactCatalogue.model_validate_json(Path(path).read_text(encoding="utf-8"))


def verify_artifact_catalogue(
    catalogue: ArtifactCatalogue,
    project_root: str | Path,
    *,
    expected_release_id: str,
) -> None:
    """Re-hash every catalogue member and enforce one active release."""
    if catalogue.release_id != expected_release_id:
        raise ValueError("artifact catalogue release does not match active certified release")
    root = Path(project_root).resolve()
    for item in catalogue.artifacts:
        path = _safe_path(root, item.relative_path)
        if not path.is_file() or path.stat().st_size != item.bytes:
            raise ValueError(f"catalogued artifact is missing or changed: {item.artifact_id}")
        if sha256_file(path) != item.sha256:
            raise ValueError(f"catalogued artifact hash mismatch: {item.artifact_id}")


class ArtifactStore:
    """Read only catalogue-selected text by stable identifier."""

    def __init__(self, root: str | Path, catalogue: ArtifactCatalogue) -> None:
        self.root = Path(root).resolve()
        self.catalogue = catalogue
        self.by_id = {item.artifact_id: item for item in catalogue.artifacts}

    def record(self, artifact_id: str) -> ArtifactRecord:
        try:
            return self.by_id[artifact_id]
        except KeyError as error:
            raise KeyError("artifact_id is not present in the active catalogue") from error

    def read(self, artifact_id: str, *, max_characters: int = 12000) -> str:
        record = self.record(artifact_id)
        path = _safe_path(self.root, record.relative_path)
        if sha256_file(path) != record.sha256:
            raise ValueError("artifact changed after catalogue verification")
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:max_characters]
