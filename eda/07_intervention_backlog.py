"""Convert validated exploratory driver signals into a non-clinical validation backlog."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from config import OUTPUT_DIR, PROJECT_ROOT, ensure_output_directories


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _evidence(driver_tree: pd.DataFrame, feature: str, outcome: str | None = None) -> str:
    selected = driver_tree[driver_tree.observed_proxy.eq(feature)]
    if outcome is not None:
        selected = selected[selected.affected_outcome.eq(outcome)]
    if selected.empty:
        return "NOT VERIFIED; no stable driver-tree row"
    row = selected.iloc[0]
    return f"{row.evidence_type}: {row.magnitude}; {row.limitation}"


def build_backlog(driver_tree: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    fitted = metrics[metrics.model_status.eq("FITTED")].set_index("target")
    initiation_auc = float(fitted.loc["non_initiated_within_90_days", "roc_auc"])
    discontinuation_auc = float(fitted.loc["discontinued_within_12_months", "roc_auc"])
    rows: list[dict[str, Any]] = [
        {
            "intervention_hypothesis": "Improve timestamp capture for referral creation and completion before any future pathway-prediction use.",
            "affected_segment": "Primary mHSPC eligibility pathway; all markets",
            "suspected_leakage_point": "Referral handoff visibility begins only after the eligibility prediction index.",
            "evidence": _evidence(driver_tree, "referral_proxy_at_eligibility"),
            "data_confidence": "HIGH for the measurement gap; NOT VERIFIED as an outcome driver",
            "feasibility_in_90_180_days": "HIGH for data-definition and timestamp audit",
            "likely_owner": "Data Strategy + Commercial Operations",
            "leading_indicator": "Percentage of referral records with governed creation/completion timestamps available before prediction index",
            "outcome_KPI": "Censor-aware 90-day initiation reporting completeness; no effectiveness claim",
            "dependency": "Agree operational prediction moment and referral event contract",
            "required_clinical_business_validation": "Commercial must validate the real handoff workflow; Medical must confirm this does not encode a clinical decision.",
            "priority": "1_HIGH_DATA_FOUNDATION",
        },
        {
            "intervention_hypothesis": "Validate market, payer and access-proxy semantics before investigating administrative pathway delay.",
            "affected_segment": "CN and payer categories with elevated descriptive non-initiation odds",
            "suspected_leakage_point": "Administrative/access pathway between eligibility and observed treatment start",
            "evidence": f"{_evidence(driver_tree, 'market_code', 'non_initiated_within_90_days')} | {_evidence(driver_tree, 'insurance_type', 'non_initiated_within_90_days')} | initiation temporal ROC-AUC={initiation_auc:.3f}",
            "data_confidence": "MEDIUM within synthetic contract; LOW for real-world mechanism",
            "feasibility_in_90_180_days": "MEDIUM",
            "likely_owner": "Market Access + Data Strategy",
            "leading_indicator": "Validated cross-market mapping coverage for payer/access fields and missingness",
            "outcome_KPI": "90-day initiation and time-to-initiation by validated administrative segment",
            "dependency": "Independent non-synthetic data and market-specific semantic review",
            "required_clinical_business_validation": "Commercial/Market Access must establish whether categories represent modifiable processes; Medical must rule out clinical case-mix explanations.",
            "priority": "2_HIGH_VALIDATION",
        },
        {
            "intervention_hypothesis": "Audit pathway handoff and scheduling measurement by care setting and provider-volume band without ranking providers.",
            "affected_segment": "Academic-oncology and high-volume provider-band pathways",
            "suspected_leakage_point": "Operational handoff/scheduling measurement after diagnosis",
            "evidence": f"{_evidence(driver_tree, 'care_setting', 'non_initiated_within_90_days')} | {_evidence(driver_tree, 'provider_volume_band', 'non_initiated_within_90_days')}",
            "data_confidence": "MEDIUM synthetic association; causal mechanism NOT ESTABLISHED",
            "feasibility_in_90_180_days": "MEDIUM",
            "likely_owner": "Commercial Operations + Data Strategy",
            "leading_indicator": "Completeness and elapsed time of governed diagnosis-to-handoff milestones",
            "outcome_KPI": "Censor-aware 90-day initiation by setting after case-mix validation",
            "dependency": "Provider-setting definitions, case-mix adjustment plan and minimum cell governance",
            "required_clinical_business_validation": "Medical review of case mix; Commercial confirmation that milestones are operationally controlled; no provider-performance use.",
            "priority": "3_MEDIUM_PATHWAY_AUDIT",
        },
        {
            "intervention_hypothesis": "Validate comorbidity and frailty proxy construction before investigating differentiated support workflows.",
            "affected_segment": "Higher comorbidity/frailty proxy segments",
            "suspected_leakage_point": "Eligibility and pathway-support documentation, not treatment choice",
            "evidence": f"{_evidence(driver_tree, 'comorbidity_score', 'non_initiated_within_90_days')} | {_evidence(driver_tree, 'comorbidity_score', 'restarted_after_gap')}",
            "data_confidence": "MEDIUM synthetic association; clinical validity NOT VERIFIED",
            "feasibility_in_90_180_days": "MEDIUM for definition review; intervention feasibility NOT PROVIDED",
            "likely_owner": "Medical + Data Strategy",
            "leading_indicator": "Agreement of proxy bands with clinically reviewed source evidence",
            "outcome_KPI": "Calibrated descriptive initiation/persistence reporting by validated burden band",
            "dependency": "Medical validation of proxy, confounding review and independent data",
            "required_clinical_business_validation": "Medical must approve interpretation; no care or treatment recommendation may be derived from the current association.",
            "priority": "4_MEDIUM_MEDICAL_VALIDATION",
        },
        {
            "intervention_hypothesis": "Extend governed pre-index observation to measure 180/365-day utilization and prior hospitalization reliably.",
            "affected_segment": "All initiation-risk-set patients",
            "suspected_leakage_point": "Baseline data coverage before diagnosis/eligibility",
            "evidence": _evidence(driver_tree, "baseline_utilization_and_provider_specialty"),
            "data_confidence": "HIGH for current coverage limitation",
            "feasibility_in_90_180_days": "DEPENDENT ON DATA AVAILABILITY",
            "likely_owner": "Data Strategy",
            "leading_indicator": "Percentage with complete 180-day and 365-day pre-index observation",
            "outcome_KPI": "Stability of baseline-driver estimates after complete lookback",
            "dependency": "Claims/encounter history or a governed statement that it is unavailable",
            "required_clinical_business_validation": "Data Strategy must establish provenance; Medical must define clinically meaningful baseline windows.",
            "priority": "5_MEDIUM_DATA_COVERAGE",
        },
        {
            "intervention_hypothesis": "Improve explicit stop, refill-gap reason, disenrollment and medication-administration capture before persistence prediction.",
            "affected_segment": "Patients entering the 12-month persistence risk set",
            "suspected_leakage_point": "Longitudinal outcome ascertainment after treatment start",
            "evidence": f"Gap-60 target is assumption-dependent; discontinuation temporal ROC-AUC={discontinuation_auc:.3f}, indicating no useful temporal discrimination from current baseline features.",
            "data_confidence": "HIGH for weak model performance; MEDIUM for synthetic event reconciliation",
            "feasibility_in_90_180_days": "MEDIUM for data contract; source acquisition NOT PROVIDED",
            "likely_owner": "Medical + Data Strategy",
            "leading_indicator": "Share of terminal gaps with explicit reason and separately observed disenrollment/administration",
            "outcome_KPI": "Reduction in proxy/unknown persistence endpoints and stable 30/60/90-day sensitivity",
            "dependency": "Validated longitudinal source fields and competing-event methodology",
            "required_clinical_business_validation": "Medical must approve discontinuation/restart definitions; Data Strategy must validate censoring and source completeness.",
            "priority": "6_MEDIUM_OUTCOME_QUALITY",
        },
        {
            "intervention_hypothesis": "Lock an independent future period and repeat calibration/subgroup testing before any operational pilot.",
            "affected_segment": "All modelled targets and reported subgroups",
            "suspected_leakage_point": "Model validation and temporal transportability",
            "evidence": "Temporal performance is directional for initiation and weak for discontinuation/switch/restart; subgroup spread is present.",
            "data_confidence": "HIGH for current internal evaluation; external transportability NOT VERIFIED",
            "feasibility_in_90_180_days": "MEDIUM if future/independent data are available",
            "likely_owner": "Data Strategy + Model Risk",
            "leading_indicator": "Locked validation protocol, zero patient overlap and predefined subgroup thresholds",
            "outcome_KPI": "External PR-AUC, Brier score, calibration error and subgroup stability",
            "dependency": "Independent non-synthetic dataset or future holdout with unchanged definitions",
            "required_clinical_business_validation": "Medical, Commercial and Data Strategy must approve intended use and stopping rules before pilot.",
            "priority": "7_RELEASE_GATE",
        },
    ]
    result = pd.DataFrame(rows)
    result["financial_value"] = "NOT PROVIDED"
    result["intervention_success_probability"] = "NOT PROVIDED"
    result["clinical_effectiveness_estimate"] = "NOT PROVIDED"
    result["treatment_recommendation"] = "NONE"
    return result


def update_model_card(backlog: pd.DataFrame) -> None:
    path = OUTPUT_DIR / "model_card.md"
    if not path.is_file():
        raise FileNotFoundError("Run eda/06_driver_analysis.py before intervention backlog")
    marker = "<!-- INTERVENTION_BACKLOG_GENERATED -->"
    existing = path.read_text(encoding="utf-8").split(marker)[0].rstrip()
    lines = [
        "",
        marker,
        "",
        "## Generated intervention-validation backlog",
        "",
        "These are measurement and validation hypotheses, not treatment recommendations. Priority reflects sequencing of validation work, not expected effectiveness or financial value.",
        "",
    ]
    for row in backlog.itertuples(index=False):
        lines.extend(
            [
                f"### {row.priority}",
                "",
                f"- **Hypothesis:** {row.intervention_hypothesis}",
                f"- **Segment:** {row.affected_segment}",
                f"- **Evidence:** {row.evidence}",
                f"- **Owner:** {row.likely_owner}",
                f"- **Required validation:** {row.required_clinical_business_validation}",
                f"- **KPI:** {row.outcome_KPI}",
                "",
            ]
        )
    path.write_text(existing + "\n" + "\n".join(lines), encoding="utf-8")


def write_manifest() -> None:
    inputs = [
        OUTPUT_DIR / "cohort_patient_flags.parquet",
        OUTPUT_DIR / "persistence_event_data.parquet",
        OUTPUT_DIR / "driver_association_table.csv",
        OUTPUT_DIR / "model_metrics.csv",
        OUTPUT_DIR / "subgroup_metrics.csv",
        OUTPUT_DIR / "feature_dictionary_for_models.csv",
        OUTPUT_DIR / "driver_tree.csv",
    ]
    scripts = [
        PROJECT_ROOT / "eda" / "06_driver_analysis.py",
        PROJECT_ROOT / "eda" / "07_intervention_backlog.py",
    ]
    outputs = [
        OUTPUT_DIR / "intervention_backlog.csv",
        OUTPUT_DIR / "model_card.md",
        OUTPUT_DIR / "figures" / "calibration_plot.png",
        OUTPUT_DIR / "figures" / "feature_importance.png",
        OUTPUT_DIR / "target_audit.csv",
        OUTPUT_DIR / "permutation_importance.csv",
        OUTPUT_DIR / "calibration_data.csv",
    ]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_data_modified": False,
        "shap_status": "NOT_GENERATED: SHAP unavailable and no justified tree challenger",
        "inputs": {str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in inputs},
        "scripts": {str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in scripts},
        "outputs": {str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in outputs},
    }
    (OUTPUT_DIR / "driver_analysis_run_manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    ensure_output_directories()
    driver_path = OUTPUT_DIR / "driver_tree.csv"
    metrics_path = OUTPUT_DIR / "model_metrics.csv"
    if not driver_path.is_file() or not metrics_path.is_file():
        raise FileNotFoundError("Run eda/06_driver_analysis.py first")
    driver_tree = pd.read_csv(driver_path)
    metrics = pd.read_csv(metrics_path)
    backlog = build_backlog(driver_tree, metrics)
    backlog.to_csv(OUTPUT_DIR / "intervention_backlog.csv", index=False)
    update_model_card(backlog)
    write_manifest()
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "backlog_items": len(backlog),
        "treatment_recommendations": 0,
        "financial_values_invented": 0,
        "success_probabilities_invented": 0,
        "source_data_modified": False,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
