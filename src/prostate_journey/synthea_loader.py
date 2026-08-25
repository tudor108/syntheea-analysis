"""Load Synthea exports and build independent multi-market patient archetypes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .market import market_profiles, scaled_market_counts

LOGGER = logging.getLogger(__name__)


def calendar_year_age(
    birth_date: pd.Timestamp | str, reference_date: pd.Timestamp | str
) -> int | None:
    """Return completed calendar years at a reference date.

    A day-count divided by 365 is not a valid age calculation around birthdays
    or leap years. February 29 birthdays advance on March 1 in non-leap years.
    """
    birth = pd.Timestamp(birth_date)
    reference = pd.Timestamp(reference_date)
    if pd.isna(birth) or pd.isna(reference):
        return None
    birthday_not_reached = (reference.month, reference.day) < (birth.month, birth.day)
    return int(reference.year - birth.year - birthday_not_reached)


def _birth_dates_for_exact_ages(
    index_dates: pd.DatetimeIndex,
    ages: np.ndarray,
    rng: np.random.Generator,
) -> pd.DatetimeIndex:
    """Sample birth dates whose completed calendar ages equal ``ages`` exactly."""
    births: list[pd.Timestamp] = []
    for index_date, age in zip(index_dates, ages, strict=True):
        most_recent_birthday = index_date - pd.DateOffset(years=int(age))
        prior_birthday = index_date - pd.DateOffset(years=int(age) + 1)
        exact_age_window_days = (most_recent_birthday - prior_birthday).days
        offset = int(rng.integers(0, exact_age_window_days))
        births.append(most_recent_birthday - pd.Timedelta(days=offset))
    return pd.DatetimeIndex(births)


def load_synthea_csv(input_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load every readable Synthea CSV keyed by lower-case stem."""
    root = Path(input_dir)
    tables = {
        path.stem.lower(): pd.read_csv(path, low_memory=False)
        for path in sorted(root.glob("*.csv"))
    }
    if tables:
        LOGGER.info("Loaded %d Synthea CSV tables from %s", len(tables), root)
    return tables


def make_base_patients(size: int, seed: int, minimum_age: int, maximum_age: int) -> pd.DataFrame:
    """Create unique Synthea-shaped US archetypes for tests and offline fallback."""
    rng = np.random.default_rng(seed)
    ages = np.clip(rng.normal(69, 9, size).round(), minimum_age, maximum_age).astype(int)
    index_dates = pd.to_datetime("2021-01-01") + pd.to_timedelta(
        rng.integers(0, 730, size), unit="D"
    )
    births = _birth_dates_for_exact_ages(index_dates, ages, rng)
    return pd.DataFrame(
        {
            "Id": [f"fallback-{i:08d}" for i in range(size)],
            "source_patient_id": pd.NA,
            "source_archetype_id": [f"ARCH-US-{i:08d}" for i in range(size)],
            "source_record_type": "generated_archetype",
            "BIRTHDATE": births,
            "GENDER": "M",
            "RACE": rng.choice(
                ["white", "black", "asian", "other"], size, p=[0.62, 0.20, 0.10, 0.08]
            ),
            "ETHNICITY": rng.choice(["nonhispanic", "hispanic"], size, p=[0.82, 0.18]),
            "STATE": rng.choice(["Northeast", "Midwest", "South", "West"], size),
            "ZIP": rng.integers(10000, 99999, size).astype(str),
            "synthetic_index_date": index_dates,
            "market_code": "US",
            "country": "United States",
            "market_depth": "deep",
            "insurance_type": rng.choice(
                ["commercial", "medicare", "medicaid", "other"],
                size,
                p=[0.24, 0.61, 0.10, 0.05],
            ),
            "access_index": np.clip(rng.normal(0.66, 0.16, size), 0.05, 0.98).round(3),
        }
    )


def _eligible_raw_patients(
    tables: dict[str, pd.DataFrame], minimum_age: int, maximum_age: int
) -> pd.DataFrame:
    if "patients" not in tables:
        return pd.DataFrame()
    raw = tables["patients"].copy()
    gender = raw.get("GENDER", raw.get("gender", ""))
    raw = raw.loc[
        pd.Series(gender, index=raw.index).astype(str).str.upper().isin(["M", "MALE"])
    ].copy()
    birth_col = "BIRTHDATE" if "BIRTHDATE" in raw else "birthdate"
    births = pd.to_datetime(raw[birth_col], errors="coerce")
    age = pd.Series(
        [calendar_year_age(birth, "2022-01-01") for birth in births],
        index=raw.index,
        dtype="Int64",
    )
    id_col = "Id" if "Id" in raw else "id"
    return (
        raw.loc[age.between(minimum_age, maximum_age)]
        .drop_duplicates(id_col)
        .reset_index(drop=True)
    )


