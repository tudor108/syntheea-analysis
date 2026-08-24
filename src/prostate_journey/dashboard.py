"""Dependency-light cohort dashboard rendered as a self-contained HTML file."""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from . import DISCLAIMER

PALETTE = ["#3b82f6", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"]


def _fmt(value: int | float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def _bar_chart(title: str, labels: list[str], values: list[float], percent: bool = False) -> str:
    """Build an accessible inline SVG horizontal bar chart."""
    width, row_height, left, right = 820, 38, 190, 90
    maximum = max(values or [1]) or 1
    height = 56 + row_height * len(labels)
    parts = [f'<div class="chart"><h3>{html.escape(title)}</h3><svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">']
    for index, (label, value) in enumerate(zip(labels, values)):
        y = 34 + index * row_height
        bar_width = max(2, (width - left - right) * float(value) / maximum)
        display = f"{value:.1f}%" if percent else _fmt(value)
        color = PALETTE[index % len(PALETTE)]
        parts.append(f'<text x="0" y="{y + 15}" class="axis-label">{html.escape(str(label))}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="22" rx="8" fill="{color}"/>')
        parts.append(f'<text x="{left + bar_width + 8:.1f}" y="{y + 16}" class="value-label">{display}</text>')
    return "".join(parts) + "</svg></div>"


def _counts(journey: pd.DataFrame, column: str) -> tuple[list[str], list[float]]:
    values = journey[column].fillna("not_initiated").value_counts().head(8)
    return [str(index).replace("_", " ") for index in values.index], values.astype(float).tolist()


def _cards(journey: pd.DataFrame) -> str:
    values = [
        ("Total cohort", len(journey), "patients"),
        ("mHSPC", int(journey.mhspc_flag.sum()), "synthetic"),
        ("Eligible ARPI", int(journey.eligible_for_arpi.sum()), "demo rule"),
        ("Initiated ≤90d", int(journey.initiated_within_90d.sum()), "patients"),
        ("Treatment gap", int(journey.eligible_not_initiated_90d.sum()), "eligible not started"),
        ("Persistent 12m", int(journey.persistent_12m.sum()), "patients"),
    ]
    return "".join(f'<div class="card"><div class="card-label">{html.escape(label)}</div><div class="card-value">{_fmt(value)}</div><div class="card-note">{html.escape(note)}</div></div>' for label, value, note in values)


def _segment_table(journey: pd.DataFrame) -> str:
    frame = journey.copy()
    frame["age_group"] = pd.cut(frame.age_at_index, [0, 64, 74, 200], labels=["<65", "65-74", "75+"])
    grouped = frame.groupby(["initial_care_setting", "age_group"], observed=True).agg(
        eligible=("eligible_for_arpi", "sum"), gap=("eligible_not_initiated_90d", "sum")
    ).reset_index()
    eligible = grouped.eligible.mask(grouped.eligible.eq(0)).astype("float64")
    grouped["gap_rate"] = (grouped.gap / eligible * 100).fillna(0.0)
    rows = "".join(f"<tr><td>{html.escape(str(row.initial_care_setting))}</td><td>{row.age_group}</td><td>{int(row.eligible)}</td><td>{int(row.gap)}</td><td>{row.gap_rate:.1f}%</td></tr>" for row in grouped.sort_values("gap_rate", ascending=False).head(12).itertuples())
    return f'<div class="table-wrap"><h3>Largest treatment gaps by segment</h3><table><thead><tr><th>Care setting</th><th>Age group</th><th>Eligible</th><th>Gap</th><th>Gap rate</th></tr></thead><tbody>{rows}</tbody></table></div>'


def write_dashboard(journey: pd.DataFrame, report_dir: str | Path) -> Path:
    """Write a self-contained HTML cohort dashboard."""
    root = Path(report_dir); root.mkdir(parents=True, exist_ok=True)
    setting = journey.groupby("initial_care_setting", dropna=False).agg(
        eligible=("eligible_for_arpi", "sum"), initiated=("initiated_within_90d", "sum"), gap=("eligible_not_initiated_90d", "sum")
    ).reset_index()
    setting["gap_rate"] = setting.gap / setting.eligible.replace(0, pd.NA) * 100
    charts = [
        _bar_chart("Cohort funnel", ["mHSPC", "eligible", "initiated ≤90d", "persistent 12m"], [journey.mhspc_flag.sum(), journey.eligible_for_arpi.sum(), journey.initiated_within_90d.sum(), journey.persistent_12m.sum()]),
        _bar_chart("Prostate stage", *_counts(journey, "prostate_stage")),
        _bar_chart("Eligible patients by care setting", setting.initial_care_setting.astype(str).tolist(), setting.eligible.astype(float).tolist()),
        _bar_chart("Treatment gap rate by care setting", setting.initial_care_setting.astype(str).tolist(), setting.gap_rate.fillna(0).tolist(), True),
        _bar_chart("Persistence landmarks", ["3 months", "6 months", "12 months"], [journey.persistent_3m.sum(), journey.persistent_6m.sum(), journey.persistent_12m.sum()]),
        _bar_chart("Final outcomes", *_counts(journey, "final_outcome_status")),
        _bar_chart("Initial treatment", *_counts(journey, "initial_treatment")),
        _segment_table(journey),
    ]
    generated = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Prostate Journey Cohort Dashboard</title><style>
    :root {{--ink:#172033;--muted:#667085;--bg:#f4f7fb;--panel:#fff;--line:#e5eaf2;}} *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,Segoe UI,Arial,sans-serif}} .page{{max-width:1440px;margin:auto;padding:34px}} header{{background:linear-gradient(120deg,#13294b,#1d4e89);color:white;border-radius:22px;padding:34px 38px;box-shadow:0 16px 45px #12213b26}} h1{{margin:0 0 8px;font-size:32px}} header p{{margin:7px 0;color:#dbeafe;max-width:950px}} .notice{{margin-top:18px;padding:11px 14px;border-radius:10px;background:#fef3c7;color:#713f12;font-weight:700;font-size:13px}} .cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin:22px 0}} .card,.chart,.table-wrap{{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:0 7px 22px #2538580b}} .card{{padding:18px}} .card-label{{color:var(--muted);font-size:13px;font-weight:600}} .card-value{{font-size:29px;font-weight:800;margin-top:10px}} .card-note{{color:var(--muted);font-size:12px;margin-top:5px}} .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}} .chart,.table-wrap{{padding:22px;overflow:hidden}} h3{{margin:0 0 14px;font-size:18px}} svg{{width:100%;height:auto;display:block}} .axis-label{{fill:#475467;font-size:14px}} .value-label{{fill:#172033;font-size:14px;font-weight:700}} table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:11px 9px;border-bottom:1px solid var(--line);text-align:left}} th{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}} footer{{color:var(--muted);font-size:12px;margin:22px 4px}} @media(max-width:1050px){{.cards{{grid-template-columns:repeat(3,1fr)}}}} @media(max-width:700px){{.page{{padding:16px}}.cards,.grid{{grid-template-columns:1fr}}h1{{font-size:25px}}}}
    </style></head><body><main class="page"><header><h1>Prostate Patient Journey – Cohort Dashboard</h1><p>Groups and treatment-pathway signals generated from the gold patient journey table.</p><p>Generated: {generated} · Scenario: synthetic demo</p><div class="notice">{html.escape(DISCLAIMER)}</div></header><section class="cards">{_cards(journey)}</section><section class="grid">{"".join(charts)}</section><footer>Interpretare: toate valorile sunt sintetice, configurate în YAML și nu reprezintă estimări clinice, comerciale sau population-representative.</footer></main></body></html>'''
    output = root / "cohort_dashboard.html"
    output.write_text(document, encoding="utf-8")
    return output
