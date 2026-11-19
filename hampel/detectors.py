"""Traditional and context-aware Hampel filters for streaming and batch data."""

import json
import math
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings as S


def _is_missing(value):
    if value is None:
        return True

    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


class _Base:
    def __init__(
        self,
        window_size=S.WINDOW_SIZE,
        max_consec=S.MAX_CONSEC,
        min_valid_frac=S.MIN_VALID_FRAC,
        buffer_mode="raw",
    ):
        if window_size <= 0:
            raise ValueError("window_size must be positive")

        if not 0 < min_valid_frac <= 1:
            raise ValueError("min_valid_frac must be between 0 and 1")

        if buffer_mode not in ("raw", "cleaned"):
            raise ValueError("buffer_mode must be 'raw' or 'cleaned'")

        self.w = window_size
        self.max_consec = max_consec

        # Ceiling ensures at least the requested fraction is observed.
        # For window=31 and fraction=0.5, this requires 16 observations.
        self.min_valid = max(1, math.ceil(window_size * min_valid_frac))

        self.buffer_mode = buffer_mode
        self.reset()

    def reset(self):
        self.raw = deque(maxlen=self.w)
        self.cln = deque(maxlen=self.w)
        self.consec = 0

    def _buffer(self):
        values = np.asarray(
            self.cln if self.buffer_mode == "cleaned" else self.raw,
            dtype=float,
        )
        return values[~np.isnan(values)]

    def _push(self, raw, cleaned):
        self.raw.append(raw)
        self.cln.append(cleaned)

    def _test(self, x, ts, buf):
        raise NotImplementedError

    def step(self, x, ts, in_flag=0):
        """
        Process one observation.

        Parameters
        ----------
        x : float or None
            Raw observation.
        ts : pandas.Timestamp or datetime
            Observation timestamp.
        in_flag : int
            0 = normal, 2 = missing, 4 = sensor warm-up.

        Returns
        -------
        tuple
            (cleaned_value, flag)
            0 = normal
            1 = outlier
            2 = missing
            4 = warm-up
        """

        if in_flag == 4:
            self._push(np.nan, np.nan)
            return np.nan, 4

        if in_flag == 2 or _is_missing(x):
            self._push(np.nan, np.nan)
            return np.nan, 2

        x = float(x)

        buf = self._buffer()

        if len(buf) < self.min_valid:
            self.consec = 0
            self._push(x, x)
            return x, 0

        is_out, median = self._test(x, pd.Timestamp(ts), buf)

        if not is_out:
            self.consec = 0
            self._push(x, x)
            return x, 0

        self.consec += 1

        if self.consec > self.max_consec:
            # Accept a sustained new pollution level.
            recent = list(self.raw)[-(self.consec - 1):]

            self.raw.clear()
            self.cln.clear()

            for value in recent:
                self._push(value, value)

            self.consec = 0
            self._push(x, x)

            return x, 0

        self._push(x, median)
        return median, 1

    def detect(self, series: pd.Series, in_flags: pd.Series = None):
        """
        Process a complete time series using the same streaming logic.

        Returns
        -------
        cleaned : pandas.Series
        flags : pandas.Series
        """

        if in_flags is not None and len(in_flags) != len(series):
            raise ValueError("in_flags and series must have equal lengths")

        self.reset()

        cleaned = []
        flags = []

        for i, (ts, value) in enumerate(series.items()):
            incoming_flag = 0 if in_flags is None else int(in_flags.iloc[i])

            c, f = self.step(value, ts, incoming_flag)

            cleaned.append(c)
            flags.append(f)

        return (
            pd.Series(cleaned, index=series.index, name=series.name),
            pd.Series(flags, index=series.index, dtype=int),
        )


class TraditionalHampel(_Base):
    """Traditional Hampel filter using median and MAD."""

    def __init__(self, k_static=S.K_STATIC, **kw):
        super().__init__(**kw)
        self.k = k_static

    def _test(self, x, ts, buf):
        median = float(np.median(buf))

        mad = float(np.median(np.abs(buf - median)))

        if mad == 0:
            sd = float(np.std(buf))
            mad = S.EPSILON if sd == 0 else sd / 1.4826

        is_outlier = abs(x - median) > self.k * 1.4826 * mad

        return is_outlier, median


