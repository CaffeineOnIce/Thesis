import numpy as np
import pandas as pd

from sim.gaps import (
    VARS,
    GROUPS,
    STEPS,
    PATTERNS,
    make_mask,
)


print("Test 1: Synthetic dataset")

n = 9600

idx = pd.date_range(
    "2025-01-01",
    periods=n,
    freq="15min",
)

rng = np.random.default_rng(42)

df = pd.DataFrame(
    rng.uniform(10, 100, (n, len(VARS))),
    index=idx,
    columns=VARS,
)

observed = pd.DataFrame(
    rng.random((n, len(VARS))) > 0.05,
    index=idx,
    columns=VARS,
)

print("Dataset shape:", df.shape)
print("Observed mask shape:", observed.shape)


print("\nTest 2: Pattern count")

assert len(PATTERNS) == 16

print("Patterns available:", len(PATTERNS))
print("PASS: 16 benchmark patterns available")


print("\nTest 3: G1 random missing values")

for pattern, expected in [
    ("G1_10", 0.10),
    ("G1_20", 0.20),
    ("G1_30", 0.30),
]:
    mask = make_mask(df, observed, pattern, seed=42)

    rates = mask.sum() / observed.sum()

    print(pattern, rates.round(3).to_dict())

    assert np.all(
        np.abs(rates.values - expected) < 0.04
    )

print("PASS: G1 shares approximately match targets")


print("\nTest 4: All G2 sensor failure patterns")

for group, variables in GROUPS.items():

    for duration, length in STEPS.items():

        pattern = f"G2_{group}_{duration}"

        mask = make_mask(df, observed, pattern, seed=42)

        non_group_vars = [
            v for v in VARS if v not in variables
        ]

        assert not mask[non_group_vars].any().any()

        rates = (
            mask[variables].sum()
            / observed[variables].sum()
        )

        assert np.all(
            np.abs(rates.values - 0.10) < 0.04
        )

        selected_rows = mask[variables].any(axis=1)

        if selected_rows.any():
            np.testing.assert_array_equal(
                mask.loc[selected_rows, variables].values,
                observed.loc[selected_rows, variables].values,
            )

        print(
            pattern,
            rates.round(3).to_dict(),
            "PASS"
        )

print("PASS: All 12 G2 patterns validated")


print("\nTest 5: G3 packet loss")

mask = make_mask(df, observed, "G3_10", seed=42)

selected_rows = mask.any(axis=1)

assert selected_rows.any()

np.testing.assert_array_equal(
    mask.loc[selected_rows, VARS].values,
    observed.loc[selected_rows, VARS].values,
)

print("G3 hidden share:", round(mask.mean().mean(), 3))
print("PASS: Packet loss affects complete records")


print("\nTest 6: TRAIN_MIX")

mask = make_mask(df, observed, "TRAIN_MIX", seed=42)

assert mask.any().any()
assert not (mask & ~observed).any().any()

print("TRAIN_MIX hidden share:", round(mask.mean().mean(), 3))
print("PASS: Training combination generated")


print("\nTest 7: Reproducibility")

mask1 = make_mask(df, observed, "G1_20", seed=100)
mask2 = make_mask(df, observed, "G1_20", seed=100)

assert mask1.equals(mask2)

print("PASS: Same seed generates identical masks")


print("\nTest 8: Originally missing values")

for pattern in PATTERNS:

    mask = make_mask(df, observed, pattern, seed=42)

    assert not (mask & ~observed).any().any()

print("PASS: No originally missing values hidden again")


print("\nTest 9: Invalid pattern")

try:
    make_mask(df, observed, "INVALID", seed=42)
except ValueError:
    print("PASS: Invalid pattern rejected")
else:
    raise AssertionError("Invalid pattern was not rejected")


print("\nAll gap simulator tests passed!")