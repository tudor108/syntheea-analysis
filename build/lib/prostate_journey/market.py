"""Configuration helpers for deterministic multi-market generation."""

from __future__ import annotations

from typing import Any


def market_profiles(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the configured seven-market profile mapping."""
    return config["market_configuration"]["markets"]


def scaled_market_counts(config: dict[str, Any]) -> dict[str, int]:
    """Scale explicit profile counts to a CLI cohort override without losing markets."""
    profiles = market_profiles(config)
    profile = config.get("profile", "full")
    key = "quick_sample_size" if profile == "quick" else "full_sample_size"
    configured = {code: int(values[key]) for code, values in profiles.items()}
    target = int(config.get("target_cohort_size", sum(configured.values())))
    configured_total = sum(configured.values())
    if target == configured_total:
        return configured

    exact = {code: target * count / configured_total for code, count in configured.items()}
    counts = {code: max(1, int(value)) for code, value in exact.items()}
    difference = target - sum(counts.values())
    order = sorted(
        profiles,
        key=lambda code: exact[code] - int(exact[code]),
        reverse=difference > 0,
    )
    cursor = 0
    while difference:
        code = order[cursor % len(order)]
        change = 1 if difference > 0 else -1
        if counts[code] + change >= 1:
            counts[code] += change
            difference -= change
        cursor += 1
    return counts


def market_profile(config: dict[str, Any], market_code: str) -> dict[str, Any]:
    """Return one market's explicit assumptions."""
    return market_profiles(config)[market_code]
