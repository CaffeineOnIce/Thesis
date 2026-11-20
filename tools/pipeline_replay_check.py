"""Replay the 2024 Oct-Nov fixture through pipeline.core.process() one record at a time and check that the
pipeline's Hampel/rule flags equal an independent run of the frozen H2 + live rule check.

  python -m tools.pipeline_replay_check --model M3-L        # uses models/M3-L.joblib
  python -m tools.pipeline_replay_check --model M3-L --n 960 # first 10 days only (faster on the Pi)

Prints per-record time (mean, p95) and flag mismatches; exits 1 on any mismatch.
"""
import argparse
import sys
import time

import numpy as np
import pandas as pd

from config import settings as S
from config import settings_live as L
from hampel.detectors import ContextAwareHampel, RuleCheck
from pipeline.core import POLL, VARS, State, process

SLICE = "tests/fixtures/hampel_slice_2024_oct_nov.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="M3-L")
    ap.add_argument("--n", type=int, default=0, help="number of records (0 = all 5856)")
    a = ap.parse_args()

    sl = pd.read_csv(SLICE, index_col="ts", parse_dates=True)
    if a.n:
        sl = sl.iloc[:a.n]
    st = State(f"models/{a.model}.joblib", detector="H2")

    outs, t0 = [], time.time()
    for ts, r in sl.iterrows():
        epoch = int(pd.Timestamp(ts).tz_localize("Asia/Kolkata").tz_convert("UTC").timestamp())
        rec = {"ts": epoch, "device_id": "replay"}
        rec.update({v: (None if (v not in sl.columns or pd.isna(r[v])) else float(r[v])) for v in VARS})
        outs.append(process(rec, st))
    o = pd.DataFrame(outs)
    print(f"{len(o)} records in {time.time() - t0:.1f} s; per record mean {o.t_total_ms.mean():.2f} ms, "
          f"p95 {o.t_total_ms.quantile(.95):.2f} ms (Hampel mean {o.t_hampel_ms.mean():.3f} ms)")

    bad = 0
    for v in POLL:
        rc, hz, ref = RuleCheck(v, stuck_steps=L.stuck_steps(v)), ContextAwareHampel(v, **S.H2_TUNED), []
        for ts, x in sl[v].items():
            x = np.nan if pd.isna(x) else float(x)
            if np.isnan(x):
                rc.step(np.nan)
                hz.step(np.nan, ts)
                ref.append(0)
            elif rc.step(x):
                hz.step(np.nan, ts)
                ref.append(1)
            else:
                ref.append(int(hz.step(x, ts)[1] == 1))
        got = (o[f"flag_{v}"].values == 1).astype(int)
        mism = int((got != np.array(ref)).sum())
        bad += mism
        print(f"  {v}: outlier flags pipeline {got.sum()}, frozen H2 reference {sum(ref)}, mismatches {mism}")
    print("PASS" if bad == 0 else "FAIL")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
