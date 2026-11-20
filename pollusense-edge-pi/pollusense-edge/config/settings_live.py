"""Live-pipeline configuration (used only by pipeline/; the frozen experiment path reads config/settings.py).

Same Hampel values as the frozen H2. Differences from the experiments, both for live use only:
  - CO stuck rule = 8 identical values (2 h) instead of 4: at CPCB's 0.01 mg/m³ resolution runs of 5-8 identical
    CO values occur naturally (106 of 179 CO stuck flags in 2024 came from such runs, docs/data_report.md / Log P1).
  - bands: data/seasonal_bands/knowledge_base_live.json if it exists (site adaptation, tools/site_adapt_bands.py),
    else the final bands of the freeze.
"""
import os

from config import settings as S

LIVE_BANDS = "data/seasonal_bands/knowledge_base_live.json"
STUCK_STEPS = {"co": 8}            # all other variables: STUCK_STEPS_DEFAULT
STUCK_STEPS_DEFAULT = 4
HAMPEL_VARS = ("pm25", "pm10", "no2", "co")


def live_profile_path(live_path=LIVE_BANDS):
    return live_path if os.path.exists(live_path) else S.H2_PROFILE_PATH


def live_h2_kwargs(live_path=LIVE_BANDS):
    kw = dict(S.H2_TUNED)
    kw["profile_path"] = live_profile_path(live_path)
    return kw


def stuck_steps(var):
    return STUCK_STEPS.get(var, STUCK_STEPS_DEFAULT)
