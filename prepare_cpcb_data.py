"""Prepare the uploaded 2023-2025 CPCB CSV files for the PolluSense guide.

Run from the PolluSense project root:
    python prepare_cpcb_data.py

Outputs:
    data/cpcb_15min_clean.parquet
    data/observed_mask.parquet

No imputation, interpolation, resampling, or outlier removal is performed.
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
OUTPUT_DIR = ROOT / "data"

YEAR_FILES = {
    2023: RAW_DIR / "2023.csv",
    2024: RAW_DIR / "2024.csv",
    2025: RAW_DIR / "2025.csv",
}

COLUMN_MAP = {
    "PM2.5 (µg/m³)": "pm25",
    "PM10 (µg/m³)": "pm10",
    "NO2 (µg/m³)": "no2",
    "CO (mg/m³)": "co",
    "AT (°C)": "temp",
    "RH (%)": "rh",
}
VARS = list(COLUMN_MAP.values())


def expected_year_index(year: int) -> pd.DatetimeIndex:
    days = 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365
    return pd.date_range(
        f"{year}-01-01 00:00:00",
        periods=days * 96,
        freq="15min",
        name="Timestamp",
    )


def load_year(year: int, path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing source CSV: {path}")

    raw = pd.read_csv(path)
    required = ["Timestamp", *COLUMN_MAP.keys()]
    missing_columns = [c for c in required if c not in raw.columns]
    if missing_columns:
        raise ValueError(f"{path.name} is missing columns: {missing_columns}")

    timestamps = pd.to_datetime(raw["Timestamp"], errors="raise")
    if timestamps.dt.tz is not None:
        raise ValueError(
            f"{path.name} contains timezone-aware timestamps. Confirm the intended "
            "timezone before converting; the research guide expects a timezone-naive IST index."
        )

    if timestamps.duplicated().any():
        examples = timestamps[timestamps.duplicated()].head().tolist()
        raise ValueError(f"Duplicate timestamps in {path.name}: {examples}")

    if not timestamps.is_monotonic_increasing:
        raise ValueError(f"Timestamps are not sorted in {path.name}")

    expected = expected_year_index(year)
    actual = pd.DatetimeIndex(timestamps, name="Timestamp")
    missing_ts = expected.difference(actual)
    extra_ts = actual.difference(expected)
    if len(missing_ts) or len(extra_ts):
        raise ValueError(
            f"Timestamp grid mismatch in {path.name}: "
            f"{len(missing_ts)} missing timestamps, {len(extra_ts)} unexpected timestamps."
        )

    frame = raw[list(COLUMN_MAP)].copy()
    frame.columns = VARS
    for col in VARS:
        frame[col] = pd.to_numeric(frame[col], errors="raise")

    frame.index = actual
    frame.index.name = "Timestamp"
    return frame


def main() -> None:
    frames = [load_year(year, path) for year, path in YEAR_FILES.items()]
    clean = pd.concat(frames, axis=0).sort_index()
    clean.index.name = "Timestamp"

    if clean.index.has_duplicates:
        raise ValueError("Duplicate timestamps found after combining years")

    expected_all = pd.date_range(
        "2023-01-01 00:00:00",
        "2026-01-01 00:00:00",
        freq="15min",
        inclusive="left",
        name="Timestamp",
    )
    if not clean.index.equals(expected_all):
        raise ValueError("Combined dataset is not a continuous 15-minute 2023-2025 grid")

    # True means the value was present in the supplied source CSV.
    # Missing measurements remain NaN in clean; nothing is imputed here.
    observed = clean.notna().astype(bool)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    clean_path = OUTPUT_DIR / "cpcb_15min_clean.parquet"
    observed_path = OUTPUT_DIR / "observed_mask.parquet"

    try:
        clean.to_parquet(clean_path, engine="pyarrow", index=True)
        observed.to_parquet(observed_path, engine="pyarrow", index=True)
    except ImportError as exc:
        raise SystemExit(
            "Parquet engine 'pyarrow' is not installed in the active Python environment.\n"
            "Activate ~/venv-ps, then run: python -m pip install pyarrow\n"
            "Then rerun: python prepare_cpcb_data.py"
        ) from exc

    # Read back both outputs and verify alignment, types, and preservation of NaNs.
    clean_check = pd.read_parquet(clean_path)
    observed_check = pd.read_parquet(observed_path)
    if not clean_check.index.equals(observed_check.index):
        raise AssertionError("Output indexes do not match")
    if list(clean_check.columns) != VARS or list(observed_check.columns) != VARS:
        raise AssertionError("Output columns do not match the six-variable contract")
    if not all(pd.api.types.is_bool_dtype(observed_check[c]) for c in VARS):
        raise AssertionError("Observed-mask columns must be boolean")
    if not observed_check.equals(clean_check.notna()):
        raise AssertionError("Observed mask does not match source non-missing values")

    print("CPCB data preparation successful")
    print(f"Rows: {len(clean_check):,}")
    print(f"Columns: {list(clean_check.columns)}")
    print(f"Start: {clean_check.index.min()}")
    print(f"End: {clean_check.index.max()}")
    print("Sampling: 15 minutes")
    print("Timezone: naive timestamps (confirm they represent IST/window-end as required)")
    print("\nMissing-value percentage by year:")
    for year in (2023, 2024, 2025):
        subset = clean_check.loc[str(year)]
        print(f"{year}: {subset.isna().mean().mul(100).round(3).to_dict()}")
    print(f"\nClean data: {clean_path}")
    print(f"Observed mask: {observed_path}")
    print("\nNo imputation, interpolation, resampling, or outlier removal was performed.")


if __name__ == "__main__":
    main()
