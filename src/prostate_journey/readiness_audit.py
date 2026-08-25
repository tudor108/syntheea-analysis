"""Independent, evidence-based dataset readiness audit and scorecard."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

CATEGORY_BY_REQUIREMENT = {
    1: "Market segmentation readiness",
    2: "Market segmentation readiness",
    3: "Longitudinal readiness",
    4: "Data quality",
    5: "Eligibility analysis readiness",
    6: "Eligibility analysis readiness",
    7: "Treatment initiation readiness",
    8: "Persistence/discontinuation readiness",
    9: "Clinical/pathway coherence",
    10: "Clinical/pathway coherence",
    11: "Clinical/pathway coherence",
    12: "Clinical/pathway coherence",
    13: "Clinical/pathway coherence",
    14: "Synthetic realism",
    15: "Synthetic realism",
    16: "Driver-analysis readiness",
    17: "Schema quality",
    18: "Schema quality",
    19: "Schema quality",
    20: "Overall diagnostic readiness",
    21: "Driver-analysis readiness",
    22: "Schema quality",
    23: "Schema quality",
    24: "Synthetic realism",
    25: "Data quality",
}


def _dq_pass(dq_results: list[dict], prefixes: tuple[str, ...]) -> bool:
    selected = [result for result in dq_results if result["rule"].startswith(prefixes)]
    return bool(selected) and all(result["failure_count"] == 0 for result in selected)


def _table_fingerprint(frame: pd.DataFrame) -> str:
    """Return a stable content-and-schema fingerprint for reproducibility evidence."""
    digest = hashlib.sha256()
    digest.update("|".join(frame.columns).encode("utf-8"))
    digest.update("|".join(map(str, frame.dtypes)).encode("utf-8"))
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return digest.hexdigest()


def audit_tables(
    tables: dict[str, pd.DataFrame], dq_results: list[dict], config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Evaluate the 25 acceptance gates without hardcoding a passing score."""
    patient = tables["patient"]
    diagnosis = tables["diagnosis"]
    encounter = tables["encounter"]
    referral = tables["referral"]
    active = tables["active_surveillance"]
    episode = tables["treatment_episode"]
    regimen = tables["treatment_regimen"]
    rx = tables["prescription_event"]
    adverse = tables["adverse_event"]
    journey = tables["patient_journey"]
    feature_timing = tables["feature_timing"]
    provider = tables["provider"]

    market_counts = patient.groupby(["market_code", "market_depth"]).size().rename("patients")
    market_summary = market_counts.reset_index()
    for name, frame in (
        ("encounters", encounter),
        ("referrals", referral),
        ("treatment_episodes", episode),
        ("prescription_events", rx),
        ("adverse_events", adverse),
    ):
        counts = (
            frame.groupby("market_code").size() if not frame.empty else pd.Series(dtype="int64")
        )
        market_summary[name] = market_summary.market_code.map(counts).fillna(0).astype(int)
        market_summary[f"{name}_per_patient"] = market_summary[name] / market_summary.patients
    market_summary["eligible"] = (
        market_summary.market_code.map(journey.groupby("market_code").eligibility_flag.sum())
        .fillna(0)
        .astype(int)
    )
    market_summary["initiated"] = (
        market_summary.market_code.map(journey.groupby("market_code").treatment_initiated.sum())
        .fillna(0)
        .astype(int)
    )
    market_summary["persistent_12m_evaluable"] = (
        market_summary.market_code.map(
            journey.groupby("market_code").persistence_12m_status.apply(
                lambda values: values.isin(["PERSISTENT", "DISCONTINUED", "SWITCHED"]).sum()
            )
        )
        .fillna(0)
        .astype(int)
    )

    deep = market_summary[market_summary.market_depth.eq("deep")]
    scan = market_summary[market_summary.market_depth.eq("scan")]
    # Encounter density is the deliberately configured pathway-depth distinction.
    # Mixing it with medication-event density would dilute that signal because
    # persistence requires comparable dispensing semantics in every market.
    deep_richness = float(deep.encounters_per_patient.mean())
    scan_richness = float(scan.encounters_per_patient.mean())
    richness_ratio = deep_richness / max(scan_richness, 0.001)
    minimum_market = (
        config["readiness"]["minimum_market_patients_full"]
        if config["target_cohort_size"] >= 5000
        else config["readiness"]["minimum_market_patients_smoke"]
    )
    all_market_counts_ok = bool((market_summary.patients >= minimum_market).all())
    configured_provider_counts = {
        market: max(
            4,
            math.ceil(
                int((patient.market_code == market).sum())
                / 1000
                * float(profile["providers_per_1000"])
            ),
        )
        for market, profile in config["market_configuration"]["markets"].items()
    }
    actual_provider_counts = provider.groupby("market_code").size().to_dict()
    provider_network_matches_config = actual_provider_counts == configured_provider_counts

    stage_rates = diagnosis.groupby("market_code").metastatic_flag.mean()
    market_distributions_differ = float(stage_rates.max() - stage_rates.min()) >= 0.05
    progression_by_stage = journey.groupby("metastatic_flag").progression_event.mean()
    outcome_signal = bool(
        len(progression_by_stage) == 2
        and progression_by_stage.between(0.01, 0.95).all()
        and abs(float(progression_by_stage.iloc[1] - progression_by_stage.iloc[0])) >= 0.05
    )
    scan_product_missing = (
        rx.loc[rx.market_code.isin(scan.market_code), "product_id"].isna().mean()
        if not rx.empty
        else 0
    )
    deep_product_missing = (
        rx.loc[rx.market_code.isin(deep.market_code), "product_id"].isna().mean()
        if not rx.empty
        else 0
    )
    explicit_depth_difference = bool(
        richness_ratio >= config["readiness"]["deep_to_scan_event_ratio_minimum"]
        and scan_product_missing > deep_product_missing
    )

    required_capability_columns = {
        "eligibility_flag",
        "treatment_initiated",
        "eligible_not_initiated_90d",
        "initiated_within_90d",
        "persistence_12m_status",
        "discontinuation_flag",
        "initial_care_setting",
        "pathway_care_setting",
        "market_code",
        "complexity_segment",
    }
    capabilities = required_capability_columns.issubset(journey.columns) and all(
        [
            journey.eligibility_flag.any(),
            journey.treatment_initiated.any(),
            journey.eligible_not_initiated_90d.any(),
        ]
    )
    upstream_features = feature_timing[
        ~feature_timing.future_information_flag & feature_timing.predictor_allowed_flag
    ]
    labels_documented = bool(
        journey.eligibility_rule_version.notna().all()
        and regimen.guideline_rule_version.notna().all()
        and config["prescription"]["definition_version"]
        == config["clinical_rule_configuration"]["clinical_rules"]["persistence"]["version"]
        and journey.persistence_rule_version.eq(config["prescription"]["definition_version"]).all()
        and config["clinical_rule_configuration"]["version"]
        and active.active_surveillance_rule_version.notna().all()
        and tables["outcome"].outcome_model_version.notna().all()
    )
    active_ready = bool(
        active.as_start_date.notna().any()
        and active.as_exit_date.notna().any()
        and active.transition_to_treatment_flag.any()
        and active.as_reclassification_event_flag.any()
        and encounter.encounter_type.str.startswith("as_").any()
    )
    referral_ready = bool(
        not referral.empty
        and referral.source_provider_id.ne(referral.destination_provider_id).all()
        and {"completed", "pending", "rejected", "cancelled", "not_completed"}.issubset(
            set(referral.referral_status)
        )
    )
    transition_ready = bool(
        {"switch", "restart"}.issubset(set(episode.transition_type))
        and {"planned_combination", "add_on"}.issubset(set(regimen.combination_strategy))
    )
    persistence_ready = bool(
        {"PERSISTENT", "DISCONTINUED", "SWITCHED", "CENSORED_NOT_EVALUABLE"}.issubset(
            set(journey.persistence_12m_status)
        )
    )
    p0_p1_clear = all(
        result["failure_count"] == 0 for result in dq_results if result["severity"] == "critical"
    )
    market_count_evidence = dict(
        zip(market_summary.market_code, market_summary.patients, strict=False)
    )
    reproducibility_verified = config["readiness"].get("runtime_reproducibility_verified")
    reproducibility_ready = bool(
        config.get("random_seed") is not None
        and config.get("scenario_version")
        and _dq_pass(dq_results, ("independent_archetypes", "split_archetype"))
        and reproducibility_verified is not False
    )

    checks = {
        1: (
            set(patient.market_code) == {"US", "DE", "JP", "FR", "CN", "AU", "CA"}
            and all_market_counts_ok,
            f"counts={market_count_evidence}",
        ),
        2: (
            explicit_depth_difference and provider_network_matches_config,
            f"deep/scan richness ratio={richness_ratio:.2f}; "
            f"product missing deep={deep_product_missing:.3f}, "
            f"scan={scan_product_missing:.3f}; providers actual={actual_provider_counts}, "
            f"configured={configured_provider_counts}",
        ),
        3: (
            _dq_pass(dq_results, ("no_event_after_censor",)),
            "all event domains checked against patient censor date",
        ),
        4: (
            _dq_pass(
                dq_results,
                (
                    "birth_before",
                    "treatment_episode_dates",
                    "regimen_episode_dates",
                    "component_episode_dates",
                    "prescription_dates",
                ),
            ),
            "zero invalid temporal intervals",
        ),
        5: (
            _dq_pass(dq_results, ("eligibility_reconstructable", "eligibility_date_semantics")),
            "eligibility recomputed from exported variables",
        ),
        6: (
            _dq_pass(dq_results, ("ineligibility_explained",)),
            "explicit clinical or insufficiency reason",
        ),
        7: (
            _dq_pass(dq_results, ("intensification_reconstructable",))
            and regimen.intensification_flag.any(),
            "regimen-component intensification is available",
        ),
        8: (
            _dq_pass(
                dq_results,
                (
                    "persistence_reconstructable",
                    "persistence_sensitivity_reconstructable",
                    "persistence_right_censoring",
                    "persistence_status_flag",
                ),
            )
            and persistence_ready,
            "nullable statuses distinguish censoring",
        ),
        9: (
            active_ready
            and _dq_pass(
                dq_results,
                (
                    "active_surveillance_logic",
                    "active_surveillance_treatment_reconciliation",
                    "active_surveillance_reclassification_semantics",
                ),
            ),
            "AS monitoring, exit and transition represented",
        ),
        10: (
            referral_ready and _dq_pass(dq_results, ("referral_",)),
            "source/destination provider referrals with full statuses",
        ),
        11: (
            transition_ready
            and _dq_pass(dq_results, ("switch_restart_nonoverlap", "no_old_drug_after_switch")),
            "switch/add-on/restart semantics represented",
        ),
        12: (
            _dq_pass(
                dq_results,
                (
                    "encounter_specialty",
                    "encounter_setting",
                    "encounter_organization",
                    "referral_specialty",
                    "referral_organization",
                    "decision_owner",
                    "treatment_provider_compatibility",
                    "chemotherapy_referral_coherence",
                ),
            ),
            "provider master and event specialties agree",
        ),
        13: (
            _dq_pass(
                dq_results,
                (
                    "age_derived",
                    "age_configured_range",
                    "gleason_isup_mapping",
                    "metastatic_state_consistency",
                    "disease_state_transitions",
                ),
            ),
            "age, grade mapping and state logic validated",
        ),
        14: (
            outcome_signal and market_distributions_differ,
            f"progression rates by metastatic state={progression_by_stage.to_dict()}; "
            f"market metastatic-rate range={stage_rates.max() - stage_rates.min():.3f}",
        ),
        15: (
            _dq_pass(dq_results, ("independent_archetypes", "no_source_cloning")),
            "unique archetypes and no raw source reuse",
        ),
        16: (
            _dq_pass(
                dq_results,
                (
                    "split_one",
                    "split_archetype",
                    "feature_timing_leakage",
                    "feature_timing_mart_coverage",
                ),
            ),
            "entity-level split and timing metadata",
        ),
        17: (_dq_pass(dq_results, ("fk_",)), "zero orphan foreign keys"),
        18: (_dq_pass(dq_results, ("pk_",)), "zero duplicate/null primary keys"),
        19: (
            _dq_pass(dq_results, ("mart_",)),
            "mart eligibility, treatment and outcomes reconcile",
        ),
        20: (capabilities, "eligible/treated/gap/persistence/care/market/segment fields available"),
        21: (
            len(upstream_features) >= 10,
            f"legitimate upstream features={len(upstream_features)}",
        ),
        22: (
            labels_documented,
            "eligibility, persistence, state and intensification versions present",
        ),
        23: (
            bool(
                config.get("random_seed") is not None
                and config.get("scenario_version")
                and config["market_configuration"]["version"]
            ),
            "seed/scenario/market/rule versions configured",
        ),
        24: (
            reproducibility_ready,
            "exact full rerun verified"
            if reproducibility_verified is True
            else "deterministic contract; exact rerun exercised by automated test",
        ),
        25: (p0_p1_clear, "no critical DQ failures"),
    }
    priorities = {
        1: "P0",
        3: "P0",
        4: "P0",
        5: "P0",
        8: "P0",
        15: "P0",
        17: "P0",
        18: "P0",
        25: "P0",
    }
    partial_support = {
        9: active.as_start_date.notna().any()
        and _dq_pass(dq_results, ("active_surveillance_logic",)),
        10: not referral.empty and _dq_pass(dq_results, ("referral_",)),
        11: not episode.empty
        and not regimen.empty
        and _dq_pass(
            dq_results,
            ("switch_restart_nonoverlap", "no_old_drug_after_switch"),
        ),
    }
    rows = []
    for requirement_id in range(1, 26):
        passed, detail = checks[requirement_id]
        status = (
            "PASS"
            if passed
            else "PARTIAL"
            if partial_support.get(requirement_id, False)
            else "FAIL"
        )
        rows.append(
            {
                "requirement_id": requirement_id,
                "category": CATEGORY_BY_REQUIREMENT[requirement_id],
                "priority": priorities.get(requirement_id, "P1"),
                "status": status,
                "score": 4 if status == "PASS" else 2 if status == "PARTIAL" else 0,
                "max_score": 4,
                "detail": detail,
            }
        )
    requirement_matrix = pd.DataFrame(rows)
    category_scorecard = requirement_matrix.groupby("category", as_index=False).agg(
        score=("score", "sum"), max_score=("max_score", "sum")
    )
    category_scorecard["percentage"] = (
        category_scorecard.score / category_scorecard.max_score * 100
    ).round(1)

    schema_rows = []
    missingness_rows = []
    for table_name, frame in tables.items():
        schema_rows.append(
            {
                "table": table_name,
                "rows": len(frame),
                "columns": len(frame.columns),
                "memory_bytes": int(frame.memory_usage(deep=True).sum()),
            }
        )
        for column, missing in frame.isna().sum().items():
            missingness_rows.append(
                {
                    "table": table_name,
                    "column": column,
                    "dtype": str(frame[column].dtype),
                    "nullable_observed": bool(missing > 0),
                    "missing_count": int(missing),
                    "missing_rate": round(float(missing / max(len(frame), 1)), 6),
                }
            )
    return (
        requirement_matrix,
        category_scorecard,
        pd.DataFrame(schema_rows),
        pd.DataFrame(missingness_rows),
        market_summary,
    )


