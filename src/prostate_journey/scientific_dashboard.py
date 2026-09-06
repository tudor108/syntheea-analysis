"""Self-contained aggregate scientific evidence frontend."""

from __future__ import annotations

import html
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from . import DISCLAIMER


def _records(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _percentage(value: Any) -> str:
    numeric = _number(value)
    return f"{100 * numeric:.1f}%" if numeric is not None else "Not evaluable"


def _decimal(value: Any, digits: int = 4) -> str:
    numeric = _number(value)
    return f"{numeric:.{digits}f}" if numeric is not None else "Not evaluable"


def build_scientific_dashboard_payload(
    scientific_dir: str | Path,
    simulation_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build a strict-JSON, aggregate-only payload from sealed evidence outputs."""
    science_root = Path(scientific_dir).resolve()
    summary = json.loads(
        (science_root / "scientific_frontend_summary.json").read_text(encoding="utf-8")
    )
    registry = yaml.safe_load(
        (science_root / "analysis_registry_snapshot.yaml").read_text(encoding="utf-8")
    )
    status_counts = Counter(str(item["reviewer_status"]) for item in registry["analyses"])
    risk = pd.read_csv(science_root / "number_at_risk.csv")
    cif = pd.read_csv(science_root / "cumulative_incidence.csv")

    simulation: dict[str, Any] = {
        "available": False,
        "within_scenario": [],
        "monte_carlo_error": [],
        "scenario_envelope": [],
        "sensitivity_drivers": [],
        "completed_seeds": {},
    }
    if simulation_dir is not None:
        simulation_root = Path(simulation_dir).resolve()
        if (simulation_root / "simulation_manifest.json").is_file():
            simulation_manifest = json.loads(
                (simulation_root / "simulation_manifest.json").read_text(encoding="utf-8")
            )
            simulation = {
                "available": True,
                "within_scenario": _records(simulation_root / "within_scenario_variability.csv"),
                "monte_carlo_error": _records(simulation_root / "monte_carlo_error.csv"),
                "scenario_envelope": _records(simulation_root / "scenario_envelope.csv"),
                "sensitivity_drivers": _records(simulation_root / "sensitivity_drivers.csv"),
                "completed_seeds": simulation_manifest["completed_seeds"],
                "scenario_axis": simulation_manifest["scenario_axis"],
                "simulation_version": simulation_manifest["simulation_version"],
            }

    survival = summary["survival"]
    initiation = next((row for row in survival if row["endpoint"] == "initiation"), None)
    missingness = summary["missingness"]
    valid_missingness = [row for row in missingness if _number(row.get("bias")) is not None]
    worst_missingness = max(
        valid_missingness,
        key=lambda row: abs(float(row["bias"])),
        default=None,
    )
    utility = summary["utility_dimensions"]
    utility_status = Counter(str(row["status"]) for row in utility)
    max_risk_difference = int(pd.to_numeric(risk.reconciliation_difference).abs().max())
    endpoint_final_risk = risk.sort_values("time_days").groupby("endpoint").tail(1)
    final_at_risk = int(endpoint_final_risk.n_at_risk_after.sum())
    competing_endpoints = int(cif.groupby("endpoint").cause.nunique().gt(1).sum())

    max_mcse = None
    strongest_driver: dict[str, Any] | None = None
    if simulation["available"]:
        mcse_values = [
            value
            for row in simulation["monte_carlo_error"]
            if (value := _number(row.get("monte_carlo_standard_error"))) is not None
        ]
        max_mcse = max(mcse_values, default=None)
        candidates = [
            row
            for row in simulation["sensitivity_drivers"]
            if row.get("scenario") != "base"
            and _number(row.get("absolute_difference_from_base")) is not None
        ]
        strongest_driver = max(
            candidates,
            key=lambda row: float(row["absolute_difference_from_base"]),
            default=None,
        )

    tactics = [
        {
            "id": "registry",
            "category": "Design",
            "title": "Analysis and estimand registry",
            "question": "Is every analytical question defined before a result is interpreted?",
            "method": (
                "Record the population, denominator, time zero, event, horizon, censoring, "
                "estimator, assumptions, sensitivities, source variables, and review status."
            ),
            "result": f"{len(registry['analyses'])} analyses are registered",
            "interpretation": (
                "The analytical intent is machine-readable and reviewable; it is not yet an "
                "approved protocol or SAP."
            ),
            "limitation": "Engineering and proposed definitions still require named SME approval.",
            "evidence": "analysis_registry_snapshot.yaml",
            "stats": [[status, count] for status, count in sorted(status_counts.items())],
        },
        {
            "id": "survival",
            "category": "Longitudinal",
            "title": "Kaplan–Meier and Greenwood",
            "question": "How does target-event timing evolve under explicit censoring rules?",
            "method": (
                "Build one deterministic first-event record per participant, then estimate "
                "Kaplan–Meier net event-free survival with Greenwood log-log pointwise bands."
            ),
            "result": (
                f"Initiation net event probability at the horizon: "
                f"{_percentage(initiation['kaplan_meier_net_event_probability'])}"
                if initiation
                else "No evaluable initiation endpoint"
            ),
            "interpretation": (
                "The Kaplan–Meier quantity is a synthetic net-event description and is not "
                "presented as absolute probability when competing events exist."
            ),
            "limitation": "Event definitions and non-informative censoring assumptions need review.",
            "evidence": "survival_curves.csv",
            "stats": [
                ["Configured endpoints", len(survival)],
                [
                    "Estimator band",
                    (
                        f"{_percentage(initiation['estimator_band_lower'])}–"
                        f"{_percentage(initiation['estimator_band_upper'])}"
                    )
                    if initiation
                    else "Not evaluable",
                ],
                ["Target events", initiation["target_event_count"] if initiation else 0],
                ["Censoring marks", initiation["censoring_mark_count"] if initiation else 0],
            ],
        },
        {
            "id": "competing",
            "category": "Longitudinal",
            "title": "Aalen–Johansen competing risks",
            "question": "What is cumulative incidence when another event prevents the target?",
            "method": (
                "Retain death and other configured competing causes in the event process and "
                "estimate cause-specific cumulative incidence with Aalen–Johansen."
            ),
            "result": (
                f"Initiation cumulative incidence at the horizon: "
                f"{_percentage(initiation['aalen_johansen_cumulative_incidence'])}"
                if initiation
                else "No evaluable initiation endpoint"
            ),
            "interpretation": (
                "Death is not silently censored when it prevents the event of interest."
            ),
            "limitation": "No adjusted cause-specific model or causal interpretation is fitted.",
            "evidence": "cumulative_incidence.csv",
            "stats": [["Endpoints with competing causes", competing_endpoints]],
        },
        {
            "id": "risk",
            "category": "Quality",
            "title": "Exact number-at-risk reconciliation",
            "question": "Can every participant be accounted for at every event time?",
            "method": (
                "Check risk before = target events + competing events + censored + risk after "
                "at every distinct time."
            ),
            "result": f"Maximum reconciliation difference: {max_risk_difference}",
            "interpretation": "Zero means the configured survival risk sets close arithmetically.",
            "limitation": "Arithmetic reconciliation does not validate clinical event definitions.",
            "evidence": "number_at_risk.csv",
            "stats": [["Final unresolved at risk", final_at_risk]],
        },
        {
            "id": "simulation",
            "category": "Uncertainty",
            "title": "Multi-seed regeneration variation",
            "question": "How stable are metrics when synthetic patients are regenerated?",
            "method": (
                "Repeat each coherent scenario across at least 100 deterministic child seeds, "
                "report empirical intervals, and quantify Monte Carlo standard error."
            ),
            "result": (
                f"Maximum monitored Monte Carlo SE: {_decimal(max_mcse)}"
                if simulation["available"]
                else "Final multi-seed evidence run pending"
            ),
            "interpretation": (
                "This is variation under unchanged synthetic assumptions, not estimator "
                "uncertainty or a real-world range."
            ),
            "limitation": "The generated cohorts and assumptions remain synthetic stress tests.",
            "evidence": (
                "within_scenario_variability.csv"
                if simulation["available"]
                else "scientific_frontend_summary.json"
            ),
            "stats": [
                [scenario.title(), count]
                for scenario, count in simulation["completed_seeds"].items()
            ],
        },
        {
            "id": "scenario",
            "category": "Uncertainty",
            "title": "Low/base/high assumption envelope",
            "question": "Which outputs move most when coherent assumptions change?",
            "method": (
                "Compare scenario means across one care-pathway-friction axis and retain the "
                "difference from base as a sensitivity driver."
            ),
            "result": (
                f"Largest displayed shift: {strongest_driver['metric_id']} in "
                f"{strongest_driver['scenario']} "
                f"({_decimal(strongest_driver['difference_from_base'])})"
                if strongest_driver
                else "Final scenario envelope pending"
            ),
            "interpretation": "The envelope is explicitly not a confidence interval.",
            "limitation": "Bundle values are unsupported until scientific and clinical review.",
            "evidence": (
                "scenario_envelope.csv"
                if simulation["available"]
                else "scientific_frontend_summary.json"
            ),
            "stats": [["Scenario axis", simulation.get("scenario_axis", "Pending")]],
        },
        {
            "id": "missingness",
            "category": "Sensitivity",
            "title": "Missing-data truth recovery",
            "question": "How much bias appears when the complete synthetic truth is deliberately masked?",
            "method": (
                "Apply existing, MCAR, MAR, and MNAR masks repeatedly; compare complete case and "
                "justified oracle weighting examples with known truth; run MNAR delta sensitivity."
            ),
            "result": (
                f"Largest absolute mean bias: {abs(float(worst_missingness['bias'])):.3f} "
                f"({worst_missingness['mechanism']}, {worst_missingness['method']})"
                if worst_missingness
                else "No evaluable missingness result"
            ),
            "interpretation": (
                "Bias, RMSE, coverage, effective sample size, and failures are visible by method."
            ),
            "limitation": "The synthetic experiment does not establish MAR for governed real data.",
            "evidence": "missingness_method_performance.csv",
            "stats": [["Mechanism/method rows", len(missingness)]],
        },
        {
            "id": "utility",
            "category": "Quality",
            "title": "Dimension-specific synthetic utility",
            "question": "Which engineering properties pass without hiding them in one score?",
            "method": (
                "Evaluate schema, keys, time, transitions, distributions, analytical utility, "
                "impossible states, rare cells, cloning, and blocked real-data tests separately."
            ),
            "result": (
                f"{utility_status.get('PASS', 0)} pass, {utility_status.get('WARN', 0)} warn, "
                f"{utility_status.get('BLOCKED', 0)} blocked"
            ),
            "interpretation": "No universal realism score is calculated.",
            "limitation": "Internal PASS does not establish clinical realism or privacy safety.",
            "evidence": "synthetic_utility_dimensions.csv",
            "stats": [[status, count] for status, count in sorted(utility_status.items())],
        },
    ]
    return {
        **summary,
        "available": True,
        "analysis_count": len(registry["analyses"]),
        "review_status_counts": dict(status_counts),
        "risk_reconciliation": {
            "maximum_difference": max_risk_difference,
            "final_unresolved_at_risk": final_at_risk,
        },
        "simulation": simulation,
        "tactics": tactics,
    }


def write_scientific_dashboard(
    scientific_dir: str | Path,
    simulation_dir: str | Path | None,
    output_dir: str | Path,
    provenance: dict[str, object],
) -> Path:
    """Write the accessible, responsive, offline scientific evidence lab."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload = build_scientific_dashboard_payload(scientific_dir, simulation_dir)
    (root / "scientific_dashboard_payload.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    payload_json = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    dataset = html.escape(str(provenance.get("dataset_version", "not recorded")))
    commit = html.escape(str(provenance.get("source_git_commit") or "not recorded")[:12])
    disclaimer = html.escape(DISCLAIMER)
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scientific Evidence Lab</title>
<style>
:root{{--night:#08192d;--ink:#152236;--blue:#155bd7;--teal:#0f9f91;--lime:#c9f26b;
--paper:#f4f5f2;--card:#fff;--muted:#647187;--line:#d9e1eb;--orange:#ef9b35;
--red:#c74747;--shadow:0 20px 55px rgba(15,37,70,.11)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);
color:var(--ink);font:15px/1.55 Inter,Segoe UI,Arial,sans-serif}}button,input{{font:inherit}}
a{{color:inherit}}:focus-visible{{outline:3px solid #ffbd3e;outline-offset:3px}}
.skip{{position:fixed;left:12px;top:8px;z-index:100;transform:translateY(-180%);padding:10px;
background:white;border-radius:8px}}.skip:focus{{transform:none}}.shell{{max-width:1480px;margin:auto;
padding:18px 28px 58px}}.top{{position:sticky;top:12px;z-index:20;display:flex;align-items:center;
gap:16px;padding:12px 16px;border:1px solid rgba(255,255,255,.7);border-radius:17px;
background:rgba(255,255,255,.9);box-shadow:0 10px 30px rgba(8,25,45,.09);
backdrop-filter:blur(16px)}}.brand{{font-weight:850;letter-spacing:-.02em}}.back{{margin-left:auto;
padding:8px 12px;border-radius:9px;background:#eaf1ff;color:var(--blue);text-decoration:none;
font-weight:750}}.hero{{position:relative;overflow:hidden;margin-top:18px;padding:52px;
border-radius:30px;background:var(--night);color:white;box-shadow:var(--shadow)}}.hero:after{{content:"";
position:absolute;width:480px;height:480px;right:-100px;top:-220px;border-radius:50%;
background:radial-gradient(circle,#24b8c6,transparent 68%);opacity:.5}}.eyebrow{{display:inline-flex;
gap:8px;align-items:center;padding:7px 11px;border-radius:99px;background:rgba(255,255,255,.1);
font-size:12px;font-weight:850;text-transform:uppercase;letter-spacing:.09em}}.dot{{width:8px;
height:8px;border-radius:50%;background:var(--lime)}}h1{{position:relative;z-index:1;max-width:850px;
margin:22px 0 12px;font-size:clamp(39px,5vw,68px);line-height:1.02;letter-spacing:-.055em}}
.hero p{{position:relative;z-index:1;max-width:790px;color:#cbd8e8;font-size:18px}}.chips{{position:relative;
z-index:1;display:flex;flex-wrap:wrap;gap:8px;margin-top:24px}}.chip{{padding:8px 11px;
border:1px solid rgba(255,255,255,.18);border-radius:10px;font-size:12px;color:#e3ecf7}}
.section{{margin-top:43px;scroll-margin-top:90px}}.head{{display:flex;align-items:end;
justify-content:space-between;gap:22px;margin-bottom:17px}}.kicker{{font-size:12px;color:var(--blue);
font-weight:850;letter-spacing:.1em;text-transform:uppercase}}h2{{margin:4px 0 0;font-size:clamp(27px,3vw,40px);
letter-spacing:-.04em;line-height:1.08}}.head p{{max-width:620px;margin:0;color:var(--muted)}}
.overview{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.kpi,.panel,.tactic{{padding:23px;
border:1px solid var(--line);border-radius:20px;background:var(--card);box-shadow:0 10px 32px
rgba(20,44,78,.05)}}.kpi small{{display:block;color:var(--muted);font-size:11px;font-weight:850;
letter-spacing:.07em;text-transform:uppercase}}.kpi strong{{display:block;margin:10px 0 4px;
font-size:35px;letter-spacing:-.04em}}.kpi span{{color:var(--muted);font-size:13px}}
.layers{{display:grid;grid-template-columns:.45fr 1.55fr;gap:15px}}.tabs{{display:flex;flex-direction:column;
gap:8px}}.tab{{padding:16px;border:1px solid var(--line);border-radius:13px;background:white;
text-align:left;font-weight:780;cursor:pointer}}.tab.active{{border-color:var(--blue);background:#eaf1ff;
color:var(--blue)}}.layer-view h3{{margin:0;font-size:22px}}.layer-view p{{color:var(--muted)}}
.metric-table{{width:100%;border-collapse:collapse;margin-top:17px;font-size:13px}}
.metric-table th,.metric-table td{{padding:11px 9px;border-bottom:1px solid var(--line);text-align:left}}
.metric-table th{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
.endpoint-tabs,.controls{{display:flex;flex-wrap:wrap;gap:8px;margin:15px 0}}.pill{{padding:9px 12px;
border:1px solid var(--line);border-radius:99px;background:white;cursor:pointer;font-weight:750}}
.pill.active{{background:var(--night);color:white;border-color:var(--night)}}.endpoint-grid{{display:grid;
grid-template-columns:repeat(3,1fr);gap:12px}}.result{{padding:18px;border-radius:15px;background:#eef3fa}}
.result small{{display:block;color:var(--muted);font-weight:750}}.result strong{{display:block;
margin-top:7px;font-size:25px}}.band{{height:10px;margin-top:12px;border-radius:99px;background:#d7e0ed;
overflow:hidden}}.band i{{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--teal))}}
.search{{min-width:280px;padding:11px 13px;border:1px solid #b9c6d6;border-radius:11px;background:white}}
.tactics{{display:grid;grid-template-columns:repeat(4,1fr);gap:13px}}.tactic{{display:flex;
flex-direction:column;min-height:265px}}.tag{{align-self:flex-start;padding:5px 8px;border-radius:7px;
background:#e8f6f3;color:#08766c;font-size:11px;font-weight:850;text-transform:uppercase}}
.tactic h3{{margin:15px 0 7px;font-size:18px;line-height:1.2}}.tactic p{{margin:0;color:var(--muted);
font-size:13px}}.headline{{margin:16px 0!important;padding:12px;border-radius:11px;background:#f0f4fa;
color:var(--ink)!important;font-weight:750}}.open{{margin-top:auto;padding:10px 12px;border:0;border-radius:10px;
background:var(--blue);color:white;font-weight:800;cursor:pointer}}.two{{display:grid;
grid-template-columns:1fr 1fr;gap:15px}}.scroll{{overflow:auto;max-height:510px}}.status{{display:inline-flex;
padding:4px 7px;border-radius:7px;font-size:11px;font-weight:850;background:#e8f6f3;color:#08766c}}
.status.WARN{{background:#fff0da;color:#925b08}}.status.BLOCKED{{background:#f3e9f7;color:#74428a}}
.status.FAIL{{background:#fce8e8;color:var(--red)}}
.notice{{margin-top:18px;padding:17px;border-left:5px solid var(--orange);border-radius:10px;
background:#fff8eb;color:#694b1e}}footer{{display:flex;justify-content:space-between;gap:20px;margin-top:45px;
padding-top:20px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}}
.backdrop{{position:fixed;inset:0;z-index:80;display:grid;place-items:center;padding:20px;
background:rgba(5,15,29,.72)}}.backdrop[hidden]{{display:none}}.modal{{width:min(850px,100%);max-height:90vh;
overflow:auto;border-radius:23px;background:white;box-shadow:0 30px 90px rgba(0,0,0,.3)}}.modal-head{{display:flex;
align-items:start;justify-content:space-between;padding:25px 27px;border-bottom:1px solid var(--line)}}
.modal-head h3{{margin:8px 0 0;font-size:27px}}.close{{width:39px;height:39px;border:1px solid var(--line);
border-radius:10px;background:white;font-size:22px;cursor:pointer}}.modal-body{{padding:27px}}
.modal-result{{padding:18px;border-radius:14px;background:var(--night);color:white;font-size:20px;
font-weight:800}}.explain{{display:grid;grid-template-columns:1fr 1fr;gap:11px;margin-top:13px}}
.explain div{{padding:16px;border-radius:12px;background:#f2f5f9}}.explain h4{{margin:0 0 5px}}
.explain p{{margin:0;color:var(--muted)}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);
gap:9px;margin:13px 0}}.stat{{padding:13px;border:1px solid var(--line);border-radius:11px}}
.stat small{{display:block;color:var(--muted)}}.evidence{{display:inline-block;margin-top:15px;padding:10px 13px;
border-radius:10px;background:#eaf1ff;color:var(--blue);font-weight:800;text-decoration:none}}
@media(max-width:1050px){{.overview,.tactics{{grid-template-columns:repeat(2,1fr)}}
.layers{{grid-template-columns:1fr}}.tabs{{flex-direction:row;flex-wrap:wrap}}}}
@media(max-width:720px){{.shell{{padding:10px 14px 38px}}.hero{{padding:35px 24px}}
.overview,.tactics,.two,.endpoint-grid{{grid-template-columns:1fr}}.top span{{display:none}}
.head{{align-items:start;flex-direction:column}}footer{{flex-direction:column}}.explain,.stats{{grid-template-columns:1fr}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
</style>
</head>
<body>
<a class="skip" href="#main-content">Skip to scientific evidence</a>
<main class="shell" id="main-content" tabindex="-1">
<div class="top"><div class="brand">Scientific Evidence Lab</div><span>Aggregate · reproducible · reviewable</span>
<a class="back" href="executive_story.html">← Patient Journey Explorer</a></div>
<header class="hero"><span class="eyebrow"><i class="dot"></i> Synthetic methods cockpit</span>
<h1>See what the analysis means — and what it cannot mean.</h1>
<p>Explore survival, competing risks, multi-seed stability, scenario sensitivity, missing-data
truth recovery, and synthetic utility without mixing their uncertainty or overstating evidence.</p>
<div class="chips"><span class="chip">Dataset {dataset}</span><span class="chip">Commit {commit}</span>
<span class="chip">No causal interpretation</span><span class="chip">Clinical validation pending</span></div></header>

<section class="section" id="overview"><div class="head"><div><span class="kicker">Evidence map</span>
<h2>What is covered</h2></div><p>These counts describe implemented synthetic controls, not scientific
approval or real-data fitness.</p></div><div class="overview"><article class="kpi"><small>Registered analyses</small>
<strong id="analysisCount">—</strong><span>questions and predictive targets</span></article>
<article class="kpi"><small>Survival endpoints</small><strong id="endpointCount">—</strong>
<span>with explicit time zero and horizon</span></article><article class="kpi"><small>Seeds completed</small>
<strong id="seedCount">—</strong><span>across low/base/high scenarios</span></article>
<article class="kpi"><small>Governed real-data hooks</small><strong id="blockedCount">—</strong>
<span>blocked pending data and approvals</span></article></div></section>

<section class="section" id="uncertainty"><div class="head"><div><span class="kicker">Do not mix</span>
<h2>Three different uncertainty questions</h2></div><p>Switch layers to see the correct quantity,
label, and interpretation.</p></div><div class="layers"><div class="tabs" role="tablist"
aria-label="Uncertainty type"><button class="tab active" data-layer="estimator" role="tab">
1 · Estimator</button><button class="tab" data-layer="regeneration" role="tab">2 · Regeneration</button>
<button class="tab" data-layer="scenario" role="tab">3 · Scenario assumptions</button></div>
<article class="panel layer-view"><h3 id="layerTitle"></h3><p id="layerCopy"></p>
<div class="scroll"><table class="metric-table"><thead id="layerHead"></thead>
<tbody id="layerBody"></tbody></table></div></article></div></section>

<section class="section" id="survival"><div class="head"><div><span class="kicker">Longitudinal</span>
<h2>Endpoint evidence at the configured horizon</h2></div><p>Kaplan–Meier is shown as a net-event
quantity; Aalen–Johansen handles configured competing causes for cumulative incidence.</p></div>
<article class="panel"><div class="endpoint-tabs" id="endpointTabs"></div>
<div class="endpoint-grid"><div class="result"><small>Study population</small><strong id="sPopulation">—</strong>
<div class="band"><i id="populationBand"></i></div></div><div class="result"><small>KM net event probability</small>
<strong id="sKm">—</strong><div class="band"><i id="kmBand"></i></div></div><div class="result">
<small>Aalen–Johansen cumulative incidence</small><strong id="sAj">—</strong>
<div class="band"><i id="ajBand"></i></div></div></div><div class="notice" id="survivalNote"></div></article></section>

<section class="section" id="tactics"><div class="head"><div><span class="kicker">Methods library</span>
<h2>Open each scientific tactic</h2></div><p>Each tactic exposes its question, method, current
synthetic result, interpretation boundary, limitation, and evidence file.</p></div>
<div class="controls"><input class="search" id="search" type="search" placeholder="Search survival, MNAR, seed…"
aria-label="Search scientific tactics"><button class="pill active" data-filter="All">All</button>
<button class="pill" data-filter="Design">Design</button><button class="pill" data-filter="Longitudinal">
Longitudinal</button><button class="pill" data-filter="Uncertainty">Uncertainty</button>
<button class="pill" data-filter="Sensitivity">Sensitivity</button><button class="pill" data-filter="Quality">
Quality</button></div><div class="tactics" id="tacticGrid"></div></section>

<section class="section"><div class="head"><div><span class="kicker">Diagnostics</span>
<h2>Missingness and utility stay disaggregated</h2></div><p>There is no universal realism score and
no assumption that MAR is true merely because a method exists.</p></div><div class="two">
<article class="panel"><h3>Missing-data method performance</h3><div class="scroll">
<table class="metric-table"><thead><tr><th>Mechanism</th><th>Method</th><th>Bias</th><th>RMSE</th>
<th>Coverage</th><th>ESS</th></tr></thead><tbody id="missingBody"></tbody></table></div></article>
<article class="panel"><h3>Synthetic utility dimensions</h3><div class="scroll">
<table class="metric-table"><thead><tr><th>Dimension</th><th>Metric</th><th>Status</th></tr></thead>
<tbody id="utilityBody"></tbody></table></div></article></div></section>

<section class="section"><div class="notice"><strong>Approval boundary.</strong> {disclaimer}.
Event definitions, tie priorities, populations, scenario bundles, and missingness assumptions need
oncology, RWE, and biostatistics review. Real-versus-synthetic, TSTR, nearest-neighbour,
membership-inference, and attribute-inference evaluations remain blocked without governed data and
privacy, security, data-owner, and model-risk approval.</div></section>
<footer><span>Scientific Evidence Lab · aggregate presentation surface</span>
<span>Release {dataset} · source commit {commit}</span></footer>
</main>

<div class="backdrop" id="modal" hidden><section class="modal" role="dialog" aria-modal="true"
aria-labelledby="modalTitle"><div class="modal-head"><div><span class="tag" id="modalCategory"></span>
<h3 id="modalTitle"></h3></div><button class="close" id="close" aria-label="Close method details">×</button>
</div><div class="modal-body"><p id="modalQuestion"></p><div class="modal-result" id="modalResult"></div>
<div class="stats" id="modalStats"></div><div class="explain"><div><h4>How it works</h4>
<p id="modalMethod"></p></div><div><h4>What it means</h4><p id="modalInterpretation"></p></div>
<div><h4>Limitation</h4><p id="modalLimitation"></p></div><div><h4>Evidence boundary</h4>
<p>Synthetic engineering evidence only; no causal, clinical, real-world, or market claim.</p></div></div>
<a class="evidence" id="modalEvidence" href="#">Open aggregate evidence</a></div></section></div>

<script id="scienceData" type="application/json">{payload_json}</script>
<script>
const data=JSON.parse(document.getElementById('scienceData').textContent);
const fmt=new Intl.NumberFormat('en-US');const percent=v=>v===null||v===undefined?'Not evaluable':
(100*v).toFixed(1)+'%';const decimal=(v,d=4)=>v===null||v===undefined?'N/A':Number(v).toFixed(d);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;',
'"':'&quot;',"'":'&#39;'}}[c]));
document.getElementById('analysisCount').textContent=fmt.format(data.analysis_count);
document.getElementById('endpointCount').textContent=fmt.format(data.survival.length);
const seedTotal=Object.values(data.simulation.completed_seeds||{{}}).reduce((a,b)=>a+b,0);
document.getElementById('seedCount').textContent=seedTotal?fmt.format(seedTotal):'Pending';
document.getElementById('blockedCount').textContent=fmt.format(data.utility_dimensions
.filter(x=>x.status==='BLOCKED').length);

const layerConfig={{estimator:{{title:'Estimator uncertainty inside one fixed dataset',
copy:'Wilson and Greenwood quantities describe precision conditional on this generated dataset. They do not include regeneration or changed assumptions.',
head:['Metric','Estimate','Lower','Upper','Label'],rows:()=>data.estimator_metrics.map(x=>
[x.metric_id,percent(x.estimate),percent(x.estimator_confidence_lower),
percent(x.estimator_confidence_upper),x.uncertainty_type])}},regeneration:{{
title:'Variation from regenerating synthetic patients',copy:'The empirical simulation interval describes repeated generated cohorts under unchanged assumptions. Monte Carlo SE describes precision of the simulated mean.',
head:['Scenario','Metric','Mean','Simulation interval','Monte Carlo SE'],rows:()=>
(data.simulation.within_scenario||[]).map(x=>[x.scenario,x.metric_id,percent(x.mean_estimate),
percent(x.simulation_interval_lower)+' – '+percent(x.simulation_interval_upper),
decimal(x.monte_carlo_standard_error)])}},scenario:{{title:'Variation from changed scenario assumptions',
copy:'The low/base/high envelope changes a coherent care-friction bundle. It is not a confidence interval and is not a real-world range.',
head:['Metric','Base mean','Envelope','Uncertainty label'],rows:()=>
(data.simulation.scenario_envelope||[]).map(x=>[x.metric_id,percent(x.base_mean),
percent(x.scenario_envelope_lower)+' – '+percent(x.scenario_envelope_upper),x.uncertainty_type])}}}};
function renderLayer(key){{const x=layerConfig[key];document.getElementById('layerTitle').textContent=x.title;
document.getElementById('layerCopy').textContent=x.copy;document.getElementById('layerHead').innerHTML=
'<tr>'+x.head.map(v=>'<th>'+esc(v)+'</th>').join('')+'</tr>';const rows=x.rows();
document.getElementById('layerBody').innerHTML=rows.length?rows.slice(0,18).map(row=>
'<tr>'+row.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join(''):
'<tr><td colspan="5">Final evidence run pending.</td></tr>';}}
document.querySelectorAll('[data-layer]').forEach(button=>button.addEventListener('click',()=>{{
document.querySelectorAll('[data-layer]').forEach(x=>{{x.classList.toggle('active',x===button);
x.setAttribute('aria-selected',String(x===button));}});
renderLayer(button.dataset.layer);}}));document.querySelectorAll('[data-layer]').forEach(x=>
x.setAttribute('aria-selected',String(x.classList.contains('active'))));renderLayer('estimator');

function renderEndpoint(endpoint){{const x=data.survival.find(v=>v.endpoint===endpoint);
document.querySelectorAll('[data-endpoint]').forEach(b=>b.classList.toggle('active',b.dataset.endpoint===endpoint));
document.getElementById('sPopulation').textContent=fmt.format(x.study_population_n);
document.getElementById('sKm').textContent=percent(x.kaplan_meier_net_event_probability);
document.getElementById('sAj').textContent=percent(x.aalen_johansen_cumulative_incidence);
document.getElementById('populationBand').style.width='100%';
document.getElementById('kmBand').style.width=(100*(x.kaplan_meier_net_event_probability||0))+'%';
document.getElementById('ajBand').style.width=(100*(x.aalen_johansen_cumulative_incidence||0))+'%';
document.getElementById('survivalNote').textContent='Horizon: '+x.horizon_days+' days. Estimator band: '+
percent(x.estimator_band_lower)+'–'+percent(x.estimator_band_upper)+'. Events: '+
fmt.format(x.target_event_count)+', competing events: '+fmt.format(x.competing_event_count)+
', censoring marks: '+fmt.format(x.censoring_mark_count)+'. '+x.limitation;}}
document.getElementById('endpointTabs').innerHTML=data.survival.map((x,i)=>
`<button class="pill ${{i===0?'active':''}}" data-endpoint="${{esc(x.endpoint)}}">${{esc(x.endpoint)}}</button>`).join('');
document.querySelectorAll('[data-endpoint]').forEach(b=>b.addEventListener('click',()=>renderEndpoint(b.dataset.endpoint)));
if(data.survival.length)renderEndpoint(data.survival[0].endpoint);

let filter='All';let lastFocus=null;function renderTactics(){{const term=document.getElementById('search')
.value.trim().toLowerCase();const items=data.tactics.filter(x=>(filter==='All'||x.category===filter)&&
(!term||(x.title+' '+x.question+' '+x.method).toLowerCase().includes(term)));
document.getElementById('tacticGrid').innerHTML=items.map(x=>`<article class="tactic"><span class="tag">
${{esc(x.category)}}</span><h3>${{esc(x.title)}}</h3><p>${{esc(x.question)}}</p><p class="headline">
${{esc(x.result)}}</p><button class="open" data-open="${{esc(x.id)}}">Open method →</button></article>`)
.join('')||'<article class="panel">No method matches the current filter.</article>';
document.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',()=>openModal(b.dataset.open)));}}
document.getElementById('search').addEventListener('input',renderTactics);
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{{
filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>
x.classList.toggle('active',x===button));renderTactics();}}));
function openModal(id){{lastFocus=document.activeElement;const x=data.tactics.find(v=>v.id===id);
document.getElementById('modalCategory').textContent=x.category;document.getElementById('modalTitle')
.textContent=x.title;document.getElementById('modalQuestion').textContent=x.question;
document.getElementById('modalResult').textContent=x.result;document.getElementById('modalMethod')
.textContent=x.method;document.getElementById('modalInterpretation').textContent=x.interpretation;
document.getElementById('modalLimitation').textContent=x.limitation;document.getElementById('modalStats')
.innerHTML=x.stats.map(v=>`<div class="stat"><small>${{esc(v[0])}}</small><strong>${{esc(v[1])}}</strong></div>`)
.join('');document.getElementById('modalEvidence').href=x.evidence;document.getElementById('modal').hidden=false;
document.getElementById('close').focus();}}
function closeModal(){{if(document.getElementById('modal').hidden)return;document.getElementById('modal').hidden=true;
if(lastFocus&&lastFocus.focus)lastFocus.focus();}}document.getElementById('close').addEventListener('click',closeModal);
document.getElementById('modal').addEventListener('click',e=>{{if(e.target.id==='modal')closeModal();}});
document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal();if(e.key==='Tab'&&
!document.getElementById('modal').hidden){{const focusable=[...document.getElementById('modal')
.querySelectorAll('button,a[href]')];const first=focusable[0],last=focusable[focusable.length-1];
if(e.shiftKey&&document.activeElement===first){{e.preventDefault();last.focus();}}
else if(!e.shiftKey&&document.activeElement===last){{e.preventDefault();first.focus();}}}}}});renderTactics();

document.getElementById('missingBody').innerHTML=data.missingness.map(x=>`<tr><td>${{esc(x.mechanism)}}</td>
<td>${{esc(x.method)}}</td><td>${{decimal(x.bias)}}</td><td>${{decimal(x.rmse)}}</td>
<td>${{percent(x.interval_coverage)}}</td><td>${{decimal(x.mean_effective_sample_size,1)}}</td></tr>`).join('');
document.getElementById('utilityBody').innerHTML=data.utility_dimensions.map(x=>`<tr><td>
${{esc(x.dimension.replaceAll('_',' '))}}</td><td>${{esc(x.metric.replaceAll('_',' '))}}</td>
<td><span class="status ${{esc(x.status)}}">${{esc(x.status)}}</span></td></tr>`).join('');
</script>
</body>
</html>"""
    output = root / "scientific_story.html"
    output.write_text(document, encoding="utf-8")
    return output
