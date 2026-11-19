import pandas as pd
from pathlib import Path

from hampel.detectors import TraditionalHampel, ContextAwareHampel

POLLUTANTS = ["pm25", "pm10", "no2", "co"]
PROFILE_PATH = "data/seasonal_bands/knowledge_base.json"


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

    return ContextAwareHampel(
        pollutant=pollutant,
        profile_path=PROFILE_PATH,
        window_size=12,
        k_loose=4.0,
        k_strict=3.0,
        k_very=2.5,
        buffer_mode="cleaned",
    )


def main():
    print("Loading original 2025 CPCB data...")

    df = pd.read_parquet(
        "data/cpcb_15min_clean.parquet"
    )
    observed = pd.read_parquet(
        "data/observed_mask.parquet"
    )

    test = df.loc["2025", POLLUTANTS]
    test_obs = observed.loc["2025", POLLUTANTS]

    daily_pm25 = test["pm25"].resample("D").mean()
    threshold = daily_pm25.quantile(0.95)

    top_days = daily_pm25[daily_pm25 >= threshold].index
    high_day_mask = test.index.normalize().isin(top_days)

    print("Daily PM2.5 95th percentile:", round(threshold, 3))
    print("High-pollution days:", len(top_days))

    rows = []

    for name in ["H1", "H2-raw", "H2-cleaned"]:
        for pollutant in POLLUTANTS:
            detector = make_detector(name, pollutant)
            _, flags = detector.detect(test[pollutant])

            valid = test_obs[pollutant]

            high_valid = high_day_mask & valid.to_numpy()
            other_valid = (~high_day_mask) & valid.to_numpy()

            high_rate = (
                float((flags.to_numpy()[high_valid] == 1).mean())
                if high_valid.any() else float("nan")
            )

            other_rate = (
                float((flags.to_numpy()[other_valid] == 1).mean())
                if other_valid.any() else float("nan")
            )

            rows.append({
                "detector": name,
                "variable": pollutant,
                "flag_rate_high_days": high_rate,
                "flag_rate_other_days": other_rate,
                "high_day_threshold_pm25": threshold,
                "number_high_days": len(top_days),
            })

            print(
                f"{name} | {pollutant} | "
                f"High days: {high_rate:.4f} | "
                f"Other days: {other_rate:.4f}"
            )

    results = pd.DataFrame(rows)

    Path("results").mkdir(exist_ok=True)
    results.to_csv("results/E2_highdays.csv", index=False)

    print("\nE2 HIGH-DAYS EVALUATION COMPLETED")
    print("Saved: results/E2_highdays.csv")


if __name__ == "__main__":
    main()