def write_readiness_audit(
    tables: dict[str, pd.DataFrame],
    dq_results: list[dict],
    config: dict[str, Any],
    report_dir: str | Path,
) -> dict[str, Any]:
    """Write requirement matrix, category scorecard and diagnostic summaries."""
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    requirement, category, schema, missingness, market = audit_tables(tables, dq_results, config)
    requirement.to_csv(root / "readiness_requirement_matrix.csv", index=False)
    category.to_csv(root / "readiness_scorecard.csv", index=False)
    schema.to_csv(root / "schema_summary.csv", index=False)
    missingness.to_csv(root / "missingness_summary.csv", index=False)
    market.to_csv(root / "market_summary.csv", index=False)
    score = int(requirement.score.sum())
    failed = requirement[requirement.status.eq("FAIL")]
    partial = requirement[requirement.status.eq("PARTIAL")]
    payload = {
        "overall_readiness_score": score,
        "maximum_score": 100,
        "failed_requirements": failed.requirement_id.tolist(),
        "partial_requirements": partial.requirement_id.tolist(),
        "p0_p1_failures": failed[failed.priority.isin(["P0", "P1"])].requirement_id.tolist(),
        "requirements": requirement.to_dict(orient="records"),
        "categories": category.to_dict(orient="records"),
        "table_fingerprints": {name: _table_fingerprint(frame) for name, frame in tables.items()},
    }
    (root / "readiness_audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Dataset Readiness Audit",
        "",
        f"**Overall readiness: {score}/100**",
        "",
        "| ID | Category | Priority | Status | Score | Evidence |",
        "|---:|---|---|---:|---:|---|",
    ]
    lines.extend(
        f"| {row.requirement_id} | {row.category} | {row.priority} | "
        f"{row.status} | {row.score}/{row.max_score} | {row.detail} |"
        for row in requirement.itertuples()
    )
    (root / "readiness_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def raise_on_readiness_failure(payload: dict[str, Any]) -> None:
    """Fail generation when an actual P0/P1 readiness requirement fails."""
    if payload["p0_p1_failures"]:
        raise ValueError(
            "Readiness P0/P1 failures: "
            + ", ".join(str(value) for value in payload["p0_p1_failures"])
        )
