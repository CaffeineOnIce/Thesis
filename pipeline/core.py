"""One processing step for one 15-min record: rules -> Hampel -> impute -> AQI.
The same code runs on the Pi (edge mode) and on the VM (cloud mode)."""
import time
import numpy as np
import pandas as pd
from hampel.detectors import RuleCheck, TraditionalHampel, ContextAwareHampel
from impute.models import Base
from impute.aqi import aqi_frame

VARS = ["pm25", "pm10", "no2", "co", "temp", "rh"]
POLL = ["pm25", "pm10", "no2", "co"]
HIST_ROWS = 200          # >= 49 h of 15-min history for the imputer
AQI_ROWS = 96            # 24 h for the running averages

class State:
    def __init__(self, model_path, detector="H2", profile="data/seasonal_bands/knowledge_base.json"):
        self.model = Base.load(model_path)
        self.rules = {v: RuleCheck(v) for v in VARS}
        mk = (lambda v: ContextAwareHampel(v, profile_path=profile)) if detector == "H2" else (lambda v: TraditionalHampel())
        self.hampel = {v: mk(v) for v in POLL}
        self.hist = pd.DataFrame(columns=VARS, dtype=float)    # observed, cleaned values only
        self.filled = pd.DataFrame(columns=VARS, dtype=float)  # observed + imputed, for AQI

def to_ist(ts_epoch):
    return pd.to_datetime(ts_epoch, unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None)

def process(rec: dict, st: State) -> dict:
    t0 = time.perf_counter_ns()
    ts = to_ist(rec["ts"])
    x = {v: (np.nan if rec.get(v) is None else float(rec[v])) for v in VARS}
    flags = {v: int(rec.get(f"flag_{v}", 0 if rec.get(v) is not None else 2)) for v in VARS}
    # 1. rules (range, stuck)
    for v in VARS:
        if flags[v] == 0 and st.rules[v].step(x[v]):
            flags[v], x[v] = 1, np.nan
        elif flags[v] != 0:
            st.rules[v].step(np.nan)
    t1 = time.perf_counter_ns()
    # 2. Hampel on the four pollutants; flagged values become missing
    for v in POLL:
        _, f = st.hampel[v].step(x[v], ts, 4 if flags[v] == 4 else 0)
        if f == 1:
            flags[v], x[v] = 1, np.nan
    t2 = time.perf_counter_ns()
    # 3. impute every missing value
    row = pd.Series(x, name=ts)
    if row.isna().any() and len(st.hist) > 0:
        filled = st.model.impute(st.hist.tail(HIST_ROWS), row)
        for v in VARS:
            if np.isnan(x[v]) and not np.isnan(filled[v]):
                flags[v] = 3 if flags[v] in (2, 4) else 1   # 1 stays 1 (outlier, now filled)
    else:
        filled = row
    t3 = time.perf_counter_ns()
    # 4. AQI on observed + imputed values
    st.hist.loc[ts] = row
    st.filled.loc[ts] = filled
    st.hist = st.hist.tail(HIST_ROWS); st.filled = st.filled.tail(AQI_ROWS)
    a = aqi_frame(st.filled).iloc[-1]
    t4 = time.perf_counter_ns()
    out = {"ts": rec["ts"], "device_id": rec.get("device_id")}
    out.update({v: (None if np.isnan(filled[v]) else round(float(filled[v]), 3)) for v in VARS})
    out.update({f"flag_{v}": flags[v] for v in VARS})
    out.update({"aqi": None if np.isnan(a["aqi"]) else round(float(a["aqi"]), 1), "category": a["category"],
                "t_rules_ms": (t1 - t0) / 1e6, "t_hampel_ms": (t2 - t1) / 1e6,
                "t_impute_ms": (t3 - t2) / 1e6, "t_aqi_ms": (t4 - t3) / 1e6, "t_total_ms": (t4 - t0) / 1e6})
    return out
