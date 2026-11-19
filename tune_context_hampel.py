import pandas as pd
import numpy as np
from pathlib import Path

from hampel.detectors import ContextAwareHampel
from sim.outliers import inject

DATA_PATH = "data/cpcb_15min_clean.parquet"
MASK_PATH = "data/observed_mask.parquet"
PROFILE_PATH = "data/seasonal_bands/knowledge_base.json"
OUTPUT_PATH = "results/context_hampel_tuning.csv"

TARGETS = ["pm25", "pm10", "no2", "co"]
WINDOWS = [12, 24, 48]

K_CONFIGS = [
    (3.5, 2.5, 2.0),
    (4.0, 3.0, 2.5),
    (3.0, 2.5, 2.0),
]

BUFFER_MODES = ["raw", "cleaned"]
SEED = 50


def calculate_metrics(y_true, y_pred):
    tp = int(np.sum(y_true & y_pred))
    fp = int(np.sum(~y_true & y_pred))
    fn = int(np.sum(y_true & ~y_pred))

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def main():
    print("Loading CPCB dataset...")

    df = pd.read_parquet(DATA_PATH)
    observed = pd.read_parquet(MASK_PATH)

    if not df.index.equals(observed.index):
        raise ValueError("Dataset and observed mask indexes do not match")

    year_mask = df.index.year == 2024

    df_2024 = df.loc[year_mask, TARGETS].copy()
    observed_2024 = observed.loc[year_mask, TARGETS].copy()

    print("2024 dataset shape:", df_2024.shape)

    injected_df, labels = inject(
        df_2024,
        observed_2024,
        seed=SEED
    )

    results = []

    total = len(BUFFER_MODES) * len(WINDOWS) * len(K_CONFIGS)
    current = 0

    for buffer_mode in BUFFER_MODES:
        for window in WINDOWS:
            for k_loose, k_strict, k_very in K_CONFIGS:
                current += 1

                print(
                    f"\n[{current}/{total}] "
                    f"Mode={buffer_mode}, Window={window}, "
                    f"K=({k_loose}, {k_strict}, {k_very})"
                )

                pollutant_metrics = []

                row = {
                    "buffer_mode": buffer_mode,
                    "window_size": window,
                    "k_loose": k_loose,
                    "k_strict": k_strict,
                    "k_very": k_very,
                }

                for pollutant in TARGETS:
                    detector = ContextAwareHampel(
                        pollutant=pollutant,
                        profile_path=PROFILE_PATH,
                        window_size=window,
                        k_loose=k_loose,
                        k_strict=k_strict,
                        k_very=k_very,
                        buffer_mode=buffer_mode,
                    )

                    _, flags = detector.detect(injected_df[pollutant])

                    label = labels[pollutant]
                    observed_points = observed_2024[pollutant].to_numpy()

                    target = label.isin(["spike", "burst"]).to_numpy()
                    clean = (label == "").to_numpy() & observed_points

                    valid = target | clean

                    y_true = target[valid]
                    y_pred = (flags.to_numpy() == 1)[valid]

                    metrics = calculate_metrics(y_true, y_pred)
                    pollutant_metrics.append(metrics)

                    row[f"{pollutant}_precision"] = metrics["precision"]
                    row[f"{pollutant}_recall"] = metrics["recall"]
                    row[f"{pollutant}_f1"] = metrics["f1"]

                    print(
                        f"{pollutant}: "
                        f"F1={metrics['f1']:.4f}, "
                        f"Precision={metrics['precision']:.4f}, "
                        f"Recall={metrics['recall']:.4f}"
                    )

                row["mean_precision"] = np.mean(
                    [m["precision"] for m in pollutant_metrics]
                )
                row["mean_recall"] = np.mean(
                    [m["recall"] for m in pollutant_metrics]
                )
                row["mean_f1"] = np.mean(
                    [m["f1"] for m in pollutant_metrics]
                )

                row["total_tp"] = sum(m["tp"] for m in pollutant_metrics)
                row["total_fp"] = sum(m["fp"] for m in pollutant_metrics)
                row["total_fn"] = sum(m["fn"] for m in pollutant_metrics)

                results.append(row)
                print("Mean F1:", round(row["mean_f1"], 4))

    results_df = pd.DataFrame(results).sort_values(
        "mean_f1",
        ascending=False
    )

    Path("results").mkdir(exist_ok=True)
    results_df.to_csv(OUTPUT_PATH, index=False)

    print("\nH2 TUNING COMPLETED")

    print(
        results_df[
            [
                "buffer_mode",
                "window_size",
                "k_loose",
                "k_strict",
                "k_very",
                "mean_precision",
                "mean_recall",
                "mean_f1",
            ]
        ].to_string(index=False)
    )

    best = results_df.iloc[0]

    print("\nBEST H2 CONFIGURATION")
    print("Buffer mode:", best["buffer_mode"])
    print("Window size:", int(best["window_size"]))
    print(
        "K values:",
        best["k_loose"],
        best["k_strict"],
        best["k_very"]
    )
    print("Mean F1:", round(best["mean_f1"], 4))
    print("\nSaved:", OUTPUT_PATH)


if __name__ == "__main__":
    main()
