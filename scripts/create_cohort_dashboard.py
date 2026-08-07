"""Create the cohort dashboard using only Python's standard library.

This fallback is useful on machines where the optional analytical environment is
not installed yet. It reads the gold patient_journey.csv and writes a self-contained
HTML file with cards, grouped bars and a treatment-gap segment table.
"""
from __future__ import annotations

import argparse
import csv
import html
from collections import Counter, defaultdict
from pathlib import Path

DISCLAIMER = "SYNTHETIC DEMO DATA – NOT REAL BAYER OR CLINICAL DATA"
COLORS = ["#3b82f6", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"]


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


def chart(title: str, labels: list[str], values: list[float], percent: bool = False) -> str:
    width, row_height, left, right = 820, 38, 190, 90
    maximum = max(values or [1]) or 1
    height = 56 + row_height * len(labels)
    out = [f'<div class="chart"><h3>{html.escape(title)}</h3><svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">']
    for index, (label, value) in enumerate(zip(labels, values)):
        y = 34 + index * row_height
        bar_width = max(2, (width - left - right) * value / maximum)
        text = f"{value:.1f}%" if percent else f"{value:,.0f}"
        color = COLORS[index % len(COLORS)]
        out.append(f'<text x="0" y="{y + 15}" class="axis-label">{html.escape(label)}</text><rect x="{left}" y="{y}" width="{bar_width:.1f}" height="22" rx="8" fill="{color}"/><text x="{left + bar_width + 8:.1f}" y="{y + 16}" class="value-label">{text}</text>')
    return "".join(out) + "</svg></div>"


def top_counts(rows: list[dict[str, str]], column: str) -> tuple[list[str], list[float]]:
    counts = Counter(row.get(column) or "not initiated" for row in rows)
    items = counts.most_common(8)
    return [key.replace("_", " ") for key, _ in items], [float(value) for _, value in items]


def build_dashboard(rows: list[dict[str, str]]) -> str:
    total = len(rows)
    mhspc = sum(as_bool(row["mhspc_flag"]) for row in rows)
    eligible = sum(as_bool(row["eligible_for_arpi"]) for row in rows)
    initiated90 = sum(as_bool(row["initiated_within_90d"]) for row in rows)
    gap = sum(as_bool(row["eligible_not_initiated_90d"]) for row in rows)
    persistent12 = sum(as_bool(row["persistent_12m"]) for row in rows)
    settings: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        settings[row.get("initial_care_setting") or "unknown"].append(row)
    setting_names = list(settings)
    eligible_setting = [sum(as_bool(row["eligible_for_arpi"]) for row in settings[name]) for name in setting_names]
    gap_rates = [100 * sum(as_bool(row["eligible_not_initiated_90d"]) for row in settings[name]) / max(1, eligible_setting[index]) for index, name in enumerate(setting_names)]
    cards = [("Total cohort", total, "patients"), ("mHSPC", mhspc, "synthetic"), ("Eligible ARPI", eligible, "demo rule"), ("Initiated ≤90d", initiated90, "patients"), ("Treatment gap", gap, "eligible not started"), ("Persistent 12m", persistent12, "patients")]
    card_html = "".join(f'<div class="card"><div class="card-label">{label}</div><div class="card-value">{value:,}</div><div class="card-note">{note}</div></div>' for label, value, note in cards)
    stage_labels, stage_values = top_counts(rows, "prostate_stage")
    outcome_labels, outcome_values = top_counts(rows, "final_outcome_status")
    treatment_labels, treatment_values = top_counts(rows, "initial_treatment")
    segments = defaultdict(lambda: [0, 0])
    for row in rows:
        age = int(float(row.get("age_at_index") or 0))
        age_group = "<65" if age < 65 else "65-74" if age < 75 else "75+"
        key = (row.get("initial_care_setting") or "unknown", age_group)
        segments[key][0] += int(as_bool(row["eligible_for_arpi"]))
        segments[key][1] += int(as_bool(row["eligible_not_initiated_90d"]))
    segment_rows = "".join(f"<tr><td>{html.escape(setting)}</td><td>{age}</td><td>{eligible_count:,}</td><td>{gap_count:,}</td><td>{100 * gap_count / max(1, eligible_count):.1f}%</td></tr>" for (setting, age), (eligible_count, gap_count) in sorted(segments.items(), key=lambda item: item[1][1] / max(1, item[1][0]), reverse=True)[:12])
    sections = [chart("Cohort funnel", ["mHSPC", "eligible", "initiated ≤90d", "persistent 12m"], [mhspc, eligible, initiated90, persistent12]), chart("Prostate stage", stage_labels, stage_values), chart("Eligible patients by care setting", setting_names, eligible_setting), chart("Treatment gap rate by care setting", setting_names, gap_rates, True), chart("Persistence landmarks", ["3 months", "6 months", "12 months"], [sum(as_bool(r["persistent_3m"]) for r in rows), sum(as_bool(r["persistent_6m"]) for r in rows), persistent12]), chart("Final outcomes", outcome_labels, outcome_values), chart("Initial treatment", treatment_labels, treatment_values), f'<div class="table-wrap"><h3>Largest treatment gaps by segment</h3><table><thead><tr><th>Care setting</th><th>Age group</th><th>Eligible</th><th>Gap</th><th>Gap rate</th></tr></thead><tbody>{segment_rows}</tbody></table></div>']
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Prostate Journey Cohort Dashboard</title><style>:root{{--ink:#172033;--muted:#667085;--bg:#f4f7fb;--panel:#fff;--line:#e5eaf2}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,Segoe UI,Arial,sans-serif}}.page{{max-width:1440px;margin:auto;padding:34px}}header{{background:linear-gradient(120deg,#13294b,#1d4e89);color:white;border-radius:22px;padding:34px 38px}}h1{{margin:0 0 8px;font-size:32px}}header p{{margin:7px 0;color:#dbeafe}}.notice{{margin-top:18px;padding:11px 14px;border-radius:10px;background:#fef3c7;color:#713f12;font-weight:700;font-size:13px}}.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin:22px 0}}.card,.chart,.table-wrap{{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:0 7px 22px #2538580b}}.card{{padding:18px}}.card-label{{color:var(--muted);font-size:13px;font-weight:600}}.card-value{{font-size:29px;font-weight:800;margin-top:10px}}.card-note{{color:var(--muted);font-size:12px;margin-top:5px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}.chart,.table-wrap{{padding:22px;overflow:hidden}}h3{{margin:0 0 14px;font-size:18px}}svg{{width:100%;height:auto;display:block}}.axis-label{{fill:#475467;font-size:14px}}.value-label{{fill:#172033;font-size:14px;font-weight:700}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:11px 9px;border-bottom:1px solid var(--line);text-align:left}}th{{color:var(--muted);font-size:12px;text-transform:uppercase}}footer{{color:var(--muted);font-size:12px;margin:22px 4px}}@media(max-width:1050px){{.cards{{grid-template-columns:repeat(3,1fr)}}}}@media(max-width:700px){{.page{{padding:16px}}.cards,.grid{{grid-template-columns:1fr}}h1{{font-size:25px}}}}</style></head><body><main class="page"><header><h1>Prostate Patient Journey – Cohort Dashboard</h1><p>Grouped synthetic cohort view from patient_journey.csv</p><p>Generated from {total:,} patients</p><div class="notice">{DISCLAIMER}</div></header><section class="cards">{card_html}</section><section class="grid">{"".join(sections)}</section><footer>All values are synthetic demo assumptions, not clinical or commercial evidence.</footer></main></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="Create cohort dashboard from gold CSV")
    parser.add_argument("--input", default="data/gold/patient_journey.csv")
    parser.add_argument("--output", default="data/reports/cohort_dashboard.html")
    args = parser.parse_args()
    with Path(args.input).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    Path(args.output).write_text(build_dashboard(rows), encoding="utf-8")
    print(f"Dashboard written to {args.output}")


if __name__ == "__main__":
    main()
