import math

VC = 5.0                    # sensor circuit voltage (V)
DIVIDER_TOTAL = 200_000     # 100k + 100k divider seen by the module output

def rl_effective(rl_ohm, divider_total=DIVIDER_TOTAL):
    """Load resistor in parallel with the divider."""
    return rl_ohm * divider_total / (rl_ohm + divider_total)

def rs_from_mv(mv_at_ao, rl_eff_ohm, vc=VC):
    """Sensor resistance from the voltage at the module output (mV)."""
    if mv_at_ao is None:
        return float("nan")
    v = mv_at_ao / 1000.0
    if v <= 0.01 or v >= vc:
        return float("nan")
    return rl_eff_ohm * (vc - v) / v

def mq135_trh_factor(t, rh):
    """MQ135 temperature/humidity correction (GeorgK MQ135 library constants)."""
    if t is None or rh is None or math.isnan(t) or math.isnan(rh):
        return 1.0
    return 0.00035 * t * t - 0.02718 * t + 1.39538 - (rh - 33.0) * 0.0018

def ppm_from_ratio(ratio, m, b):
    """log10(ppm) = m * log10(Rs/R0) + b."""
    if ratio is None or not ratio > 0:
        return float("nan")
    return 10 ** (m * math.log10(ratio) + b)

def no2_ugm3_from_ppm(ppm):
    return ppm * 1880.0      # 1 ppb NO2 = 1.88 ug/m3 at 25 C

def co_mgm3_from_ppm(ppm):
    return ppm * 1.145       # 1 ppm CO = 1.145 mg/m3 at 25 C
