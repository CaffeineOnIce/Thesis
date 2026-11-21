"""Detector cost: microseconds per step() call (Phase 6). Same command on the laptop and on the Pi:

  python -m bench.bench_detectors --label laptop        -> results/E3_detector_cost_laptop.csv
  python -m bench.bench_detectors --label pi            -> results/E3_detector_cost_pi.csv

Input: a synthetic, seeded 15-min series (level 60, noise sd 4, 2 % spikes, 15 % NaN, November timestamps),
so no data files are needed on the Pi. Each detector: 10 000 steps, 5 repeats (fresh detector each repeat);
every call is timed individually with perf_counter_ns. Reported: median and p95 per call over all calls, and the
mean per call of each repeat (min / median over repeats).
Detectors: rule check, H1 (frozen), H2 (frozen), H2 frozen-with-all-switches-off plus each switch on alone.
Settings come from results/frozen_settings.json (falls back to the placeholders if it does not exist).
"""
import argparse
import importlib.metadata as md
import json
import os
import platform
import subprocess
import time

import numpy as np
import pandas as pd

from hampel.detectors import ContextAwareHampel, RuleCheck, TraditionalHampel

N, REPEATS = 10_000, 5
SWITCHES = ("level_shift_rule", "trend_outside_band", "monthly_bands", "log_scale", "window_by_observed")


def cpu_model():
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "(Get-CimInstance Win32_Processor).Name"], capture_output=True, text=True, timeout=20)
            if out.stdout.strip():
                return out.stdout.strip().splitlines()[0]
        if os.path.exists("/proc/cpuinfo"):
            for line in open("/proc/cpuinfo"):
                if line.lower().startswith(("model name", "model")):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine()


def series():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-11-01", periods=N, freq="15min")
    x = 60 + rng.normal(0, 4, N)
    x[rng.random(N) < 0.02] = 300
    x[rng.random(N) < 0.15] = np.nan
    return list(idx), [float(v) for v in x]


def settings():
    path = "results/frozen_settings.json"
    if os.path.exists(path):
        fz = json.load(open(path)); return fz["H1"], fz["H2"], path
    return {}, {"profile_path": "data/seasonal_bands/knowledge_base.json"}, "placeholders"


def time_calls(make, ts, xs, rule=False):
    per_call, means = [], []
    for _ in range(REPEATS):
        d = make(); buf = np.empty(N, dtype=np.int64)
        pc = time.perf_counter_ns
        if rule:
            for i, x in enumerate(xs):
                t0 = pc(); d.step(x); buf[i] = pc() - t0
        else:
            for i, (t, x) in enumerate(zip(ts, xs)):
                t0 = pc(); d.step(x, t); buf[i] = pc() - t0
        per_call.append(buf / 1000.0); means.append(buf.mean() / 1000.0)
    allc = np.concatenate(per_call)
    return dict(us_median=round(float(np.median(allc)), 2), us_p95=round(float(np.percentile(allc, 95)), 2),
                us_mean_min=round(min(means), 2), us_mean_median=round(float(np.median(means)), 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="laptop")
    a = ap.parse_args()
    h1, h2, src = settings()
    ts, xs = series()
    base = {**h2, **{s: False for s in SWITCHES}}
    dets = [("rule check (pm25)", lambda: RuleCheck("pm25"), True),
            ("H1 frozen", lambda: TraditionalHampel(**h1), False),
            ("H2 frozen", lambda: ContextAwareHampel("pm25", **h2), False),
            ("H2 frozen, all switches off", lambda: ContextAwareHampel("pm25", **base), False)]
    for s in SWITCHES:
        dets.append((f"H2 frozen, only {s} on", lambda s=s: ContextAwareHampel("pm25", **{**base, s: True}), False))
    env = dict(label=a.label, cpu=cpu_model(), machine=platform.machine(), os=platform.platform(),
               python=platform.python_version(), numpy=md.version("numpy"), pandas=md.version("pandas"),
               settings=src, steps=N, repeats=REPEATS)
    rows = []
    for name, mk, rule in dets:
        r = time_calls(mk, ts, xs, rule)
        rows.append(dict(detector=name, **r, **env)); print(f"  {name:40s} median {r['us_median']:7.1f} us  p95 {r['us_p95']:7.1f} us")
    os.makedirs("results", exist_ok=True)
    out = f"results/E3_detector_cost_{a.label}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"written {out}  ({env['cpu']}, Python {env['python']}, numpy {env['numpy']}, pandas {env['pandas']})")


if __name__ == "__main__":
    main()
