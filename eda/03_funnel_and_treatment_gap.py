"""Aggregate cohort funnels, treatment gaps, sensitivity, ranking and PNG figures."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from cohort_config import (
    COHORT_INITIATION_WINDOWS,
    COHORT_PATHWAYS,
    COHORT_PRIMARY_WINDOW_DAYS,
    COHORT_SMALL_CELL_THRESHOLD,
)
from config import (
    ANALYSIS_DISCLAIMER,
    DEEP_MARKETS,
    FIGURES_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    REQUIRED_MARKETS,
    ensure_output_directories,
    resolve_analytical_data_dir,
)
from png_charts import Canvas, contrasting_text, gap_color

PATHWAY_LABELS = {
    "mhspc_mcspc": "mHSPC/mCSPC",
    "nmcrpc": "nmCRPC",
    "mcrpc": "mCRPC",
    "active_surveillance": "Active surveillance uptake",
}
ALLOWED_CONCLUSION_TYPES = {
    "DESCRIPTIVE",
    "ASSOCIATIONAL",
    "PROXY-BASED",
    "NOT COMPUTABLE",
}
CONFIDENCE_SCORES = {
    "HIGH": 1.0,
    "MEDIUM": 0.7,
    "LOW": 0.35,
    "NOT COMPUTABLE": 0.0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def wilson_interval(
    successes: int, denominator: int, z_score: float = 1.96
) -> tuple[float | None, float | None]:
    """Return the two-sided Wilson score interval for a binomial proportion."""
    if denominator <= 0:
        return None, None
    proportion = successes / denominator
    z_squared = z_score**2
    center = (proportion + z_squared / (2 * denominator)) / (1 + z_squared / denominator)
    margin = (
        z_score
        * math.sqrt(proportion * (1 - proportion) / denominator + z_squared / (4 * denominator**2))
        / (1 + z_squared / denominator)
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _conclusion_type(pathway: str) -> str:
    if pathway == "nmcrpc":
        return "NOT COMPUTABLE"
    if pathway in {"mcrpc", "active_surveillance"}:
        return "PROXY-BASED"
    return "DESCRIPTIVE"


def _data_confidence(
    pathway: str,
    eligible_n: int,
    evaluable_n: int,
    followup_adequacy: float | None,
    missingness_rate: float | None,
    market_depth: str | None = None,
) -> str:
    if pathway == "nmcrpc" or eligible_n == 0:
        return "NOT COMPUTABLE"
    if pathway == "mcrpc":
        return "LOW"
    followup = followup_adequacy or 0.0
    missingness = missingness_rate if missingness_rate is not None else 1.0
    if eligible_n >= 100 and evaluable_n >= 100 and followup >= 0.90 and missingness <= 0.10:
        confidence = "HIGH"
    elif eligible_n >= COHORT_SMALL_CELL_THRESHOLD and followup >= 0.80 and missingness <= 0.20:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    if pathway == "active_surveillance" and confidence == "HIGH":
        confidence = "MEDIUM"
    if market_depth == "scan" and confidence == "HIGH":
        confidence = "MEDIUM"
    return confidence


def _actionability(
    pathway: str,
    eligible_n: int,
    evaluable_n: int,
    confidence: str,
    market_depth: str | None,
) -> str:
    if pathway == "nmcrpc" or eligible_n == 0:
        return "NOT_COMPUTABLE"
    if eligible_n < COHORT_SMALL_CELL_THRESHOLD or evaluable_n < COHORT_SMALL_CELL_THRESHOLD:
        return "TOO_SMALL"
    if pathway != "mhspc_mcspc" or market_depth == "scan" or confidence == "LOW":
        return "DIRECTIONAL_ONLY"
    return "ACTIONABLE_DESCRIPTIVE"


def aggregate_metrics(
    frame: pd.DataFrame,
    pathway: str,
    window_days: int,
    market_depth: str | None = None,
) -> dict[str, Any]:
    """Calculate censor-aware gap metrics from pathway-member rows."""
    members = frame[frame.pathway_membership].copy()
    eligible = members.eligible_candidate.fillna(False)
    observable = members[f"observable_for_{window_days}d"].fillna(False)
    evaluable = eligible & observable
    initiated = evaluable & members[f"initiated_within_{window_days}d"].eq(True).fillna(False)
    member_n = len(members)
    eligible_n = int(eligible.sum())
    evaluable_n = int(evaluable.sum())
    initiated_n = int(initiated.sum())
    initiation_rate = initiated_n / evaluable_n if evaluable_n else None
    treatment_gap = 1 - initiation_rate if initiation_rate is not None else None
    gap_n = evaluable_n - initiated_n
    lower, upper = wilson_interval(initiated_n, evaluable_n)
    followup_adequacy = evaluable_n / eligible_n if eligible_n else None
    missingness_rate = (
        float(members.loc[eligible, "row_missingness_rate"].mean()) if eligible_n else None
    )
    non_intensified_n = (
        int((initiated & members.non_intensified_regimen.eq(True).fillna(False)).sum())
        if pathway == "mhspc_mcspc"
        else None
    )
    non_intensified_rate = (
        non_intensified_n / initiated_n
        if pathway == "mhspc_mcspc" and initiated_n
        else None
    )
    confidence = _data_confidence(
        pathway,
        eligible_n,
        evaluable_n,
        followup_adequacy,
        missingness_rate,
        market_depth,
    )
    return {
        "n": member_n,
        "eligible_n": eligible_n,
        "eligible_observed_n": int(members.eligible_observed.fillna(False).sum()),
        "eligible_proxy_n": int(members.eligible_proxy.fillna(False).sum()),
        "eligibility_uncertain_n": int(members.eligibility_uncertain.fillna(False).sum()),
        "evaluable_eligible_n": evaluable_n,
        "censored_before_window_n": eligible_n - evaluable_n,
        "initiated_n": initiated_n,
        "eligible_but_not_initiated_n": gap_n,
        "initiation_rate": initiation_rate,
        "treatment_gap": treatment_gap,
        "wilson_95_lower": lower,
        "wilson_95_upper": upper,
        "non_intensified_n": non_intensified_n,
        "non_intensified_rate": non_intensified_rate,
        "follow_up_adequacy": followup_adequacy,
        "missingness_rate": missingness_rate,
        "confidence_category": confidence,
        "actionability": _actionability(pathway, eligible_n, evaluable_n, confidence, market_depth),
        "conclusion_type": _conclusion_type(pathway),
        "initiation_event_type": (
            "active_surveillance_uptake"
            if pathway == "active_surveillance"
            else "not_computable"
            if pathway == "nmcrpc"
            else "treatment_initiation"
        ),
    }


def build_market_summary(flags: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pathway in COHORT_PATHWAYS:
        path_rows = flags[flags.pathway.eq(pathway)]
        for market in ("ALL", *REQUIRED_MARKETS):
            group = path_rows if market == "ALL" else path_rows[path_rows.market_code.eq(market)]
            depths = group.market_depth.dropna().unique()
            depth = str(depths[0]) if len(depths) == 1 else "all"
            row: dict[str, Any] = {
                "pathway": pathway,
                "pathway_label": PATHWAY_LABELS[pathway],
                "market_code": market,
                "market_group": "ALL"
                if market == "ALL"
                else ("Deep" if market in DEEP_MARKETS else "Scan"),
                "market_depth": depth,
            }
            for window in COHORT_INITIATION_WINDOWS:
                metrics = aggregate_metrics(group, pathway, window, depth)
                for key, value in metrics.items():
                    row[f"{key}_{window}d"] = value
            rows.append(row)
    return pd.DataFrame(rows)


def build_segment_metrics(flags: pd.DataFrame) -> pd.DataFrame:
    dimensions = {
        "overall": None,
        "market": "market_code",
        "market_group": "market_group",
        "disease_state": "disease_state",
        "active_surveillance_status": "active_surveillance_status",
        "care_setting": "initial_care_setting",
        "provider_specialty": "initial_provider_specialty",
        "academic_vs_community": "academic_vs_community",
        "age_band": "age_band",
        "comorbidity_band": "comorbidity_band",
        "metastatic_site": "metastatic_site",
        "calendar_period": "calendar_period",
        "prior_treatment_status": "prior_treatment_status",
    }
    rows: list[dict[str, Any]] = []
    for pathway in COHORT_PATHWAYS:
        path_rows = flags[flags.pathway.eq(pathway)]
        members = path_rows[path_rows.pathway_membership]
        for dimension, column in dimensions.items():
            if column is None:
                groups = [("ALL", members)]
            elif members.empty:
                groups = [("NOT_AVAILABLE", members)]
            else:
                grouping = members[column].astype("string").fillna("<missing>")
                groups = [
                    (str(value), members.loc[index])
                    for value, index in grouping.groupby(grouping).groups.items()
                ]
            for value, group in groups:
                depth_values = group.market_depth.dropna().unique()
                depth = str(depth_values[0]) if len(depth_values) == 1 else "mixed"
                for window in COHORT_INITIATION_WINDOWS:
                    rows.append(
                        {
                            "pathway": pathway,
                            "pathway_label": PATHWAY_LABELS[pathway],
                            "segment_dimension": dimension,
                            "segment_value": value,
                            "window_days": window,
                            "market_depth_context": depth,
                            **aggregate_metrics(group, pathway, window, depth),
                        }
                    )
    return pd.DataFrame(rows)


def build_sensitivity(segment_metrics: pd.DataFrame) -> pd.DataFrame:
    return (
        segment_metrics[
            segment_metrics.segment_dimension.eq("overall")
            & segment_metrics.segment_value.eq("ALL")
        ]
        .sort_values(["pathway", "window_days"])
        .reset_index(drop=True)
    )


def build_heatmap_table(flags: pd.DataFrame) -> pd.DataFrame:
    """Build Deep-market detail rows and directional Scan-market aggregate rows."""
    care_settings = sorted(
        flags.loc[flags.pathway_membership, "initial_care_setting"].dropna().unique()
    )
    display_rows: list[tuple[str, str, str, str]] = []
    for market in REQUIRED_MARKETS:
        if market in DEEP_MARKETS:
            for setting in care_settings:
                display_rows.append((f"{market} | {setting}", market, "Deep", str(setting)))
        else:
            display_rows.append(
                (f"{market} | ALL (directional)", market, "Scan", "ALL_DIRECTIONAL")
            )

    rows: list[dict[str, Any]] = []
    for label, market, market_group, care_setting in display_rows:
        row: dict[str, Any] = {
            "heatmap_row": label,
            "market_code": market,
            "market_group": market_group,
            "care_setting": care_setting,
            "display_scope": "DEEP_DETAIL" if market_group == "Deep" else "SCAN_DIRECTIONAL",
        }
        for pathway in COHORT_PATHWAYS:
            subset = flags[flags.pathway.eq(pathway) & flags.market_code.eq(market)]
            if care_setting != "ALL_DIRECTIONAL":
                subset = subset[subset.initial_care_setting.eq(care_setting)]
            metrics = aggregate_metrics(
                subset,
                pathway,
                COHORT_PRIMARY_WINDOW_DAYS,
                "deep" if market_group == "Deep" else "scan",
            )
            for key in (
                "n",
                "eligible_n",
                "evaluable_eligible_n",
                "initiated_n",
                "eligible_but_not_initiated_n",
                "initiation_rate",
                "treatment_gap",
                "wilson_95_lower",
                "wilson_95_upper",
                "follow_up_adequacy",
                "missingness_rate",
                "confidence_category",
                "actionability",
                "conclusion_type",
                "initiation_event_type",
            ):
                row[f"{pathway}_{key}"] = metrics[key]
        rows.append(row)
    return pd.DataFrame(rows)


def build_value_pool_candidates(flags: pd.DataFrame) -> pd.DataFrame:
    """Rank analytical candidates by gap volume, completeness and confidence, never finance."""
    member_rows = flags[flags.pathway_membership & ~flags.pathway.eq("nmcrpc")].copy()
    group_columns = [
        "pathway",
        "market_code",
        "market_group",
        "market_depth",
        "initial_care_setting",
        "initial_provider_specialty",
        "academic_vs_community",
    ]
    rows: list[dict[str, Any]] = []
    for keys, group in member_rows.groupby(group_columns, dropna=False):
        (
            pathway,
            market,
            market_group,
            depth,
            setting,
            specialty,
            academic,
        ) = keys
        metrics = aggregate_metrics(
            group,
            str(pathway),
            COHORT_PRIMARY_WINDOW_DAYS,
            str(depth),
        )
        feasibility = (metrics["follow_up_adequacy"] or 0.0) * (
            1 - (metrics["missingness_rate"] if metrics["missingness_rate"] is not None else 1.0)
        )
        confidence_score = CONFIDENCE_SCORES[metrics["confidence_category"]]
        analytical_priority_score = (
            metrics["eligible_but_not_initiated_n"] * feasibility * confidence_score
        )
        rows.append(
            {
                "pathway": pathway,
                "pathway_label": PATHWAY_LABELS[str(pathway)],
                "market_code": market,
                "market_group": market_group,
                "market_depth": depth,
                "care_setting": setting,
                "provider_specialty": specialty,
                "academic_vs_community": academic,
                **metrics,
                "feasibility_proxy": feasibility,
                "feasibility_proxy_definition": "follow_up_adequacy * (1 - missingness_rate); analytical feasibility only",
                "data_confidence_score": confidence_score,
                "analytical_priority_score": analytical_priority_score,
                "ranking_basis": "eligible-but-not-initiated volume, gap, follow-up/completeness feasibility and data confidence",
                "business_value_input": None,
                "business_value_status": "NOT COMPUTABLE: no explicit business-value input exists",
            }
        )
    result = pd.DataFrame(rows)
    result["pathway_rank"] = (
        result.groupby("pathway")["analytical_priority_score"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    return result.sort_values(
        ["pathway", "pathway_rank", "eligible_but_not_initiated_n"],
        ascending=[True, True, False],
        ignore_index=True,
    )


def write_interpretation(
    sensitivity: pd.DataFrame, candidates: pd.DataFrame, flags: pd.DataFrame
) -> None:
    mhspc = sensitivity[sensitivity.pathway.eq("mhspc_mcspc")].set_index("window_days")
    mcrpc = sensitivity[sensitivity.pathway.eq("mcrpc") & sensitivity.window_days.eq(90)].iloc[0]
    active_surveillance = sensitivity[
        sensitivity.pathway.eq("active_surveillance") & sensitivity.window_days.eq(90)
    ].iloc[0]
    top = (
        candidates[
            candidates.pathway.eq("mhspc_mcspc")
            & candidates.actionability.isin(["ACTIONABLE_DESCRIPTIVE", "DIRECTIONAL_ONLY"])
            & candidates.eligible_n.ge(COHORT_SMALL_CELL_THRESHOLD)
        ]
        .sort_values(
            ["eligible_but_not_initiated_n", "analytical_priority_score", "treatment_gap"],
            ascending=False,
        )
        .head(5)
    )
    lines = [
        "# Cohort funnel and treatment-gap interpretation",
        "",
        f"> **{ANALYSIS_DISCLAIMER}**",
        "",
        "## Executive interpretation",
        "",
        f"- **[DESCRIPTIVE]** In the governed synthetic mHSPC denominator, 30/60/90-day initiation is {int(mhspc.loc[30, 'initiated_n']):,}/{int(mhspc.loc[60, 'initiated_n']):,}/{int(mhspc.loc[90, 'initiated_n']):,} among {int(mhspc.loc[90, 'evaluable_eligible_n']):,} 90-day evaluable eligible patients; the 90-day observed gap is {int(mhspc.loc[90, 'eligible_but_not_initiated_n']):,} ({mhspc.loc[90, 'treatment_gap']:.1%}).",
        f"- **[PROXY-BASED]** The exact mCRPC state cohort has {int(mcrpc.eligible_n):,} proxy-eligible and {int(mcrpc.evaluable_eligible_n):,} 90-day evaluable records, with {int(mcrpc.initiated_n):,} new post-state treatment starts. This is not evidence of undertreatment because indication-specific eligibility and appropriateness are absent and prior ongoing treatment is common.",
        f"- **[PROXY-BASED]** Active surveillance has {int(active_surveillance.evaluable_eligible_n):,} evaluable synthetic AS-eligible patients and {int(active_surveillance.initiated_n):,} AS starts within 90 days. This is an uptake metric, not a treatment gap and is not compared directly with metastatic pathways.",
        "- **[NOT COMPUTABLE]** nmCRPC has no explicit state or eligibility definition in the certified release; no patient was inferred into that pathway.",
        "- **[ASSOCIATIONAL]** No causal or adjusted association is estimated here. Market, setting and specialty differences are descriptive segment signals only and do not show that a provider or market caused non-initiation.",
        "",
        "## Top five mHSPC gap-volume candidates",
        "",
    ]
    if top.empty:
        lines.append(
            "- **[NOT COMPUTABLE]** No segment met the configured analytical cell threshold."
        )
    else:
        for rank, row in enumerate(top.itertuples(index=False), start=1):
            lines.append(
                f"{rank}. **[DESCRIPTIVE]** {row.market_code} | {row.care_setting} | "
                f"{row.provider_specialty}: eligible={row.eligible_n:,}, evaluable={row.evaluable_eligible_n:,}, "
                f"initiated={row.initiated_n:,}, gap volume={row.eligible_but_not_initiated_n:,}, "
                f"gap={row.treatment_gap:.1%}, confidence={row.confidence_category}, "
                f"handling={row.actionability}. This is a prioritization candidate for further review, not a causal claim."
            )
    mcrpc_members = flags[flags.pathway.eq("mcrpc") & flags.pathway_membership]
    prior_mcrpc = int(mcrpc_members.prior_treatment_status.eq("prior_treatment_observed").sum())
    lines.extend(
        [
            "",
            "## Limitations and unresolved definitions",
            "",
            "- **[NOT COMPUTABLE]** Pre-index clinical baseline history is unavailable; the configured baseline is zero days and only validates observable origin at/before index.",
            "- **[NOT COMPUTABLE]** mCSPC is not a recorded value and is not silently mapped to mHSPC; nmCRPC is absent.",
            f"- **[PROXY-BASED]** {prior_mcrpc:,} mCRPC members already had prior treatment; a low post-state initiation rate cannot establish a treatment gap without regimen appropriateness and line-specific clinical rules.",
            "- **[PROXY-BASED]** mCRPC contraindication/data-sufficiency inputs reuse available synthetic proxies that were not designed as an indication-specific eligibility rule.",
            "- **[PROXY-BASED]** AS eligibility has an explicit synthetic flag, but its index uses diagnosis date because no separate eligibility-assessment date is collected.",
            "- **[DESCRIPTIVE]** Care setting and specialty use the first normalized encounter. For later mCRPC entry this may not represent the provider at the state transition.",
            "- **[NOT COMPUTABLE]** No financial value, market revenue, intervention success probability or real-world treatment-effect input exists; analytical priority scores are not business value.",
            "- **[ASSOCIATIONAL]** Unadjusted segmented rates may reflect scenario construction, case mix, missingness and follow-up. They are not evidence of causal undertreatment.",
        ]
    )
    (OUTPUT_DIR / "cohort_interpretation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def draw_funnel(attrition: pd.DataFrame) -> None:
    width = 1500
    panel_height = 258
    height = 90 + panel_height * len(COHORT_PATHWAYS)
    canvas = Canvas(width, height)
    canvas.text(28, 20, "COHORT ATTRITION FUNNEL - SYNTHETIC AGGREGATES", scale=3)
    canvas.text(
        28,
        52,
        "STEP 10 IS AN OUTCOME BRANCH REFERENCED TO ELIGIBLE STEP 8",
        color=(90, 90, 90),
        scale=1,
    )
    colors = {
        "mhspc_mcspc": (35, 110, 170),
        "nmcrpc": (155, 160, 170),
        "mcrpc": (130, 75, 155),
        "active_surveillance": (35, 145, 100),
    }
    short_labels = {
        1: "ALL UNIQUE PATIENTS",
        2: "PROSTATE CANCER",
        3: "VALID STATE EVIDENCE",
        4: "RELEVANT PATHWAY",
        5: "VALID INDEX",
        6: "BASELINE OBSERVED",
        7: "OBSERVABLE 90D",
        8: "ELIGIBLE",
        9: "INITIATED 90D",
        10: "GAP OR NON-INTENSIFIED",
    }
    for panel, pathway in enumerate(COHORT_PATHWAYS):
        group = attrition[attrition.pathway.eq(pathway)].sort_values("step_number")
        y0 = 78 + panel * panel_height
        conclusion = group.iloc[-1].conclusion_type
        canvas.text(
            28, y0, f"{PATHWAY_LABELS[pathway]} | {conclusion}", color=colors[pathway], scale=2
        )
        maximum = max(1, int(group.patient_count.max()))
        for row_number, row in enumerate(group.itertuples(index=False)):
            y = y0 + 27 + row_number * 21
            canvas.text(
                28, y + 4, f"{row.step_number:02d} {short_labels[row.step_number]}", scale=1
            )
            bar_x = 250
            bar_width = round(1020 * row.patient_count / maximum)
            color = (225, 132, 55) if row.step_number == 10 else colors[pathway]
            canvas.rectangle(bar_x, y, max(1, bar_width), 15, color)
            canvas.text(bar_x + max(6, bar_width + 7), y + 4, f"N={row.patient_count:,}", scale=1)
        canvas.rectangle(24, y0 + panel_height - 11, width - 48, 1, (225, 225, 225))
    canvas.save(FIGURES_DIR / "cohort_funnel.png")


def draw_heatmap(heatmap: pd.DataFrame) -> None:
    width = 1580
    row_height = 54
    top = 125
    height = top + row_height * len(heatmap) + 95
    label_width = 330
    cell_width = 300
    canvas = Canvas(width, height)
    canvas.text(24, 18, "90-DAY PATHWAY GAP HEATMAP", scale=3)
    canvas.text(
        24,
        50,
        "FILL=GAP | LEFT MARKER=CONFIDENCE | DEEP DETAIL, SCAN DIRECTIONAL",
        color=(85, 85, 85),
        scale=1,
    )
    canvas.text(24, 70, "AS COLUMN IS UPTAKE GAP, NOT TREATMENT GAP", color=(85, 85, 85), scale=1)
    headers = ["MHSPC/MCSPC", "NMCRPC", "MCRPC PROXY", "AS UPTAKE"]
    for column, header in enumerate(headers):
        canvas.text(label_width + column * cell_width + 18, 99, header, scale=1)
    confidence_colors = {
        "HIGH": (0, 128, 85),
        "MEDIUM": (238, 166, 35),
        "LOW": (190, 35, 45),
        "NOT COMPUTABLE": (125, 130, 140),
    }
    for row_number, row in enumerate(heatmap.itertuples(index=False)):
        y = top + row_number * row_height
        canvas.text(18, y + 18, row.heatmap_row[:48], scale=1)
        for column, pathway in enumerate(COHORT_PATHWAYS):
            gap = getattr(row, f"{pathway}_treatment_gap")
            gap_value = None if pd.isna(gap) else float(gap)
            confidence = str(getattr(row, f"{pathway}_confidence_category"))
            actionability = str(getattr(row, f"{pathway}_actionability"))
            eligible = int(getattr(row, f"{pathway}_eligible_n"))
            initiated = int(getattr(row, f"{pathway}_initiated_n"))
            x = label_width + column * cell_width
            fill = gap_color(gap_value)
            canvas.rectangle(x, y, cell_width - 6, row_height - 5, fill)
            canvas.rectangle(
                x, y, 10, row_height - 5, confidence_colors.get(confidence, (125, 130, 140))
            )
            canvas.outline(x, y, cell_width - 6, row_height - 5, (255, 255, 255), thickness=1)
            text_color = contrasting_text(fill)
            gap_text = "GAP N/C" if gap_value is None else f"GAP {gap_value:.1%}"
            canvas.text(x + 18, y + 8, gap_text, color=text_color, scale=1)
            canvas.text(
                x + 18,
                y + 25,
                f"E={eligible:,} I={initiated:,} | {confidence}"
                + (" | SMALL N" if actionability == "TOO_SMALL" else ""),
                color=text_color,
                scale=1,
            )
    legend_y = height - 65
    canvas.text(24, legend_y, f"SMALL-CELL THRESHOLD: N={COHORT_SMALL_CELL_THRESHOLD}", scale=1)
    canvas.text(450, legend_y, "GREEN=HIGH  AMBER=MEDIUM  RED=LOW  GREY=NOT COMPUTABLE", scale=1)
    canvas.save(FIGURES_DIR / "treatment_gap_heatmap.png")


def _git_value(arguments: list[str]) -> str | None:
    result = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _package_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_manifest(
    started_at: datetime,
    analytical_dir: Path,
    selection_metadata: dict[str, object],
    flags: pd.DataFrame,
    summary: pd.DataFrame,
    segment_metrics: pd.DataFrame,
    heatmap: pd.DataFrame,
    candidates: pd.DataFrame,
) -> None:
    manifest_path = OUTPUT_DIR / "cohort_run_manifest.json"
    output_names = (
        "cohort_patient_flags.parquet",
        "cohort_definitions.csv",
        "cohort_definitions.md",
        "cohort_attrition.csv",
        "cohort_summary_by_market.csv",
        "treatment_gap_by_segment.csv",
        "treatment_gap_heatmap.csv",
        "value_pool_candidates.csv",
        "initiation_sensitivity.csv",
        "cohort_interpretation.md",
        "cohort_engine_run_summary.json",
        "figures/cohort_funnel.png",
        "figures/treatment_gap_heatmap.png",
    )
    outputs = [OUTPUT_DIR / name for name in output_names]
    input_names = (
        "patient",
        "diagnosis",
        "disease_state_event",
        "eligibility",
        "observation",
        "encounter",
        "active_surveillance",
        "treatment_episode",
        "treatment_regimen",
        "outcome",
        "patient_journey",
    )
    input_files = [analytical_dir / f"{name}.parquet" for name in input_names]
    prompt1_files = [
        OUTPUT_DIR / "data_inventory.csv",
        OUTPUT_DIR / "data_dictionary.csv",
        OUTPUT_DIR / "data_quality_summary.csv",
        OUTPUT_DIR / "eda_run_manifest.json",
    ]
    scripts = [
        Path(__file__).with_name("config.py"),
        Path(__file__).with_name("cohort_config.py"),
        Path(__file__).with_name("png_charts.py"),
        Path(__file__).with_name("02_cohort_engine.py"),
        Path(__file__),
    ]
    source_selection = {
        key: selection_metadata.get(key)
        for key in (
            "dataset_version",
            "created_at",
            "decision",
            "overall_readiness",
            "selection_method",
        )
    }
    git_status = _git_value(["status", "--porcelain=v1", "--untracked-files=all"]) or ""
    payload = {
        "run_id": f"COHORT-{started_at.strftime('%Y%m%dT%H%M%SZ')}",
        "status": "PASS_WITH_DECLARED_LIMITATIONS",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "analysis_disclaimer": ANALYSIS_DISCLAIMER,
        "analytical_data_dir": str(analytical_dir),
        "dataset_selection": source_selection,
        "configuration": {
            "initiation_windows_days": list(COHORT_INITIATION_WINDOWS),
            "primary_window_days": COHORT_PRIMARY_WINDOW_DAYS,
            "small_cell_threshold": COHORT_SMALL_CELL_THRESHOLD,
            "wilson_z_score": 1.96,
            "pathways": list(COHORT_PATHWAYS),
        },
        "computability": {
            "mhspc_mcspc": "DESCRIPTIVE within governed synthetic proxy",
            "nmcrpc": "NOT COMPUTABLE: explicit state absent",
            "mcrpc": "PROXY-BASED: indication-specific eligibility absent",
            "active_surveillance": "PROXY-BASED: initiation is AS uptake, not treatment",
            "financial_value": "NOT COMPUTABLE: no input",
            "causal_effect": "NOT COMPUTABLE: descriptive design",
        },
        "quality_summary": {
            "patient_pathway_rows": len(flags),
            "unique_patients": int(flags.patient_id.nunique()),
            "market_summary_rows": len(summary),
            "segment_metric_rows": len(segment_metrics),
            "heatmap_rows": len(heatmap),
            "value_pool_rows": len(candidates),
            "nmcrpc_members": int(
                flags.loc[flags.pathway.eq("nmcrpc"), "pathway_membership"].sum()
            ),
            "invalid_conclusion_types": int(
                (~segment_metrics.conclusion_type.isin(ALLOWED_CONCLUSION_TYPES)).sum()
            ),
        },
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
            "dependencies": {
                package: _package_version(package) for package in ("pandas", "pyarrow", "numpy")
            },
            "png_renderer": "dependency-free standard-library RGB/zlib renderer",
        },
        "repository": {
            "git_commit": _git_value(["rev-parse", "HEAD"]),
            "git_branch": _git_value(["branch", "--show-current"]),
            "worktree_clean": not bool(git_status),
            "worktree_change_count": len(git_status.splitlines()),
        },
        "input_file_hashes": {
            path.relative_to(PROJECT_ROOT).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in [*input_files, *prompt1_files]
        },
        "script_hashes": {
            path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path) for path in scripts
        },
        "output_file_hashes": {
            path.relative_to(OUTPUT_DIR).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in outputs
        },
        "privacy": {
            "aggregate_reports_and_figures_only": True,
            "patient_flag_file_contains_synthetic_patient_id": True,
            "patient_flag_file_contains_direct_identifiers": False,
            "small_cells_flagged": True,
            "small_cells_removed_from_source_data": False,
        },
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def validate_outputs(
    flags: pd.DataFrame,
    summary: pd.DataFrame,
    segments: pd.DataFrame,
    heatmap: pd.DataFrame,
    candidates: pd.DataFrame,
) -> None:
    if flags.duplicated(["patient_id", "pathway"]).any():
        raise ValueError("Patient-pathway flags are not unique")
    if set(summary.market_code) != {"ALL", *REQUIRED_MARKETS}:
        raise ValueError("Market summary does not contain ALL plus all seven required markets")
    if (~segments.conclusion_type.isin(ALLOWED_CONCLUSION_TYPES)).any():
        raise ValueError("Segment output contains an invalid conclusion type")
    with_denominator = segments.evaluable_eligible_n.gt(0)
    invalid_rate = with_denominator & ~segments.initiation_rate.between(0, 1)
    if invalid_rate.any():
        raise ValueError("Initiation rate is invalid")
    invalid_wilson = with_denominator & (
        segments.wilson_95_lower.gt(segments.initiation_rate + 1e-12)
        | segments.wilson_95_upper.lt(segments.initiation_rate - 1e-12)
    )
    if invalid_wilson.any():
        raise ValueError("Wilson interval does not contain the observed rate")
    if heatmap.heatmap_row.duplicated().any():
        raise ValueError("Heatmap row labels are not unique")
    if candidates.business_value_input.notna().any():
        raise ValueError("A financial/business value was unexpectedly populated")
    for image_name in ("cohort_funnel.png", "treatment_gap_heatmap.png"):
        payload = (FIGURES_DIR / image_name).read_bytes()
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"{image_name} is not a valid PNG signature")


def main() -> None:
    started_at = datetime.now(UTC)
    ensure_output_directories()
    flags_path = OUTPUT_DIR / "cohort_patient_flags.parquet"
    attrition_path = OUTPUT_DIR / "cohort_attrition.csv"
    if not flags_path.is_file() or not attrition_path.is_file():
        raise FileNotFoundError("Run eda/02_cohort_engine.py before funnel/gap analysis")
    analytical_dir, selection_metadata = resolve_analytical_data_dir()
    flags = pd.read_parquet(flags_path)
    attrition = pd.read_csv(attrition_path)

    market_summary = build_market_summary(flags)
    segment_metrics = build_segment_metrics(flags)
    sensitivity = build_sensitivity(segment_metrics)
    heatmap = build_heatmap_table(flags)
    candidates = build_value_pool_candidates(flags)

    market_summary.to_csv(OUTPUT_DIR / "cohort_summary_by_market.csv", index=False)
    segment_metrics.to_csv(OUTPUT_DIR / "treatment_gap_by_segment.csv", index=False)
    heatmap.to_csv(OUTPUT_DIR / "treatment_gap_heatmap.csv", index=False)
    candidates.to_csv(OUTPUT_DIR / "value_pool_candidates.csv", index=False)
    sensitivity.to_csv(OUTPUT_DIR / "initiation_sensitivity.csv", index=False)
    write_interpretation(sensitivity, candidates, flags)
    draw_funnel(attrition)
    draw_heatmap(heatmap)
    validate_outputs(flags, market_summary, segment_metrics, heatmap, candidates)
    write_manifest(
        started_at,
        analytical_dir,
        selection_metadata,
        flags,
        market_summary,
        segment_metrics,
        heatmap,
        candidates,
    )
    print(
        f"Funnel/gap analysis complete: {len(segment_metrics):,} segment-window rows, "
        f"{len(candidates):,} ranked candidates, figures=2 PNG; "
        "nmCRPC=NOT COMPUTABLE"
    )


if __name__ == "__main__":
    main()
