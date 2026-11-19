"""Traditional and context-aware Hampel filters, written as step functions so the same code
runs on a whole series (experiments) and one record at a time (pipeline).
Flags: 0 normal, 1 outlier, 2 missing, 4 MQ warm-up."""
import json
from collections import deque
import numpy as np
import pandas as pd
from config import settings as S

class _Base:
    def __init__(self, window_size=S.WINDOW_SIZE, max_consec=S.MAX_CONSEC,
                 min_valid_frac=S.MIN_VALID_FRAC, buffer_mode="raw"):
        assert buffer_mode in ("raw", "cleaned")
        self.w, self.max_consec, self.min_valid = window_size, max_consec, int(window_size * min_valid_frac)
        self.buffer_mode = buffer_mode
        self.reset()

    def reset(self):
        self.raw = deque(maxlen=self.w)       # last w raw values (NaN where missing)
        self.cln = deque(maxlen=self.w)       # last w cleaned values
        self.consec = 0

    def _buffer(self):
        b = np.array(self.cln if self.buffer_mode == "cleaned" else self.raw, dtype=float)
        return b[~np.isnan(b)]

    def _push(self, raw, cleaned):
        self.raw.append(raw); self.cln.append(cleaned)

    def step(self, x, ts, in_flag=0):
        """x: value (NaN if missing); ts: pandas Timestamp (IST); in_flag 4 = warm-up.
        Returns (cleaned_value, flag)."""
        if in_flag == 4:
            self._push(np.nan, np.nan); return np.nan, 4
        if x is None or np.isnan(x):
            self._push(np.nan, np.nan); return np.nan, 2
        buf = self._buffer()
        if len(buf) < self.min_valid:                     # not enough history: accept
            self.consec = 0; self._push(x, x); return x, 0
        is_out, median = self._test(x, ts, buf)
        if not is_out:
            self.consec = 0; self._push(x, x); return x, 0
        self.consec += 1
        if self.consec > self.max_consec:                 # lock-in guard: accept the new level
            recent = list(self.raw)[-(self.consec - 1):]  # the raw values that were just flagged
            self.raw.clear(); self.cln.clear()            # forget the old level
            for v in recent:
                self._push(v, v)
            self.consec = 0; self._push(x, x); return x, 0
        self._push(x, median); return median, 1

    def detect(self, series: pd.Series, in_flags: pd.Series = None):
        """Whole series (regular 15-min index). Returns (cleaned, flags)."""
        self.reset()
        out, fl = [], []
        for i, (ts, x) in enumerate(series.items()):
            c, f = self.step(float(x), ts, 0 if in_flags is None else int(in_flags.iloc[i]))
            out.append(c); fl.append(f)
        return pd.Series(out, index=series.index), pd.Series(fl, index=series.index, dtype=int)

class TraditionalHampel(_Base):
    def __init__(self, k_static=S.K_STATIC, **kw):
        super().__init__(**kw); self.k = k_static
    def _test(self, x, ts, buf):
        m = float(np.median(buf)); mad = float(np.median(np.abs(buf - m)))
        if mad == 0:
            sd = float(np.std(buf)); mad = S.EPSILON if sd == 0 else sd / 1.4826
        return abs(x - m) > self.k * 1.4826 * mad, m

class ContextAwareHampel(_Base):
    def __init__(self, pollutant, profile_path="data/seasonal_bands/knowledge_base.json",
                 k_loose=S.K_LOOSE, k_strict=S.K_STRICT, k_very=S.K_VERY, beta=S.BETA,
                 floor=S.SEASONAL_FLOOR_FACTOR, trend_threshold=S.TREND_THRESHOLD,
                 trend_relaxation=S.TREND_RELAXATION, max_k=S.MAX_K, buffer_mode="cleaned", **kw):
        super().__init__(buffer_mode=buffer_mode, **kw)
        prof = json.load(open(profile_path))
        self.stats = prof["pollutants"][pollutant]
        self.month2season = {m: s for s, months in prof["seasons"].items() for m in months}   # from the JSON only
        self.kl, self.ks, self.kv, self.beta = k_loose, k_strict, k_very, beta
        self.floor, self.tt, self.tr, self.max_k = floor, trend_threshold, trend_relaxation, max_k
    def _test(self, x, ts, buf):
        st = self.stats[self.month2season[ts.month]]
        lo, hi = float(st["p5"]), float(st["p95"])
        m = float(np.median(buf))
        mad = max(float(np.median(np.abs(buf - m))), self.floor * float(st["mad"]), S.EPSILON)
        slope = float(np.polyfit(np.arange(len(buf)), buf, 1)[0]) if len(buf) > 1 else 0.0
        if x < lo or x > hi:
            k, inside = self.kv, False
        else:
            r = float(np.clip((m - lo) / ((hi - lo) or S.EPSILON), 0, 1))
            a = float(np.clip((r - self.beta) / (1 - self.beta), 0, 1))
            k, inside = self.kl - a * (self.kl - self.ks), True
        follows = (slope > 0 and x >= m) or (slope < 0 and x <= m)
        if inside and abs(slope) / (mad + S.EPSILON) > self.tt and follows:
            k = min(self.max_k, k * self.tr)
        return abs(x - m) > k * 1.4826 * mad, m

class RuleCheck:
    """Physical range and stuck-sensor rule (Hampel cannot see a frozen value: its deviation is zero).
    A value is flagged if outside [lo, hi] or identical to the previous `stuck_steps` raw values."""
    RANGES = {"pm25": (0, 1000), "pm10": (0, 1000), "no2": (0, 1000), "co": (0, 50), "temp": (-5, 55), "rh": (0, 100)}
    def __init__(self, var, stuck_steps=4):
        self.lo, self.hi = self.RANGES[var]; self.k = stuck_steps; self.hist = deque(maxlen=stuck_steps)
    def step(self, x):
        if x is None or np.isnan(x):
            self.hist.append(np.nan); return False
        bad = not (self.lo <= x <= self.hi)
        stuck = len(self.hist) == self.k and all(h == x for h in self.hist)
        self.hist.append(x)
        return bad or stuck
