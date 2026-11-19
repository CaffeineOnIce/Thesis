
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
