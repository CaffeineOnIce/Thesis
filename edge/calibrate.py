import math
VC = 5.0
DIVIDER_TOTAL = 200_000
def rl_effective(rl_ohm, divider_total=DIVIDER_TOTAL):
    return rl_ohm * divider_total / (rl_ohm + divider_total)
def rs_from_mv(mv_at_ao, rl_eff_ohm, vc=VC):
    if mv_at_ao is None: return float("nan")
    v = mv_at_ao / 1000.0
    if v <= 0.01 or v >= vc: return float("nan")
    return rl_eff_ohm * (vc - v) / v
def mq135_trh_factor(t, rh):
    if t is None or rh is None or math.isnan(t) or math.isnan(rh): return 1.0
    return 0.00035 * t * t - 0.02718 * t + 1.39538 - (rh - 33.0) * 0.0018
def ppm_from_ratio(ratio, m, b):
    if ratio is None or not ratio > 0 or math.isnan(ratio): return float("nan")
    return 10 ** (m * math.log10(ratio) + b)
def no2_ugm3_from_ppm(ppm):
    return ppm * 1880.0 if not math.isnan(ppm) else float("nan")
def co_mgm3_from_ppm(ppm):
    return ppm * 1.145 if not math.isnan(ppm) else float("nan")
