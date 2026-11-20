"""Traditional and context-aware Hampel filters, written as step functions so the same code
runs on a whole series (experiments) and one record at a time (pipeline).
Flags: 0 normal, 1 outlier, 2 missing, 4 MQ warm-up.

Optional switches (all off by default = original behaviour; spec §4, §5.1, §5.3):
  both filters:        window_by_observed  window = last W *observed* values instead of last W steps
  ContextAwareHampel:  level_shift_rule    accept x if it agrees with the median of the last hour (raw values)
                       trend_outside_band  trend protection also for values outside the seasonal band
                       monthly_bands       use monthly p5/p95/mad ("pollutants_monthly" in the knowledge base)
                       log_scale           run the H2 test on log1p(values)
"""
import json
from collections import deque
import numpy as np
import pandas as pd
from config import settings as S

LEVEL_SHIFT_STEPS = 4      # level_shift_rule: 'recent' = last 4 steps (1 h) of raw observed values


def _median(b):
    """np.median for a 1-D float array without NaN, with less overhead (same result: middle value, or the
    mean of the two middle values computed as (a + b) / 2 like np.mean)."""
    s = np.sort(b); n = len(s); h = n // 2
    return float(s[h]) if n % 2 else float((s[h - 1] + s[h]) / 2)


def _slope(b):
    """Least-squares slope of b against 0..n-1 (closed form; 0 if n < 2)."""
    n = len(b)
    if n < 2:
        return 0.0
    i = np.arange(n, dtype=float); i -= i.mean()
    return float(np.dot(i, b - b.mean()) / np.dot(i, i))


class _Base:
    def __init__(self, window_size=S.WINDOW_SIZE, max_consec=S.MAX_CONSEC,
                 min_valid_frac=S.MIN_VALID_FRAC, buffer_mode="raw", window_by_observed=False, trace=False):
        if buffer_mode not in ("raw", "cleaned"):          # explicit raise: asserts vanish under python -O
            raise ValueError(f"buffer_mode must be 'raw' or 'cleaned', got {buffer_mode!r}")
        self.w, self.max_consec, self.min_valid = window_size, max_consec, int(window_size * min_valid_frac)
        self.buffer_mode = buffer_mode
        self.by_obs = bool(window_by_observed)
        self.trace = bool(trace)       # analysis only: _test stores its intermediate values in self.last
        self.last = None
        self.reset()

    def reset(self):
        self.raw = deque(maxlen=self.w)       # last w steps: raw values (NaN where missing)
        self.cln = deque(maxlen=self.w)       # last w steps: cleaned values
        self.oraw = deque(maxlen=self.w)      # last w observed raw values (window_by_observed)
        self.ocln = deque(maxlen=self.w)      # last w observed cleaned values (window_by_observed)
        self.consec = 0

    def _buffer(self):
        if self.by_obs:
            src = self.ocln if self.buffer_mode == "cleaned" else self.oraw
        else:
            src = self.cln if self.buffer_mode == "cleaned" else self.raw
        b = np.array(src, dtype=float)
        return b[~np.isnan(b)]

    def _push(self, raw, cleaned):
        self.raw.append(raw); self.cln.append(cleaned)
        if not np.isnan(raw):
            self.oraw.append(raw); self.ocln.append(cleaned)

    def _recent_raw(self, n):
        """Raw observed values among the last n steps (before the current one)."""
        r = np.array(list(self.raw)[-n:], dtype=float)
        return r[~np.isnan(r)]

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
            src = self.oraw if self.by_obs else self.raw
            recent = list(src)[-(self.consec - 1):]       # the raw values that were just flagged
            self.raw.clear(); self.cln.clear()            # forget the old level
            self.oraw.clear(); self.ocln.clear()
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
        m = _median(buf); mad = _median(np.abs(buf - m))
        if mad == 0:
            sd = float(np.std(buf)); mad = S.EPSILON if sd == 0 else sd / 1.4826
        thr = self.k * 1.4826 * mad
        if self.trace:
            self.last = dict(median=m, mad=mad, k=self.k, threshold=thr, n_buf=len(buf))
        return abs(x - m) > thr, m


