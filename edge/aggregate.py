"""Build the 15-min record for the window that just ended; store it and publish it locally.
Run by a systemd timer at :01, :16, :31, :46 every hour.
"""
import json, math, sqlite3, sys, time
import numpy as np
from calibrate import (rl_effective, rs_from_mv, mq135_trh_factor,
                       ppm_from_ratio, no2_ugm3_from_ppm, co_mgm3_from_ppm)

DB = "/home/pi/pollusense/data.db"
CAL = json.load(open("/home/pi/pollusense/calibration.json"))
WARMUP_S = 600   # MQ readings within 10 min of boot are not used
VARS = ["pm25", "pm10", "no2", "co", "temp", "rh"]

def _med(vals):
    v = [x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return (float(np.median(v)), len(v)) if v else (None, 0)

def build_record(msgs, window_end_utc, cal):
    rl135, rl7 = rl_effective(cal["mq135_rl"]), rl_effective(cal["mq7_rl"])
    pm25, pm10, temp, rh, no2, co = [], [], [], [], [], []
    warm = 0
    for d in msgs:
        p25, p10 = d.get("pm25"), d.get("pm10")
        if p25 is not None and p10 is not None and p25 <= p10 * 1.1:
            pm25.append(p25); pm10.append(p10)
        temp.append(d.get("temp")); rh.append(d.get("rh"))
        if d.get("uptime_s", 0) < WARMUP_S:
            warm += 1
            continue
        t = d.get("temp") if d.get("temp") is not None else float("nan")
        h = d.get("rh") if d.get("rh") is not None else float("nan")
        rs = rs_from_mv(d.get("mq135_mv"), rl135)
        if not math.isnan(rs):
            ratio = rs / mq135_trh_factor(t, h) / cal["mq135_r0"]
            no2.append(no2_ugm3_from_ppm(ppm_from_ratio(ratio, cal["no2_m"], cal["no2_b"])))
        rs7 = rs_from_mv(d.get("mq7_mv"), rl7)
        if not math.isnan(rs7):
            co.append(co_mgm3_from_ppm(ppm_from_ratio(rs7 / cal["mq7_r0"], cal["co_m"], cal["co_b"])))
    rec = {"ts": window_end_utc, "device_id": msgs[0]["device_id"] if msgs else None}
    rules = {"pm25": (pm25, 8), "pm10": (pm10, 8), "temp": (temp, 8), "rh": (rh, 8),
             "no2": (no2, 8), "co": (co, 3)}
    for name, (vals, need) in rules.items():
        med, n = _med(vals)
        rec[name] = med if n >= need else None
        rec[f"n_{name}"] = n
        if n >= need:
            rec[f"flag_{name}"] = 0
        elif name in ("no2", "co") and msgs and warm >= len(msgs) / 2:
            rec[f"flag_{name}"] = 4
        else:
            rec[f"flag_{name}"] = 2
    return rec

def main(db=DB, now=None, publish=True):
    now = int(now or time.time())
    end = now - (now % 900)            # most recent 15-min boundary (UTC)
    start = end - 900
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE IF NOT EXISTS records_15min (
        ts INTEGER PRIMARY KEY, device_id TEXT, record TEXT)""")
    rows = con.execute("SELECT payload FROM raw_1min WHERE ts >= ? AND ts < ? ORDER BY ts",
                       (start, end)).fetchall()
    msgs = [json.loads(p) for (p,) in rows]
    rec = build_record(msgs, end, CAL)
    if rec["device_id"] is None:
        rec["device_id"] = CAL.get("device_id", "ps01")
    con.execute("INSERT OR REPLACE INTO records_15min VALUES (?,?,?)",
                (end, rec["device_id"], json.dumps(rec)))
    con.commit()
    print(json.dumps(rec))
    if publish:
        import paho.mqtt.publish as pub
        pub.single(f"pollusense/{rec['device_id']}/rec15", json.dumps(rec), qos=1,
                   hostname="localhost", auth={"username": CAL["mqtt_user"], "password": CAL["mqtt_pass"]})

if __name__ == "__main__":
    main()