class ContextAwareHampel(_Base):
    """
    Context-aware Hampel filter.

    Requires the original seasonal knowledge_base.json.
    """

    def __init__(
        self,
        pollutant,
        profile_path="data/seasonal_bands/knowledge_base.json",
        k_loose=S.K_LOOSE,
        k_strict=S.K_STRICT,
        k_very=S.K_VERY,
        beta=S.BETA,
        floor=S.SEASONAL_FLOOR_FACTOR,
        trend_threshold=S.TREND_THRESHOLD,
        trend_relaxation=S.TREND_RELAXATION,
        max_k=S.MAX_K,
        buffer_mode="cleaned",
        **kw,
    ):
        super().__init__(buffer_mode=buffer_mode, **kw)

        self.profile_path = Path(profile_path)

        if not self.profile_path.is_file():
            raise FileNotFoundError(
                f"Seasonal knowledge base not found: {self.profile_path}. "
                "Obtain the original file from the research team."
            )

        with self.profile_path.open("r", encoding="utf-8") as file:
            profile = json.load(file)

        if pollutant not in profile["pollutants"]:
            raise ValueError(f"Pollutant not found in profile: {pollutant}")

        self.stats = profile["pollutants"][pollutant]

        self.month2season = {
            month: season
            for season, months in profile["seasons"].items()
            for month in months
        }

        if not all(month in self.month2season for month in range(1, 13)):
            raise ValueError("Seasonal profile must map all 12 months")

        if not 0 <= beta < 1:
            raise ValueError("beta must be in the interval [0, 1)")

        self.kl = k_loose
        self.ks = k_strict
        self.kv = k_very
        self.beta = beta

        self.floor = floor
        self.tt = trend_threshold
        self.tr = trend_relaxation
        self.max_k = max_k

    def _test(self, x, ts, buf):
        season = self.month2season[ts.month]
        stats = self.stats[season]

        lo = float(stats["p5"])
        hi = float(stats["p95"])

        median = float(np.median(buf))

        mad = max(
            float(np.median(np.abs(buf - median))),
            self.floor * float(stats["mad"]),
            S.EPSILON,
        )

        slope = (
            float(np.polyfit(np.arange(len(buf)), buf, 1)[0])
            if len(buf) > 1
            else 0.0
        )

        if x < lo or x > hi:
            k = self.kv
            inside = False
        else:
            r = float(
                np.clip(
                    (median - lo) / ((hi - lo) or S.EPSILON),
                    0,
                    1,
                )
            )

            a = float(
                np.clip(
                    (r - self.beta) / (1 - self.beta),
                    0,
                    1,
                )
            )

            k = self.kl - a * (self.kl - self.ks)
            inside = True

        follows_trend = (
            (slope > 0 and x >= median)
            or (slope < 0 and x <= median)
        )

        if (
            inside
            and abs(slope) / (mad + S.EPSILON) > self.tt
            and follows_trend
        ):
            k = min(self.max_k, k * self.tr)

        is_outlier = abs(x - median) > k * 1.4826 * mad

        return is_outlier, median


class RuleCheck:
    """Physical range and stuck-sensor detection."""

    RANGES = {
        "pm25": (0, 1000),
        "pm10": (0, 1000),
        "no2": (0, 1000),
        "co": (0, 50),
        "temp": (-5, 55),
        "rh": (0, 100),
    }

    def __init__(self, var, stuck_steps=4):
        if var not in self.RANGES:
            raise ValueError(f"Unknown sensor variable: {var}")

        if stuck_steps <= 0:
            raise ValueError("stuck_steps must be positive")

        self.lo, self.hi = self.RANGES[var]
        self.k = stuck_steps
        self.hist = deque(maxlen=stuck_steps)

    def reset(self):
        self.hist.clear()

    def step(self, x):
        if _is_missing(x):
            self.hist.append(np.nan)
            return False

        x = float(x)

        bad = not (self.lo <= x <= self.hi)

        stuck = (
            len(self.hist) == self.k
            and all(value == x for value in self.hist)
        )

        self.hist.append(x)

        return bad or stuck