def select_base_patients(
    tables: dict[str, pd.DataFrame], size: int, seed: int, minimum_age: int, maximum_age: int
) -> pd.DataFrame:
    """Select raw patients once and fill any shortfall with unique generated archetypes."""
    raw = _eligible_raw_patients(tables, minimum_age, maximum_age)
    if raw.empty:
        LOGGER.warning("No eligible patients.csv rows; using independent generated archetypes")
        return make_base_patients(size, seed, minimum_age, maximum_age)
    selected = raw.sample(min(size, len(raw)), random_state=seed, replace=False).copy()
    selected["synthetic_index_date"] = pd.Timestamp("2022-01-01")
    if len(selected) == size:
        return selected.reset_index(drop=True)
    generated = make_base_patients(size - len(selected), seed + 104729, minimum_age, maximum_age)
    generated["Id"] = [f"augmented-{i:08d}" for i in range(len(generated))]
    LOGGER.warning(
        "Only %d unique eligible raw rows; adding %d independent archetypes without cloning",
        len(selected),
        len(generated),
    )
    return pd.concat([selected, generated], ignore_index=True, sort=False)


def make_multimarket_base(tables: dict[str, pd.DataFrame], config: dict[str, Any]) -> pd.DataFrame:
    """Generate independent archetypes for all configured markets, using raw US rows once."""
    rng = np.random.default_rng(config["random_seed"])
    counts = scaled_market_counts(config)
    profiles = market_profiles(config)
    diagnosis_start = pd.Timestamp(config["diagnosis_start_date"])
    diagnosis_end = pd.Timestamp(config["diagnosis_end_date"])
    date_span = (diagnosis_end - diagnosis_start).days + 1
    frames: list[pd.DataFrame] = []

    for market_code, count in counts.items():
        profile = profiles[market_code]
        ages = np.clip(
            rng.normal(profile["age_mean"], profile["age_sd"], count).round(),
            config["minimum_age"],
            config["maximum_age"],
        ).astype(int)
        index_dates = diagnosis_start + pd.to_timedelta(rng.integers(0, date_span, count), unit="D")
        births = _birth_dates_for_exact_ages(index_dates, ages, rng)
        races = profile["race_distribution"]
        insurance = profile["insurance_distribution"]
        rows = pd.DataFrame(
            {
                "Id": [f"generated-{market_code}-{i:08d}" for i in range(count)],
                "source_patient_id": pd.NA,
                "source_archetype_id": [f"ARCH-{market_code}-{i:08d}" for i in range(count)],
                "source_record_type": "generated_archetype",
                "BIRTHDATE": births,
                "GENDER": "M",
                "RACE": rng.choice(list(races), count, p=list(races.values())),
                "ETHNICITY": rng.choice(
                    ["majority", "minority", "unknown"], count, p=[0.78, 0.19, 0.03]
                ),
                "STATE": rng.choice(profile["regions"], count),
                "ZIP": rng.integers(10000, 99999, count).astype(str),
                "synthetic_index_date": index_dates,
                "market_code": market_code,
                "country": profile["market_name"],
                "market_depth": profile["depth"],
                "insurance_type": rng.choice(list(insurance), count, p=list(insurance.values())),
                "access_index": np.clip(
                    rng.normal(profile["access_index_mean"], 0.15, count), 0.05, 0.98
                ).round(3),
            }
        )
        frames.append(rows)

    base = pd.concat(frames, ignore_index=True)
    raw = _eligible_raw_patients(tables, config["minimum_age"], config["maximum_age"])
    if not raw.empty:
        available_us_indices = list(base.index[base.market_code.eq("US")])
        raw = raw.sample(
            min(len(raw), len(available_us_indices)),
            random_state=config["random_seed"],
        )
        for _, source in raw.iterrows():
            birth_col = "BIRTHDATE" if "BIRTHDATE" in source else "birthdate"
            id_col = "Id" if "Id" in source else "id"
            source_birth = pd.to_datetime(source[birth_col])
            compatible = [
                target_index
                for target_index in available_us_indices
                if config["minimum_age"]
                <= calendar_year_age(
                    source_birth,
                    pd.Timestamp(base.loc[target_index, "synthetic_index_date"]),
                )
                <= config["maximum_age"]
            ]
            if not compatible:
                continue
            target_index = compatible[0]
            available_us_indices.remove(target_index)
            base.loc[target_index, "BIRTHDATE"] = source_birth
            base.loc[target_index, "source_patient_id"] = str(source[id_col])
            base.loc[target_index, "source_record_type"] = "synthea_unique"
            for source_col, target_col in (
                ("RACE", "RACE"),
                ("ETHNICITY", "ETHNICITY"),
            ):
                if source_col in source and pd.notna(source[source_col]):
                    base.loc[target_index, target_col] = source[source_col]
    return base.reset_index(drop=True)
