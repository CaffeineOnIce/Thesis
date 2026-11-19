"""TEMPLATE - replace with the real outlier detection file.

Contract the pipeline relies on:
    detect_outliers(frame) -> frame
    in : DataFrame on a 15-min DatetimeIndex, columns PM2.5, PM10, CO, NO2, Temperature, Humidity (NaN = missing)
    out: same index and columns, with every value judged an outlier set to NaN (the imputation then fills it)
"""
import numpy as np

LIMITS = {
    'PM2.5': (0, 1000),
    'PM10': (0, 1000),
    'CO': (0, 50),
    'NO2': (0, 1000),
    'Temperature': (-10, 60),
    'Humidity': (0, 100),
}


def detect_outliers(frame):
    out = frame.copy()
    for col, (lo, hi) in LIMITS.items():
        if col in out:
            bad = (out[col] < lo) | (out[col] > hi)
            out.loc[bad, col] = np.nan
    return out
