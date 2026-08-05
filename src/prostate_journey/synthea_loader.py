"""Load Synthea CSV exports and provide a documented demo fallback."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def load_synthea_csv(input_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load every readable Synthea CSV keyed by lower-case stem."""
    root = Path(input_dir)
    tables: dict[str, pd.DataFrame] = {}
    for path in sorted(root.glob("*.csv")):
        tables[path.stem.lower()] = pd.read_csv(path, low_memory=False)
    if tables:
        LOGGER.info("Loaded %d Synthea CSV tables from %s", len(tables), root)
    return tables


def make_base_patients(size: int, seed: int, minimum_age: int, maximum_age: int) -> pd.DataFrame:
    """Create Synthea-shaped male patients when no raw export is available."""
    rng = np.random.default_rng(seed)
    ages = np.clip(rng.normal(69, 9, size).round(), minimum_age, maximum_age).astype(int)
    index_dates = pd.to_datetime("2021-01-01") + pd.to_timedelta(
        rng.integers(0, 730, size), unit="D"
    )
    births = index_dates - pd.to_timedelta((ages * 365.25).astype(int), unit="D")
    return pd.DataFrame(
        {
            "Id": [f"fallback-{i:08d}" for i in range(size)],
            "BIRTHDATE": births,
            "GENDER": "M",
            "RACE": rng.choice(["white", "black", "asian", "other"], size, p=[.62, .20, .10, .08]),
            "ETHNICITY": rng.choice(["nonhispanic", "hispanic"], size, p=[.82, .18]),
            "STATE": rng.choice(["MA", "NY", "CA", "TX", "FL"], size),
            "ZIP": rng.integers(10000, 99999, size).astype(str),
            "synthetic_index_date": index_dates,
        }
    )


def select_base_patients(
    tables: dict[str, pd.DataFrame], size: int, seed: int, minimum_age: int, maximum_age: int
) -> pd.DataFrame:
    """Select eligible Synthea males or augment them with fallback rows."""
    if "patients" not in tables:
        LOGGER.warning("No patients.csv found; using reproducible Synthea-shaped demo input")
        return make_base_patients(size, seed, minimum_age, maximum_age)
    raw = tables["patients"].copy()
    gender = raw.get("GENDER", raw.get("gender", ""))
    raw = raw.loc[pd.Series(gender, index=raw.index).astype(str).str.upper().isin(["M", "MALE"])].copy()
    birth_col = "BIRTHDATE" if "BIRTHDATE" in raw else "birthdate"
    births = pd.to_datetime(raw[birth_col], errors="coerce")
    index_date = pd.Timestamp("2022-01-01")
    age = ((index_date - births).dt.days // 365).astype("Int64")
    raw = raw.loc[age.between(minimum_age, maximum_age)].copy()
    raw["synthetic_index_date"] = index_date
    if len(raw) >= size:
        return raw.sample(size, random_state=seed).reset_index(drop=True)
    LOGGER.warning("Only %d eligible raw rows; oversampling with replacement to %d", len(raw), size)
    if raw.empty:
        return make_base_patients(size, seed, minimum_age, maximum_age)
    return raw.sample(size, replace=True, random_state=seed).reset_index(drop=True)
