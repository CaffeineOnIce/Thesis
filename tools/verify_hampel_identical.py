"""Check that the frozen detectors give identical output on two machines (laptop vs Raspberry Pi) — A4.

  python -m tools.verify_hampel_identical --label laptop      -> results/hampel_identity_laptop.csv
  python -m tools.verify_hampel_identical --label pi          -> results/hampel_identity_pi.csv   (on the Pi)
  python -m tools.verify_hampel_identical --compare results/hampel_identity_laptop.csv results/hampel_identity_pi.csv

Input: tests/fixtures/hampel_slice_2024_oct_nov.csv (cleaned 2024-10-01 .. 2024-11-30, tracked in git, so the Pi
needs no data files). Detectors: frozen H1-tuned, H2-tuned and H1-loose from results/frozen_settings.json.
--compare passes if every flag is identical and every cleaned value differs by less than 1e-9 (NaN == NaN).
"""
import argparse
import json
import sys

import numpy as np
import pandas as pd

from hampel.detectors import ContextAwareHampel, TraditionalHampel

SLICE = "tests/fixtures/hampel_slice_2024_oct_nov.csv"
TOL = 1e-9


def run(label):
    fz = json.load(open("results/frozen_settings.json"))
    df = pd.read_csv(SLICE, index_col="ts", parse_dates=True)
    dets = {"H1-tuned": lambda v: TraditionalHampel(**fz["H1"]),
            "H2-tuned": lambda v: ContextAwareHampel(v, **fz["H2"]),
            "H1-loose": lambda v: TraditionalHampel(**fz["H1_loose_reference"])}
    parts = []
    for v in df.columns:
        for name, mk in dets.items():
            c, f = mk(v).detect(df[v])
            parts.append(pd.DataFrame({"ts": df.index, "var": v, "detector": name, "cleaned": c.values, "flag": f.values}))
    out = pd.concat(parts, ignore_index=True)
    path = f"results/hampel_identity_{label}.csv"
    out.to_csv(path, index=False, float_format="%.17g")
    print(f"written {path}: {len(out)} rows, flags {out.flag.value_counts().to_dict()}")
    return path


def compare(a, b):
    x, y = pd.read_csv(a), pd.read_csv(b)
    if len(x) != len(y) or not (x[["ts", "var", "detector"]].values == y[["ts", "var", "detector"]].values).all():
        print("FAIL: rows differ"); return 1
    flags = int((x.flag != y.flag).sum())
    cx, cy = x.cleaned.to_numpy(), y.cleaned.to_numpy()
    both_nan = np.isnan(cx) & np.isnan(cy)
    diff = np.where(both_nan, 0.0, np.abs(cx - cy))
    worst = float(np.nanmax(diff)) if len(diff) else 0.0
    nan_mismatch = int((np.isnan(cx) != np.isnan(cy)).sum())
    ok = flags == 0 and nan_mismatch == 0 and worst < TOL
    print(f"{'PASS' if ok else 'FAIL'}: flag mismatches {flags}, NaN mismatches {nan_mismatch}, max |diff| {worst:.3g}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--compare", nargs=2)
    a = ap.parse_args()
    if a.compare:
        sys.exit(compare(*a.compare))
    run(a.label or "laptop")


if __name__ == "__main__":
    main()
