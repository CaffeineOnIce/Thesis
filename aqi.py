"""TEMPLATE - replace with the real AQI file.

Simplified Indian NAQI (CPCB breakpoints): PM2.5, PM10 and NO2 use a rolling 24 h mean, CO a rolling 8 h mean.
AQI = highest sub-index; the pollutant giving it is the dominant pollutant.

Contract the pipeline relies on:
    compute_aqi(filled) -> DataFrame with columns AQI, Category, Dominant (same index as filled)
    filled: DataFrame on a 15-min DatetimeIndex with no missing values, oldest rows first
"""
import numpy as np
import pandas as pd

BREAKPOINTS = {
    'PM2.5': [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200), (91, 120, 201, 300),
              (121, 250, 301, 400), (251, 380, 401, 500)],
    'PM10': [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200), (251, 350, 201, 300),
             (351, 430, 301, 400), (431, 510, 401, 500)],
    'NO2': [(0, 40, 0, 50), (41, 80, 51, 100), (81, 180, 101, 200), (181, 280, 201, 300),
            (281, 400, 301, 400), (401, 800, 401, 500)],
    'CO': [(0, 1.0, 0, 50), (1.1, 2.0, 51, 100), (2.1, 10, 101, 200), (10.1, 17, 201, 300),
           (17.1, 34, 301, 400), (34.1, 50, 401, 500)],
}
AVERAGING = {'PM2.5': '24h', 'PM10': '24h', 'NO2': '24h', 'CO': '8h'}
CATEGORIES = [(50, 'Good'), (100, 'Satisfactory'), (200, 'Moderate'), (300, 'Poor'),
              (400, 'Very Poor'), (500, 'Severe')]


def sub_index(value, breakpoints):
    if pd.isna(value):
        return np.nan
    for c_lo, c_hi, i_lo, i_hi in breakpoints:
        if value <= c_hi:
            value = max(value, c_lo)
            return i_lo + (i_hi - i_lo) * (value - c_lo) / (c_hi - c_lo)
    return 500.0


def category(aqi):
    for upper, name in CATEGORIES:
        if aqi <= upper:
            return name
    return 'Severe'


def compute_aqi(filled):
    subs = pd.DataFrame(index=filled.index)
    for p, window in AVERAGING.items():
        avg = filled[p].rolling(window).mean()
        subs[f'SI_{p}'] = avg.apply(lambda v: sub_index(v, BREAKPOINTS[p]))
    out = pd.DataFrame(index=filled.index)
    out['AQI'] = subs.max(axis=1).round().astype(int)
    out['Category'] = out['AQI'].apply(category)
    out['Dominant'] = subs.idxmax(axis=1).str.replace('SI_', '', regex=False)
    return out
