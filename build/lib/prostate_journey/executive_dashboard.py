"""Industry-grade, aggregate-only certified Analytics product experience."""

from __future__ import annotations

import html
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from . import DISCLAIMER
from .dashboard import eligible_cohort_funnel_counts
from .tactic_registry import (
    DEFAULT_TACTIC_REGISTRY,
    TacticRegistry,
    load_tactic_registry,
    registry_json,
)

FRONTEND_ASSET_ROOT = Path(__file__).with_name("frontend")
PERSISTENCE_EVALUABLE = {"PERSISTENT", "DISCONTINUED", "SWITCHED"}
PROHIBITED_USE = (
    "Not for clinical decisions, treatment recommendations, patient action, market ranking, "
    "causal claims, commercial conclusions, or production AI."
)


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


def _distribution(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    counts = frame[column].fillna("Not available").astype(str).value_counts()
    total = int(counts.sum())
    return [
        {
            "label": str(label).replace("_", " ").title(),
            "value": int(value),
            "pct": _pct(int(value), total),
        }
        for label, value in counts.items()
    ]


def _initiation_windows(frame: pd.DataFrame, eligible: pd.Series) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    eligibility_date = pd.to_datetime(frame.eligibility_date, errors="coerce")
    censor_date = pd.to_datetime(frame.censor_date, errors="coerce")
    eligible_n = int(eligible.sum())
    for days in (30, 60, 90):
        initiated = eligible & frame[f"initiated_within_{days}d"].fillna(False).astype(bool)
        observable_to_landmark = (
            eligibility_date.notna()
            & censor_date.notna()
            & censor_date.ge(eligibility_date + pd.to_timedelta(days, unit="D"))
        )
        censored = eligible & ~initiated & ~observable_to_landmark
        evaluable = eligible & ~censored
        gap = evaluable & ~initiated
        windows.append(
            {
                "days": days,
                "value": int(initiated.sum()),
                "rate": _pct(int(initiated.sum()), eligible_n),
                "evaluable": int(evaluable.sum()),
                "gap": int(gap.sum()),
                "gap_rate_evaluable": _pct(int(gap.sum()), int(evaluable.sum())),
                "censored": int(censored.sum()),
            }
        )
    return windows


def _persistence_sensitivity(frame: pd.DataFrame, initiated_90d: pd.Series) -> list[dict[str, Any]]:
    sensitivity: list[dict[str, Any]] = []
    for gap in (30, 60, 90):
        status = frame[f"persistence_12m_status_gap_{gap}d"].astype("string")
        evaluable = initiated_90d & status.isin(PERSISTENCE_EVALUABLE)
        persistent = initiated_90d & status.eq("PERSISTENT")
        censored = initiated_90d & status.eq("CENSORED_NOT_EVALUABLE")
        sensitivity.append(
            {
                "gap_days": gap,
                "at_risk": int(initiated_90d.sum()),
                "evaluable": int(evaluable.sum()),
                "persistent": int(persistent.sum()),
                "censored": int(censored.sum()),
                "rate": _pct(int(persistent.sum()), int(evaluable.sum())),
            }
        )
    return sensitivity


def _journey_summary(frame: pd.DataFrame) -> dict[str, Any]:
    funnel = eligible_cohort_funnel_counts(frame)
    eligible = frame.eligibility_flag.fillna(False).astype(bool)
    initiated_90d = eligible & frame.initiated_within_90d.fillna(False).astype(bool)
    initiation_windows = _initiation_windows(frame, eligible)
    persistence_sensitivity = _persistence_sensitivity(frame, initiated_90d)
    initiated_days = pd.to_numeric(frame.loc[initiated_90d, "days_to_initiation"], errors="coerce")
    missingness_fields = [
        "race",
        "insurance_type",
        "psa_value",
        "gleason_score",
        "referral_delay_days",
    ]
    missingness = [
        {
            "field": field.replace("_", " ").title(),
            "missing": int(frame[field].isna().sum()),
            "rate": _pct(int(frame[field].isna().sum()), int(len(frame))),
        }
        for field in missingness_fields
        if field in frame
    ]
    active_surveillance = frame.active_surveillance_start_date.notna()
    settings: list[dict[str, Any]] = []
    for setting, group in frame.groupby("initial_care_setting", dropna=False):
        group_eligible = group.eligibility_flag.fillna(False).astype(bool)
        eligible_n = int(group_eligible.sum())
        gap_n = int((group_eligible & group.eligible_not_initiated_90d.fillna(False)).sum())
        settings.append(
            {
                "label": str(setting).replace("_", " ").title(),
                "eligible": eligible_n,
                "gap": gap_n,
                "gap_rate": _pct(gap_n, eligible_n),
            }
        )
    transitions = [
        {
            "label": "Discontinued",
            "value": int((initiated_90d & frame.discontinuation_flag.fillna(False)).sum()),
            "denominator": int(initiated_90d.sum()),
            "definition": "Observed operational discontinuation among eligible day-90 initiators.",
        },
        {
            "label": "Switched",
            "value": int((initiated_90d & frame.switch_flag.fillna(False)).sum()),
            "denominator": int(initiated_90d.sum()),
            "definition": "Explicit treatment switch among eligible day-90 initiators.",
        },
        {
            "label": "Restarted",
            "value": int((initiated_90d & frame.restart_flag.fillna(False)).sum()),
            "denominator": int(initiated_90d.sum()),
            "definition": "Explicit restart among eligible day-90 initiators.",
        },
        {
            "label": "Active surveillance started",
            "value": int(active_surveillance.sum()),
            "denominator": int(len(frame)),
            "definition": "Distinct localized-disease pathway; not part of the mHSPC treatment funnel.",
        },
    ]
    primary_persistence = next(item for item in persistence_sensitivity if item["gap_days"] == 60)
    return {
        "total": int(len(frame)),
        "eligible": funnel["eligible"],
        "eligible_rate": _pct(funnel["eligible"], int(len(frame))),
        "initiated90": funnel["initiated_90d"],
        "initiation_rate": _pct(funnel["initiated_90d"], funnel["eligible"]),
        "gap90": funnel["treatment_gap_90d"],
        "gap_rate": _pct(funnel["treatment_gap_90d"], funnel["eligible"]),
        "initiation_censored": funnel["initiation_censored_not_evaluable_90d"],
        "evaluable12": primary_persistence["evaluable"],
        "persistent12": primary_persistence["persistent"],
        "persistence_rate": primary_persistence["rate"],
        "censored12": primary_persistence["censored"],
        "initiation_windows": initiation_windows,
        "median_days_to_initiation": round(float(initiated_days.median()), 1)
        if not initiated_days.empty
        else None,
        "persistence_sensitivity": persistence_sensitivity,
        "missingness": missingness,
        "duplicate_patient_ids": int(frame.patient_id.duplicated().sum()),
        "active_surveillance_started": int(active_surveillance.sum()),
        "active_surveillance_exited": int(
            (active_surveillance & frame.active_surveillance_exit_date.notna()).sum()
        ),
        "stages": _distribution(frame, "prostate_stage"),
        "settings": sorted(settings, key=lambda item: item["gap_rate"] or 0, reverse=True),
        "regimens": _distribution(
            frame.loc[frame.treatment_initiated.fillna(False)], "initial_regimen"
        )[:6],
        "transitions": transitions,
    }


def _referral_summary(referral: pd.DataFrame) -> dict[str, Any]:
    if referral.empty:
        return {"total": 0, "completed": 0, "completion_rate": None, "median_delay": None}
    completed = referral.referral_status.eq("completed") & referral.completion_date.notna()
    delays = (
        pd.to_datetime(referral.loc[completed, "completion_date"])
        - pd.to_datetime(referral.loc[completed, "referral_date"])
    ).dt.days
    return {
        "total": int(len(referral)),
        "completed": int(completed.sum()),
        "completion_rate": _pct(int(completed.sum()), int(len(referral))),
        "median_delay": round(float(delays.median()), 1) if not delays.empty else None,
    }


def _model_summary(path: str | Path | None) -> dict[str, Any]:
    if path is None or not Path(path).is_file():
        return {"available": False, "items": [], "research_count": 0, "rejected_count": 0}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    items = payload.get("models", [])
    if not isinstance(items, list):
        raise ValueError("Predictive frontend summary models must be a list")
    contract_path = Path(path).with_name("model_target_contracts_snapshot.yaml")
    contract_map: dict[str, dict[str, Any]] = {}
    if contract_path.is_file():
        contract_payload = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        if isinstance(contract_payload, dict) and isinstance(contract_payload.get("models"), list):
            contract_map = {
                str(item["model_id"]): item
                for item in contract_payload["models"]
                if isinstance(item, dict) and item.get("model_id")
            }
    safe_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Predictive frontend model entries must be mappings")
        model_id = str(item.get("model_id"))
        contract = contract_map.get(model_id, {})
        safe_items.append(
            {
                "model_id": model_id,
                "target_name": item.get("target_name")
                or item.get("target")
                or contract.get("target_name"),
                "population": contract.get("model_development_population"),
                "prediction_time": contract.get("prediction_time"),
                "prediction_horizon_days": contract.get("prediction_horizon_days"),
                "validation_n": item.get("validation_n"),
                "validation_event_n": item.get("validation_event_n"),
                "event_prevalence": item.get("event_prevalence"),
                "roc_auc": item.get("roc_auc"),
                "pr_auc": item.get("pr_auc"),
                "brier_score": item.get("brier_score"),
                "calibration_intercept": item.get("calibration_intercept"),
                "calibration_slope": item.get("calibration_slope"),
                "disposition": item.get("disposition"),
                "reason": item.get("reason"),
            }
        )
    dispositions = [str(item.get("disposition")) for item in safe_items]
    return {
        "available": True,
        "items": safe_items,
        "research_count": dispositions.count("RESEARCH ONLY"),
        "rejected_count": dispositions.count("REJECTED"),
    }


def build_executive_payload(
    tables: dict[str, pd.DataFrame],
    registry: TacticRegistry | None = None,
    provenance: dict[str, object] | None = None,
    predictive_summary_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build privacy-safe aggregates; tactic metadata comes only from the canonical registry."""
    tactic_registry = registry or load_tactic_registry(DEFAULT_TACTIC_REGISTRY)
    journey = tables["patient_journey"]
    referral = tables["referral"]
    markets = sorted(journey.market_code.dropna().astype(str).unique())
    segments: dict[str, Any] = {}
    for market in ["ALL", *markets]:
        journey_part = journey if market == "ALL" else journey.loc[journey.market_code.eq(market)]
        referral_part = (
            referral if market == "ALL" else referral.loc[referral.market_code.eq(market)]
        )
        segments[market] = {
            **_journey_summary(journey_part),
            "referrals": _referral_summary(referral_part),
        }
    context = dict(provenance or {})
    release_id = str(context.get("dataset_version", "not recorded"))
    context.update(
        {
            "release_id": release_id,
            "release_short": release_id.removeprefix("BAYER_PROSTATE_PATIENT_JOURNEY_SYNTHETIC_"),
            "source_commit": context.get("source_git_commit") or "not recorded",
            "analysis_commit": context.get("analysis_git_commit") or "not recorded",
            "configuration_hash": context.get("configuration_hash") or "not recorded",
            "generated_at": context.get("generated_at") or datetime.now(UTC).isoformat(),
            "selection_method": context.get("selection_method") or "explicit certified release",
            "qa_status": context.get("qa_status") or "INTERNAL CONSISTENCY PASSED",
            "analytical_status": context.get("analytical_status")
            or "STAGE-4 CONDITIONAL — SYNTHETIC ONLY",
            "verified_artifacts": context.get("verified_artifacts") or 0,
            "primary_limitation": (
                "Synthetic scenario evidence only; independent clinical, RWE, statistical, "
                "privacy, security, and source validation remain required."
            ),
        }
    )
    return {
        "markets": markets,
        "segments": segments,
        "tactics": [item.model_dump(mode="json") for item in tactic_registry.tactics],
        "models": _model_summary(predictive_summary_path),
        "provenance": context,
        "synthetic_only": True,
        "prohibited_use": PROHIBITED_USE,
    }


def _write_assets(output_dir: Path) -> None:
    assets = output_dir / "assets"
    assets.mkdir(exist_ok=True)
    for filename in ("analytics.css", "analytics.js"):
        source = FRONTEND_ASSET_ROOT / filename
        if not source.is_file():
            raise FileNotFoundError(f"Required frontend asset is missing: {source}")
        shutil.copy2(source, assets / filename)


def _write_aggregate_export(payload: dict[str, Any], output_dir: Path) -> None:
    segment = payload["segments"]["ALL"]
    provenance = payload["provenance"]
    rows: list[dict[str, Any]] = []

    def add_row(
        metric_id: str,
        value: int,
        numerator: int,
        denominator: int,
        population: str,
        time_window: str,
        method: str,
    ) -> None:
        rows.append(
            {
                "metric_id": metric_id,
                "value": value,
                "numerator": numerator,
                "denominator": denominator,
                "rate": numerator / denominator if denominator else None,
                "population": population,
                "time_window": time_window,
                "selected_scenario": "ALL CONFIGURED SYNTHETIC SCENARIOS",
                "method": method,
                "release_id": provenance["release_id"],
                "source_commit": provenance["source_commit"],
                "active_filters": "market=ALL;initiation_window=90;persistence_gap=60",
                "generated_time": provenance["generated_at"],
                "prohibited_use": PROHIBITED_USE,
                "synthetic_only": True,
            }
        )

    add_row(
        "eligible",
        segment["eligible"],
        segment["eligible"],
        segment["total"],
        "Selected synthetic cohort",
        "Eligibility index",
        "Versioned cohort attrition",
    )
    for item in segment["initiation_windows"]:
        add_row(
            f"initiated_{item['days']}d",
            item["value"],
            item["value"],
            segment["eligible"],
            "Eligible synthetic records",
            f"{item['days']} days after eligibility",
            "Censor-aware cumulative landmark count",
        )
        add_row(
            f"not_initiated_{item['days']}d_evaluable",
            item["gap"],
            item["gap"],
            item["evaluable"],
            "Eligible records evaluable through the landmark",
            f"{item['days']} days after eligibility",
            "Evaluable landmark complement with censoring separate",
        )
    for item in segment["persistence_sensitivity"]:
        add_row(
            f"persistent_12m_gap_{item['gap_days']}d",
            item["persistent"],
            item["persistent"],
            item["evaluable"],
            "Evaluable eligible day-90 initiators",
            f"365 days; {item['gap_days']}-day permissible gap",
            "Operational persistence landmark sensitivity",
        )
    pd.DataFrame(rows).to_csv(output_dir / "aggregate_export.csv", index=False)


def _write_accessible_report(payload: dict[str, Any], output_dir: Path) -> None:
    segment = payload["segments"]["ALL"]
    provenance = payload["provenance"]
    market_rows = "".join(
        "<tr>"
        f"<th scope='row'>{html.escape(market)}</th>"
        f"<td>{summary['total']:,}</td><td>{summary['eligible']:,}</td>"
        f"<td>{summary['initiated90']:,}/{summary['eligible']:,}</td>"
        f"<td>{summary['persistent12']:,}/{summary['evaluable12']:,}</td>"
        "</tr>"
        for market, summary in (
            (market, payload["segments"][market]) for market in payload["markets"]
        )
    )
    tactic_rows = "".join(
        "<tr>"
        f"<th scope='row'>{html.escape(tactic['title'])}</th>"
        f"<td>{html.escape(tactic['numerator_definition'])}</td>"
        f"<td>{html.escape(tactic['denominator_definition'])}</td>"
        f"<td>{html.escape(tactic['method'])}</td>"
        f"<td>{html.escape(tactic['limitation'])}</td>"
        "</tr>"
        for tactic in payload["tactics"]
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Accessible Certified Analytics Report</title><link rel="stylesheet" href="assets/analytics.css"></head>
<body><a class="skip-link" href="#report">Skip to report</a>
<div class="trust-warning">SYNTHETIC SCENARIO — NOT REAL PATIENT, BAYER, CLINICAL, COMMERCIAL, OR POPULATION DATA</div>
<main id="report" class="shell"><h1>Accessible certified Analytics report</h1>
<p><strong>Release:</strong> {html.escape(str(provenance["release_id"]))}<br>
<strong>Source commit:</strong> {html.escape(str(provenance["source_commit"]))}<br>
<strong>Configuration hash:</strong> {html.escape(str(provenance["configuration_hash"]))}<br>
<strong>Generated:</strong> {html.escape(str(provenance["generated_at"]))}<br>
<strong>Filters:</strong> all configured scenarios; 90-day initiation; 60-day persistence gap.</p>
<section><h2>Denominator ledger</h2><ol>
<li>{segment["total"]:,} total synthetic records.</li>
<li>{segment["eligible"]:,} eligible records.</li>
<li>{segment["initiated90"]:,} of {segment["eligible"]:,} initiated by day 90.</li>
<li>{segment["gap90"]:,} eligible/evaluable records not initiated by day 90.</li>
<li>{segment["evaluable12"]:,} day-90 initiators evaluable at month 12.</li>
<li>{segment["persistent12"]:,} of {segment["evaluable12"]:,} meet the 60-day operational persistence definition.</li>
<li>{segment["censored12"]:,} month-12 censored records are shown separately and are not in the persistence denominator.</li>
</ol></section>
<section><h2>Configured scenario table</h2><div class="table-wrap"><table><caption>Exact aggregate counts; not a real-market comparison.</caption>
<thead><tr><th>Scenario</th><th>Total</th><th>Eligible</th><th>Initiated by day 90</th><th>Persistent at month 12</th></tr></thead>
<tbody>{market_rows}</tbody></table></div></section>
<section><h2>Tactic methodology</h2><div class="table-wrap"><table><caption>Canonical Tactic Library v2 metadata.</caption>
<thead><tr><th>Tactic</th><th>Numerator</th><th>Denominator</th><th>Method</th><th>Limitation</th></tr></thead>
<tbody>{tactic_rows}</tbody></table></div></section>
<section><h2>Prohibited use</h2><p>{html.escape(PROHIBITED_USE)}</p></section>
</main></body></html>"""
    (output_dir / "accessible_report.html").write_text(document, encoding="utf-8")


def _write_demo_fallback(payload: dict[str, Any], output_dir: Path) -> None:
    segment = payload["segments"]["ALL"]
    windows = {item["days"]: item for item in segment["initiation_windows"]}
    provenance = payload["provenance"]
    steps = [
        ("Executive overview", "Start with the analytical question and synthetic-data boundary."),
        ("Trust bar", f"Release {provenance['release_id']}; all configured synthetic scenarios."),
        (
            "Denominator chain",
            f"{segment['total']:,} total → {segment['eligible']:,} eligible → "
            f"{segment['initiated90']:,} initiated by day 90.",
        ),
        (
            "Change 90 days to 60 days",
            f"{windows[60]['value']:,}/{segment['eligible']:,} initiate by day 60; "
            f"the eligible denominator remains visible.",
        ),
        (
            "Scenario comparison",
            "Compare configured scenario dots with exact n/N; do not rank markets.",
        ),
        ("Open a tactic", "Open Persistence definition sensitivity and review Levels 1–3."),
        (
            "Method and limitation",
            "Show evaluable denominator, 365-day horizon, and dispensing-proxy limitation.",
        ),
        (
            "Provenance",
            "Show release, commit, configuration hash, analysis ID, tactic ID, and evidence file.",
        ),
        (
            "Model disposition",
            "No release-matched predictive evidence is available here; no model metric or status is inferred.",
        ),
        ("Reset", "Return to all scenarios, 90-day initiation, and 60-day persistence gap."),
    ]
    fallback_dir = output_dir / "fallback"
    fallback_dir.mkdir(exist_ok=True)
    fallback_boards = [
        (
            "01-executive-overview.svg",
            "A confident denominator beats a confident prediction",
            [
                f"{segment['total']:,} total synthetic records",
                f"{segment['eligible']:,} eligible",
                f"{segment['initiated90']:,}/{segment['eligible']:,} initiated by day 90",
            ],
        ),
        (
            "02-denominator-ledger.svg",
            "Every number has a denominator",
            [
                f"Initiation: {segment['initiated90']:,}/{segment['eligible']:,}",
                f"Persistence: {segment['persistent12']:,}/{segment['evaluable12']:,}",
                f"Censored separately: {segment['censored12']:,}",
            ],
        ),
        (
            "03-method-evidence.svg",
            "Every result opens to method, limitation, and evidence",
            [
                "Tactic Library v2: 10 canonical analytical contracts",
                "Three disclosure levels: plain language, method, evidence",
                f"Release: {provenance['release_id']}",
            ],
        ),
        (
            "04-model-disposition.svg",
            "Weak or unavailable models show where not to automate",
            [
                "Release-matched predictive evidence unavailable",
                "No AUC, status, or deployment claim inferred",
                "Operational models: 0",
            ],
        ),
    ]
    for filename, title, lines in fallback_boards:
        line_markup = "".join(
            f'<text x="100" y="{300 + index * 90}" font-family="Arial" font-size="38" '
            f'fill="#152536">{html.escape(line)}</text>'
            for index, line in enumerate(lines)
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" role="img" aria-labelledby="title description">
<title id="title">{html.escape(title)}</title><desc id="description">Static certified Analytics demo fallback for synthetic data.</desc>
<rect width="1600" height="900" fill="#f3f6f8"/><rect x="60" y="60" width="1480" height="780" rx="28" fill="#fff" stroke="#cad5df"/>
<rect x="60" y="60" width="1480" height="110" rx="28" fill="#102a43"/><text x="100" y="130" font-family="Arial" font-size="28" font-weight="700" fill="#fff">SYNTHETIC SCENARIO — NOT REAL PATIENT, BAYER, CLINICAL, COMMERCIAL, OR POPULATION DATA</text>
<text x="100" y="240" font-family="Arial" font-size="52" font-weight="700" fill="#102a43">{html.escape(title)}</text>{line_markup}
<text x="100" y="790" font-family="Arial" font-size="24" fill="#526579">{html.escape(str(provenance["release_id"]))} · {html.escape(PROHIBITED_USE)}</text></svg>"""
        (fallback_dir / filename).write_text(svg, encoding="utf-8")
    cards = "".join(
        f"<article class='panel'><span class='kicker'>Step {index}</span><h2>{html.escape(title)}</h2>"
        f"<p>{html.escape(copy)}</p><p class='metadata'>Expected state: {html.escape(copy)}</p></article>"
        for index, (title, copy) in enumerate(steps, start=1)
    )
    board_links = "".join(
        f'<li><a href="fallback/{filename}">{html.escape(title)}</a></li>'
        for filename, title, _ in fallback_boards
    )
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Static demo fallback</title>
<link rel="stylesheet" href="assets/analytics.css"></head><body>
<div class="trust-warning">SYNTHETIC SCENARIO — NOT REAL PATIENT, BAYER, CLINICAL, COMMERCIAL, OR POPULATION DATA</div>
<main class="shell"><h1>Five-minute deterministic demo — static fallback</h1>
<p>Release <code>{html.escape(str(provenance["release_id"]))}</code>. Use these fixed boards if live interaction is unavailable.</p>
<h2>Static fallback visuals</h2><ul>{board_links}</ul>
<div class="question-grid">{cards}</div><p><strong>{html.escape(PROHIBITED_USE)}</strong></p></main></body></html>"""
    (output_dir / "demo_fallback.html").write_text(document, encoding="utf-8")


def _dashboard_document(payload: dict[str, Any]) -> str:
    provenance = payload["provenance"]
    cohort_size = f"{int(payload['segments']['ALL']['total']):,}"
    market_count = len(payload["markets"])
    science_link = (
        '<a class="button secondary" href="scientific_story.html">Scientific evidence</a>'
        if provenance.get("scientific_evidence_available")
        else ""
    )
    model_link = (
        '<a class="button secondary" href="model_story.html">Model evidence</a>'
        if provenance.get("predictive_evidence_available")
        else ""
    )
    data_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    release = html.escape(str(provenance["release_id"]))
    source_commit = html.escape(str(provenance["source_commit"]))
    config_hash = html.escape(str(provenance["configuration_hash"]))
    generated_at = html.escape(str(provenance["generated_at"]))
    disclaimer = html.escape(DISCLAIMER)
    filters = [
        "All",
        "Cohort",
        "Longitudinal",
        "Treatment",
        "Referral",
        "Missingness",
        "Data Quality",
        "Predictive",
        "Governance",
    ]
    filter_buttons = "".join(
        f'<button class="filter-button" type="button" data-filter="{category}" '
        f'aria-pressed="{str(category == "All").lower()}">{category}</button>'
        for category in filters
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Certified aggregate synthetic patient-journey analytics product">
<title>Patient Journey Explorer — Certified Analytics</title>
<link rel="stylesheet" href="assets/analytics.css"></head><body>
<a class="skip-link" href="#main-content">Skip to certified analytics</a>
<header class="trust-bar" id="trustDetail">
  <div class="trust-warning">SYNTHETIC SCENARIO — NOT REAL PATIENT, BAYER, CLINICAL, COMMERCIAL, OR POPULATION DATA</div>
  <div class="trust-context" aria-label="Persistent analytical context">
    <div class="trust-item"><span>Certified release</span><strong id="trustRelease"></strong></div>
    <div class="trust-item"><span>Scenario</span><strong id="trustScenario"></strong></div>
    <div class="trust-item"><span>Active cohort</span><strong id="trustCohort"></strong></div>
    <div class="trust-item"><span>Active denominator</span><strong id="trustDenominator"></strong></div>
    <div class="trust-item"><span>Initiation window</span><strong id="trustWindow"></strong></div>
    <div class="trust-item"><span>Persistence gap</span><strong id="trustGap"></strong></div>
    <div class="trust-item"><span>Analytical status</span><strong id="trustStatus"></strong></div>
    <button class="button" type="button" data-reset>Reset to Certified View</button>
  </div>
</header>
<div class="shell">
  <nav class="product-nav" aria-label="Analytics product navigation">
    <div class="brand"><span class="brand-mark">PJ</span><span>Patient Journey Explorer</span></div>
    <div class="view-tabs" role="tablist" aria-label="Product views">
      <button class="view-tab" type="button" role="tab" aria-selected="true" data-view-target="executive">Executive</button>
      <button class="view-tab" type="button" role="tab" aria-selected="false" data-view-target="analyst">Analyst</button>
      <button class="view-tab" type="button" role="tab" aria-selected="false" data-view-target="methodology">Methodology</button>
      <button class="view-tab" type="button" role="tab" aria-selected="false" data-view-target="governance">Governance</button>
    </div>
    <div class="nav-actions"><button class="button primary" id="presentationMode" type="button">Presentation Mode</button>{science_link}{model_link}</div>
  </nav>
  <section class="panel non-presentation" aria-labelledby="controlsHeading">
    <h2 id="controlsHeading">Analytical controls</h2>
    <p class="subtle">Every change updates the persistent context. Denominator changes are announced and never hidden.</p>
    <div class="control-row">
      <label>Configured scenario <select class="select-control" id="marketSelect"><option value="ALL">All configured scenarios</option></select></label>
      <label>Initiation window <select class="select-control" id="windowSelect"><option value="30">30 days</option><option value="60">60 days</option><option value="90">90 days</option></select></label>
      <label>Persistence gap <select class="select-control" id="gapSelect"><option value="30">30 days</option><option value="60">60 days</option><option value="90">90 days</option></select></label>
      <button class="button secondary" type="button" data-reset>Reset Demo</button>
    </div>
  </section>
  <div class="denominator-change" id="denominatorChange" role="status" aria-live="polite" hidden></div>
  <div class="denominator-change" id="windowChange" role="status" aria-live="polite" hidden></div>
  <div id="liveStatus" class="sr-only" role="status" aria-live="polite"></div>
  <div id="loadingState" class="loading-state">Loading certified aggregate evidence…</div>
  <div id="fatalState" class="error-state" hidden></div>

  <main id="main-content">
    <div class="view" data-view="executive">
      <section class="hero" aria-labelledby="executiveHeading">
        <div><span class="eyebrow">Executive · deterministic certified Analytics</span>
          <h1 id="executiveHeading" tabindex="-1">A confident denominator beats a confident prediction.</h1>
          <p>Explore how {cohort_size} synthetic patients move through a governed cohort, initiation, referral, and longitudinal evidence contract across {market_count} configured scenarios.</p>
        </div>
        <aside class="hero-side"><strong>Question being explored</strong><p>Can explicit cohort, timing, censoring, and provenance contracts create a safer foundation for a future governed pilot?</p></aside>
      </section>
      <section class="section" aria-labelledby="overviewQuestions">
        <div class="section-heading"><div><span class="kicker">Executive Overview</span><h2 id="overviewQuestions">What this scenario can—and cannot—tell us</h2></div><p>The product separates an analytical observation from a real-world conclusion.</p></div>
        <div class="question-grid">
          <article class="panel"><h3>Who is in the denominator?</h3><p>Versioned synthetic eligibility and evaluability rules define each population before a KPI is calculated.</p></article>
          <article class="panel"><h3>What does it show?</h3><p>Configured scenario behavior across initiation, persistence, referral, transitions, segmentation, and missingness.</p></article>
          <article class="panel"><h3>What should a pilot test?</h3><p>One approved source-fit and workflow question, with named owners, harms, stop criteria, and validation evidence.</p></article>
        </div>
      </section>
      <section class="section" aria-labelledby="headlineHeading">
        <div class="section-heading"><div><span class="kicker">Cohort &amp; Initiation</span><h2 id="headlineHeading">Every headline exposes n/N</h2></div><p>Counts, population, time window, and release travel with each result.</p></div>
        <div class="kpi-grid" id="executiveKpis"></div>
      </section>
      <section class="section" id="denominatorLedger" aria-labelledby="ledgerHeading">
        <div class="section-heading"><div><span class="kicker">Denominator ledger</span><h2 id="ledgerHeading" tabindex="-1">Attrition and censoring are separate branches</h2></div><button class="evidence-button" type="button" data-evidence="cohort_definition">Evidence &amp; provenance</button></div>
        <article class="panel"><div class="ledger" id="cohortLedger"></div><p class="chart-summary" id="ledgerSummary"></p></article>
      </section>
      <section class="section two-column" id="initiationSection" aria-label="Initiation and persistence views">
        <article class="panel"><span class="kicker">Initiation</span><h2 tabindex="-1">Cumulative landmarks, not a decorative funnel</h2><div class="dot-plot" id="initiationPlot"></div><p class="chart-summary" id="initiationSummary"></p><button class="evidence-button" type="button" data-evidence="initiation_landmarks">Evidence &amp; provenance</button></article>
        <article class="panel"><span class="kicker">Longitudinal journey</span><h2>Persistence definition sensitivity</h2><div class="dot-plot" id="persistencePlot"></div><p class="chart-summary" id="persistenceSummary"></p><button class="evidence-button" type="button" data-evidence="persistence_sensitivity">Evidence &amp; provenance</button></article>
      </section>
      <section class="section" aria-labelledby="uncertaintyHeading">
        <div class="section-heading"><div><span class="kicker">Uncertainty</span><h2 id="uncertaintyHeading">Three questions, three labels</h2></div><p>Unavailable uncertainty is stated, never replaced by a generic “95% confidence interval.”</p></div>
        <div class="uncertainty-grid">
          <article class="panel uncertainty-card"><h3>Simulation variability</h3><p>How much a result changes when a new synthetic cohort is generated under the same assumptions.</p><p><span class="status-chip unavailable">UNAVAILABLE FOR SELECTED RELEASE</span></p></article>
          <article class="panel uncertainty-card"><h3>Scenario assumption range</h3><p id="scenarioRange"></p></article>
          <article class="panel uncertainty-card"><h3>Statistical estimation uncertainty</h3><p>Sampling/estimator precision inside one fixed generated dataset.</p><p><span class="status-chip unavailable">RELEASE-MATCHED SCIENTIFIC EVIDENCE UNAVAILABLE</span></p></article>
        </div>
      </section>
      <section class="section" id="pilotSection" aria-labelledby="pilotHeading">
        <div class="section-heading"><div><span class="kicker">Pilot hypotheses</span><h2 id="pilotHeading" tabindex="-1">Pilot one governed question, not an entire platform</h2></div><p>Transform an observation into a reviewable test—never a treatment or patient recommendation.</p></div>
        <article class="panel"><p>A hypothesis captures population, suspected mechanism, workflow step, source fields, validation, potential harm, human owner, approval, and stop criterion.</p><button class="button primary" id="createPilot" type="button">Create Pilot Hypothesis</button></article>
      </section>
    </div>

    <div class="view" data-view="analyst" hidden>
      <header class="section-heading"><div><span class="kicker">Analyst workspace</span><h1 id="analystHeading" tabindex="-1">Inspect the pathway without losing the denominator</h1></div><p>Aggregate scenario exploration only; no patient-level export or silent fallback.</p></header>
      <section class="section two-column" aria-label="Referral and transition summaries">
        <article class="panel"><h2>Referral pathway</h2><div class="inspector-grid" id="referralSummary"></div><button class="evidence-button" type="button" data-evidence="referral_pathway">Evidence &amp; provenance</button></article>
        <article class="panel"><h2>Treatment transitions</h2><div class="inspector-grid" id="transitionSummary"></div><p class="chart-summary">Transition counts are descriptive states, not treatment quality or benefit.</p></article>
      </section>
      <section class="section" id="scenarioSection" aria-labelledby="scenarioHeading">
        <div class="section-heading"><div><span class="kicker">Scenario Comparison</span><h2 id="scenarioHeading" tabindex="-1">Configured differences are hypotheses, not rankings</h2></div><button class="evidence-button" type="button" data-evidence="segmented_treatment_gap">Evidence &amp; provenance</button></div>
        <article class="panel"><div class="dot-plot" id="marketPlot"></div><p class="chart-summary">Direct labels show exact n/N. Position supports comparison without “best” or “worst” language.</p></article>
        <div class="table-wrap" style="margin-top:14px"><table><caption>Aggregate synthetic scenario measures under one cohort definition.</caption><thead><tr><th>Scenario</th><th>Cohort</th><th>Eligible</th><th>Initiated n/N</th><th>Initiation rate</th><th>Not initiated n/N</th><th>Persistent n/N</th></tr></thead><tbody id="marketTableBody"></tbody></table></div>
      </section>
      <section class="section" aria-labelledby="missingnessHeading">
        <div class="section-heading"><div><span class="kicker">Missingness</span><h2 id="missingnessHeading">Availability by field and configured scenario</h2></div><button class="evidence-button" type="button" data-evidence="missingness_profile">Evidence &amp; provenance</button></div>
        <article class="panel"><div class="heatmap" id="missingnessHeatmap" role="group" aria-label="Missingness heatmap with exact text labels"></div><p class="chart-summary" id="missingnessSummary"></p></article>
      </section>
      <section class="section" id="tacticSection" aria-labelledby="tacticHeading">
        <div class="section-heading"><div><span class="kicker">Tactic Library v2</span><h2 id="tacticHeading" tabindex="-1">Open every analytical tactic</h2></div><p>One canonical registry supplies metadata to this product and the future Evidence Copilot.</p></div>
        <div class="filter-row"><label class="sr-only" for="tacticSearch">Search tactics</label><input class="search-control" id="tacticSearch" type="search" placeholder="Search tactics, methods, or categories">{filter_buttons}</div><div class="tactic-grid" id="tacticGrid"></div>
      </section>
    </div>

    <div class="view" data-view="methodology" hidden>
      <header class="section-heading"><div><span class="kicker">Methodology</span><h1 id="methodologyHeading" tabindex="-1">The analytical contract before interpretation</h1></div><p>Research question, population, numerator, denominator, time zero, horizon, censoring, assumptions, sensitivity, and limitations.</p></header>
      <section class="section panel" aria-labelledby="inspectorHeading"><div class="section-heading"><div><span class="kicker">Reusable control</span><h2 id="inspectorHeading">Denominator Inspector</h2></div><label>Analysis <select class="select-control" id="denominatorAnalysis"><option value="initiation">Initiation</option><option value="persistence">Persistence</option><option value="referral">Referral</option></select></label></div><h3 id="inspectorTitle"></h3><div class="inspector-grid" id="inspectorGrid"></div></section>
      <section class="section" aria-labelledby="contractHeading"><div class="section-heading"><div><span class="kicker">Progressive disclosure</span><h2 id="contractHeading">Method contracts by tactic</h2></div><p>Experts can open exact definitions; executive views remain concise.</p></div><div id="methodologyContracts"></div></section>
      <section class="section three-column" aria-label="Method limitations">
        <article class="panel"><h2>Estimator</h2><p>Current historical release supports descriptive landmark summaries. Release-matched scientific evidence is required before displaying survival or competing-risk estimators.</p></article>
        <article class="panel"><h2>Missingness strategy</h2><p>Describe configured absence. Do not infer MCAR, MAR, or MNAR and do not apply a universal imputation rule.</p></article>
        <article class="panel"><h2>Causal boundary</h2><p>No causal estimand, treatment effect, comparative effectiveness, clinical recommendation, or population estimate is supported.</p></article>
      </section>
    </div>

    <div class="view" data-view="governance" hidden>
      <header class="section-heading"><div><span class="kicker">Governance</span><h1 id="governanceHeading" tabindex="-1">Every result opens to method, limitation, and evidence</h1></div><p>Release identity, lineage, QA state, model disposition, prohibited uses, and reviewer status remain visible.</p></header>
      <section class="section governance-grid">
        <article class="panel"><h2>Certified release context</h2><dl class="provenance-list" id="governanceProvenance"></dl><button class="evidence-button" type="button" data-evidence="evidence_governance">Evidence &amp; provenance</button></article>
        <article class="panel"><h2>Prohibited uses</h2><ul><li>No clinical decision or treatment recommendation.</li><li>No patient outreach, ranking, eligibility, or access action.</li><li>No Bayer, provider, site, market, or commercial performance claim.</li><li>No causal, comparative-effectiveness, population, or real-world-evidence claim.</li><li>No production authorization or real-patient-data processing.</li></ul></article>
      </section>
      <section class="section" id="modelSection" aria-labelledby="modelHeading"><div class="section-heading"><div><span class="kicker">Model disposition</span><h2 id="modelHeading" tabindex="-1">Weak or unavailable evidence is never promoted</h2></div><button class="evidence-button" type="button" data-evidence="model_disposition">Evidence &amp; provenance</button></div><div class="model-grid" id="modelExperience"></div></section>
      <section class="section" aria-labelledby="exportHeading"><div class="section-heading"><div><span class="kicker">Governed exports</span><h2 id="exportHeading">Aggregate and provenance-complete only</h2></div><p>Every generated export includes the synthetic boundary, release, source, active filters, method, denominator, time, and prohibited use.</p></div>
        <article class="panel"><div class="export-row"><button class="button primary" id="downloadPng" type="button">Download presentation PNG</button><a class="button secondary" href="accessible_report.html">Accessible report</a><a class="button secondary" href="aggregate_export.csv" download>Aggregate CSV</a><a class="button secondary" href="evidence_manifest.json" download>Evidence manifest</a><button class="button secondary" id="copyState" type="button">Copy shareable filter state</button><button class="button secondary" id="printReport" type="button">Print / save PDF</button></div><p class="chart-summary">Patient-level export is prohibited and is not implemented.</p></article>
      </section>
      <section class="section" aria-labelledby="statesHeading"><div class="section-heading"><div><span class="kicker">Operational states</span><h2 id="statesHeading">No fake or stale KPI states</h2></div></div><div class="governance-grid">
        <div class="loading-state">Loading certified aggregate evidence…</div><div class="empty-state">No synthetic records meet the current analytical definition.</div><div class="empty-state">The selected analytical population is below the configured reporting threshold.</div><div class="empty-state">This analytical method is not valid under the selected configuration.</div><div class="error-state">The selected certified release could not be resolved. No fallback dataset has been loaded.</div>
      </div></section>
    </div>
  </main>
  <footer class="footer"><strong>{disclaimer}</strong><span>Release {release} · source {source_commit} · config {config_hash} · generated {generated_at}<br>{html.escape(PROHIBITED_USE)}</span></footer>
</div>

<div class="drawer-backdrop" id="evidenceBackdrop" hidden></div><aside class="drawer" id="evidenceDrawer" role="dialog" aria-modal="true" aria-labelledby="evidenceTitle" hidden><div class="drawer-header"><div><span class="kicker">Evidence &amp; Provenance</span><h2 id="evidenceTitle"></h2></div><button class="icon-button" id="closeEvidence" type="button" aria-label="Close evidence drawer">×</button></div><div class="drawer-body" id="evidenceBody"></div><div class="drawer-actions drawer-body"><a class="button primary" id="evidenceFileLink" href="#" target="_blank" rel="noopener">Open evidence file</a><a class="button secondary" href="evidence_manifest.json">Open evidence manifest</a></div></aside>

<div class="modal-backdrop" id="tacticModalBackdrop" hidden></div><section class="modal" id="tacticModal" role="dialog" aria-modal="true" aria-labelledby="tacticTitle" hidden><div class="modal-header"><div><span class="tactic-category" id="tacticCategory"></span><h2 id="tacticTitle"></h2></div><button class="icon-button" id="closeTactic" type="button" aria-label="Close tactic details">×</button></div><div class="modal-body"><section class="tactic-level"><span class="level-label">Level 1 · Plain language</span><div id="tacticLevel1"></div></section><section class="tactic-level"><span class="level-label">Level 2 · Method and denominator</span><div id="tacticLevel2"></div></section><section class="tactic-level"><span class="level-label">Level 3 · Evidence and implementation</span><div id="tacticLevel3"></div></section><button class="button primary" id="tacticEvidence" type="button">Evidence &amp; provenance</button></div></section>

<div class="modal-backdrop" id="pilotBackdrop" hidden></div><section class="modal" id="pilotModal" role="dialog" aria-modal="true" aria-labelledby="pilotModalTitle" hidden><div class="modal-header"><div><span class="kicker">Synthetic hypothesis only</span><h2 id="pilotModalTitle">Create Pilot Hypothesis</h2></div><button class="icon-button" id="closePilot" type="button" aria-label="Close pilot hypothesis">×</button></div><div class="modal-body"><p class="chart-summary">This workflow records a question for governed validation. It is not a recommended treatment, patient action, or operational instruction.</p><form class="pilot-form" onsubmit="return false">
<label class="wide">Analytical observation<textarea id="pilotObservation"></textarea></label><label>Affected analytical population<textarea id="pilotPopulation"></textarea></label><label>Suspected mechanism<textarea id="pilotMechanism" placeholder="Hypothesis only — not established"></textarea></label><label>Workflow step<input id="pilotWorkflow" value="TO BE AGREED"></label><label class="wide">Testable question<textarea id="pilotQuestion"></textarea></label><label>Required source fields<textarea id="pilotFields" placeholder="TO BE AGREED after source assessment"></textarea></label><label>Suggested analytical method<textarea id="pilotMethod" placeholder="Prespecified descriptive or causal method, subject to approval"></textarea></label><label>Expected validation<textarea id="pilotValidation" placeholder="Source, phenotype, endpoint, statistical, and workflow validation"></textarea></label><label>Potential harm<textarea id="pilotHarm" placeholder="False action, inequity, burden, privacy, or misinterpretation"></textarea></label><label>Human owner<input id="pilotOwner"></label><label>Approval required<textarea id="pilotApproval"></textarea></label><label class="wide">Stop criterion<textarea id="pilotStop" placeholder="Stop on data, safety, fairness, validity, workflow, or governance failure"></textarea></label></form><button class="button primary" id="downloadPilot" type="button">Download review draft</button></div></section>

<div class="presentation-controls" id="presentationControls" aria-label="Presentation navigation" hidden><button class="button secondary" id="previousStep" type="button">Previous</button><span class="presentation-step" id="presentationStep"></span><button class="button primary" id="nextStep" type="button">Next</button><button class="button" id="exitPresentation" type="button">Reset Demo</button></div>
<script id="dashboardData" type="application/json">{data_json}</script><script src="assets/analytics.js"></script></body></html>"""


def write_executive_dashboard(
    tables: dict[str, pd.DataFrame],
    output_dir: str | Path,
    provenance: dict[str, object],
    *,
    registry: TacticRegistry | None = None,
    predictive_summary_path: str | Path | None = None,
) -> Path:
    """Write the four-view product, governed exports, and deterministic fallback route."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    tactic_registry = registry or load_tactic_registry(DEFAULT_TACTIC_REGISTRY)
    payload = build_executive_payload(
        tables,
        registry=tactic_registry,
        provenance=provenance,
        predictive_summary_path=predictive_summary_path,
    )
    _write_assets(root)
    (root / "tactic_registry.json").write_text(registry_json(tactic_registry), encoding="utf-8")
    _write_aggregate_export(payload, root)
    _write_accessible_report(payload, root)
    _write_demo_fallback(payload, root)
    output = root / "executive_story.html"
    output.write_text(_dashboard_document(payload), encoding="utf-8")
    return output
