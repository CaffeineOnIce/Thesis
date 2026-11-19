import numpy as np
import pandas as pd
from pathlib import Path

from hampel.detectors import (
    TraditionalHampel,
    ContextAwareHampel,
    RuleCheck,
)
from sim.outliers import inject

POLLUTANTS = ["pm25", "pm10", "no2", "co"]
SEEDS = range(5)
PROFILE_PATH = "data/seasonal_bands/knowledge_base.json"


def calculate_metrics(labels, predictions, clean_points):
    target = labels != ""

    tp = int((predictions & target).sum())
    fp = int((predictions & clean_points).sum())
    fn = int((~predictions & target).sum())

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )

    false_flag_rate = (
        float(predictions[clean_points].mean())
        if clean_points.any() else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_flag_rate": false_flag_rate,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def make_detector(name, pollutant):
    if name == "H1":
        return TraditionalHampel(
            window_size=12,
            k_static=3.5,
            buffer_mode="raw",
        )

    if name == "H2-raw":
        return ContextAwareHampel(
            pollutant=pollutant,
            profile_path=PROFILE_PATH,
            window_size=12,
            k_loose=4.0,
            k_strict=3.0,
            k_very=2.5,
            buffer_mode="raw",
        )

    if name == "H2-cleaned":
        return ContextAwareHampel(
            pollutant=pollutant,
            profile_path=PROFILE_PATH,
            window_size=12,
            k_loose=4.0,
            k_strict=3.0,
            k_very=2.5,
            buffer_mode="cleaned",
        )

    raise ValueError(f"Unknown detector: {name}")


def rule_flags(series, pollutant):
    rule = RuleCheck(pollutant)
    return pd.Series(
        [rule.step(value) for value in series],
        index=series.index,
        dtype=bool,
    )


def main():
    print("Loading 2025 CPCB dataset...")

    df = pd.read_parquet("data/cpcb_15min_clean.parquet")
    observed = pd.read_parquet("data/observed_mask.parquet")

    test = df.loc["2025", POLLUTANTS].copy()
    test_obs = observed.loc["2025", POLLUTANTS].copy()

    if not test.index.equals(test_obs.index):
        raise ValueError("2025 dataset and observed mask do not match")

    print("2025 dataset shape:", test.shape)

    detector_names = ["H1", "H2-raw", "H2-cleaned"]
    rows = []

    for seed in SEEDS:
        print(f"\nSeed {seed}")

        corrupted, labels = inject(
            test,
            test_obs,
            seed=seed,
        )

        for name in detector_names:
            print("  Detector:", name)

            for pollutant in POLLUTANTS:
                detector = make_detector(name, pollutant)

                _, flags = detector.detect(corrupted[pollutant])

                hampel_predictions = flags == 1
                rules = rule_flags(corrupted[pollutant], pollutant)

                label = labels[pollutant]
                clean_points = (label == "") & test_obs[pollutant]

                for use_rules in (False, True):
                    predictions = hampel_predictions.copy()

                    if use_rules:
                        predictions = predictions | rules

                    metrics = calculate_metrics(
                        label,
                        predictions,
                        clean_points,
                    )

                    detector_label = (
                        name + "+rules" if use_rules else name
                    )

                    row = {
                        "seed": seed,
                        "detector": detector_label,
                        "variable": pollutant,
                        **metrics,
                    }

                    for outlier_type in [
                        "spike",
                        "burst",
                        "stuck",
                        "drift",
                    ]:
                        selected = label == outlier_type

                        row[f"recall_{outlier_type}"] = (
                            float(predictions[selected].mean())
                            if selected.any() else np.nan
                        )

                    rows.append(row)

    results = pd.DataFrame(rows)

    Path("results").mkdir(exist_ok=True)
    results.to_csv("results/E2_detection.csv", index=False)

    print("\nE2 DETECTION COMPLETED")
    print("Saved: results/E2_detection.csv")

    summary = (
        results.groupby("detector")[
            ["precision", "recall", "f1", "false_flag_rate"]
        ]
        .mean()
        .round(4)
    )

    print("\nMean results across seeds and pollutants:")
    print(summary.to_string())


if __name__ == "__main__":
    main()
