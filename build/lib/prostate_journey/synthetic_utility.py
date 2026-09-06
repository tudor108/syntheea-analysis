"""Dimension-specific synthetic utility and realism checks without a universal score."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from . import DISCLAIMER
from .data_quality import validate_tables
from .pipeline import TABLES


def _common_metadata(
    *,
    release: str,
    scenario: str,
    seed_summary: str,
) -> dict[str, Any]:
    return {
        "population_definition": "generated records in the selected synthetic analytical dataset",
        "time_zero": "analysis-specific generated index date",
        "horizon_days": "analysis-specific",
        "scenario": scenario,
        "seed_summary": seed_summary,
        "release": release,
        "assumptions": "versioned synthetic generator and analytical contract",
        "limitation": (
            "Internal synthetic engineering diagnostic only; no clinical realism, privacy safety, "
            "real-data fitness, or population fidelity is established."
        ),
        "synthetic_data_only": True,
    }


def _row(
    dimension: str,
    metric: str,
    value: float | int | str,
    status: str,
    numerator: str,
    numerator_count: int | float | None,
    denominator: str,
    denominator_count: int | float | None,
    interpretation: str,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "metric": metric,
        "value": value,
        "status": status,
        "numerator": numerator,
        "numerator_count": numerator_count,
        "denominator": denominator,
        "denominator_count": denominator_count,
        "interpretation": interpretation,
        **common,
    }


def _event_after_censor_count(journey: pd.DataFrame) -> int:
    censor = pd.to_datetime(journey.censor_date, errors="coerce")
    failures = 0
    for column in (
        "treatment_start_date",
        "discontinuation_date",
        "switch_date",
        "progression_date",
        "first_hospitalisation_date",
    ):
        event = pd.to_datetime(journey[column], errors="coerce")
        failures += int((event.notna() & censor.notna() & event.gt(censor)).sum())
    return failures


def _transition_failures(events: pd.DataFrame) -> int:
    failures = 0
    ordered = events.sort_values(["patient_id", "state_date", "disease_state_event_id"])
    for _, group in ordered.groupby("patient_id"):
        previous: str | None = None
        for event in group.itertuples(index=False):
            declared = None if pd.isna(event.previous_state) else str(event.previous_state)
            if previous is None:
                failures += int(declared is not None)
            else:
                failures += int(declared != previous)
            previous = str(event.state)
    return failures


def evaluate_synthetic_utility(
    tables: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
    *,
    release: str,
    scenario: str,
    seed_summary: str,
    real_hook_spec: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Return separate evidence rows for each requested utility/realism dimension."""
    common = _common_metadata(release=release, scenario=scenario, seed_summary=seed_summary)
    rows: list[dict[str, Any]] = []
    missing_tables = sorted(set(TABLES) - tables.keys())
    rows.append(
        _row(
            "schema_and_structural_validity",
            "required_table_presence",
            len(missing_tables),
            "PASS" if not missing_tables else "FAIL",
            "missing required tables",
            len(missing_tables),
            "contracted tables",
            len(TABLES),
            f"Missing tables: {missing_tables}",
            common,
        )
    )

    dq = validate_tables(dict(tables))
    key_rules = [item for item in dq if str(item["rule"]).startswith(("pk_", "fk_"))]
    key_failures = sum(int(item["failure_count"]) for item in key_rules)
    rows.append(
        _row(
            "key_and_referential_integrity",
            "primary_and_foreign_key_failures",
            key_failures,
            "PASS" if key_failures == 0 else "FAIL",
            "failed key references or duplicate/null primary keys",
            key_failures,
            "executed key rules",
            len(key_rules),
            "Every populated key must resolve at its contracted grain.",
            common,
        )
    )

    journey = tables["patient_journey"]
    after_censor = _event_after_censor_count(journey)
    rows.append(
        _row(
            "temporal_validity",
            "events_after_governed_censor",
            after_censor,
            "PASS" if after_censor == 0 else "FAIL",
            "events dated after censor_date",
            after_censor,
            "generated patient journeys",
            len(journey),
            "No analyzed event may occur after the governed observation boundary.",
            common,
        )
    )

    transition_failures = _transition_failures(tables["disease_state_event"])
    rows.append(
        _row(
            "state_transition_validity",
            "previous_state_chain_failures",
            transition_failures,
            "PASS" if transition_failures == 0 else "FAIL",
            "events whose previous_state disagrees with prior chronological state",
            transition_failures,
            "disease-state events",
            len(tables["disease_state_event"]),
            "State lineage is checked mechanically; clinical transition validity still needs "
            "review.",
            common,
        )
    )

    patient = tables["patient"]
    configured_markets = config["market_configuration"]["markets"]
    expected_counts = {
        market: float(profile["full_sample_size"]) for market, profile in configured_markets.items()
    }
    expected_total = sum(expected_counts.values())
    expected_share = {market: count / expected_total for market, count in expected_counts.items()}
    observed_share = patient.market_code.value_counts(normalize=True).to_dict()
    market_max_difference = max(
        abs(float(observed_share.get(market, 0.0)) - expected)
        for market, expected in expected_share.items()
    )
    rows.append(
        _row(
            "marginal_distribution_fidelity",
            "maximum_market_share_absolute_difference",
            market_max_difference,
            "PASS" if market_max_difference <= 0.02 else "WARN",
            "largest absolute observed-minus-configured market share",
            market_max_difference,
            "probability scale",
            1.0,
            "Comparison is against configured assumptions, not a real population.",
            common,
        )
    )

    eligible = journey.loc[journey.eligibility_flag.fillna(False).astype(bool)].copy()
    completed = eligible.referral_completed_flag.fillna(False).astype(bool)
    initiated = eligible.initiated_within_90d.fillna(False).astype(bool)
    completed_rate = float(initiated.loc[completed].mean()) if completed.any() else np.nan
    other_rate = float(initiated.loc[~completed].mean()) if (~completed).any() else np.nan
    association = (
        completed_rate - other_rate if np.isfinite(completed_rate + other_rate) else np.nan
    )
    rows.append(
        _row(
            "conditional_relationship_fidelity",
            "referral_completion_initiation_rate_difference",
            association,
            "PASS" if np.isfinite(association) and association >= 0 else "WARN",
            "difference in descriptive initiation proportions",
            association,
            "completed-referral rate minus other rate",
            1.0,
            "Checks configured direction only; it is confounded and not a causal effect.",
            common,
        )
    )

    treatment = tables["treatment_episode"]
    date_failures = int(
        (
            pd.to_datetime(treatment.treatment_end_date, errors="coerce")
            < pd.to_datetime(treatment.treatment_start_date, errors="coerce")
        ).sum()
    )
    rows.append(
        _row(
            "longitudinal_pattern_fidelity",
            "negative_treatment_episode_durations",
            date_failures,
            "PASS" if date_failures == 0 else "FAIL",
            "episodes ending before they start",
            date_failures,
            "treatment episodes",
            len(treatment),
            "Longitudinal coherence is tested independently of marginal fit.",
            common,
        )
    )

    initiation_status = journey.initiation_90d_status.astype("string")
    initiation_evaluable = initiation_status.isin(
        ["INITIATED_WITHIN_90D", "NOT_INITIATED_WITHIN_90D"]
    )
    outcome_classes = int(initiation_status.loc[initiation_evaluable].nunique())
    rows.append(
        _row(
            "analytical_task_utility",
            "evaluable_initiation_target_classes",
            outcome_classes,
            "PASS" if outcome_classes == 2 else "WARN",
            "distinct evaluable initiation target classes",
            outcome_classes,
            "required binary classes",
            2,
            "Two classes permit a technical prediction task; usefulness or transportability is "
            "not proven.",
            common,
        )
    )

    stage_flags = journey[["metastatic_flag"]].copy()
    stage_flags["localized"] = journey.prostate_stage.eq("localized")
    stage_flags["locally_advanced"] = journey.prostate_stage.eq("locally_advanced")
    stage_conflicts = int(stage_flags.astype(int).sum(axis=1).gt(1).sum())
    biology_conflicts = int(
        (
            journey.hormone_sensitive_flag.fillna(False).astype(bool)
            & journey.castration_resistant_flag.fillna(False).astype(bool)
        ).sum()
    )
    impossible = stage_conflicts + biology_conflicts + after_censor
    rows.append(
        _row(
            "impossible_clinical_journeys",
            "mutually_exclusive_or_post_censor_conflicts",
            impossible,
            "PASS" if impossible == 0 else "FAIL",
            "generated journeys violating explicit engineering impossibility rules",
            impossible,
            "generated patient journeys",
            len(journey),
            "The rule set is incomplete until oncology/RWE specialists approve clinical states.",
            common,
        )
    )

    quasi = patient.assign(age_band=(patient.age_at_index // 5 * 5).astype(int))
    cell_sizes = quasi.groupby(
        ["market_code", "age_band", "race", "insurance_type"], dropna=False
    ).size()
    rare_records = int(cell_sizes.loc[cell_sizes.lt(5)].sum())
    rows.append(
        _row(
            "rare_combination_risk",
            "records_in_quasi_identifier_cells_below_5",
            rare_records / len(patient) if len(patient) else np.nan,
            "WARN" if rare_records else "PASS",
            "records in configured quasi-identifier cells with fewer than five records",
            rare_records,
            "generated patient records",
            len(patient),
            "A synthetic rare-cell diagnostic is not a formal privacy or disclosure-risk "
            "assessment.",
            common,
        )
    )

    archetype_duplicates = int(patient.source_archetype_id.duplicated().sum())
    source_rows = patient.loc[patient.source_record_type.eq("synthea_unique")]
    source_duplicates = int(source_rows.source_patient_id.dropna().duplicated().sum())
    clone_failures = archetype_duplicates + source_duplicates
    rows.append(
        _row(
            "accidental_source_row_cloning",
            "duplicate_archetype_or_source_rows",
            clone_failures,
            "PASS" if clone_failures == 0 else "FAIL",
            "duplicate archetype IDs plus duplicated used source-row IDs",
            clone_failures,
            "generated patient records",
            len(patient),
            "Zero duplication supports the no-cloning engineering contract only.",
            common,
        )
    )

    if real_hook_spec:
        for hook in real_hook_spec.get("hooks", []):
            rows.append(
                _row(
                    "governed_real_data_evaluation",
                    str(hook["hook_id"]),
                    "BLOCKED",
                    "BLOCKED",
                    "completed governed evaluation",
                    0,
                    "required governed evaluation",
                    1,
                    f"{hook['method']} Dependency: {real_hook_spec['blocking_dependency']}",
                    common,
                )
            )
    return pd.DataFrame(rows)


def load_real_data_hook_spec(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "hooks" not in payload:
        raise ValueError("Invalid real-data evaluation hook specification")
    return payload


def write_utility_outputs(
    tables: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
    output_dir: str | Path,
    *,
    release: str,
    scenario: str,
    seed_summary: str,
    real_hook_spec: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence = evaluate_synthetic_utility(
        tables,
        config,
        release=release,
        scenario=scenario,
        seed_summary=seed_summary,
        real_hook_spec=real_hook_spec,
    )
    csv_path = output / "synthetic_utility_dimensions.csv"
    json_path = output / "synthetic_utility_report.json"
    markdown_path = output / "synthetic_utility_report.md"
    evidence.to_csv(csv_path, index=False)
    payload = {
        "synthetic_data_only": True,
        "disclaimer": DISCLAIMER,
        "universal_realism_score_produced": False,
        "dimensions": evidence.to_dict(orient="records"),
        "boundary": (
            "Dimensions are intentionally separate. PASS means agreement with an internal "
            "engineering contract, never clinical realism or privacy certification."
        ),
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Synthetic-data utility and realism evidence",
        "",
        f"> **{DISCLAIMER}**",
        "",
        "No universal realism score is calculated. Each dimension has a separate result and "
        "boundary.",
        "",
        "| Dimension | Metric | Status | Value | Interpretation |",
        "|---|---|---|---:|---|",
    ]
    for row in evidence.itertuples(index=False):
        lines.append(
            f"| {row.dimension} | {row.metric} | {row.status} | {row.value} | "
            f"{row.interpretation} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv": csv_path, "json": json_path, "markdown": markdown_path}