class ContextAwareHampel(_Base):
    def __init__(self, pollutant, profile_path="data/seasonal_bands/knowledge_base.json",
                 k_loose=S.K_LOOSE, k_strict=S.K_STRICT, k_very=S.K_VERY, beta=S.BETA,
                 floor=S.SEASONAL_FLOOR_FACTOR, trend_threshold=S.TREND_THRESHOLD,
                 trend_relaxation=S.TREND_RELAXATION, max_k=S.MAX_K, buffer_mode="cleaned",
                 level_shift_rule=False, trend_outside_band=False, monthly_bands=False, log_scale=False,
                 level_shift_steps=LEVEL_SHIFT_STEPS, disable_band_k=False, disable_mad_floor=False,
                 disable_trend=False, **kw):
        super().__init__(buffer_mode=buffer_mode, **kw)
        with open(profile_path, encoding="utf-8-sig") as f:
            prof = json.load(f)
        self.stats = prof["pollutants"][pollutant]
        self.month2season = {m: s for s, months in prof["seasons"].items() for m in months}   # from the JSON only
        self.monthly = bool(monthly_bands)
        if self.monthly:
            if pollutant not in prof.get("pollutants_monthly", {}):
                raise ValueError(f"monthly_bands=True needs 'pollutants_monthly' for {pollutant!r} in {profile_path} "
                                 "(build it with tools/build_knowledge_base.py)")
            self.month_stats = {int(k): v for k, v in prof["pollutants_monthly"][pollutant].items()}
        self.kl, self.ks, self.kv, self.beta = k_loose, k_strict, k_very, beta
        self.floor, self.tt, self.tr, self.max_k = floor, trend_threshold, trend_relaxation, max_k
        self.level_shift, self.ls_steps = bool(level_shift_rule), int(level_shift_steps)
        self.trend_out, self.log = bool(trend_outside_band), bool(log_scale)
        # core-component ablation (analysis only, spec §4.2): all off = frozen behaviour
        self.no_band_k, self.no_floor, self.no_trend = bool(disable_band_k), bool(disable_mad_floor), bool(disable_trend)

    def _band(self, ts):
        return self.month_stats[ts.month] if self.monthly else self.stats[self.month2season[ts.month]]

    @staticmethod
    def _log(v):
        return np.log1p(np.maximum(v, 0.0))           # concentrations are >= 0; clip guards log1p(-1)

    def _test(self, x, ts, buf):
        st = self._band(ts)
        lo, hi, mad_s = float(st["p5"]), float(st["p95"]), float(st["mad"])
        m = _median(buf)                              # replacement value, always in original units
        if self.log:                                  # test on log1p scale
            x, buf = float(self._log(x)), self._log(buf)
            lo, hi = float(self._log(lo)), float(self._log(hi))
            mad_s = float(st["mad_log"]) if "mad_log" in st else mad_s / (1.0 + float(st["median"]))
            mt = _median(buf)
        else:
            mt = m
        if self.no_floor:
            mad = max(_median(np.abs(buf - mt)), S.EPSILON)
        else:
            mad = max(_median(np.abs(buf - mt)), self.floor * mad_s, S.EPSILON)
        slope = _slope(buf)
        if x < lo or x > hi:
            k, inside = self.kv, False
        else:
            r = float(np.clip((mt - lo) / ((hi - lo) or S.EPSILON), 0, 1))
            a = float(np.clip((r - self.beta) / (1 - self.beta), 0, 1))
            k, inside = self.kl - a * (self.kl - self.ks), True
        if self.no_band_k:
            k = self.kl
        follows = (slope > 0 and x >= mt) or (slope < 0 and x <= mt)
        if not self.no_trend and (inside or self.trend_out) and abs(slope) / (mad + S.EPSILON) > self.tt and follows:
            k = min(self.max_k, k * self.tr)
        thr = k * 1.4826 * mad
        is_out = abs(x - mt) > thr
        if is_out and self.level_shift:               # x agrees with the last hour -> level change, not a spike
            rec = self._recent_raw(self.ls_steps)
            if len(rec) >= 2:
                rm = _median(self._log(rec) if self.log else rec)
                if abs(x - rm) <= thr:
                    is_out = False
        if self.trace:
            self.last = dict(median=mt, mad=mad, k=k, threshold=thr, n_buf=len(buf), inside_band=inside,
                             slope=slope, band_lo=lo, band_hi=hi)
        return is_out, m


class RuleCheck:
    """Physical range and stuck-sensor rule.
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
