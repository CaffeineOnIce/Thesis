"""15-Minute Rolling Mean Aggregator with Direct CSV Storage.

Runs every 15 minutes (:01, :16, :31, :46) via systemd timer. Computes basic
arithmetic means across all 1-minute measurements collected in each window,
applies dynamic calibration to derive ambient NO2 and CO, and appends the
calibrated record directly to '~/pollusense/records_15min.csv'.
"""

import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
import sqlite3
import sys
import time

from calibrate import (
    co_mgm3_from_ppm,
    mq135_trh_factor,
    no2_ugm3_from_ppm,
    ppm_from_ratio,
    rl_effective,
    rs_from_mv,
)

DATA_DIR = os.path.expanduser("~/pollusense")
DB = os.path.join(DATA_DIR, "data.db")
CAL_PATH = os.path.join(DATA_DIR, "calibration.json")
CSV_OUT = os.path.join(DATA_DIR, "records_15min.csv")
IST = timezone(timedelta(hours=5, minutes=30))


def calc_mean(vals):
    """Computes arithmetic mean, ignoring None and NaN."""
    valid = [
        x
        for x in vals
        if x is not None and not (isinstance(x, float) and math.isnan(x))
    ]
    return round(float(sum(valid) / len(valid)), 2) if valid else None


def main(now=None):
    if not os.path.isfile(CAL_PATH):
        print(f"Error: Calibration file not found at {CAL_PATH}")
        sys.exit(1)

    cal = json.load(open(CAL_PATH))

    now = int(now or time.time())
    end = now - (now % 900)  # Align to 15-minute boundary
    start = end - 900

    if not os.path.isfile(DB):
        print(f"Database not found at {DB}. Waiting for ingest.")
        return

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT payload FROM raw_1min WHERE ts >= ? AND ts < ? ORDER BY ts",
        (start, end),
    ).fetchall()

    if not rows:
        print(
            f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}] No records found in window {start} to {end}"
        )
        return

    msgs = [json.loads(p) for (p,) in rows]

    pm25_vals = [d.get("pm25") for d in msgs]
    pm10_vals = [d.get("pm10") for d in msgs]
    temp_vals = [d.get("temp") for d in msgs]
    rh_vals = [d.get("rh") for d in msgs]
    m135_vals = [d.get("mq135_mv") for d in msgs]
    mq7_vals = [d.get("mq7_mv") for d in msgs]

    # 1. Compute Basic Means across the 15-minute window
    mean_pm25 = calc_mean(pm25_vals)
    mean_pm10 = calc_mean(pm10_vals)
    mean_temp = calc_mean(temp_vals)
    mean_rh = calc_mean(rh_vals)
    mean_m135 = calc_mean(m135_vals)
    mean_mq7 = calc_mean(mq7_vals)

    # 2. Dynamic Calibration from Mean Voltages
    rl135 = rl_effective(cal.get("mq135_rl", 1000))
    rl7 = rl_effective(cal.get("mq7_rl", 10000))

    rs135 = rs_from_mv(mean_m135, rl135)
    rs7 = rs_from_mv(mean_mq7, rl7)

    no2_ugm3 = None
    if not math.isnan(rs135) and mean_temp is not None and mean_rh is not None:
        ratio135 = (
            rs135
            / mq135_trh_factor(mean_temp, mean_rh)
            / cal.get("mq135_r0", 4930.0)
        )
        no2_ugm3 = round(
            no2_ugm3_from_ppm(
                ppm_from_ratio(
                    ratio135,
                    cal.get("no2_m", -0.4282),
                    cal.get("no2_b", -1.6500),
                )
            ),
            2,
        )

    co_mgm3 = None
    if not math.isnan(rs7):
        ratio7 = rs7 / cal.get("mq7_r0", 1800.0)
        co_mgm3 = round(
            co_mgm3_from_ppm(
                ppm_from_ratio(
                    ratio7, cal.get("co_m", -1.518), cal.get("co_b", 1.9958)
                )
            ),
            3,
        )

    dt_utc = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    dt_ist = datetime.fromtimestamp(end, tz=IST).strftime("%Y-%m-%d %H:%M:%S")

    record = {
        "datetime_ist": dt_ist,
        "datetime_utc": dt_utc,
        "ts": end,
        "device_id": msgs[0].get("device_id", cal.get("device_id", "ps01")),
        "minutes_counted": len(msgs),
        "pm25": mean_pm25,
        "pm10": mean_pm10,
        "temp": mean_temp,
        "rh": mean_rh,
        "mq135_mv": mean_m135,
        "mq7_mv": mean_mq7,
        "no2_ugm3": no2_ugm3,
        "co_mgm3": co_mgm3,
    }

    # 3. Direct CSV Logging (Appends to continuous CSV file)
    file_exists = os.path.isfile(CSV_OUT)
    fields = [
        "datetime_ist",
        "datetime_utc",
        "ts",
        "device_id",
        "minutes_counted",
        "pm25",
        "pm10",
        "temp",
        "rh",
        "mq135_mv",
        "mq7_mv",
        "no2_ugm3",
        "co_mgm3",
    ]

    with open(CSV_OUT, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)

    # 4. Also store in SQLite for resilient range queries and indexing
    con.execute(
        """CREATE TABLE IF NOT EXISTS records_15min (
        ts INTEGER PRIMARY KEY, datetime_ist TEXT, device_id TEXT, record TEXT
    )"""
    )
    con.execute(
        "INSERT OR REPLACE INTO records_15min VALUES (?,?,?,?)",
        (end, dt_ist, record["device_id"], json.dumps(record)),
    )
    con.commit()

    print(f"[{dt_ist}] Stored 15-min rolling mean to {CSV_OUT}: {record}")


if __name__ == "__main__":
    main()
