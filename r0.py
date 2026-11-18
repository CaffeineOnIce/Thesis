"""Compute R0 for MQ135 and MQ7 from raw_1min database over a time window.

Usage:
  # Compute from a specific UTC time window:
  python r0.py "2026-11-20 00:00" "2026-11-20 01:00"

  # Or auto-compute from the last 1 hour of recorded data:
  python r0.py --last1h
"""

from datetime import datetime, timezone
import json
import os
import sqlite3
import statistics
import sys
import time

from calibrate import mq135_trh_factor, rl_effective, rs_from_mv

DATA_DIR = os.path.expanduser("~/pollusense")
DB = os.path.join(DATA_DIR, "data.db")
HW_PATH = os.path.join(DATA_DIR, "hardware.json")

RATIO_AIR_MQ135 = 3.6  # Rs/R0 in clean air (datasheet)
RATIO_AIR_MQ7 = 27.5  # Rs/R0 in clean air (datasheet)


def epoch(s):
    return int(
        datetime.strptime(s, "%Y-%m-%d %H:%M")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def main(db, start, end):
    if not os.path.isfile(HW_PATH):
        print(f"Error: {HW_PATH} not found. Please create hardware.json first.")
        sys.exit(1)

    if not os.path.isfile(db):
        print(f"Error: Database {db} not found.")
        sys.exit(1)

    hw = json.load(open(HW_PATH))

    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT payload FROM raw_1min WHERE ts >= ? AND ts < ? ORDER BY ts",
        (start, end),
    ).fetchall()

    if not rows:
        print(
            f"No records found in database between epoch {start} and {end}."
        )
        print("Tip: Ensure the ESP32 has published telemetry in this window.")
        return

    rl135 = rl_effective(hw["mq135_rl"])
    rl7 = rl_effective(hw["mq7_rl"])
    rs135, rs7, temps, rhs = [], [], [], []

    for (p,) in rows:
        d = json.loads(p)
        if d.get("uptime_s", 0) < 600 and len(rows) > 30:
            continue  # Discard first 10-min warm-up if plenty of data
        t, h = d.get("temp"), d.get("rh")
        r = rs_from_mv(d.get("mq135_mv"), rl135)
        if r == r and t is not None and h is not None:
            rs135.append(r / mq135_trh_factor(t, h))
            temps.append(t)
            rhs.append(h)
        r7 = rs_from_mv(d.get("mq7_mv"), rl7)
        if r7 == r7:
            rs7.append(r7)

    out = {
        "n_samples_mq135": len(rs135),
        "n_samples_mq7": len(rs7),
        "mq135_r0": (
            round(statistics.median(rs135) / RATIO_AIR_MQ135, 1)
            if rs135
            else None
        ),
        "mq7_r0": (
            round(statistics.median(rs7) / RATIO_AIR_MQ7, 1) if rs7 else None
        ),
        "temp_median": statistics.median(temps) if temps else None,
        "rh_median": statistics.median(rhs) if rhs else None,
    }

    print("\n========================================================")
    print("           CALCULATED SENSOR BASELINES (R0)")
    print("========================================================")
    print(json.dumps(out, indent=2))

    r0_path = os.path.join(DATA_DIR, "r0.json")
    json.dump(out, open(r0_path, "w"), indent=2)
    print(f"\nSaved R0 baselines to {r0_path}")
    print(
        "Tip: Update mq135_r0 and mq7_r0 in ~/pollusense/calibration.json with these values.\n"
    )


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--last1h":
        now_ts = int(time.time())
        main(DB, now_ts - 3600, now_ts)
    elif len(sys.argv) >= 3:
        main(DB, epoch(sys.argv[1]), epoch(sys.argv[2]))
    else:
        # Default: auto-select last 1 hour of available data
        now_ts = int(time.time())
        main(DB, now_ts - 3600, now_ts)
