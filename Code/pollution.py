"""
Station-agnostic PM2.5 forecasting for one city (Kolkata: Ballygunge, Jadavpur, ...).

- Global River model: learns from every station.  Local River model: one per station.
- A UCB bandit per station picks which one (global/local) to trust for the next hour.
- Rolling windows (24 h, 7 days, 30 days) + same-hour-yesterday / last-week lags + day-of-year
  cycle let the models follow seasonal swings (winter smog, monsoon washout) as the stream runs.
- Works on history (stations/<Station>/<year>.csv) and on the live data.gov.in feed.
- Live mode is a continuous stream: it checks the API once every hour, learns from each new
  reading and forecasts the next hour, saving the engine after every check.

    python pollution.py history     # replay all yearly files, save engine + error log
    python pollution.py live        # stream forever: check API hourly, keep learning
"""
import io
import math
import pickle
import re
import sys
import time
from collections import deque
from pathlib import Path

import pandas as pd
import requests
from river import bandit, compose, forest, preprocessing, stats

DATA_DIR = Path("stations")                           # stations/Jadavpur/*.csv, stations/Ballygunge/*.csv
STATE_PATH = Path("artifacts/pollution_engine.pkl")
LOG_PATH = Path("artifacts/pollution_log.csv")
FEATURES = ["pm25", "pm10", "no2", "so2", "co", "o3", "nh3"]   # only pollutants the live feed also sends
REWARD_SCALE = 10.0                                             # reward = exp(-|error| / REWARD_SCALE)

API_URL = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
API_KEY = "579b464db66ec23bdd0000017db212e92c76426c51124c7fc0555235"
LIVE_STATIONS = {"Jadavpur": "Jadavpur, Kolkata - WBPCB",      # folder name -> station name in the API
                 "Ballygunge": "Ballygunge, Kolkata - WBPCB"}
POLL_MINUTES = 60                                               # check for new data once an hour

WINDOW_HOURS = 30 * 24                                          # longest rolling window kept per station
ROLLING = {"24h": 24, "7d": 7 * 24, "30d": 30 * 24}             # rolling-mean windows used as features

ARMS = ["global", "local"]
ONE_HOUR = pd.Timedelta(hours=1)


# ------------------------------------------------------------------ history data
COLUMNS = {"pm2.5": "pm25", "pm10": "pm10", "no2": "no2", "so2": "so2",
           "co": "co", "ozone": "o3", "nh3": "nh3"}


def load_station(folder: Path) -> pd.DataFrame:
    """All yearly CSVs of one station -> hourly rows with FEATURES columns."""
    frames = []
    for f in sorted(folder.glob("*.csv")):
        df = pd.read_csv(f, na_values=["NA", "None"])
        df.columns = [re.sub(r"\(.*?\)", "", c).strip().lower() for c in df.columns]   # "PM2.5 (µg/m³)" -> "pm2.5"
        df = df.rename(columns=COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        frames.append(df.dropna(subset=["timestamp"]).set_index("timestamp")[[c for c in FEATURES if c in df]])
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated()].apply(pd.to_numeric, errors="coerce").resample("1h").mean()
    df["station"] = folder.name
    return df.reset_index()


def load_city() -> pd.DataFrame:
    frames = [load_station(p) for p in sorted(DATA_DIR.iterdir()) if p.is_dir()]
    return pd.concat(frames, ignore_index=True).sort_values(["timestamp", "station"], kind="stable")


# ------------------------------------------------------------------ engine
def new_model():
    return compose.Pipeline(preprocessing.StandardScaler(), forest.ARFRegressor(n_models=10, seed=42))


def new_policy():
    return bandit.UCB(delta=0.5, reward_obj=stats.EWMean(fading_factor=0.05), burn_in=24, seed=42)


def rolling_mean(h, n):
    """Mean of the last n hours, ignoring missing hours; None if fewer than half are present."""
    vals = [v for v in h[-n:] if not math.isnan(v)]
    return sum(vals) / len(vals) if len(vals) >= n // 2 else None


