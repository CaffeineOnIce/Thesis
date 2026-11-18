"""PolluSense Mathematical Calibration Engine.

Provides core functions for effective load resistance computation (accounting
for the 100k/100k voltage divider), sensor resistance extraction (Rs),
temperature and relative humidity compensation for MQ-135, and power-law
gas concentration conversions (ppm -> µg/m³ for NO2, ppm -> mg/m³ for CO).
"""

import math

VC = 5.0
DIVIDER_TOTAL = 200_000  # 100k + 100k in parallel with RL


def rl_effective(rl_ohm: float, divider_total: float = DIVIDER_TOTAL) -> float:
    """Calculates effective load resistance in parallel with the 200k divider."""
    return rl_ohm * divider_total / (rl_ohm + divider_total)


def rs_from_mv(mv_at_ao: float, rl_eff_ohm: float, vc: float = VC) -> float:
    """Calculates sensor resistance Rs from analog output voltage (in mV)."""
    if mv_at_ao is None:
        return float("nan")
    v = mv_at_ao / 1000.0
    if v <= 0.01 or v >= vc:
        return float("nan")
    return rl_eff_ohm * (vc - v) / v


def mq135_trh_factor(t: float, rh: float) -> float:
    """Calculates temperature and relative humidity compensation factor for MQ-135."""
    if t is None or rh is None or math.isnan(t) or math.isnan(rh):
        return 1.0
    return 0.00035 * t * t - 0.02718 * t + 1.39538 - (rh - 33.0) * 0.0018


def ppm_from_ratio(ratio: float, m: float, b: float) -> float:
    """Converts Rs/R0 ratio to gas concentration (ppm) via power-law: ppm = 10^(m * log10(ratio) + b)."""
    if ratio is None or not ratio > 0 or math.isnan(ratio):
        return float("nan")
    return 10 ** (m * math.log10(ratio) + b)


def no2_ugm3_from_ppm(ppm: float) -> float:
    """Converts NO2 concentration from ppm to µg/m³ (CPCB standard conditions)."""
    return ppm * 1880.0 if not math.isnan(ppm) else float("nan")


def co_mgm3_from_ppm(ppm: float) -> float:
    """Converts CO concentration from ppm to mg/m³ (CPCB standard conditions)."""
    return ppm * 1.145 if not math.isnan(ppm) else float("nan")
