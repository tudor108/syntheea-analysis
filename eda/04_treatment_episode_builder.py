"""Build auditable longitudinal treatment episodes from normalized event tables."""

# ruff: noqa: E501

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from config import (
    OUTPUT_DIR,
    ensure_output_directories,
    resolve_analytical_data_dir,
    write_eda_artifact_manifest,
)

DATE_COLUMNS = {
    "treatment_episode": (
        "treatment_start_date",
        "treatment_end_date",
        "discontinuation_date",
        "switch_date",
        "restart_date",
    ),
    "treatment_regimen": ("regimen_start_date", "regimen_end_date"),
    "treatment_regimen_component": ("component_start_date", "component_end_date"),
    "prescription_event": (
        "service_date",
        "nominal_covered_until_date",
        "covered_until_date",
    ),
    "observation": (
        "observation_start_date",
        "observation_end_date",
        "last_observed_date",
        "loss_to_follow_up_date",
        "death_date",
        "censor_date",
    ),
}


def _load(analytical_dir: Path, name: str) -> pd.DataFrame:
    frame = pd.read_parquet(analytical_dir / f"{name}.parquet")
    for column in DATE_COLUMNS.get(name, ()):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _joined_values(values: pd.Series) -> str | Any:
    result = sorted({str(value) for value in values.dropna()})
    return " + ".join(result) if result else pd.NA


