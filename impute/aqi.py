"""CPCB-style AQI from PM2.5, PM10, NO2 (24 h running mean) and CO (8 h running mean)."""
import numpy as np
import pandas as pd

# concentration breakpoints (CPCB NAQI) and matching index breakpoints
BP = {"pm25": [0, 30, 60, 90, 120, 250], "pm10": [0, 50, 100, 250, 350, 430],
      "no2": [0, 40, 80, 180, 280, 400], "co": [0, 1.0, 2.0, 10, 17, 34]}
IDX = [0, 50, 100, 200, 300, 400]
CATS = ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
WINDOW = {"pm25": ("24h", 64), "pm10": ("24h", 64), "no2": ("24h", 64), "co": ("8h", 24)}  # min 16 h / 6 h of 15-min data

def sub_index(c, var):
    if c is None or np.isnan(c):
        return np.nan
    b = BP[var]
    for k in range(1, len(b)):
        if c <= b[k]:
            return IDX[k-1] + (c - b[k-1]) * (IDX[k] - IDX[k-1]) / (b[k] - b[k-1])
    # above the Severe threshold: ASSUMPTION, slope of 100 index points per b[-1] units, capped at 500
    return min(500.0, 400 + (c - b[-1]) * 100 / b[-1])

def category(aqi):
    if np.isnan(aqi):
        return None
    return CATS[min(5, int(np.searchsorted(IDX[1:], aqi, side="left")))]

def aqi_frame(df: pd.DataFrame) -> pd.DataFrame:
    """df: 15-min frame with pm25, pm10, no2, co. Returns running sub-indices, AQI and category."""
    out = pd.DataFrame(index=df.index)
    for v, (win, need) in WINDOW.items():
        avg = df[v].rolling(win, min_periods=need).mean()
        out[f"si_{v}"] = [sub_index(x, v) for x in avg]
    si = out[[f"si_{v}" for v in WINDOW]]
    n_ok = si.notna().sum(axis=1)
    pm_ok = si[["si_pm25", "si_pm10"]].notna().any(axis=1)
    out["aqi"] = si.max(axis=1).where((n_ok >= 3) & pm_ok)
    out["category"] = [category(a) for a in out["aqi"]]
    return out
