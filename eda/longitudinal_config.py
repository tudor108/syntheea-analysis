"""Configurable, descriptive assumptions for longitudinal treatment EDA."""

from __future__ import annotations

import os


def _integer_tuple(name: str, default: str) -> tuple[int, ...]:
    values = tuple(int(value.strip()) for value in os.environ.get(name, default).split(","))
    if not values or any(value <= 0 for value in values):
        raise ValueError(f"{name} must contain positive comma-separated integers")
    return tuple(sorted(set(values)))


INITIATION_WINDOWS_DAYS = _integer_tuple("LONGITUDINAL_INITIATION_WINDOWS", "30,60,90")
DISCONTINUATION_GAPS_DAYS = _integer_tuple("LONGITUDINAL_GAP_THRESHOLDS", "30,60,90")
PERSISTENCE_LANDMARKS_DAYS = _integer_tuple("LONGITUDINAL_LANDMARKS", "90,180,365")
BASELINE_REQUIREMENTS_DAYS = _integer_tuple("LONGITUDINAL_BASELINE_WINDOWS", "180,365")
MINIMUM_FOLLOW_UP_DAYS = _integer_tuple("LONGITUDINAL_MIN_FOLLOWUP", "90,180,365")
SMALL_CELL_THRESHOLD = int(os.environ.get("LONGITUDINAL_SMALL_CELL_THRESHOLD", "30"))

# Only used when a selected component genuinely has no observed dispensing/administration
# duration. Results that use these values must retain scenario_based=True.
MISSING_SUPPLY_SCENARIOS_DAYS = _integer_tuple("LONGITUDINAL_MISSING_SUPPLY_SCENARIOS", "30,60,90")

if SMALL_CELL_THRESHOLD < 1:
    raise ValueError("LONGITUDINAL_SMALL_CELL_THRESHOLD must be positive")
