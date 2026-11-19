"""Gap simulator for sensor failures and communication loss."""

import os

import numpy as np
import pandas as pd

VARS = ["pm25", "pm10", "no2", "co", "temp", "rh"]

GROUPS = {
    "PMS": ["pm25", "pm10"],
    "MQ135": ["no2"],
    "MQ7": ["co"],
    "DHT": ["temp", "rh"],
}

STEPS = {
    "1h": 4,
    "6h": 24,
    "24h": 96,
}

COVER = 0.10

PATTERNS = (
    ["G1_10", "G1_20", "G1_30"]
    + [
        f"G2_{group}_{duration}"
        for group in GROUPS
        for duration in STEPS
    ]
    + ["G3_10"]
)


def _validate_inputs(df, observed):
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    if not isinstance(observed, pd.DataFrame):
        raise TypeError("observed must be a pandas DataFrame")

    missing_df = set(VARS) - set(df.columns)
    missing_obs = set(VARS) - set(observed.columns)

    if missing_df:
        raise ValueError(f"Missing columns in df: {sorted(missing_df)}")

    if missing_obs:
        raise ValueError(
            f"Missing columns in observed: {sorted(missing_obs)}"
        )

    if not df.index.equals(observed.index):
        raise ValueError("df and observed must have identical indexes")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("DataFrame index must be a DatetimeIndex")

    if not df.index.is_monotonic_increasing:
        raise ValueError("DataFrame index must be sorted")

    if df.index.has_duplicates:
        raise ValueError("DataFrame index must not contain duplicates")

    if df.index.tz is not None:
        raise ValueError("Expected timezone-naive IST index")

    if len(df) == 0:
        raise ValueError("Input DataFrames must not be empty")

    if len(df) > 1:
        differences = df.index.to_series().diff().dropna()

        if not (differences == pd.Timedelta("15min")).all():
            raise ValueError("Expected a regular 15-minute time series")

    for col in VARS:
        if not pd.api.types.is_bool_dtype(observed[col]):
            raise TypeError(
                f"observed[{col}] must contain boolean values"
            )


def _g1(df, frac, rng):
    values = rng.random((len(df), len(VARS))) < frac

    return pd.DataFrame(
        values,
        index=df.index,
        columns=VARS,
    )


def _g2(df, group, length, rng):
    if group not in GROUPS:
        raise ValueError(f"Unknown sensor group: {group}")

    n = len(df)

    if n < length:
        raise ValueError(
            f"At least {length} observations are required"
        )

    slots = n // length
    k = max(1, int(COVER * n / length))

    chosen = rng.choice(
        slots,
        size=min(k, slots),
        replace=False,
    )

    shift = int(rng.integers(0, length))

    hide_rows = np.zeros(n, dtype=bool)

    for s in chosen:
        start = s * length + shift
        hide_rows[start:start + length] = True

    mask = pd.DataFrame(
        False,
        index=df.index,
        columns=VARS,
    )

    for variable in GROUPS[group]:
        mask[variable] = hide_rows

    return mask


def _g3(df, frac, rng):
    rows = rng.random(len(df)) < frac

    return pd.DataFrame(
        np.repeat(rows[:, None], len(VARS), axis=1),
        index=df.index,
        columns=VARS,
    )


def make_mask(df, observed, pattern, seed):
    """
    Generate a boolean missing-value mask.

    True means hide the observation.
    False means retain the observation.

    Only originally observed values can be hidden.
    """

    _validate_inputs(df, observed)

    rng = np.random.default_rng(seed)

    if pattern in ("G1_10", "G1_20", "G1_30"):
        frac = int(pattern.split("_")[1]) / 100
        mask = _g1(df, frac, rng)

    elif pattern.startswith("G2_"):
        parts = pattern.split("_")

        if len(parts) != 3:
            raise ValueError(f"Invalid G2 pattern: {pattern}")

        _, group, duration = parts

        if duration not in STEPS:
            raise ValueError(f"Invalid G2 duration: {duration}")

        mask = _g2(df, group, STEPS[duration], rng)

    elif pattern == "G3_10":
        mask = _g3(df, 0.10, rng)

    elif pattern == "TRAIN_MIX":
        mask = _g1(df, 0.20, rng) | _g3(df, 0.10, rng)

        for group in GROUPS:
            mask |= _g2(df, group, STEPS["6h"], rng)

    else:
        raise ValueError(f"Unknown gap pattern: {pattern}")

    return mask & observed[VARS]


def generate_2025_masks():
    """Generate 80 benchmark masks from the real 2025 CPCB dataset."""

    clean_path = "data/cpcb_15min_clean.parquet"
    observed_path = "data/observed_mask.parquet"

    if not os.path.exists(clean_path):
        raise FileNotFoundError(f"Dataset not found: {clean_path}")

    if not os.path.exists(observed_path):
        raise FileNotFoundError(
            f"Observed mask not found: {observed_path}"
        )

    df = pd.read_parquet(clean_path).loc["2025"]
    observed = pd.read_parquet(observed_path).loc["2025"]

    os.makedirs("masks", exist_ok=True)

    for pattern in PATTERNS:
        for seed in range(5):
            mask = make_mask(df, observed, pattern, seed)

            output = f"masks/{pattern}_s{seed}.parquet"
            mask.to_parquet(output)

            print(
                pattern,
                seed,
                mask.mean().round(3).to_dict(),
            )


if __name__ == "__main__":
    generate_2025_masks()