def _component_summary(components: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for episode_id, group in components.groupby("treatment_episode_id", sort=False):
        non_oral = group[group.route.isin(["injection", "infusion", "procedure"])]
        rows.append(
            {
                "treatment_episode_id": episode_id,
                "treatment_class": _joined_values(group.drug_class),
                "drug_components": _joined_values(group.drug_name),
                "component_roles": _joined_values(group.component_role),
                "component_count": int(len(group)),
                # This is a dated administration/procedure proxy, not a claim of observed drug administration.
                "administration_date": non_oral.component_start_date.min(),
                "administration_date_basis": (
                    "component_start_date for injection/infusion/procedure"
                    if not non_oral.empty
                    else "NOT_AVAILABLE"
                ),
                "latest_component_start_date": group.component_start_date.max(),
                "latest_component_end_date": group.component_end_date.max(),
                "component_source_ids": "|".join(sorted(group.component_id.astype(str))),
            }
        )
    return pd.DataFrame(rows)


def _prescription_summary(episodes: pd.DataFrame, prescriptions: pd.DataFrame) -> pd.DataFrame:
    tracking = episodes[["treatment_episode_id", "tracking_component_id"]].merge(
        prescriptions.drop(columns=["treatment_episode_id"]),
        left_on="tracking_component_id",
        right_on="component_id",
        how="left",
    )
    rows: list[dict[str, Any]] = []
    for episode_id, group in tracking.groupby("treatment_episode_id", sort=False):
        observed = group[group.prescription_event_id.notna()].sort_values(
            ["service_date", "prescription_event_id"]
        )
        supply = pd.to_numeric(observed.days_supply, errors="coerce").dropna()
        gaps = pd.to_numeric(observed.refill_gap_days, errors="coerce").dropna()
        rows.append(
            {
                "treatment_episode_id": episode_id,
                "days_supply": float(supply.median()) if not supply.empty else np.nan,
                "days_supply_min": float(supply.min()) if not supply.empty else np.nan,
                "days_supply_max": float(supply.max()) if not supply.empty else np.nan,
                "days_supply_values": (
                    "|".join(str(int(value)) for value in sorted(supply.unique()))
                    if not supply.empty
                    else pd.NA
                ),
                "days_supply_basis": (
                    "observed tracking-component prescription events; median reported"
                    if not supply.empty
                    else "NOT_AVAILABLE; no value fabricated"
                ),
                "scenario_based_days_supply": False,
                "observed_gap_days": float(gaps.max()) if not gaps.empty else np.nan,
                "first_prescription_date": observed.service_date.min(),
                "last_prescription_date": observed.service_date.max(),
                "coverage_end_date": observed.covered_until_date.max(),
                "tracking_prescription_event_count": int(len(observed)),
                "prescription_source_ids": (
                    "|".join(observed.prescription_event_id.astype(str))
                    if not observed.empty
                    else pd.NA
                ),
            }
        )
    return pd.DataFrame(rows)


def _event_classification(row: pd.Series) -> tuple[str, str]:
    if bool(row.switch_out_flag):
        return "SWITCHED", "explicit source switch_date/switch_flag on the outgoing episode"
    if bool(row.restart_out_flag):
        return (
            "TEMPORARY_GAP_RESTARTED",
            "explicit temporary-gap stop followed by an observed restart_date",
        )
    if bool(row.add_on_flag):
        return "ADD_ON", "later component in a regimen explicitly labelled add_on"
    if bool(row.documented_stop_flag):
        return "DISCONTINUED", "explicit discontinuation_flag and discontinuation_date"
    reaches_censor = pd.notna(row.censor_date) and row.treatment_end_date >= row.censor_date
    if reaches_censor and row.censor_reason == "death":
        return "DEATH", "episode observed through the governed death censor date"
    if reaches_censor and row.censor_reason == "loss_to_follow_up":
        return "LOST_TO_FOLLOW_UP", "episode observed through the governed LTFU censor date"
    if reaches_censor and row.censor_reason == "administrative_end":
        return "ADMINISTRATIVE_CENSORING", "episode observed through dataset administrative end"
    if row.treatment_status == "ongoing":
        return "CONTINUED", "source episode remains ongoing before the censor boundary"
    return "UNKNOWN", "no explicit governed terminal event supports another classification"


def build_treatment_episodes(analytical_dir: Path) -> pd.DataFrame:
    """Reconcile episode, regimen, component, refill, provider and censoring evidence."""
    episode = _load(analytical_dir, "treatment_episode")
    regimen = _load(analytical_dir, "treatment_regimen")
    component = _load(analytical_dir, "treatment_regimen_component")
    prescription = _load(analytical_dir, "prescription_event")
    observation = _load(analytical_dir, "observation")
    provider = _load(analytical_dir, "provider")

    duplicate_regimens = regimen.treatment_episode_id.duplicated(keep=False)
    if duplicate_regimens.any():
        raise ValueError("Episode builder requires one normalized regimen per treatment episode")

    result = episode.merge(
        regimen[
            [
                "treatment_episode_id",
                "regimen_id",
                "regimen_name",
                "regimen_type",
                "combination_strategy",
                "regimen_start_date",
                "regimen_end_date",
                "intensification_flag",
            ]
        ],
        on="treatment_episode_id",
        how="left",
        validate="one_to_one",
    )
    result = result.merge(
        _component_summary(component), on="treatment_episode_id", how="left", validate="one_to_one"
    )
    result = result.merge(
        _prescription_summary(episode, prescription),
        on="treatment_episode_id",
        how="left",
        validate="one_to_one",
    )
    result = result.merge(
        observation[
            [
                "patient_id",
                "observation_start_date",
                "last_observed_date",
                "death_date",
                "loss_to_follow_up_date",
                "censor_date",
                "censor_reason",
            ]
        ],
        on="patient_id",
        how="left",
        validate="many_to_one",
    )
    result = result.merge(
        provider[["provider_id", "provider_specialty", "care_setting"]],
        left_on="prescribing_provider_id",
        right_on="provider_id",
        how="left",
        validate="many_to_one",
    )

    result = result.sort_values(
        ["patient_id", "treatment_start_date", "treatment_line", "treatment_episode_id"]
    ).reset_index(drop=True)
    grouped = result.groupby("patient_id", sort=False)
    result["previous_regimen"] = grouped.regimen_name.shift()
    result["next_regimen"] = grouped.regimen_name.shift(-1)
    result["previous_episode_end_date"] = grouped.treatment_end_date.shift()
    result["next_episode_start_date"] = grouped.treatment_start_date.shift(-1)
    result["inter_episode_gap_days"] = (
        result.treatment_start_date - result.previous_episode_end_date
    ).dt.days
    result["episode_overlap_days"] = (
        (-result.inter_episode_gap_days.clip(upper=0)).fillna(0).astype(int)
    )
    result["episode_overlap_flag"] = result.episode_overlap_days.gt(0)
    result["same_day_episode_flag"] = result.inter_episode_gap_days.eq(0)
    result["same_day_ordering_rule"] = (
        "treatment_start_date, treatment_line, treatment_episode_id; no same-day episode ties observed"
    )

    result["switch_out_flag"] = result.switch_flag.fillna(False).astype(bool)
    result["switch_in_flag"] = result.transition_type.eq("switch")
    result["switch_flag"] = result.switch_out_flag | result.switch_in_flag
    result["restart_out_flag"] = result.restart_flag.fillna(False).astype(bool)
    result["restart_in_flag"] = result.transition_type.eq("restart")
    result["restart_flag"] = result.restart_out_flag | result.restart_in_flag
    result["add_on_flag"] = result.combination_strategy.eq("add_on")
    result["add_on_date"] = result.latest_component_start_date.where(result.add_on_flag)
    result["documented_stop_flag"] = (
        result.discontinuation_flag.fillna(False)
        & result.discontinuation_date.notna()
        & ~result.restart_out_flag
    )
    result["documented_temporary_stop_flag"] = (
        result.discontinuation_flag.fillna(False)
        & result.discontinuation_date.notna()
        & result.restart_out_flag
    )
    result["continuation_flag"] = (
        (
            result.coverage_end_date.ge(result.treatment_end_date)
            | result.latest_component_end_date.ge(result.treatment_end_date)
        )
        & ~result.switch_out_flag
        & ~result.documented_stop_flag
        & ~result.documented_temporary_stop_flag
    )
    # Analysis-friendly aliases retain the governed source field names alongside
    # the exact concepts requested by the longitudinal contract.
    result["regimen"] = result.regimen_name
    result["line_of_therapy"] = result.treatment_line
    result["start_date"] = result.treatment_start_date
    result["end_date"] = result.treatment_end_date
    classifications = result.apply(_event_classification, axis=1, result_type="expand")
    result[["event_classification", "event_classification_reason"]] = classifications

    result["censoring_status"] = result.censor_reason.map(
        {
            "death": "DEATH",
            "loss_to_follow_up": "LOST_TO_FOLLOW_UP",
            "administrative_end": "ADMINISTRATIVE_CENSORING",
        }
    ).fillna("UNKNOWN")
    result["source_evidence"] = result.apply(
        lambda row: (
            f"treatment_episode:{row.treatment_episode_id};regimen:{row.regimen_id};"
            f"components:{row.component_count};tracking_rx:{row.tracking_prescription_event_count};"
            f"observation:{row.censor_reason};provider:{row.prescribing_provider_id}"
        ),
        axis=1,
    )
    result["episode_builder_version"] = "LONGITUDINAL-EDA-v1.0"

    required = {
        "patient_id",
        "treatment_class",
        "regimen",
        "line_of_therapy",
        "start_date",
        "end_date",
        "days_supply",
        "administration_date",
        "observed_gap_days",
        "previous_regimen",
        "next_regimen",
        "switch_flag",
        "add_on_flag",
        "restart_flag",
        "continuation_flag",
        "documented_stop_flag",
        "censoring_status",
        "source_evidence",
    }
    missing = required.difference(result.columns)
    if missing:
        raise AssertionError(f"Missing required episode fields: {sorted(missing)}")
    invalid_discontinuation = result.event_classification.eq("DISCONTINUED") & (
        ~result.documented_stop_flag
    )
    if invalid_discontinuation.any():
        raise AssertionError("A non-documented terminal event was classified as discontinuation")
    if len(result) != len(episode) or result.treatment_episode_id.duplicated().any():
        raise AssertionError("Episode grain changed during reconciliation")
    return result


def main() -> int:
    ensure_output_directories()
    analytical_dir, selection = resolve_analytical_data_dir()
    result = build_treatment_episodes(analytical_dir)
    output_path = OUTPUT_DIR / "treatment_episodes.parquet"
    result.to_parquet(output_path, index=False)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "analytical_dataset": str(analytical_dir),
        "selection_method": selection.get("selection_method"),
        "episode_count": int(len(result)),
        "patient_count": int(result.patient_id.nunique()),
        "classification_counts": result.event_classification.value_counts().to_dict(),
        "switch_out_count": int(result.switch_out_flag.sum()),
        "restart_out_count": int(result.restart_out_flag.sum()),
        "add_on_count": int(result.add_on_flag.sum()),
        "documented_stop_count": int(result.documented_stop_flag.sum()),
        "episode_overlap_count": int(result.episode_overlap_flag.sum()),
        "days_supply_missing_episode_count": int(result.days_supply.isna().sum()),
        "source_data_modified": False,
    }
    (OUTPUT_DIR / "treatment_episode_build_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    write_eda_artifact_manifest(analytical_dir, selection)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
