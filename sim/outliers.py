
import numpy as np
import pandas as pd

TARGETS = ["pm25", "pm10", "no2", "co"]


def inject(df, observed, seed):
    rng = np.random.default_rng(seed)

    out = df.copy()
    lab = pd.DataFrame("", index=df.index, columns=TARGETS)

    n = len(df)

    for v in TARGETS:
        x = out[v].values.copy()
        L = lab[v].values.copy()
        ok = observed[v].values.copy()

        # Spikes: 0.5% of observed points, multiplied by 3–10
        for i in rng.choice(
            np.where(ok)[0],
            size=int(0.005 * ok.sum()),
            replace=False
        ):
            x[i] *= rng.uniform(3, 10)
            L[i] = "spike"

        # Bursts: 0.2% of observed points start a 3–4 step burst
        for i in rng.choice(
            np.where(ok)[0],
            size=int(0.002 * ok.sum()),
            replace=False
        ):
            ln = int(rng.integers(3, 5))
            f = rng.uniform(2, 5)

            for j in range(i, min(n, i + ln)):
                if ok[j] and L[j] == "":
                    x[j] *= f
                    L[j] = "burst"

        # Stuck values: 3 episodes per month, lasting 2–6 hours
        months = df.index.to_period("M")

        for mth in months.unique():
            pos = np.where((months == mth) & ok)[0]

            for i in rng.choice(
                pos,
                size=min(3, len(pos)),
                replace=False
            ):
                ln = int(rng.integers(8, 25))

                for j in range(i + 1, min(n, i + ln)):
                    if ok[j] and L[j] == "":
                        x[j] = x[i]
                        L[j] = "stuck"

        # Drift: NO2 and CO only, over 3 days
        if v in ("no2", "co"):
            for i in rng.choice(
                np.arange(0, n - 288),
                size=2,
                replace=False
            ):
                for k, j in enumerate(range(i, i + 288)):
                    if ok[j] and L[j] == "":
                        x[j] *= 1 + 0.3 * k / 287
                        L[j] = "drift"

        out[v] = x
        lab[v] = L

    return out, lab
