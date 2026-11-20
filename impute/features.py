"""Causal features. One function serves training (whole frame) and run time (history + one row),
so training and serving can never disagree."""
import numpy as np
import pandas as pd

VARS = ["pm25", "pm10", "no2", "co", "temp", "rh"]
GROUPS = {"PMS": ["pm25", "pm10"], "MQ135": ["no2"], "MQ7": ["co"], "DHT": ["temp", "rh"]}
MAX_AGE_H = 48.0
SEASON = {12: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3}

def time_features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    h = idx.hour + idx.minute / 60.0
    f = pd.DataFrame(index=idx)
    f["hour_sin"] = np.sin(2 * np.pi * h / 24)
    f["hour_cos"] = np.cos(2 * np.pi * h / 24)
    f["dow"] = idx.dayofweek
    s = idx.month.map(SEASON)
    for k in range(4):
        f[f"season_{k}"] = (np.asarray(s) == k).astype(float)
    return f

def make_features(obs: pd.DataFrame) -> pd.DataFrame:
    """obs: 15-min frame (IST index) of VARS, NaN where not observed (incl. simulated gaps).
    Row t uses: values observed at t ('cur_'), and only values before t for history."""
    f = time_features(obs.index)
    for v in VARS:
        s = obs[v]
        f[f"cur_{v}"] = s
        prev = s.shift(1)
        last = prev.ffill()
        t_obs = pd.Series(np.where(prev.notna(), obs.index.values, np.datetime64("NaT")),
                          index=obs.index).ffill()
        age = (obs.index.to_series() - t_obs).dt.total_seconds() / 3600.0
        stale = age.isna() | (age > MAX_AGE_H)
        f[f"last_{v}"] = last.where(~stale)
        f[f"age_{v}"] = age.where(~stale, MAX_AGE_H)
        f[f"med1h_{v}"] = s.rolling("1h", closed="left").median()
        f[f"med3h_{v}"] = s.rolling("3h", closed="left").median()
    return f

def features_for_record(history: pd.DataFrame, record: pd.Series) -> pd.DataFrame:
    """Run time: history = previous records (>= 49 h, observed values only), record = current row."""
    frame = pd.concat([history, record.to_frame().T.astype(float)])
    return make_features(frame).iloc[[-1]]
