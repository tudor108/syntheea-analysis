"""Configurable, non-clinical parameters for cohort and gap analysis."""

from __future__ import annotations

import os

COHORT_INITIATION_WINDOWS = (30, 60, 90)
COHORT_PRIMARY_WINDOW_DAYS = 90
COHORT_BASELINE_DAYS = 0
COHORT_SMALL_CELL_THRESHOLD = int(os.environ.get("COHORT_SMALL_CELL_THRESHOLD", "30"))
COHORT_PATHWAYS = (
    "mhspc_mcspc",
    "nmcrpc",
    "mcrpc",
    "active_surveillance",
)

if COHORT_SMALL_CELL_THRESHOLD < 1:
    raise ValueError("COHORT_SMALL_CELL_THRESHOLD must be a positive integer")
