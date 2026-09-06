"""Read-only integrity checks for certified releases and presentation packages."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_config import ApplicationSettings
from .dataset_resolver import (
    ACCEPTED_RELEASE_DECISIONS,
    LEGACY_CERTIFIED_DECISION,
    resolve_analytical_dataset,
)
from .pipeline import TABLES

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReleaseIntegrity:
    """Verified immutable release identity."""

    release_dir: Path
    analytical_dir: Path
    dataset_version: str
    manifest: dict[str, Any]
    manifest_sha256: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PresentationIntegrity:
    """Verified aggregate presentation identity and serve allow-list."""

    presentation_dir: Path
    dataset_version: str
    manifest: dict[str, Any]
    output_files: frozenset[str]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ApplicationArtifacts:
    """One release-matched pair safe for the local presentation service."""

    release: ReleaseIntegrity
    presentation: PresentationIntegrity


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Manifest path escapes package root: {relative}") from error
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid or unreadable JSON manifest: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must contain one JSON object: {path}")
    return payload


def _portable_path_match(recorded: str, expected: Path, required_tail: tuple[str, ...]) -> bool:
    """Allow a verified package to move across OS mounts while fixing its trusted path tail."""
    if not recorded:
        return False
    try:
        if Path(recorded).resolve() == expected:
            return True
    except OSError:
        pass
    normalized = recorded.replace("\\", "/").rstrip("/")
    parts = tuple(part.casefold() for part in normalized.split("/") if part)
    tail = tuple(part.casefold() for part in required_tail)
    return len(parts) >= len(tail) and parts[-len(tail) :] == tail


def _marker_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"Immutable release marker is missing: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            raise ValueError(f"Invalid immutable release marker line: {line!r}")
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _verify_release_checksums(release: Path) -> None:
    checksum_path = release / "CHECKSUMS.sha256"
    if not checksum_path.is_file():
        raise ValueError(f"Release checksum inventory is missing: {checksum_path}")
    recorded: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as error:
            raise ValueError(f"Invalid checksum inventory line: {line!r}") from error
        if not SHA256_PATTERN.fullmatch(digest) or relative in recorded:
            raise ValueError(f"Invalid or duplicate checksum entry: {line!r}")
        recorded[relative] = digest
    if not recorded:
        raise ValueError("Release checksum inventory is empty")
    observed_files = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if observed_files != set(recorded):
        missing = sorted(set(recorded) - observed_files)
        unexpected = sorted(observed_files - set(recorded))
        raise ValueError(
            f"Release file inventory mismatch; missing={missing}, unexpected={unexpected}"
        )
    for relative, expected in recorded.items():
        member = _safe_member(release, relative)
        if sha256_file(member) != expected:
            raise ValueError(f"Certified release checksum mismatch: {relative}")


def verify_release_integrity(
    release_dir: str | Path,
    *,
    verify_hashes: bool = True,
) -> ReleaseIntegrity:
    """Verify the release marker, identity, archive hashes, and optional full inventory."""
    release = Path(release_dir).resolve()
    manifest_path = release / "release_manifest.json"
    manifest = _read_json(manifest_path)
    dataset_version = str(manifest.get("dataset_version", ""))
    if not dataset_version or dataset_version != release.name:
        raise ValueError("Release directory and manifest dataset_version do not match")
    if manifest.get("decision") not in ACCEPTED_RELEASE_DECISIONS:
        raise ValueError(f"Release decision is not accepted: {manifest.get('decision')!r}")
    if manifest.get("immutable") is not True:
        raise ValueError("Release manifest does not declare immutable=true")
    analytical = _safe_member(
        release, str(manifest.get("analytical_dataset_directory", "analytical_dataset"))
    )
    if not analytical.is_dir():
        raise ValueError(f"Certified analytical directory is missing: {analytical}")

    digest = sha256_file(manifest_path)
    marker = _marker_values(release / "IMMUTABLE_RELEASE")
    if marker.get("dataset_version") != dataset_version:
        raise ValueError("Immutable marker dataset_version does not match release manifest")
    if marker.get("release_manifest_sha256") != digest:
        raise ValueError("Immutable marker release manifest SHA-256 mismatch")

    archives = manifest.get("archives")
    if not isinstance(archives, dict) or set(archives) != {"analytical", "qa_evidence"}:
        raise ValueError("Release manifest must identify separate analytical and QA archives")
    for label, entry in archives.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid {label} archive entry")
        archive = _safe_member(release, str(entry.get("path", "")))
        if not archive.is_file() or archive.stat().st_size != int(entry.get("bytes", -1)):
            raise ValueError(f"{label} archive is missing or has the wrong size")
        if verify_hashes and sha256_file(archive) != entry.get("sha256"):
            raise ValueError(f"{label} archive SHA-256 mismatch")
    if verify_hashes:
        _verify_release_checksums(release)

    warnings: list[str] = []
    if manifest.get("decision") == LEGACY_CERTIFIED_DECISION:
        warnings.append(
            "Legacy v2.1 decision wording is historical and is not Bayer, clinical, or "
            "production approval."
        )
    return ReleaseIntegrity(
        release_dir=release,
        analytical_dir=analytical,
        dataset_version=dataset_version,
        manifest=manifest,
        manifest_sha256=digest,
        warnings=tuple(warnings),
    )


def verify_presentation_integrity(
    presentation_dir: str | Path,
    *,
    presentation_root: str | Path,
    release: ReleaseIntegrity,
    entrypoint: str,
    verify_hashes: bool = True,
) -> PresentationIntegrity:
    """Verify a release-matched, aggregate-only presentation and return its allow-list."""
    root = Path(presentation_root).resolve()
    presentation = Path(presentation_dir).resolve()
    try:
        presentation.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "Presentation package is outside the configured presentation namespace"
        ) from error
    manifest = _read_json(presentation / "presentation_manifest.json")
    if manifest.get("dataset_version") != release.dataset_version:
        raise ValueError("Presentation and certified release dataset versions do not match")
    if manifest.get("source_release_decision") not in ACCEPTED_RELEASE_DECISIONS:
        raise ValueError("Presentation source release decision is not accepted")
    if manifest.get("patient_level_data_included") is not False:
        raise ValueError("Presentation package must be aggregate-only")
    recorded_release = str(manifest.get("release_directory", ""))
    if not _portable_path_match(
        recorded_release,
        release.release_dir,
        (release.dataset_version,),
    ):
        raise ValueError("Presentation release directory does not match the selected release")
    recorded_analytical = str(manifest.get("analytical_dataset_directory", ""))
    if not _portable_path_match(
        recorded_analytical,
        release.analytical_dir,
        (release.dataset_version, release.analytical_dir.name),
    ):
        raise ValueError("Presentation analytical directory does not match the selected release")

    output_manifest = manifest.get("output_files")
    if not isinstance(output_manifest, dict) or not output_manifest:
        raise ValueError("Presentation output file manifest is missing or empty")
    output_files = frozenset(map(str, output_manifest))
    if entrypoint not in output_files:
        raise ValueError(f"Presentation entrypoint is not governed by the manifest: {entrypoint}")
    for relative, metadata in output_manifest.items():
        if not isinstance(metadata, dict):
            raise ValueError(f"Invalid presentation manifest entry: {relative}")
        member = _safe_member(presentation, str(relative))
        if not member.is_file() or member.stat().st_size != int(metadata.get("bytes", -1)):
            raise ValueError(f"Presentation artifact is missing or has the wrong size: {relative}")
        if verify_hashes and sha256_file(member) != metadata.get("sha256"):
            raise ValueError(f"Presentation artifact SHA-256 mismatch: {relative}")

    warnings: list[str] = []
    if Path(recorded_release).resolve() != release.release_dir:
        warnings.append(
            "Presentation package paths were safely relocated to the current runtime mount."
        )
    analysis_git = manifest.get("analysis_git", {})
    if isinstance(analysis_git, dict) and analysis_git.get("tracked_source_clean") is not True:
        warnings.append(
            "Presentation was generated from a historically dirty analysis worktree; "
            "regenerate for v2.2."
        )
    return PresentationIntegrity(
        presentation_dir=presentation,
        dataset_version=release.dataset_version,
        manifest=manifest,
        output_files=output_files,
        warnings=tuple(warnings),
    )


def resolve_application_artifacts(settings: ApplicationSettings) -> ApplicationArtifacts:
    """Resolve only the newest certified release and its matching presentation package."""
    selected = resolve_analytical_dataset(
        settings.project_root,
        TABLES,
        require_certified=True,
        release_root=settings.paths.certified_releases,
    )
    if selected.release_dir is None:
        raise ValueError("Application startup requires a certified release directory")
    release = verify_release_integrity(
        selected.release_dir,
        verify_hashes=settings.verify_release_hashes,
    )
    presentation_dir = (
        settings.presentation_dir
        if settings.presentation_dir is not None
        else settings.paths.presentations / release.dataset_version
    )
    presentation = verify_presentation_integrity(
        presentation_dir,
        presentation_root=settings.paths.presentations,
        release=release,
        entrypoint=settings.presentation_entrypoint,
        verify_hashes=settings.verify_release_hashes,
    )
    return ApplicationArtifacts(release=release, presentation=presentation)