def make_features(ts, row, hist):
    """hist = last WINDOW_HOURS hourly PM2.5 values, current value last. None if recent values are missing."""
    h = list(hist)
    if len(h) < 24 or any(math.isnan(v) for v in h[-3:]):
        return None
    doy = ts.dayofyear
    x = {"y_t": h[-1], "y_t-1": h[-2], "y_t-2": h[-3],
         "hour_sin": math.sin(2 * math.pi * ts.hour / 24), "hour_cos": math.cos(2 * math.pi * ts.hour / 24),
         "dow_sin": math.sin(2 * math.pi * ts.dayofweek / 7), "dow_cos": math.cos(2 * math.pi * ts.dayofweek / 7),
         "doy_sin": math.sin(2 * math.pi * doy / 365.25), "doy_cos": math.cos(2 * math.pi * doy / 365.25)}

    # rolling windows: short-term level (24 h), weekly level (7 d), seasonal level (30 d)
    for name, n in ROLLING.items():
        m = rolling_mean(h, n)
        if m is not None:
            x[f"mean_{name}"] = m
    if "mean_24h" in x and "mean_30d" in x:
        x["anomaly_vs_30d"] = x["mean_24h"] - x["mean_30d"]   # today vs the season's normal

    # seasonal lags for the forecast hour (t+1): same hour yesterday, same hour last week
    for name, back in {"y_lag24": 24, "y_lag168": 168}.items():
        if len(h) >= back and not math.isnan(h[-back]):
            x[name] = h[-back]

    x.update({k: float(v) for k, v in row.items() if k != "pm25" and v == v})   # co-pollutants; v == v drops NaN
    return x


def clip(v):
    return 0.0 if v is None or not math.isfinite(v) else min(max(v, 0.0), 1000.0)


