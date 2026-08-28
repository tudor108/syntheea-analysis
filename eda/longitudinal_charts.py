"""Small dependency-free line-chart helpers for longitudinal PNG outputs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from png_charts import RGB, Canvas


def line(canvas: Canvas, x1: int, y1: int, x2: int, y2: int, color: RGB, width: int = 2) -> None:
    """Draw a solid line with integer Bresenham coordinates."""
    dx = abs(x2 - x1)
    sx = 1 if x1 < x2 else -1
    dy = -abs(y2 - y1)
    sy = 1 if y1 < y2 else -1
    error = dx + dy
    while True:
        canvas.rectangle(x1 - width // 2, y1 - width // 2, width, width, color)
        if x1 == x2 and y1 == y2:
            break
        twice = 2 * error
        if twice >= dy:
            error += dy
            x1 += sx
        if twice <= dx:
            error += dx
            y1 += sy


def render_line_chart(
    path: Path,
    title: str,
    series: list[tuple[str, list[tuple[float, float]], RGB]],
    *,
    x_label: str,
    y_label: str,
    x_max: float | None = None,
    y_min: float = 0.0,
    y_max: float = 1.0,
) -> None:
    """Render aggregate line series with a compact legend."""
    canvas = Canvas(1500, 980, (250, 252, 255))
    left, top, right, bottom = 150, 125, 1420, 815
    canvas.text(70, 45, title, (24, 52, 91), 3)
    canvas.text(620, 900, x_label, (50, 59, 73), 2)
    canvas.text(20, 450, y_label, (50, 59, 73), 2)
    canvas.rectangle(left, top, right - left, bottom - top, (255, 255, 255))
    canvas.outline(left, top, right - left, bottom - top, (70, 82, 99), 2)

    all_x = [x for _, points, _ in series for x, _ in points]
    maximum_x = x_max if x_max is not None else max(all_x, default=1.0)
    maximum_x = max(float(maximum_x), 1.0)
    span_y = max(y_max - y_min, 1e-12)

    for tick in range(6):
        value_y = y_min + span_y * tick / 5
        py = bottom - round((bottom - top) * tick / 5)
        line(canvas, left, py, right, py, (225, 231, 239), 1)
        canvas.text(72, py - 8, f"{value_y:.1f}", (80, 88, 102), 2)
        value_x = maximum_x * tick / 5
        px = left + round((right - left) * tick / 5)
        line(canvas, px, top, px, bottom, (238, 241, 246), 1)
        canvas.text(px - 18, bottom + 18, f"{value_x:.0f}", (80, 88, 102), 2)

    legend_x = 830
    for index, (label, points, color) in enumerate(series):
        coordinates: list[tuple[int, int]] = []
        ordered = sorted(points)
        visible = [(x, y) for x, y in ordered if 0.0 <= x <= maximum_x]
        if visible and ordered and ordered[-1][0] > maximum_x and visible[-1][0] < maximum_x:
            visible.append((maximum_x, visible[-1][1]))
        for x, y in visible:
            px = left + round((right - left) * x / maximum_x)
            clipped_y = min(max(y, y_min), y_max)
            py = bottom - round((bottom - top) * (clipped_y - y_min) / span_y)
            coordinates.append((px, py))
        for first, second in zip(coordinates, coordinates[1:], strict=False):
            line(canvas, *first, *second, color, 3)
        for px, py in coordinates[:: max(1, len(coordinates) // 80)]:
            canvas.rectangle(px - 2, py - 2, 5, 5, color)
        ly = 66 + index * 28
        line(canvas, legend_x, ly + 7, legend_x + 40, ly + 7, color, 4)
        canvas.text(legend_x + 52, ly, label, (35, 43, 56), 2)

    canvas.text(20, 450, y_label, (50, 59, 73), 2)
    canvas.save(path)


def step_points(frame: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """Turn survival coordinates into horizontal/vertical step coordinates."""
    values = list(frame)
    if not values:
        return []
    output = [values[0]]
    for x, y in values[1:]:
        output.append((x, output[-1][1]))
        output.append((x, y))
    return output
