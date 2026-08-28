"""Tiny dependency-free SVG chart helpers for aggregate-only EDA figures."""

# ruff: noqa: E501

from __future__ import annotations

import html
from collections.abc import Sequence
from pathlib import Path

COLORS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#17becf", "#8c564b")


def _write(path: Path, body: str, width: int, height: int, title: str, subtitle: str) -> None:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<text x="28" y="30" font-family="Arial" font-size="18" font-weight="700">{html.escape(title)}</text>'
        f'<text x="28" y="50" font-family="Arial" font-size="11" fill="#555">{html.escape(subtitle)}</text>'
        f"{body}</svg>"
    )
    path.write_text(svg, encoding="utf-8")


def bar_chart(
    path: Path,
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str,
    subtitle: str,
    horizontal: bool = False,
    value_format: str = ".1f",
) -> None:
    width = 920
    count = max(1, len(labels))
    height = max(420, 105 + count * 30) if horizontal else 520
    left, right, top, bottom = (210, 35, 75, 55) if horizontal else (65, 25, 75, 125)
    chart_w, chart_h = width - left - right, height - top - bottom
    maximum = max([float(value) for value in values] + [1.0])
    parts = [
        f'<line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#444"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#444"/>',
    ]
    if horizontal:
        slot = chart_h / count
        for index, (label, value) in enumerate(zip(labels, values, strict=True)):
            y = top + index * slot + slot * 0.16
            bar_h = slot * 0.68
            bar_w = chart_w * float(value) / maximum
            parts.extend(
                [
                    f'<text x="{left - 8}" y="{y + bar_h * 0.72:.1f}" text-anchor="end" font-family="Arial" font-size="10">{html.escape(str(label)[:30])}</text>',
                    f'<rect x="{left}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{COLORS[index % len(COLORS)]}"/>',
                    f'<text x="{left + bar_w + 5:.1f}" y="{y + bar_h * 0.72:.1f}" font-family="Arial" font-size="10">{format(float(value), value_format)}</text>',
                ]
            )
    else:
        slot = chart_w / count
        for index, (label, value) in enumerate(zip(labels, values, strict=True)):
            bar_w = slot * 0.68
            bar_h = chart_h * float(value) / maximum
            x = left + index * slot + slot * 0.16
            y = top + chart_h - bar_h
            parts.extend(
                [
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{COLORS[index % len(COLORS)]}"/>',
                    f'<text x="{x + bar_w / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle" font-family="Arial" font-size="10">{format(float(value), value_format)}</text>',
                    f'<text x="{x + bar_w / 2:.1f}" y="{top + chart_h + 15}" transform="rotate(45 {x + bar_w / 2:.1f} {top + chart_h + 15})" font-family="Arial" font-size="9">{html.escape(str(label)[:25])}</text>',
                ]
            )
    _write(path, "".join(parts), width, height, title, subtitle)


def line_chart(
    path: Path,
    x_labels: Sequence[str],
    series: dict[str, Sequence[float]],
    *,
    title: str,
    subtitle: str,
) -> None:
    width, height = 1000, 520
    left, right, top, bottom = 70, 30, 75, 80
    chart_w, chart_h = width - left - right, height - top - bottom
    maximum = max([float(value) for values in series.values() for value in values] + [1.0])
    count = max(2, len(x_labels))
    parts = [
        f'<line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#444"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#444"/>',
    ]
    for index, (name, values) in enumerate(series.items()):
        points = []
        for position, value in enumerate(values):
            x = left + chart_w * position / (count - 1)
            y = top + chart_h * (1 - float(value) / maximum)
            points.append(f"{x:.1f},{y:.1f}")
        color = COLORS[index % len(COLORS)]
        parts.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        parts.append(
            f'<rect x="{left + index * 170}" y="{height - 28}" width="12" height="12" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{left + index * 170 + 18}" y="{height - 17}" font-family="Arial" font-size="10">{html.escape(name)}</text>'
        )
    tick_positions = sorted(
        {0, len(x_labels) // 4, len(x_labels) // 2, 3 * len(x_labels) // 4, len(x_labels) - 1}
    )
    for position in tick_positions:
        x = left + chart_w * position / (count - 1)
        parts.append(
            f'<text x="{x:.1f}" y="{top + chart_h + 18}" text-anchor="middle" font-family="Arial" font-size="9">{html.escape(str(x_labels[position]))}</text>'
        )
    _write(path, "".join(parts), width, height, title, subtitle)


def heatmap(
    path: Path,
    row_labels: Sequence[str],
    column_labels: Sequence[str],
    values: Sequence[Sequence[float]],
    *,
    title: str,
    subtitle: str,
) -> None:
    cell_w, cell_h = 95, 28
    left, top = 210, 105
    width = left + cell_w * len(column_labels) + 30
    height = top + cell_h * len(row_labels) + 50
    maximum = max([float(value) for row in values for value in row] + [1.0])
    parts: list[str] = []
    for col, label in enumerate(column_labels):
        x = left + col * cell_w + cell_w / 2
        parts.append(
            f'<text x="{x:.1f}" y="{top - 8}" text-anchor="end" transform="rotate(45 {x:.1f} {top - 8})" font-family="Arial" font-size="9">{html.escape(str(label))}</text>'
        )
    for row_index, (label, row) in enumerate(zip(row_labels, values, strict=True)):
        y = top + row_index * cell_h
        parts.append(
            f'<text x="{left - 8}" y="{y + 19}" text-anchor="end" font-family="Arial" font-size="9">{html.escape(str(label)[:32])}</text>'
        )
        for col, value in enumerate(row):
            intensity = min(1.0, float(value) / maximum) if maximum else 0.0
            red = int(245 - 110 * intensity)
            green = int(250 - 165 * intensity)
            blue = int(255 - 115 * intensity)
            x = left + col * cell_w
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell_w - 1}" height="{cell_h - 1}" fill="rgb({red},{green},{blue})"/>'
            )
            parts.append(
                f'<text x="{x + cell_w / 2:.1f}" y="{y + 18}" text-anchor="middle" font-family="Arial" font-size="9">{float(value):.1f}</text>'
            )
    _write(path, "".join(parts), width, height, title, subtitle)
