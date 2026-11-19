
import pandas as pd

from sim.outliers import inject
from sim.gaps import make_mask
from hampel.detectors import ContextAwareHampel
from external_imputation.imputation import load_imputer

POLLUTANTS = ["pm25", "pm10", "no2", "co"]

COLUMN_MAP = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "no2": "NO2",
    "co": "CO",
    "temp": "Temperature",
    "rh": "Humidity",
}

SEEDS = range(5)


def load_data():
    df = pd.read_parquet("data/cpcb_15min_clean.parquet")
    observed = pd.read_parquet("data/observed_mask.parquet")

    test = df.loc["2025"].copy()
    test_obs = observed.loc["2025"].copy()

    warm = df.loc[
        test.index[0] - pd.Timedelta("3D"):
        test.index[0] - pd.Timedelta("15min")
    ].copy()

    return test, test_obs, warm


def fill_missing(frame, warm, imputer):
    combined = pd.concat([warm, frame]).rename(columns=COLUMN_MAP)

    predictions = imputer(combined)
    predictions = predictions.loc[frame.index]

    predictions = predictions.rename(
        columns={v: k for k, v in COLUMN_MAP.items()}
    )

    return frame.fillna(predictions)


def strategy_a(inp, warm, imputer):
    cleaned = inp.copy()

    for pollutant in POLLUTANTS:
        detector = ContextAwareHampel(pollutant)
        _, flags = detector.detect(cleaned[pollutant])

        cleaned.loc[flags == 1, pollutant] = float("nan")

    return fill_missing(cleaned, warm, imputer)


def strategy_b(inp, warm, imputer):
    filled = fill_missing(inp, warm, imputer)
    cleaned = filled.copy()

    for pollutant in POLLUTANTS:
        detector = ContextAwareHampel(pollutant)
        cleaned[pollutant] = detector.detect(filled[pollutant])[0]

    return cleaned


def strategy_c(inp, warm, imputer):
    cleaned = inp.copy()

    for pollutant in POLLUTANTS:
        detector = ContextAwareHampel(pollutant)
        cleaned[pollutant] = detector.detect(cleaned[pollutant])[0]

    return fill_missing(cleaned, warm, imputer)


def main():
    test, test_obs, warm = load_data()

    # Load the Stacking Ensemble model once
    imputer = load_imputer("stacking")

    rows = []

    for seed in SEEDS:
        print(f"\nRunning seed {seed}...")

        # Inject artificial outliers
        corrupted, labels = inject(test, test_obs, seed)

        # Introduce 10% random missing gaps
        hide = make_mask(corrupted, test_obs, "G1_10", seed)
        inp = corrupted.mask(hide)

        # Execute the three strategies
        strategy_results = [
            ("hampel_then_impute", strategy_a(inp, warm, imputer)),
            ("impute_then_hampel", strategy_b(inp, warm, imputer)),
            ("hampel_median_fill", strategy_c(inp, warm, imputer)),
        ]

        for pollutant in POLLUTANTS:
            # Original injected outlier points that were not hidden
            out_pts = (labels[pollutant] != "") & ~hide[pollutant]

            # Artificial gaps at originally observed positions
            gap_pts = hide[pollutant] & test_obs[pollutant]

            for variant, output in strategy_results:
                mae_out = (
                    (output.loc[out_pts, pollutant]
                     - test.loc[out_pts, pollutant]).abs().mean()
                    if out_pts.any() else float("nan")
                )

                mae_gap = (
                    (output.loc[gap_pts, pollutant]
                     - test.loc[gap_pts, pollutant]).abs().mean()
                    if gap_pts.any() else float("nan")
                )

                rows.append({
                    "seed": seed,
                    "variant": variant,
                    "variable": pollutant,
                    "mae_outlier_points": mae_out,
                    "mae_gap_points": mae_gap,
                })

        print(f"Seed {seed} completed.")

    # Save final ablation results
    results = pd.DataFrame(rows)
    results.to_csv("results/E2_ablation.csv", index=False)

    print("\nE2 ablation experiment completed.")
    print("Total result rows:", len(results))
    print("Saved: results/E2_ablation.csv")
    print(results.groupby("variant")[
        ["mae_outlier_points", "mae_gap_points"]
    ].mean())


if __name__ == "__main__":
    main()

