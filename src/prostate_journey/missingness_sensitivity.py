"""Synthetic truth-recovery experiments for explicit missing-data mechanisms."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import DISCLAIMER

Z_975 = 1.959963984540054


def build_complete_truth_frame(tables: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Retain the generated pre-missingness PSA and mechanism drivers."""
    patient = tables["patient"][["patient_id", "market_code", "access_index", "comorbidity_score"]]
    diagnosis = tables["diagnosis"][["patient_id", "psa_value"]]
    truth = patient.merge(diagnosis, on="patient_id", validate="one_to_one")
    truth["psa_value"] = pd.to_numeric(truth.psa_value, errors="coerce")
    if truth.psa_value.isna().any():
        raise ValueError("Pre-missingness truth frame must contain complete PSA values")
    if truth.patient_id.duplicated().any():
        raise AssertionError("Truth frame must remain one row per generated patient")
    return truth


def _standardize(values: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    standard_deviation = float(np.nanstd(numeric))
    if not math.isfinite(standard_deviation) or standard_deviation < 1e-12:
        return np.zeros(len(numeric), dtype=float)
    return (numeric - float(np.nanmean(numeric))) / standard_deviation


def _calibrate_probabilities(weights: np.ndarray, target_rate: float) -> np.ndarray:
    if not 0 < target_rate < 0.95:
        raise ValueError("Target missing rate must be between 0 and 0.95")
    positive = np.clip(np.asarray(weights, dtype=float), 1e-6, None)
    low, high = 0.0, 100.0
    for _ in range(80):
        middle = (low + high) / 2
        mean = float(np.minimum(0.95, middle * positive).mean())
        if mean < target_rate:
            low = middle
        else:
            high = middle
    return np.minimum(0.95, high * positive)


def missingness_probabilities(
    truth: pd.DataFrame,
    mechanism: str,
    target_rate: float,
    config: Mapping[str, Any],
) -> np.ndarray:
    """Return known synthetic mask probabilities without inferring a real mechanism."""
    if mechanism == "EXISTING_CONFIGURED":
        profiles = config["market_configuration"]["markets"]
        base = float(config["missingness"]["psa_base"])
        probabilities = truth.market_code.map(
            lambda market: base * float(profiles[str(market)]["clinical_missingness_multiplier"])
        )
        return probabilities.clip(lower=0.0, upper=0.45).to_numpy(dtype=float)
    if mechanism == "MCAR":
        return np.repeat(target_rate, len(truth))
    if mechanism == "MAR":
        access = -_standardize(truth.access_index)
        comorbidity = _standardize(truth.comorbidity_score)
        scan_market = truth.market_code.isin(["FR", "CN", "AU", "CA"]).to_numpy(dtype=float)
        weights = np.exp(np.clip(0.55 * access + 0.35 * comorbidity + 0.25 * scan_market, -3, 3))
        return _calibrate_probabilities(weights, target_rate)
    if mechanism == "MNAR":
        unobserved_psa = _standardize(truth.psa_value)
        weights = np.exp(np.clip(0.85 * unobserved_psa, -3, 3))
        return _calibrate_probabilities(weights, target_rate)
    raise ValueError(f"Unsupported missingness mechanism: {mechanism}")


def _mean_interval(values: np.ndarray, weights: np.ndarray | None = None) -> dict[str, float]:
    finite = np.isfinite(values)
    observed = values[finite]
    if len(observed) < 2:
        return {
            "estimate": math.nan,
            "standard_error": math.nan,
            "confidence_lower": math.nan,
            "confidence_upper": math.nan,
            "effective_sample_size": float(len(observed)),
        }
    if weights is None:
        estimate = float(observed.mean())
        standard_error = float(observed.std(ddof=1) / math.sqrt(len(observed)))
        effective_sample_size = float(len(observed))
    else:
        observed_weights = np.asarray(weights, dtype=float)[finite]
        total_weight = float(observed_weights.sum())
        if total_weight <= 0:
            return {
                "estimate": math.nan,
                "standard_error": math.nan,
                "confidence_lower": math.nan,
                "confidence_upper": math.nan,
                "effective_sample_size": 0.0,
            }
        normalized = observed_weights / total_weight
        estimate = float(np.sum(normalized * observed))
        effective_sample_size = float(1.0 / np.sum(normalized**2))
        variance = float(np.sum(normalized * (observed - estimate) ** 2))
        standard_error = math.sqrt(variance / max(effective_sample_size, 1.0))
    return {
        "estimate": estimate,
        "standard_error": standard_error,
        "confidence_lower": estimate - Z_975 * standard_error,
        "confidence_upper": estimate + Z_975 * standard_error,
        "effective_sample_size": effective_sample_size,
    }


def run_truth_recovery_experiment(
    truth: pd.DataFrame,
    config: Mapping[str, Any],
    experiment: Mapping[str, Any],
    *,
    release: str,
    scenario: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Evaluate complete case, oracle weighting, and MNAR delta adjustment."""
    variable = str(experiment["variable"])
    if variable != "psa_value":
        raise ValueError("The implemented truth-recovery estimand currently supports psa_value")
    values = truth[variable].to_numpy(dtype=float)
    truth_mean = float(values.mean())
    truth_standard_deviation = float(values.std(ddof=1))
    replications = int(experiment["replications"])
    seed_start = int(experiment["seed_start"])
    target_rate = float(experiment["target_missing_rate"])
    mechanisms = list(map(str, experiment["mechanisms"]))
    deltas = list(map(float, experiment["delta_standard_deviations"]))
    common = {
        "numerator": "sum of observed or weighted generated pre-missingness PSA values",
        "denominator": "observed count, weighted effective sample, or complete generated count",
        "population_definition": "complete generated pre-missingness PSA truth cohort",
        "time_zero": "generated diagnosis date (cross-sectional estimand)",
        "horizon_days": 0,
        "scenario": scenario,
        "seed_summary": f"{replications} mask seeds: {seed_start}-{seed_start + replications - 1}",
        "release": release,
        "assumptions": (
            "MCAR/MAR/MNAR and existing probabilities are known engineering stress tests; "
            "oracle weighting does not establish MAR in practice."
        ),
        "limitation": (
            "Synthetic truth recovery for one mean estimand; not evidence that a method is valid "
            "for a governed real dataset."
        ),
        "synthetic_data_only": True,
    }
    rows: list[dict[str, Any]] = []
    tipping_rows: list[dict[str, Any]] = []
    for mechanism in mechanisms:
        probabilities = missingness_probabilities(truth, mechanism, target_rate, config)
        for replication in range(replications):
            seed = seed_start + replication
            rng = np.random.default_rng(seed + 1_000_000 * mechanisms.index(mechanism))
            missing = rng.random(len(values)) < probabilities
            observed = values.copy()
            observed[missing] = np.nan
            complete_case = _mean_interval(observed)
            methods: list[tuple[str, dict[str, float]]] = [("COMPLETE_CASE", complete_case)]
            if mechanism != "MNAR":
                oracle_weights = 1.0 / np.clip(1.0 - probabilities, 1e-6, None)
                methods.append(
                    ("ORACLE_IPW_KNOWN_SYNTHETIC_MASK", _mean_interval(observed, oracle_weights))
                )
            for method, result in methods:
                estimate = result["estimate"]
                rows.append(
                    {
                        "mechanism": mechanism,
                        "method": method,
                        "replication": replication,
                        "mask_seed": seed,
                        "truth": truth_mean,
                        "estimate": estimate,
                        "bias": estimate - truth_mean if math.isfinite(estimate) else math.nan,
                        "squared_error": (estimate - truth_mean) ** 2
                        if math.isfinite(estimate)
                        else math.nan,
                        "estimator_standard_error": result["standard_error"],
                        "estimator_confidence_lower": result["confidence_lower"],
                        "estimator_confidence_upper": result["confidence_upper"],
                        "truth_covered": bool(
                            result["confidence_lower"] <= truth_mean <= result["confidence_upper"]
                        )
                        if math.isfinite(result["confidence_lower"])
                        else False,
                        "effective_sample_size": result["effective_sample_size"],
                        "complete_truth_n": len(values),
                        "observed_n": int((~missing).sum()),
                        "realized_missing_rate": float(missing.mean()),
                        "failure": not math.isfinite(estimate),
                        "uncertainty_type": "ESTIMATOR_CONFIDENCE_INTERVAL_95_WITHIN_ONE_MASK",
                        **common,
                    }
                )
            if mechanism == "MNAR" and (~missing).any():
                observed_mean = float(np.nanmean(observed))
                for delta in deltas:
                    adjusted = observed.copy()
                    adjusted[missing] = observed_mean + delta * truth_standard_deviation
                    result = _mean_interval(adjusted)
                    tipping_rows.append(
                        {
                            "mechanism": mechanism,
                            "method": "MNAR_DELTA_ADJUSTMENT",
                            "replication": replication,
                            "mask_seed": seed,
                            "delta_standard_deviations": delta,
                            "truth": truth_mean,
                            "estimate": result["estimate"],
                            "bias": result["estimate"] - truth_mean,
                            "truth_covered": bool(
                                result["confidence_lower"]
                                <= truth_mean
                                <= result["confidence_upper"]
                            ),
                            "effective_sample_size": result["effective_sample_size"],
                            "uncertainty_type": "MNAR_DELTA_TIPPING_POINT_SENSITIVITY",
                            **common,
                        }
                    )
    replicate_results = pd.DataFrame(rows)
    summary_rows: list[dict[str, Any]] = []
    for (mechanism_key, method_key), group in replicate_results.groupby(
        ["mechanism", "method"], sort=True
    ):
        valid = group.loc[~group.failure]
        first = group.iloc[0]
        summary_rows.append(
            {
                "mechanism": str(mechanism_key),
                "method": str(method_key),
                "truth": truth_mean,
                "mean_estimate": float(valid.estimate.mean()) if not valid.empty else math.nan,
                "bias": float(valid.bias.mean()) if not valid.empty else math.nan,
                "rmse": math.sqrt(float(valid.squared_error.mean()))
                if not valid.empty
                else math.nan,
                "interval_coverage": float(valid.truth_covered.mean())
                if not valid.empty
                else math.nan,
                "mean_effective_sample_size": float(valid.effective_sample_size.mean())
                if not valid.empty
                else 0.0,
                "mean_realized_missing_rate": float(group.realized_missing_rate.mean()),
                "replications": len(group),
                "failure_count": int(group.failure.sum()),
                "uncertainty_type": "MISSINGNESS_METHOD_PERFORMANCE_ACROSS_MASK_REPLICATIONS",
                **{key: first[key] for key in common},
            }
        )
    return replicate_results, pd.DataFrame(summary_rows), pd.DataFrame(tipping_rows)


def write_missingness_outputs(
    truth: pd.DataFrame,
    config: Mapping[str, Any],
    experiment: Mapping[str, Any],
    output_dir: str | Path,
    *,
    release: str,
    scenario: str,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    replicates, summary, tipping = run_truth_recovery_experiment(
        truth,
        config,
        experiment,
        release=release,
        scenario=scenario,
    )
    paths = {
        "truth": output / "truth_complete_pre_missingness.parquet",
        "replicates": output / "missingness_replicate_results.csv",
        "summary": output / "missingness_method_performance.csv",
        "tipping": output / "missingness_tipping_point.csv",
        "report": output / "missingness_sensitivity_report.md",
    }
    truth.to_parquet(paths["truth"], index=False)
    replicates.to_csv(paths["replicates"], index=False)
    summary.to_csv(paths["summary"], index=False)
    tipping.to_csv(paths["tipping"], index=False)
    report_lines: Sequence[str] = (
        "# Missing-data synthetic truth-recovery experiment",
        "",
        f"> **{DISCLAIMER}**",
        "",
        "The complete pre-missingness generated PSA values are retained separately. Repeated masks "
        "then evaluate configured existing, MCAR, MAR, and MNAR engineering mechanisms.",
        "",
        "Complete-case and oracle inverse-probability weighted examples are evaluated with bias, "
        "RMSE, interval coverage, effective sample size, and explicit failure counts. Oracle "
        "weighting uses known synthetic mask probabilities and does not prove that MAR is "
        "plausible.",
        "",
        "MNAR results include delta-adjustment rows across the configured tipping-point grid. "
        "No imputation or missingness assumption is recommended for real data.",
    )
    paths["report"].write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return paths