class Engine:
    def __init__(self):
        self.global_model = new_model()
        self.local, self.policy, self.hist, self.last_ts = {}, {}, {}, {}
        self.pending = {}     # (station, target_time) -> forecast waiting for its true value
        self.latest = {}      # station -> last forecast (used for the LLM context)

    def update(self, ts, station, row):
        """Feed one hourly observation; returns an error record when an old forecast gets its true value."""
        ts = pd.Timestamp(ts)
        if station not in self.local:
            self.local[station], self.policy[station] = new_model(), new_policy()
            self.hist[station] = deque(maxlen=WINDOW_HOURS)
        y = float(row.get("pm25", float("nan")))
        record = None

        # 1) truth for the forecast made one hour ago -> reward the chosen arm, train both models
        p = self.pending.pop((station, ts), None)
        if p and y == y:
            arm = p["arm"]
            self.policy[station].update(arm, math.exp(-abs(y - p["preds"][arm]) / REWARD_SCALE))
            self.global_model.learn_one(p["x"], y)
            self.local[station].learn_one(p["x"], y)
            record = {"timestamp": ts, "station": station, "y_true": y, "arm": arm,
                      "pred_global": p["preds"]["global"], "pred_local": p["preds"]["local"],
                      "pred_bandit": p["preds"][arm], "pred_persistence": p["y_then"]}

        # 2) mark missing hours (outages, or the jump from history to live) so stale values aren't used as lags
        if station in self.last_ts:
            gap = int((ts - self.last_ts[station]) / ONE_HOUR) - 1
            self.hist[station].extend([float("nan")] * min(max(gap, 0), WINDOW_HOURS))
        self.last_ts[station] = ts
        self.hist[station].append(y)

        # 3) forecast the next hour
        x = make_features(ts, row, self.hist[station])
        if x is not None:
            preds = {"global": clip(self.global_model.predict_one(x)),
                     "local": clip(self.local[station].predict_one(x))}
            arm = self.policy[station].pull(ARMS)
            self.pending[(station, ts + ONE_HOUR)] = {"x": x, "preds": preds, "arm": arm, "y_then": y}
            self.latest[station] = {"observed": y, "predicted": preds[arm], "for": ts + ONE_HOUR, "arm": arm}
        return record

    def run(self, df):
        records = [self.update(r["timestamp"], r["station"], {k: r[k] for k in FEATURES if k in r})
                   for r in df.to_dict("records")]
        return pd.DataFrame([r for r in records if r])

    def context(self, station):
        s = self.latest[station]
        cat = pm25_category(s["predicted"])
        return {"station": station, "observed_pm25": round(s["observed"], 1), "predicted_pm25": round(s["predicted"], 1),
                "forecast_for": str(s["for"]), "category": cat, "health_note": HEALTH_NOTE[cat]}

    def save(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_PATH, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load():
        with open(STATE_PATH, "rb") as f:
            return pickle.load(f)


def summarize(log):
    """MAE per station for each forecaster + how often the bandit picked the local model."""
    out = log.groupby("station").apply(lambda g: pd.Series(
        {**{f"MAE_{m}": (g["y_true"] - g[f"pred_{m}"]).abs().mean() for m in ["global", "local", "bandit", "persistence"]},
         "share_local": (g["arm"] == "local").mean(), "n": len(g)}))
    return out.round(2)


# ------------------------------------------------------------------ CPCB categories
PM25_BANDS = [(30, "Good"), (60, "Satisfactory"), (90, "Moderate"), (120, "Poor"), (250, "Very Poor"), (math.inf, "Severe")]
HEALTH_NOTE = {
    "Good": "Minimal impact.",
    "Satisfactory": "May cause minor breathing discomfort in sensitive people.",
    "Moderate": "May cause breathing discomfort in people with lung disease such as COPD or asthma, and heart disease.",
    "Poor": "May cause breathing discomfort to most people on prolonged exposure.",
    "Very Poor": "May cause respiratory illness on prolonged exposure.",
    "Severe": "Affects healthy people and seriously affects people with existing lung or heart disease.",
}


def pm25_category(v):
    return next(name for upper, name in PM25_BANDS if v <= upper)


def scenario_context(station, pm25_now, pm25_pred=None):
    """Hand-set pollution context for controlled test questions (clean day vs severe day)."""
    pred = pm25_now if pm25_pred is None else pm25_pred
    cat = pm25_category(pred)
    return {"station": station, "observed_pm25": pm25_now, "predicted_pm25": pred,
            "forecast_for": "scenario", "category": cat, "health_note": HEALTH_NOTE[cat]}


# ------------------------------------------------------------------ live feed
# The API sends AQI sub-indices, not concentrations (its PM10 can be lower than PM2.5).
# Convert back with the CPCB breakpoints: index bands -> concentration bands (CO in mg/m³, rest µg/m³).
API_NAMES = {"PM2.5": "pm25", "PM10": "pm10", "NO2": "no2", "SO2": "so2", "CO": "co", "OZONE": "o3", "NH3": "nh3"}
INDEX_BANDS = [(0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500)]
CONC_BANDS = {
    "pm10": [(0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (431, 510)],
    "pm25": [(0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (251, 380)],
    "no2": [(0, 40), (41, 80), (81, 180), (181, 280), (281, 400), (401, 520)],
    "so2": [(0, 40), (41, 80), (81, 380), (381, 800), (801, 1600), (1601, 2400)],
    "co": [(0, 1.0), (1.1, 2.0), (2.1, 10), (10.1, 17), (17.1, 34), (34.1, 51)],
    "o3": [(0, 50), (51, 100), (101, 168), (169, 208), (209, 748), (749, 1288)],
    "nh3": [(0, 200), (201, 400), (401, 800), (801, 1200), (1201, 1800), (1801, 2400)],
}   # Severe upper ends aren't fixed by CPCB; they only keep the formula defined above 400


def subindex_to_conc(pollutant, idx):
    for (ilo, ihi), (clo, chi) in zip(INDEX_BANDS, CONC_BANDS[pollutant]):
        if idx <= ihi or ihi == 500:
            return clo + (idx - ilo) * (chi - clo) / (ihi - ilo)


def fetch(api_station):
    """Latest API rows for one station -> [(timestamp, {pm25: .., pm10: .., ...})]."""
    params = {"api-key": API_KEY, "format": "csv", "offset": 0, "limit": 10,
              "filters[country]": "India", "filters[state]": "West Bengal",
              "filters[city]": "Kolkata", "filters[station]": api_station}
    r = requests.get(API_URL, params=params, headers={"accept": "*/*"}, timeout=30)
    df = pd.read_csv(io.StringIO(r.text))
    df = df[df["pollutant_id"].isin(API_NAMES)]
    df["timestamp"] = pd.to_datetime(df["last_update"], format="%d-%m-%Y %H:%M:%S")
    rows = []
    for ts, g in df.groupby("timestamp"):
        row = {API_NAMES[p]: subindex_to_conc(API_NAMES[p], float(v))
               for p, v in zip(g["pollutant_id"], g["pollutant_avg"]) if v == v}
        rows.append((ts, row))
    return sorted(rows)


def live():
    """Continuous stream: every POLL_MINUTES, pull the newest reading per station, learn from it, forecast next hour."""
    engine = Engine.load() if STATE_PATH.exists() else Engine()   # continues from the history-trained models
    while True:
        records = []
        for station, api_name in LIVE_STATIONS.items():
            try:
                rows = fetch(api_name)
            except Exception as e:
                print(f"[{station}] fetch failed: {e}")
                continue
            for ts, row in rows:
                if station in engine.last_ts and ts <= engine.last_ts[station]:
                    continue                                  # already seen (also after a restart)
                rec = engine.update(ts, station, row)
                if rec:
                    records.append(rec)
                f = engine.latest.get(station)
                print(f"[{station}] {ts}  PM2.5={row.get('pm25', float('nan')):.1f}  "
                      + (f"next hour → {f['predicted']:.1f} ({f['arm']})" if f and f["for"] == ts + ONE_HOUR
                         else "warming up (needs 3 consecutive hours)"))
        engine.save()
        if records:
            pd.DataFrame(records).to_csv(LOG_PATH, mode="a", index=False, header=not LOG_PATH.exists())
        time.sleep(POLL_MINUTES * 60)


if __name__ == "__main__":
    if (sys.argv[1] if len(sys.argv) > 1 else "history") == "live":
        live()
    else:
        engine = Engine()
        log = engine.run(load_city())
        engine.save()
        log.to_csv(LOG_PATH, index=False)
        print(summarize(log))
