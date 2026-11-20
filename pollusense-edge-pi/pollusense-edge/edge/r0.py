"""Compute R0 for MQ135 and MQ7 from raw_1min over a time window.
Usage: python r0.py "2026-11-20 00:00" "2026-11-20 01:00"   (times in UTC)
"""
import json, sqlite3, sys, statistics
from datetime import datetime, timezone
from calibrate import rl_effective, rs_from_mv, mq135_trh_factor

DB = "/home/pi/pollusense/data.db"
HW = json.load(open("hardware.json"))          # {"mq135_rl": 1000, "mq7_rl": 9870}
RATIO_AIR_MQ135 = 3.6     # Rs/R0 in clean air, MQ135 datasheet
RATIO_AIR_MQ7 = 27.5      # Rs/R0 in clean air, MQ7 datasheet

def epoch(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())

def main(db, start, end):
    rows = sqlite3.connect(db).execute(
        "SELECT payload FROM raw_1min WHERE ts >= ? AND ts < ?", (epoch(start), epoch(end))).fetchall()
    rl135, rl7 = rl_effective(HW["mq135_rl"]), rl_effective(HW["mq7_rl"])
    rs135, rs7, temps, rhs = [], [], [], []
    for (p,) in rows:
        d = json.loads(p)
        if d.get("uptime_s", 0) < 600:
            continue
        t, h = d.get("temp"), d.get("rh")
        r = rs_from_mv(d.get("mq135_mv"), rl135)
        if r == r and t is not None and h is not None:
            rs135.append(r / mq135_trh_factor(t, h)); temps.append(t); rhs.append(h)
        r7 = rs_from_mv(d.get("mq7_mv"), rl7)
        if r7 == r7:
            rs7.append(r7)
    out = {"window_utc": [start, end], "n_mq135": len(rs135), "n_mq7": len(rs7),
           "mq135_r0": statistics.median(rs135) / RATIO_AIR_MQ135 if rs135 else None,
           "mq7_r0": statistics.median(rs7) / RATIO_AIR_MQ7 if rs7 else None,
           "temp_median": statistics.median(temps) if temps else None,
           "rh_median": statistics.median(rhs) if rhs else None}
    print(json.dumps(out, indent=2))
    json.dump(out, open("r0.json", "w"), indent=2)

if __name__ == "__main__":
    main(sys.argv[3] if len(sys.argv) > 3 else DB, sys.argv[1], sys.argv[2])
