"""Detector factory for the live pipeline (pipeline/core.py imports this; the experiments do not).

  from pipeline.live_detectors import make_live_detectors
  rules, hampel = make_live_detectors()          # dicts keyed by variable
  per record: flag = rules[v].step(x); if v in hampel: x_clean, f = hampel[v].step(x_or_nan, ts, in_flag)

Configuration: config/settings_live.py (frozen H2 values, CO stuck rule 8 steps, live bands if present).
Timestamps: live records are labelled by window END; the detectors only use ts.month, so the label convention
does not change their output except for the 15 min at a month boundary (see data.timestamps.to_window_start).
"""
from config import settings_live as L
from hampel.detectors import ContextAwareHampel, RuleCheck

RULE_VARS = ("pm25", "pm10", "no2", "co", "temp", "rh")


def make_live_detectors(live_path=L.LIVE_BANDS):
    rules = {v: RuleCheck(v, stuck_steps=L.stuck_steps(v)) for v in RULE_VARS}
    kw = L.live_h2_kwargs(live_path)
    hampel = {v: ContextAwareHampel(v, **kw) for v in L.HAMPEL_VARS}
    return rules, hampel
