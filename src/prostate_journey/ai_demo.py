"""Deterministic static fallback package for the AI Analysis Studio demo."""

from __future__ import annotations

import html
import json
import re
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ai_artifact_catalog import ArtifactCatalogue, build_artifact_catalogue
from .ai_evidence_tools import EvidenceTools
from .ai_studio_config import AIStudioSettings
from .release_integrity import sha256_file
from .specialist_contracts import ExpertLens, InteractiveRun
from .specialist_orchestrator import SpecialistOrchestrator
from .specialist_tools import SpecialistAnalysisTools

STATIC_FALLBACK_LABEL = "STATIC FALLBACK CAPTURE · SYNTHETIC ANALYTICAL DEMO"
INTERACTIVE_LABEL = "INTERACTIVE SYNTHETIC ANALYSIS — NOT PART OF THE CERTIFIED RELEASE"
PROHIBITED_USE = (
    "Not Bayer, patient, clinical, commercial, real-world, population, or causal evidence. "
    "Not for treatment, patient, market-ranking, certification, or production-AI decisions."
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def _release_hashes(root: Path, catalogue: ArtifactCatalogue) -> dict[str, str]:
    record = next(
        item
        for item in catalogue.artifacts
        if item.source_scope == "release" and item.artifact_name == "release_manifest.json"
    )
    manifest = (root / record.relative_path).resolve()
    checksums = manifest.parent / "CHECKSUMS.sha256"
    return {
        "release_manifest.json": sha256_file(manifest),
        "CHECKSUMS.sha256": sha256_file(checksums),
    }


def _lines(values: list[str], *, width: int = 88, maximum: int = 13) -> list[str]:
    output: list[str] = []
    for value in values:
        wrapped = textwrap.wrap(str(value), width=width) or [""]
        output.extend(wrapped)
    if len(output) > maximum:
        output = [*output[: maximum - 1], "…"]
    return output


def _write_svg(
    path: Path,
    *,
    step: int,
    title: str,
    body: list[str],
    release_id: str,
    status: str,
) -> None:
    safe_title = html.escape(title)
    safe_release = html.escape(release_id)
    safe_status = html.escape(status)
    line_nodes = []
    for index, line in enumerate(_lines(body)):
        y = 318 + index * 38
        line_nodes.append(f'<text x="104" y="{y}" class="body">{html.escape(line)}</text>')
    payload = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="900" viewBox="0 0 1440 900" role="img" aria-labelledby="title description">
  <title id="title">Step {step}: {safe_title}</title>
  <desc id="description">Static deterministic fallback for an interactive synthetic analytics demonstration.</desc>
  <defs><linearGradient id="header" x1="0" x2="1"><stop stop-color="#102c43"/><stop offset="1" stop-color="#174f63"/></linearGradient></defs>
  <rect width="1440" height="900" fill="#f4f7f8"/>
  <rect width="1440" height="112" fill="url(#header)"/>
  <rect y="112" width="1440" height="62" fill="#ffe9ad"/>
  <text x="72" y="48" class="kicker">AI ANALYSIS STUDIO · STEP {step} OF 10</text>
  <text x="72" y="86" class="brand">{html.escape(STATIC_FALLBACK_LABEL)}</text>
  <text x="72" y="150" class="warning">{html.escape(INTERACTIVE_LABEL)}</text>
  <rect x="72" y="214" width="1296" height="548" rx="22" fill="#ffffff" stroke="#cad6dc" stroke-width="2"/>
  <text x="104" y="270" class="title">{safe_title}</text>
  {"".join(line_nodes)}
  <rect x="104" y="688" width="1232" height="1" fill="#dce5e9"/>
  <text x="104" y="725" class="status">{safe_status}</text>
  <text x="72" y="815" class="footer">Parent release: {safe_release}</text>
  <text x="72" y="851" class="footer">{html.escape(PROHIBITED_USE)}</text>
  <style>
    text {{ font-family: Inter, Arial, sans-serif; fill: #17313d; }}
    .kicker {{ font-size: 17px; font-weight: 700; letter-spacing: 2px; fill: #9dd8df; }}
    .brand {{ font-size: 26px; font-weight: 750; fill: #fff; }}
    .warning {{ font-size: 18px; font-weight: 800; fill: #4b3700; letter-spacing: .4px; }}
    .title {{ font-size: 34px; font-weight: 760; fill: #102c43; }}
    .body {{ font-size: 23px; fill: #274550; }}
    .status {{ font-size: 20px; font-weight: 700; fill: #176b62; }}
    .footer {{ font-size: 16px; fill: #49636e; }}
  </style>
</svg>
"""
    path.write_text(payload, encoding="utf-8")


def _write_index(path: Path, *, release_id: str, slides: list[dict[str, str]]) -> None:
    cards = "\n".join(
        (
            '<figure><a href="{file}"><img src="{file}" alt="Step {step}: {title}"></a>'
            "<figcaption><strong>Step {step}: {title}</strong><br>{status}</figcaption></figure>"
        ).format(
            file=html.escape(item["file"]),
            step=item["step"],
            title=html.escape(item["title"]),
            status=html.escape(item["status"]),
        )
        for item in slides
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Analysis Studio · deterministic fallback</title>
<style>body{{margin:0;background:#eef3f5;color:#17313d;font-family:Inter,Arial,sans-serif}}header,main{{max-width:1180px;margin:auto;padding:28px}}header{{background:#102c43;color:white;max-width:none}}header>div{{max-width:1180px;margin:auto}}.warning{{background:#ffe9ad;color:#4b3700;padding:14px;font-weight:800}}figure{{margin:28px 0;background:white;border:1px solid #cad6dc;border-radius:14px;padding:16px}}img{{display:block;width:100%;height:auto}}figcaption{{padding:14px 4px 2px;line-height:1.5}}code{{overflow-wrap:anywhere}}a:focus-visible{{outline:4px solid #f2a900;outline-offset:4px}}</style>
</head><body><header><div><h1>AI Analysis Studio · static deterministic fallback</h1><p>Ten reproducible presentation frames generated from one certified synthetic release and a zero-provider-cost local analysis.</p></div></header>
<div class="warning">{html.escape(INTERACTIVE_LABEL)}</div>
<main><p><strong>Parent release:</strong> <code>{html.escape(release_id)}</code></p><p>{html.escape(PROHIBITED_USE)}</p>{cards}</main></body></html>"""
    path.write_text(document, encoding="utf-8")


def build_ai_demo_package(
    root: Path,
    settings: AIStudioSettings,
    *,
    output_dir: Path | None = None,
    confirm_run: bool = False,
) -> dict[str, Any]:
    """Build ten deterministic fallback frames; execute only with explicit confirmation."""
    root = root.resolve()
    offline = settings.model_copy(update={"openai_api_key": None, "vector_store_id": None})
    catalogue = build_artifact_catalogue(root, offline)
    evidence = EvidenceTools(root, catalogue)
    specialist_tools = SpecialistAnalysisTools(offline, evidence)
    orchestrator = SpecialistOrchestrator(offline, specialist_tools)
    before = _release_hashes(root, catalogue)

    metric = evidence.get_certified_metric("initiated_90d", "ALL")
    tactics = {item["tactic_id"]: item for item in specialist_tools.list_tactics()}
    initiation = tactics["initiation_landmarks"]
    model_disposition = tactics["model_disposition"]
    preview = orchestrator.prepare_preview(
        "Compare DE and FR using a 60-day initiation window. Keep market denominators separate.",
        selected_lens=ExpertLens.RWE_EPIDEMIOLOGY,
        tactic_id="initiation_landmarks",
        parameters={"markets": ["DE", "FR"], "initiation_window_days": 60},
        remaining_budget_usd=2.0,
        specialist_mode=True,
        use_model_router=False,
    )
    run: InteractiveRun | None = None
    if confirm_run:
        if not preview.confirmation_token:
            raise ValueError("deterministic demo preview is not executable")
        run = orchestrator.execute(
            preview.request_id,
            confirmation_token=preview.confirmation_token,
            confirmation_text="RUN THIS ANALYSIS",
            use_model_summary=False,
        )

    target = (
        output_dir.resolve()
        if output_dir
        else (
            root
            / "outputs"
            / "experiments"
            / "ai_studio"
            / "demo_fallback"
            / _slug(catalogue.release_id)
        ).resolve()
    )
    experiment_root = (root / "outputs" / "experiments").resolve()
    if not target.is_relative_to(experiment_root):
        raise ValueError("demo fallback must remain inside outputs/experiments")
    target.mkdir(parents=True, exist_ok=True)

    denominator_lines = [
        f"{item.market}: numerator {item.numerator} / denominator {item.denominator}; "
        f"excluded {item.excluded}; censored {item.censored}."
        for item in preview.population_preview.slices
    ]
    diff_lines = [
        f"{item.parameter}: {item.certified_value} → {item.proposed_value}. {item.impact}"
        for item in preview.parameter_diff
        if item.changed
    ]
    result_lines = (
        [
            f"{item.market}: {item.label} = {item.rate * 100:.1f}% "
            f"({item.numerator}/{item.denominator}); {item.time_window}."
            for item in run.results
            if item.rate is not None
        ]
        if run
        else ["Execution intentionally not performed; use --confirm-run to create an isolated run."]
    )
    slides_data: list[tuple[str, list[str], str]] = [
        (
            "Certified initiation answer",
            [
                f"Certified synthetic 90-day initiation: {metric.value:.1f}%.",
                f"Numerator {metric.numerator} / denominator {metric.denominator}.",
                f"Population: {metric.population}.",
                f"Method: {metric.method}.",
            ],
            "DETERMINISTIC DERIVATION · MODEL NOT USED",
        ),
        (
            "Cited evidence and provenance",
            [
                f"Evidence file: {metric.source_file}.",
                f"Artifact ID: {metric.source_artifact_id}.",
                f"Source commit: {catalogue.source_commit}.",
                f"Release manifest SHA-256: {before['release_manifest.json']}.",
            ],
            "CERTIFIED SOURCE · RELEASE-SCOPED",
        ),
        (
            "Initiation tactic contract",
            [
                str(initiation["question"]),
                f"Target: {initiation['target_population']}.",
                f"Denominator: {initiation['denominator_definition']}.",
                f"Method: {initiation['method']}.",
                f"Limitation: {initiation['limitation']}.",
            ],
            f"REGISTERED TACTIC · {initiation['reviewer_status']}",
        ),
        (
            "Natural-language parameter change",
            [
                "Question: Compare DE and FR using a 60-day initiation window.",
                "Expert lens: RWE epidemiology.",
                "Routing model: OFF for deterministic presentation.",
                "Narrative model summary: OFF.",
                *diff_lines,
            ],
            "INTERACTIVE RE-RUN · EXPLICIT PARAMETER DIFF",
        ),
        (
            "Typed diff and denominator preview",
            [
                f"AnalysisSpec request ID: {preview.request_id}.",
                f"Validation: {'PASS' if preview.validation.valid else 'FAIL'}.",
                f"Current combined denominator preview: {preview.population_preview.current_denominator}.",
                *denominator_lines,
            ],
            "DENOMINATORS VISIBLE BEFORE EXECUTION",
        ),
        (
            "Explicit controlled execution",
            [
                "Execution required the exact confirmation: RUN THIS ANALYSIS.",
                "Engine: deterministic local Python.",
                "Patient-level export: prohibited.",
                "Certified output mutation: prohibited.",
                f"Execution performed for this package: {'YES' if run else 'NO'}.",
            ],
            "HUMAN CONFIRMATION BOUNDARY",
        ),
        (
            "Result, QA, provenance, and cost",
            [
                *result_lines,
                f"QA: {run.qa.status if run else 'NOT RUN'}.",
                f"Provider cost: ${run.manifest.actual_provider_cost_usd:.6f}."
                if run
                else "Provider cost: $0.000000.",
                f"Run ID: {run.manifest.run_id if run else 'NOT CREATED'}.",
            ],
            "AGGREGATE-ONLY · QA-GATED · ZERO API COST",
        ),
        (
            "Certified Analytics remains unchanged",
            [
                "The re-run is stored only in outputs/experiments/ai_studio/interactive_runs.",
                "Standard Analytics remains independently usable with AI Studio disabled.",
                f"CHECKSUMS.sha256 before: {before['CHECKSUMS.sha256']}.",
                "The final package manifest records the matching after hash.",
            ],
            "CERTIFIED RELEASE IMMUTABLE",
        ),
        (
            "Weak model evidence is not deployable",
            [
                str(model_disposition["question"]),
                f"Method: {model_disposition['method']}.",
                f"Limitation: {model_disposition['limitation']}.",
                "Disposition comes from the verified model registry, never AUC alone.",
                "No AI confidence score or operational recommendation is generated.",
            ],
            "MODEL GOVERNANCE · BROWSE ONLY",
        ),
        (
            "Narrow governed pilot message",
            [
                "Pilot one approved analytical question, not an entire platform.",
                "Keep one accountable human owner and a pre-agreed stop criterion.",
                "Validate source fitness, denominator definitions, and potential harm.",
                "Interactive outputs require human review and never self-certify.",
            ],
            "PROPOSED PILOT · REQUIRES HUMAN APPROVAL",
        ),
    ]

    slides: list[dict[str, str]] = []
    for index, (title, body, status) in enumerate(slides_data, start=1):
        filename = f"step-{index:02d}.svg"
        _write_svg(
            target / filename,
            step=index,
            title=title,
            body=body,
            release_id=catalogue.release_id,
            status=status,
        )
        slides.append({"step": str(index), "file": filename, "title": title, "status": status})

    _write_index(target / "index.html", release_id=catalogue.release_id, slides=slides)
    after = _release_hashes(root, catalogue)
    if before != after:
        raise RuntimeError("certified release hashes changed while building the demo package")
    files = ["index.html", *[item["file"] for item in slides]]
    manifest = {
        "schema_version": "AI-STUDIO-DEMO-FALLBACK-v1.0",
        "generated_at": _now(),
        "static_fallback": True,
        "synthetic_only": True,
        "parent_release_id": catalogue.release_id,
        "source_commit": catalogue.source_commit,
        "tactic_id": "initiation_landmarks",
        "question": preview.spec.research_question,
        "request_id": preview.request_id,
        "run_id": run.manifest.run_id if run else None,
        "qa_status": run.qa.status if run else "NOT_RUN",
        "provider_cost_usd": run.manifest.actual_provider_cost_usd if run else 0.0,
        "certified_hashes_before": before,
        "certified_hashes_after": after,
        "certified_release_unchanged": before == after,
        "prohibited_use": PROHIBITED_USE,
        "files": {name: sha256_file(target / name) for name in files},
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {**manifest, "output_directory": str(target), "slides": len(slides)}
